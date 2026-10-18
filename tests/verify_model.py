#!/usr/bin/env python3
"""Verify that the original scientific model and optimizer remain unchanged.

The default checks source compatibility and dependencies without running another
optimization. Use --output-dir for additional checks of a completed original run.
"""
import argparse
import ast
import difflib
import hashlib
import importlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = '91be63a'
EXPECTED_OPTIMIZER = {
    'move': .2, 'maximum_iterations': 200, 'm': 1, 'IP': 0,
    'tol': 1e-6, 'accepted_tol': 1e-4, 'norm': 'L2', 'gcmma': False,
}
# These additions only export existing tape values. Listing their exact syntax
# prevents the source check from silently accepting a changed computational form.
EXTRA_TOP_LEVEL = [
    'import sys',
    'from pathlib import Path',
    'sys.path.insert(0, str(Path(__file__).with_name("vendor")))',
    'from run_results import RunResults',
    'fda.continue_annotation()',
]
EXTRA_BODY = [
    'Jcontrol = fda.Control(J)',
    'Ucontrol = fda.Control(u_sol)',
    'results = RunResults(output_dir, RHO.dim(), W.dim(), float(total_vol), parameters_mma)',
]
EXTRA_CALLBACK = '''results.record(iter, float(Jcontrol.tape_value()) / 10.0,
                                   float(VolControl.tape_value()))'''
FINAL_EXPORT = '''with fda.stop_annotating():
    rho_viz_f.assign(rhofControl.tape_value())
    fd.par_loop(
        ("{[i] : 0 <= i < f.dofs}", "f[i, 0] = 1.0"),
        dx(DECK), {"f": (rho_viz_f, fd.WRITE)}, is_loopy_kernel=True,
    )
    displacement_viz = Ucontrol.tape_value().copy(deepcopy=True)
    displacement_viz.rename("displacement")
    fd.VTKFile(f"{output_dir}/final.pvd", target_continuity=fd.H1).write(
        rho_viz_f, displacement_viz)
    results.finish(solver, float(Jcontrol.tape_value()) / 10.0,
                   float(VolControl.tape_value()))
'''


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def dump(node):
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def statement(text):
    return ast.parse(text).body[0]


def original_bytes(name):
    completed = subprocess.run(
        ['git', '-c', f'safe.directory={ROOT}', 'show', f'{REFERENCE}:{name}'], cwd=ROOT,
        capture_output=True, check=True)
    return completed.stdout


class CompatibilityNormalizer(ast.NodeTransformer):
    """Undo only the approved API changes after removing exact export nodes."""
    def visit_Import(self, node):
        for name in node.names:
            if name.name == 'firedrake.adjoint' and name.asname == 'fda':
                name.name = 'firedrake_adjoint'
        return node

    def visit_Call(self, node):
        node = self.generic_visit(node)
        if (isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == 'fd' and node.func.attr == 'VTKFile'):
            node.func.attr = 'File'
        if (isinstance(node.func, ast.Attribute) and node.func.attr == 'interpolate'
                and isinstance(node.func.value, ast.Call)
                and dump(node.func.value.func) == dump(ast.parse('fd.Function', mode='eval').body)
                and len(node.func.value.args) == 1 and not node.func.value.keywords
                and len(node.args) == 1 and not node.keywords):
            return ast.Call(func=ast.parse('fd.interpolate', mode='eval').body,
                            args=[node.args[0], node.func.value.args[0]], keywords=[])
        return node


def scientific_source_check():
    original = ast.parse(original_bytes('bridge.py').decode())
    current = ast.parse((ROOT/'bridge.py').read_text())
    allowed_top = {dump(statement(s)): s for s in EXTRA_TOP_LEVEL}
    removed = []
    clean_top = []
    for node in current.body:
        key = dump(node)
        if key in allowed_top:
            removed.append(allowed_top[key])
        else:
            clean_top.append(node)
    require(sorted(removed) == sorted(EXTRA_TOP_LEVEL),
            'Top-level compatibility/export additions differ from their exact whitelist.')
    current.body = clean_top
    function = next(n for n in current.body
                    if isinstance(n, ast.FunctionDef) and n.name == 'compliance_bridge')
    allowed_body = {dump(statement(s)): s for s in EXTRA_BODY}
    allowed_body[dump(statement(FINAL_EXPORT))] = 'final output export'
    removed_body = []
    clean_body = []
    for node in function.body:
        key = dump(node)
        if key in allowed_body:
            removed_body.append(allowed_body[key])
        else:
            clean_body.append(node)
    require(sorted(removed_body) == sorted(list(EXTRA_BODY)+['final output export']),
            'Read-only control/export additions differ from their exact whitelist.')
    function.body = clean_body
    callback = next(n for n in function.body
                    if isinstance(n, ast.FunctionDef) and n.name == 'deriv_cb')
    callback_additions = {dump(statement(EXTRA_CALLBACK)), dump(statement('return design'))}
    removed_callback = [dump(n) for n in callback.body if dump(n) in callback_additions]
    require(len(removed_callback) == 2 and set(removed_callback) == callback_additions,
            'Derivative callback compatibility/output additions differ from whitelist.')
    callback.body = [n for n in callback.body if dump(n) not in callback_additions]
    current = CompatibilityNormalizer().visit(current)
    before, after = dump(original), dump(current)
    if before != after:
        difference = '\n'.join(difflib.unified_diff(
            ast.unparse(original).splitlines(), ast.unparse(current).splitlines(),
            fromfile=f'original {REFERENCE}', tofile='current after allowed compatibility changes'))
        raise AssertionError('Original scientific source was changed:\n'+difference)
    parameters = next(n.value for n in function.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'parameters_mma'
                              for t in n.targets))
    require(ast.literal_eval(parameters) == EXPECTED_OPTIMIZER,
            'Original optimizer parameters changed.')
    return dict(passed=True, reference=REFERENCE,
                original_ast_sha256=hashlib.sha256(before.encode()).hexdigest(),
                normalized_current_ast_sha256=hashlib.sha256(after.encode()).hexdigest(),
                allowed_changes=[
                    'firedrake.adjoint import and explicit annotation enable',
                    'concrete coordinate interpolation Functions',
                    'VTKFile replaces File with original H1 export',
                    'derivative callback returns controls',
                    'vendor import path and exact read-only diagnostic exports',
                ], optimizer_parameters=EXPECTED_OPTIMIZER)


