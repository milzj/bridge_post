"""Density-filtered bridge optimization for Firedrake 2026.10 and mmapy.

Retains the original linear elasticity, RAMP, and DG0 Helmholtz filter.
Uses exact discrete self-adjoint derivatives in place of obsolete adapters.
"""
import argparse
import csv
import json
from importlib.metadata import version
from pathlib import Path
import subprocess
import sys
import time

# Firedrake initializes PETSc at import time. Keep this application's argparse
# options out of PETSc's option database (otherwise it reports them as unused).
_application_argv = sys.argv
try:
    sys.argv = sys.argv[:1]
    import firedrake as fd
finally:
    sys.argv = _application_argv
import numpy as np
from mmapy import mmasub
from penalization import ramp
from solver_parameters import elasticity_parameters, filter_parameters

FIREDRAKE_VERSION = version('firedrake')


def make_mesh(path, size):
    subprocess.run([
        "gmsh", "-3", str(Path(__file__).with_name("bridge.geo")),
        "-clmin", str(size), "-clmax", str(size), "-format", "msh2",
        "-o", str(path), "-nt", "1", "-v", "2",
    ], check=True)


class Bridge:
    def __init__(self, path, fraction, radius, solver):
        self.mesh = fd.Mesh(str(path))
        if self.mesh.comm.size != 1:
            raise RuntimeError("Use one MPI rank: the MMA driver is serial.")
        self.Q = fd.FunctionSpace(self.mesh, "DG", 0)
        self.W = fd.VectorFunctionSpace(self.mesh, "CG", 1)
        self.rho = fd.Function(self.Q, name="density").assign(fraction)
        self.filtered = fd.Function(self.Q, name="density_filtered")
        self.material = fd.Function(self.Q, name="material_density")
        self.u = fd.Function(self.W, name="displacement")
        self.dx, self.ds = fd.dx(domain=self.mesh), fd.ds(domain=self.mesh)
        self.volume = float(fd.assemble(fd.Constant(1.)*self.dx(1)))
        self.deck_volume = float(fd.assemble(fd.Constant(1.)*self.dx(0)))
        self.load_area = float(fd.assemble(fd.Constant(1.)*self.ds(3)))
        if min(self.volume, self.deck_volume, self.load_area) <= 0:
            raise RuntimeError("Missing design/deck/load mesh markers.")
        self.volume_limit = fraction*self.volume
        a, b = fd.TrialFunction(self.Q), fd.TestFunction(self.Q)
        coordinates = [fd.Function(self.Q).interpolate(x)
                       for x in fd.SpatialCoordinate(self.mesh)]
        distance = fd.sqrt(sum(fd.jump(x)**2 for x in coordinates))
        self.filter_a = (radius**2*fd.jump(a)*fd.jump(b)/distance*fd.dS
                         + a*b*self.dx)
        self.forward_filter = fd.LinearVariationalSolver(
            fd.LinearVariationalProblem(self.filter_a, self.rho*b*self.dx,
                                        self.filtered, constant_jacobian=True),
            solver_parameters=filter_parameters)
        E, nu = 1., .3
        mu, lam = fd.Constant(E/(2*(1+nu))), fd.Constant(E*nu/((1+nu)*(1-2*nu)))
        def sigma(v):
            return 2*mu*fd.sym(fd.grad(v)) + lam*fd.div(v)*fd.Identity(3)
        trial, test = fd.TrialFunction(self.W), fd.TestFunction(self.W)
        stiffness = ramp(self.filtered, ramp_p=10., val_0=1e-5)
        self.traction = fd.Constant((0., 0., -1.))
        state_a = (fd.inner(stiffness*sigma(trial), fd.grad(test))*self.dx(1)
                   + fd.inner(sigma(trial), fd.grad(test))*self.dx(0))
        state_L = fd.inner(self.traction, test)*self.ds(3)
        bcs = [fd.DirichletBC(self.W, (0., 0., 0.), 2),
               fd.DirichletBC(self.W.sub(0), 0., 4),
               fd.DirichletBC(self.W.sub(1), 0., 5)]
        x, y, z = fd.SpatialCoordinate(self.mesh)
        modes = [fd.Function(self.W).interpolate(v) for v in (
            fd.as_vector((1, 0, 0)), fd.as_vector((0, 1, 0)),
            fd.as_vector((0, 0, 1)), fd.as_vector((0, z, -y)),
            fd.as_vector((-z, 0, x)), fd.as_vector((y, -x, 0)))]
        nullspace = fd.VectorSpaceBasis(modes)
        nullspace.orthonormalize()
        self.state_solver = fd.LinearVariationalSolver(
            fd.LinearVariationalProblem(state_a, state_L, self.u, bcs=bcs),
            solver_parameters=elasticity_parameters(solver), near_nullspace=nullspace)
        # For A u=f, d(f^T u)/d(r_f)=-u^T A' u. The filter is symmetric.
        energy = fd.inner(stiffness*sigma(self.u), fd.grad(self.u))*self.dx(1)
        self.adjoint = fd.Function(self.Q)
        self.adjoint_filter = fd.LinearVariationalSolver(
            fd.LinearVariationalProblem(self.filter_a,
                -fd.derivative(energy, self.filtered, b), self.adjoint,
                constant_jacobian=True), solver_parameters=filter_parameters)
        vadj = fd.Function(self.Q)
        fd.solve(self.filter_a == b*self.dx(1), vadj, solver_parameters=filter_parameters)
        self.volume_gradient = fd.assemble(vadj*b*self.dx).dat.data_ro.copy()
        self.gradient_form = self.adjoint*b*self.dx
        self.compliance_form = fd.inner(self.traction, self.u)*self.ds(3)
        self.design_mask = fd.assemble(b*self.dx(1)).dat.data_ro > 0
        self.cells = self.Q.dim()

    def evaluate(self, x, gradient=True):
        self.rho.dat.data[:] = np.asarray(x).ravel()
        self.forward_filter.solve()
        self.state_solver.solve()
        J = float(fd.assemble(self.compliance_form))
        V = float(fd.assemble(self.filtered*self.dx(1)))
        if not np.isfinite(J) or J <= 0:
            raise RuntimeError(f"Invalid compliance: {J}")
        if not gradient:
            return J, V
        self.adjoint_filter.solve()
        g = fd.assemble(self.gradient_form).dat.data_ro.copy()
        if not np.all(np.isfinite(g)):
            raise RuntimeError("Nonfinite reduced gradient.")
        return J, V, g

    def write(self, writer, step):
        self.material.dat.data[:] = np.where(self.design_mask, self.filtered.dat.data_ro, 1.)
        writer.write(self.rho, self.filtered, self.material, self.u, time=float(step))

    def verify_gradient(self, x):
        direction = np.random.default_rng(17).uniform(-1., 1., x.size)
        J, V, g = self.evaluate(x)
        slope, vslope = float(g@direction), float(self.volume_gradient@direction)
        rows = []
        for h in [.04, .02, .01, .005]:
            jp, vp = self.evaluate(x+h*direction, False)
            jm, vm = self.evaluate(x-h*direction, False)
            rows.append(dict(step=h, remainder=abs(jp-J-h*slope),
                relative_error=abs((jp-jm)/(2*h)-slope)/max(abs(slope), 1e-12),
                volume_relative_error=abs((vp-vm)/(2*h)-vslope)/max(abs(vslope), 1e-12)))
        rates = [float(np.log2(a['remainder']/b['remainder']))
                 for a, b in zip(rows[:-1], rows[1:])]
        passed = (min(rates[-2:]) > 1.8 and rows[-1]['relative_error'] < .01
                  and rows[-1]['volume_relative_error'] < 1e-5)
        self.evaluate(x)
        result = dict(passed=bool(passed), convergence_rates=rates, samples=rows)
        print('Gradient verification:', json.dumps(result), flush=True)
        if not passed:
            raise RuntimeError('Discrete adjoint failed its directional Taylor test.')
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mesh-size', type=float, default=.04)
    parser.add_argument('--mesh', type=Path)
    parser.add_argument('--max-iterations', type=int, default=200)
    parser.add_argument('--output-dir', '--output_dir', type=Path, default=Path('output/demo'))
    parser.add_argument('--volume-fraction', type=float, default=.15)
    parser.add_argument('--filter-radius', type=float, default=float(np.sqrt(2e-4)))
    parser.add_argument('--solver', choices=['amg', 'direct'], default='amg')
    parser.add_argument('--verify-gradient', action='store_true')
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--no-render', action='store_true')
    parser.add_argument('--save-every', type=int, default=10)
    parser.add_argument('--move-limit', type=float, default=.1)
    parser.add_argument('--tolerance', type=float, default=1e-3)
    args = parser.parse_args()
    if args.mesh_size <= 0 or args.filter_radius <= 0:
        parser.error('Mesh size and filter radius must be positive.')
    if not .05 <= args.volume_fraction < 1:
        parser.error('Volume fraction must be in [0.05, 1).')
    if args.max_iterations < 0 or args.save_every < 1 or not 0 < args.move_limit <= 1:
        parser.error('Invalid iteration, save-every, or move-limit argument.')
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    mesh_path = args.mesh or out/'bridge.msh'
    if args.mesh is None:
        make_mesh(mesh_path, args.mesh_size)
    model = Bridge(mesh_path, args.volume_fraction, args.filter_radius, args.solver)
    x = model.rho.dat.data_ro.copy()
    gradient_check = model.verify_gradient(x) if args.verify_gradient else None
    writer = fd.VTKFile(str(out/'bridge_evolution.pvd'))
    final_writer = fd.VTKFile(str(out/'final.pvd'))
    initial_J, _, _ = model.evaluate(x)
    model.write(writer, 0)
    print(f'Firedrake {FIREDRAKE_VERSION}: {model.cells} cells, {model.W.dim()} displacement DOFs', flush=True)
    print('iteration,compliance,volume_fraction,max_density_change,elapsed_seconds', flush=True)
    xold1, xold2 = x.copy(), x.copy()
    low, upp = np.zeros((x.size, 1)), np.ones((x.size, 1))
    history, converged, last_change = [], False, 0.
    nsteps = 0 if args.check_only else args.max_iterations
    with (out/'history.csv').open('w', newline='') as f:
        log = csv.DictWriter(f, fieldnames=['iteration', 'compliance', 'volume_fraction',
                                          'max_density_change', 'elapsed_seconds'])
        log.writeheader()
        for iteration in range(nsteps+1):
            J, V, g = model.evaluate(x)
            row = dict(iteration=iteration, compliance=J, volume_fraction=V/model.volume,
                       max_density_change=last_change, elapsed_seconds=time.monotonic()-start)
            history.append(row)
            log.writerow(row)
            f.flush()
            print(f'{iteration},{J:.9g},{V/model.volume:.7f},{last_change:.5g},{row["elapsed_seconds"]:.2f}', flush=True)
            if iteration and (iteration % args.save_every == 0 or iteration == nsteps):
                model.write(writer, iteration)
            if iteration >= 20 and last_change < args.tolerance and V <= model.volume_limit*1.001:
                converged = True
                if iteration % args.save_every:
                    model.write(writer, iteration)
                break
            if iteration == nsteps:
                break
            col = lambda v: np.asarray(v).reshape(-1, 1)
            result = mmasub(1, x.size, iteration+1, col(x), np.zeros((x.size, 1)),
                np.ones((x.size, 1)), col(xold1), col(xold2), J/initial_J, col(g)/initial_J,
                np.array([[V/model.volume_limit-1.]]),
                (model.volume_gradient/model.volume_limit).reshape(1, -1), low, upp,
                1., np.zeros((1, 1)), np.full((1, 1), 1000.), np.zeros((1, 1)),
                move=args.move_limit)
            newx = result[0].ravel()
            low, upp = result[-2:]
            last_change = float(np.max(np.abs(newx-x)))
            xold2, xold1, x = xold1.copy(), x.copy(), newx.copy()
    model.write(final_writer, history[-1]['iteration'])
    np.savez_compressed(out/'design.npz', density=x,
        density_filtered=model.filtered.dat.data_ro, material_density=model.material.dat.data_ro)
    final = history[-1]
    summary = dict(firedrake_version=FIREDRAKE_VERSION, mesh_size=args.mesh_size,
        cells=model.cells, displacement_dofs=model.W.dim(), iterations=final['iteration'],
        initial_compliance=initial_J, final_compliance=final['compliance'],
        compliance_reduction_percent=100*(1-final['compliance']/initial_J),
        volume_fraction=final['volume_fraction'], volume_limit=args.volume_fraction,
        design_volume=model.volume, deck_volume=model.deck_volume, load_area=model.load_area,
        filter_radius=args.filter_radius, filter_coefficient=args.filter_radius**2,
        min_density=float(np.min(x)), max_density=float(np.max(x)), converged=converged,
        stopping_reason='density_change' if converged else
            ('forward_check' if args.check_only else 'iteration_limit'),
        max_density_change=last_change, elapsed_seconds=time.monotonic()-start,
        gradient_check=gradient_check, solver=args.solver, symmetry_planes=dict(x=0., y=1.))
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    if not args.check_only and nsteps >= 20:
        if final['volume_fraction'] > args.volume_fraction*1.005:
            raise RuntimeError('Final volume constraint violation exceeds 0.5%.')
        if final['compliance'] >= initial_J:
            raise RuntimeError('Optimization did not reduce compliance.')
    if not args.no_render:
        subprocess.run([sys.executable, str(Path(__file__).with_name('render_results.py')),
            '--input', str(out/'final.pvd'), '--history', str(out/'history.csv'),
            '--summary', str(out/'summary.json'), '--output-dir', str(out)], check=True)
    print(f'Results saved to {out}', flush=True)


if __name__ == '__main__':
    main()
