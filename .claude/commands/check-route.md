---
description: Run the planner on the fixed route cases and the Perseverance comparison
---
Run `PYTHONUTF8=1 .venv/Scripts/python -m scripts.check_routes` from the repo root (cases live in
`tests/route_cases.yaml`).

Report, as a compact table: case, objective, distance (km), duration (h), O2 (kg), battery (Wh),
max slope (deg), feasible, point of no return; then the Perseverance comparison (rover vs planned
length, mean deviation, Frechet distance) and the compute time per case.

If any expectation fails, say which, and investigate before changing an expectation: a failing case
usually means a regression in `planner/` or a changed `config/model.yaml`. Only relax an expectation
when the change is intended, and say so explicitly.