def file_source_checks():
    checks = {}
    for name in ['solver_parameters.py', 'penalization.py']:
        expected = original_bytes(name)
        actual = (ROOT/name).read_bytes()
        require(actual == expected, f'{name} differs from the original source.')
        checks[name] = dict(passed=True, sha256=hashlib.sha256(actual).hexdigest())
    def geo_code(text):
        return re.sub(r'\s+', '', re.sub(r'//[^\n]*', '', text))
    original_geo = original_bytes('bridge.geo').decode()
    require(original_geo.count('Line(24) = {6, 6};') == 1,
            'Unexpected original zero-length line definition.')
    expected = geo_code(original_geo.replace('Line(24) = {6, 6};', ''))
    actual = geo_code((ROOT/'bridge.geo').read_text())
    require(actual == expected,
            'Geometry differs from original beyond removal of unused zero-length Line(24).')
    checks['bridge.geo'] = dict(passed=True, mesh_size=.015,
                                allowed_change='Remove unused zero-length Line(24); comments ignored.')
    package = ROOT/'vendor'/'pyMMAopt'
    provenance = json.loads((package/'UPSTREAM.json').read_text())
    require(provenance['commit'] == '934c0f304354fcb9430e2c326dedf557e3705eab',
            'Vendored optimizer is not pinned to the original blog-date revision.')
    require(not provenance['compatibility_patches'],
            'Unexpected changes recorded to the original optimizer.')
    hashes = {}
    for name, entry in provenance['files'].items():
        digest = hashlib.sha256((package/name).read_bytes()).hexdigest()
        require(digest == entry['sha256'], f'Vendored optimizer file changed: {name}.')
        hashes[name] = digest
    checks['pyMMAopt'] = dict(passed=True, commit=provenance['commit'], sha256=hashes)
    return checks


def dependency_checks():
    sys.path.insert(0, str(ROOT/'vendor'))
    # Application options are unrelated to PETSc's own option parser.
    saved_argv = sys.argv
    try:
        sys.argv = sys.argv[:1]
        imports = ['firedrake', 'firedrake.adjoint', 'pyMMAopt', 'numexpr',
                   'numpy', 'matplotlib', 'pyvista', 'plotly']
        loaded = {name: importlib.import_module(name) for name in imports}
    finally:
        sys.argv = saved_argv
    require(version('firedrake') == '2026.10.0', 'Expected the pinned current Firedrake release.')
    require(Path(loaded['pyMMAopt'].__file__).resolve().parent == ROOT/'vendor'/'pyMMAopt',
            'Python imported an optimizer other than the pinned original package.')
    gmsh = subprocess.run(['gmsh', '--version'], capture_output=True, text=True, check=True)
    return dict(passed=True, firedrake=version('firedrake'), numexpr=version('numexpr'),
                pyMMAopt=loaded['pyMMAopt'].__version__,
                gmsh=(gmsh.stdout+gmsh.stderr).strip(), imports=imports)


