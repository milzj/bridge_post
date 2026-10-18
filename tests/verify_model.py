#!/usr/bin/env python3
"""Check geometry, filter invariants, linear solves, and reduced derivatives.

Run inside the project container with ``python3 tests/verify_model.py``.
The coarse mesh keeps these independent numerical checks inexpensive.
"""

import argparse
import json
from pathlib import Path
import sys
import time

import firedrake as fd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge import Bridge, FIREDRAKE_VERSION, make_mesh


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("output/numerics"))
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report = {"passed": False, "firedrake_version": FIREDRAKE_VERSION,
              "mesh_size": 0.15, "checks": {}}
    checks = report["checks"]
    try:
        mesh_path = output / "bridge.msh"
        make_mesh(mesh_path, 0.15)
        direct = Bridge(mesh_path, fraction=0.15, radius=np.sqrt(2e-4), solver="direct")
        amg = Bridge(mesh_path, fraction=0.15, radius=np.sqrt(2e-4), solver="amg")
        report["cells"] = direct.cells
        report["displacement_dofs"] = direct.W.dim()

        # These values come directly from the CAD dimensions, independently of
        # the discrete filter, elasticity forms, and optimization derivatives.
        expected = {"design_volume": 0.49, "deck_volume": 0.01,
                    "load_area": 0.5, "support_area": 0.06,
                    "symmetry_x_area": 1.0, "symmetry_y_area": 0.5}
        measured = {"design_volume": direct.volume,
                    "deck_volume": direct.deck_volume,
                    "load_area": direct.load_area,
                    "support_area": float(fd.assemble(fd.Constant(1.) * direct.ds(2))),
                    "symmetry_x_area": float(fd.assemble(fd.Constant(1.) * direct.ds(4))),
                    "symmetry_y_area": float(fd.assemble(fd.Constant(1.) * direct.ds(5)))}
        checks["geometry"] = {"expected": expected, "measured": measured,
                              "absolute_tolerance": 1e-10}
        for name, target in expected.items():
            require(abs(measured[name] - target) < 1e-10,
                    f"Geometry check {name}: measured {measured[name]}, expected {target}.")

        uniform = np.full(direct.cells, 0.15)
        jd, vd, _ = direct.evaluate(uniform)
        ja, va, _ = amg.evaluate(uniform)
        constant_error = float(np.max(np.abs(direct.filtered.dat.data_ro - 0.15)))
        checks["constant_filter"] = {"maximum_density_error": constant_error,
                                     "absolute_tolerance": 1e-9,
                                     "filtered_design_volume": vd,
                                     "expected_design_volume": 0.15 * direct.volume}
        require(constant_error < 1e-9, "The Helmholtz filter did not preserve constant density.")
        require(abs(vd - 0.15 * direct.volume) < 1e-10,
                "Uniform density did not give the expected filtered design volume.")

        relative = abs(ja - jd) / abs(jd)
        checks["uniform_solver_agreement"] = {"direct_compliance": jd,
            "amg_compliance": ja, "relative_error": relative, "relative_tolerance": 1e-7}
        require(relative < 1e-7, "Direct and AMG uniform-density compliances disagree.")
        require(abs(va - vd) < 1e-10, "Direct and AMG models produced different filtered volumes.")

        # A nonuniform control exercises the filter chain and nonlinear RAMP
        # derivative away from the initial constant-density state.
        nonuniform = 0.15 + 0.03 * np.sin(np.arange(direct.cells))
        checks["nonuniform_gradient"] = direct.verify_gradient(nonuniform)
        jd, vd, _ = direct.evaluate(nonuniform)
        ja, va, _ = amg.evaluate(nonuniform)
        relative = abs(ja - jd) / abs(jd)
        checks["nonuniform_solver_agreement"] = {"direct_compliance": jd,
            "amg_compliance": ja, "relative_error": relative, "relative_tolerance": 1e-7}
        require(relative < 1e-7, "Direct and AMG nonuniform-density compliances disagree.")
        require(abs(va - vd) < 1e-10, "Nonuniform filtered volumes differ between models.")

        # The no-flux filter preserves total mass over the whole mesh even
        # though only the design-region volume is constrained by the optimizer.
        raw_mass = float(fd.assemble(direct.rho * direct.dx))
        filtered_mass = float(fd.assemble(direct.filtered * direct.dx))
        checks["filter_mass"] = {"raw_mass": raw_mass, "filtered_mass": filtered_mass,
                                 "absolute_tolerance": 1e-10}
        require(abs(raw_mass - filtered_mass) < 1e-10, "The Helmholtz filter changed total mass.")
        report["passed"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        (output / "numerical_checks.json").write_text(json.dumps(report, indent=2) + "\n")
        print("Numerical verification:", json.dumps(report), flush=True)
    print(f"Numerical checks passed. Results: {output / 'numerical_checks.json'}", flush=True)


if __name__ == "__main__":
    main()
