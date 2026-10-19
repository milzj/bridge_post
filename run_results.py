"""Save diagnostics without modifying the original model or optimizer."""
import csv
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import time

from firedrake import COMM_WORLD


class RunResults:
    def __init__(self, output_dir, cells, displacement_dofs, design_volume, parameters):
        self.output = Path(output_dir)
        self.cells = cells
        self.displacement_dofs = displacement_dofs
        self.design_volume = design_volume
        self.parameters = {key: parameters[key] for key in (
            'move', 'maximum_iterations', 'm', 'IP', 'tol', 'accepted_tol', 'norm', 'gcmma')}
        mesh_settings = Path('mesh-settings.json')
        self.mesh_settings = (json.loads(mesh_settings.read_text()) if mesh_settings.exists() else
                              dict(original_mesh_size=0.015, mesh_scale=1.0, mesh_size=0.015,
                                   mesh_note='Original mesh specification.'))
        self.started = time.monotonic()
        self.history = []

    def record(self, iteration, compliance, volume):
        row = dict(iteration=iteration, compliance=compliance,
                   volume_fraction=volume/self.design_volume,
                   elapsed_seconds=time.monotonic()-self.started)
        self.history.append(row)
        if COMM_WORLD.rank == 0:
            with (self.output/'history.csv').open('w', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row))
                writer.writeheader()
                writer.writerows(self.history)

    def finish(self, solver, compliance, volume):
        self.record(solver.loop, compliance, volume)
        summary = dict(
            firedrake_version=version('firedrake'), cells=self.cells,
            displacement_dofs=self.displacement_dofs, mpi_ranks=COMM_WORLD.size,
            iterations=solver.loop, initial_density=0.5,
            original_mesh_size=self.mesh_settings['original_mesh_size'],
            mesh_size=self.mesh_settings['mesh_size'], mesh_scale=self.mesh_settings['mesh_scale'],
            mesh_note=self.mesh_settings['mesh_note'],
            initial_compliance=self.history[0]['compliance'],
            final_compliance=compliance, volume_fraction=volume/self.design_volume,
            volume_limit=0.15, design_volume=self.design_volume,
            filter_coefficient=2e-4, objective_scale=10.0,
            optimizer='original pyMMAopt 934c0f3',
            optimizer_parameters=self.parameters,
            optimizer_change=float(solver.change),
            converged=bool(solver.change <= self.parameters['tol']),
            stopping_reason=('original_change_tolerance' if solver.change <= self.parameters['tol']
                             else 'original_iteration_limit'),
            elapsed_seconds=time.monotonic()-self.started,
            mesh_sha256=hashlib.sha256(Path('bridge.msh').read_bytes()).hexdigest(),
            symmetry_planes=dict(x=0.0, y=1.0),
        )
        if COMM_WORLD.rank == 0:
            (self.output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
