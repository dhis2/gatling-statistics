# Conventions

## Dependencies

Prefer the Python standard library. Reach for a third-party dep only when stdlib genuinely
doesn't cover the need (e.g. plotting via plotly, CSV/percentile math via pandas/numpy). When
in doubt, ask before adding to `pyproject.toml`.

## Tooling

`uv` manages everything: dependencies, virtualenv, build, tests, linting. Do not suggest `pip`,
`venv`, `python -m pip`, or system-Python commands. If you need to run something, prefix with
`uv run ...` or `uv tool run ...`.

`uv tool install .` (re)installs gstat as a global command from the current checkout; use this
when testing CLI changes end-to-end.
