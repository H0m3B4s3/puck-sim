# PuckSim

A text-based, Football-Manager-style NHL franchise simulation — the hockey sibling of [HoopR](https://github.com/), reusing its proven architectural patterns (layered domain model, seedable RNG, JSON saves) while building a hockey-native simulation engine from scratch.

See [DESIGN.md](DESIGN.md) for the full design rationale and [DEVPLAN.md](DEVPLAN.md) for the step-by-step build plan.

## Install

```bash
pip install -e ".[dev,web]"
```

## Run tests

```bash
pytest
```

## Run the web app

Not yet available — the FastAPI + React web app is built in Phase 2 (v1) of [DEVPLAN.md](DEVPLAN.md).

## Headless simulation (dev/test harness)

```bash
python testkit/run_season.py --seed 1 --seasons 3
```
