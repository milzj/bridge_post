# Reference files

The figures and run records here are from the completed mesh-size `0.03` run.
Open `.png` files in an image viewer and `.json` files in a text editor;
GitHub can display both directly.

| File | Contents |
| --- | --- |
| `bridge.png` | Illustrated design problem and computed bridge |
| `convergence.png` | Compliance and material-volume history |
| `run-summary.json` | Final results, parameters, and stopping condition |
| `mesh-settings.json` | Mesh size and scaling factor |
| `verification.json` | Saved source, dependency, and completed-run checks |
| `source-verification.json` | Original-source and dependency checks |
| `pyMMAopt-source.json` | Upstream optimizer revision and file hashes |

New runs save their output in `output/demo/`. From the repository root, run
`./scripts/open.sh` to open that run's interactive HTML report. Installation and
run commands are in the [main README](../README.md).
