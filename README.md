# Original bridge example with current Firedrake

Run Miguel Salazar de Troya's [bridge topology optimization example](https://www.migueloptimization.com/posts/open-source/)
with Firedrake 2026.10.0 in Docker. This port preserves the original problem,
mesh specification, starting density, and optimizer. The source changes are
limited to compatibility with the current environment and saving results for
inspection outside Docker.

## Start Docker

Install [Docker Desktop](https://docs.docker.com/get-started/get-docker/) on macOS
or [Docker Engine](https://docs.docker.com/engine/install/) on Linux. No host
installation of Python, Firedrake, Gmsh, or graphics libraries is needed.

On macOS, start Docker Desktop and wait for its engine to run:

```bash
open -a Docker
docker info
```

On Linux with systemd, start the installed engine with
`sudo systemctl start docker`. Your user must have permission to run `docker info`;
follow Docker's installation instructions for your system.

The scripts use your computer's native architecture, including Apple Silicon.
This is the original three-dimensional mesh, which requires substantially more
memory and time than a small demonstration case. If Docker runs out of memory,
increase its memory allocation in Docker Desktop settings.

## Build and run

In a terminal, change into your clone of this fork, then run:

```bash
./scripts/build.sh
./scripts/run.sh
./scripts/verify.sh
./scripts/open.sh
```

`build.sh` builds the pinned environment from [Dockerfile](Dockerfile) and
[requirements.txt](requirements.txt). `run.sh` generates the mesh from the
original `bridge.geo`, runs the original optimization, and renders the results
in `output/demo/`. `verify.sh` checks the environment, the vendored optimizer,
and the saved run. It does not substitute a coarser mesh or a different starting
point. `open.sh` opens the saved graphical report in your host web browser.

The image download is large, and the first solve compiles finite element
kernels. Leave the terminal running until optimization and rendering finish.
Ctrl-C interrupts a run; files already written remain in your checkout.

## What is preserved

The [original bridge source](https://github.com/salazardetroya/bridge_post)
defines deterministic compliance minimization with linear elasticity, a DG0
Helmholtz filter, RAMP interpolation, a solid deck, and a volume constraint.
The solve uses one quarter of the bridge. This port retains:

| Setting | Original value retained |
| --- | --- |
| Gmsh characteristic size | `0.015` in `bridge.geo` |
| Geometry and physical surfaces | Original definitions, including symmetry surface `4 = {5}` and `5 = {4}` |
| Initial design density | `0.5` |
| Material volume limit | `0.15` of the design region |
| Helmholtz coefficient | `2e-4` multiplying the interior-face jump term |
| RAMP parameters | `ramp_p=10.0`, `val_0=1e-5` |
| Objective | `10 * compliance` |
| Optimizer | Original 2021 `pyMMAopt`, with its mass-weighted `L2` formulation |
| MMA move limit | `0.2` |
| MMA iteration parameter | `maximum_iterations=200` |
| MMA tolerances | `tol=1e-6`, `accepted_tol=1e-4` |
| MMA mode | `gcmma=False`, `IP=0`, one constraint |
| Linear solver parameters | Original elasticity and filter configurations |

The upstream repository supplies `bridge.geo`, rather than an archived generated
mesh. The pinned Gmsh installation generates a mesh using that original size and
geometry; no command-line mesh-size override is applied. Gmsh versions can
produce different tetrahedral connectivity from the same specification.

The blog describes a 100-iteration run. The code in the supplied fork sets
`maximum_iterations=200`; its original loop can perform 201 MMA updates. This
port retains that behavior. A completed run therefore need not be identical to
the image in the post or meet the optimizer's stopping tolerance.

## Compatibility changes

Current Firedrake provides its adjoint interface as `firedrake.adjoint`.
The port updates that import, annotation initialization, interpolation and VTK
output APIs, and the derivative callback's return value. The optimization
continues to use the original adjoint formulation and optimizer.

The original `pyMMAopt` revision is included unchanged under
[`vendor/pyMMAopt`](vendor/pyMMAopt). Its upstream revision and file hashes are
recorded in [UPSTREAM.json](vendor/pyMMAopt/UPSTREAM.json). This avoids fetching
a newer optimizer implementation when rebuilding the environment.

Current Gmsh rejects the unused zero-length declaration `Line(24) = {6, 6}`.
Only that declaration is removed from `bridge.geo`; it is not referenced by
any surface or volume. Geometry, mesh size, and boundary labels are preserved.

The [source verification](docs/source-verification.json) compares the scientific
Python syntax tree with the original commit after an explicit compatibility
whitelist. It also checks original solver files, geometry, and optimizer hashes.
The checker rejects changes to mesh size, initialization, forms, or parameters.

The remaining additions are Docker helpers and exports for the report,
optimization history, and final density. They do not change the optimization
parameters. No coarse-mesh or alternative-initial-density presets are supplied.

## Open results outside Docker

The container mounts your checkout at `/workspace`. Consequently,
`/workspace/output/demo` is the `output/demo` folder on your computer. No
`docker cp` command is needed. Results remain after the container exits, and
the container writes files as your host user.

- Open `output/demo/report.html` using `./scripts/open.sh` or your file manager.
- Open `output/demo/bridge.png` and `output/demo/convergence.png` in Preview on
  macOS or your preferred image viewer.
- Open `output/demo/final.pvd` or `output/demo/bridge_evolution.pvd` with a host
  installation of [ParaView](https://www.paraview.org/download/). Keep the
  corresponding data folder beside each `.pvd` file.
- Inspect `output/demo/history.csv` and `output/demo/summary.json` for the saved
  optimization history and run metadata.

To regenerate the illustration and report from saved output:

```bash
./scripts/render.sh output/demo
./scripts/open.sh output/demo
```

Rendering runs offscreen inside Docker. The HTML report is self-contained and
works offline; its three-dimensional view supports rotation and zooming.

The illustration reflects the computed quarter across the two symmetry planes
to show the full bridge. It uses a density isosurface at `0.8` with smoothing,
following the visualization described in the blog. These are display settings;
they do not alter the mesh, density field, or optimizer. The VTK files contain
the saved density for inspection using other display settings.

## Environment controls

The scripts use one BLAS/OpenMP thread by default. You can limit the container's
CPU or memory allocation:

```bash
BRIDGE_CPUS=4 BRIDGE_MEMORY=12g ./scripts/run.sh
```

`BRIDGE_MPI_RANKS` selects the number of MPI processes (default `1`); this only
partitions the original mesh. Use fewer processes if Docker exhausts its memory.
For example, `BRIDGE_MPI_RANKS=4 ./scripts/run.sh` uses four processes.

`BRIDGE_THREADS` changes the thread count. `BRIDGE_IMAGE` changes the local image
tag used by both `build.sh` and the run helpers. `BRIDGE_PLATFORM` can request
`linux/arm64` or `linux/amd64`; normally leave it unset to use the native
architecture. Rebuild after changing the requested platform.

To inspect the same environment interactively:

```bash
./scripts/container.sh python3 -c 'import importlib.metadata; print(importlib.metadata.version("firedrake"))'
./scripts/container.sh bash
```

Runtime output and generated meshes are excluded from Git. Source files are
mounted directly, so source edits do not require an image rebuild. Rebuild
when changing environment dependencies.

## Troubleshooting

**Cannot connect to Docker:** start Docker Desktop or the Docker Engine service,
then verify that `docker info` works in the same terminal.

**Container killed, often with exit code 137:** increase Docker Desktop's memory
allocation. Preserve the original mesh and optimization settings when
reproducing this example.

**No report yet:** wait for optimization and rendering to finish. The output
directory must contain `final.pvd`, its companion data folder, `history.csv`,
and `summary.json` before you can regenerate the report with `render.sh`.

**Opening output from a headless Linux host:** copy the complete output folder
to a computer with a browser, image viewer, or ParaView.

## Attribution

The original bridge example is by Miguel Salazar de Troya. See the original
[repository](https://github.com/salazardetroya/bridge_post),
[blog post](https://www.migueloptimization.com/posts/open-source/), and
[LICENSE](LICENSE). The vendored `pyMMAopt` code retains its
[GPL-2.0 license](vendor/pyMMAopt/LICENSE) and [NOTICE](vendor/pyMMAopt/NOTICE).
The Docker environment includes third-party packages under their respective
licenses.