def completed_run_checks(directory):
    directory = directory.resolve()
    summary = json.loads((directory/'summary.json').read_text())
    for key, expected in dict(mesh_size=.015, initial_density=.5,
                              filter_coefficient=2e-4, objective_scale=10.,
                              volume_limit=.15, design_volume=.49).items():
        require(math.isclose(summary[key], expected, rel_tol=1e-10, abs_tol=1e-10),
                f'Completed run did not use original {key}={expected}.')
    require(summary['optimizer_parameters'] == EXPECTED_OPTIMIZER,
            'Completed run used different optimizer settings.')
    require(summary['firedrake_version'] == version('firedrake'),
            'Completed run used a different Firedrake release.')
    require(summary['optimizer'] == 'original pyMMAopt 934c0f3', 'Unexpected completed-run optimizer.')
    require(0 < summary['volume_fraction'] <= .15*1.005,
            'Final density violates the original material-volume limit by more than 0.5%.')
    require(1 <= summary['iterations'] <= EXPECTED_OPTIMIZER['maximum_iterations']+1,
            'Unexpected iteration count for the original <= iteration-limit loop.')
    for key in ['initial_compliance', 'final_compliance', 'elapsed_seconds', 'optimizer_change']:
        require(math.isfinite(summary[key]) and summary[key] >= 0,
                f'Nonfinite or negative completed-run {key}.')
    require(summary['final_compliance'] > 0, 'Final compliance must be positive.')
    converged = summary['optimizer_change'] <= EXPECTED_OPTIMIZER['tol']
    require(summary['converged'] == converged, 'Convergence flag disagrees with original stopping test.')
    import csv
    with (directory/'history.csv').open(newline='') as handle:
        history = list(csv.DictReader(handle))
    require(len(history) > 1, 'Missing optimization history.')
    for row in history:
        require(all(math.isfinite(float(v)) for v in row.values()), 'Nonfinite optimization history.')
    require(math.isclose(float(history[0]['volume_fraction']), .5, rel_tol=1e-4),
            'Initial recorded density is not the original 0.5.')
    require(math.isclose(float(history[-1]['compliance']), summary['final_compliance'], rel_tol=1e-12),
            'Final compliance disagrees between history and summary.')
    require(math.isclose(float(history[-1]['volume_fraction']), summary['volume_fraction'], rel_tol=1e-12),
            'Final volume disagrees between history and summary.')
    require(int(history[-1]['iteration']) == summary['iterations'], 'Final iteration count disagrees.')
    candidates = [directory/'bridge.msh', ROOT/'bridge.msh']
    require(any(path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == summary['mesh_sha256']
                for path in candidates), 'Completed-run mesh hash does not match an available mesh.')
    pvd = directory/'final.pvd'
    entries = ET.parse(pvd).findall('.//DataSet')
    require(entries, 'No datasets found in final PVD.')
    for entry in entries:
        require((directory/entry.attrib['file']).is_file(), 'PVD refers to a missing VTK dataset.')
    import pyvista as pv
    import numpy as np
    reader = pv.get_reader(str(pvd))
    if getattr(reader, 'time_values', None):
        reader.set_active_time_value(reader.time_values[-1])
    grid = reader.read()
    while isinstance(grid, pv.MultiBlock):
        grid = grid[0] if len(grid) == 1 else grid.combine()
    require(grid.n_cells > 0, 'Empty final VTK dataset.')
    require('rho' in grid.array_names and 'displacement' in grid.array_names,
            'Missing final original density or displacement fields.')
    for name in grid.array_names:
        array = np.asarray(grid[name])
        if np.issubdtype(array.dtype, np.number):
            require(np.isfinite(array).all(), f'Nonfinite saved field {name}.')
    density = np.asarray(grid['rho'])
    # Iterative filtering/export may introduce small floating-point deviations.
    require(float(density.min()) >= -1e-4 and float(density.max()) <= 1.0001,
            'Saved density leaves its physical bounds beyond numerical tolerance.')
    for name in ['bridge.png', 'convergence.png', 'report.html']:
        require((directory/name).is_file() and (directory/name).stat().st_size > 100,
                f'Missing rendered output: {name}.')
    return dict(passed=True, directory=str(directory), cells=summary['cells'],
                mpi_ranks=summary['mpi_ranks'], iterations=summary['iterations'],
                final_compliance=summary['final_compliance'],
                volume_fraction=summary['volume_fraction'],
                converged=summary['converged'], stopping_reason=summary['stopping_reason'],
                saved_density_range=[float(density.min()), float(density.max())],
                mesh_sha256=summary['mesh_sha256'],
                interpretation='Verifies the original setup and completed output; no claim of a unique topology.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path,
                        help='Check this completed original run in addition to sources and dependencies.')
    parser.add_argument('--report', type=Path, default=Path('output/verification/verification.json'))
    args = parser.parse_args()
    started = time.monotonic()
    report = dict(passed=False, reference=REFERENCE, checks={})
    args.report.parent.mkdir(parents=True, exist_ok=True)
    try:
        report['checks']['scientific_source'] = scientific_source_check()
        report['checks']['original_files'] = file_source_checks()
        report['checks']['dependencies'] = dependency_checks()
        if args.output_dir is not None:
            report['checks']['completed_run'] = completed_run_checks(args.output_dir)
        report['passed'] = True
    except Exception as error:
        report['error'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        report['elapsed_seconds'] = time.monotonic()-started
        args.report.write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
