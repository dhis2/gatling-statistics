# gstat - Gatling Statistics CLI

A Python CLI tool that calculates and plots statistics like percentiles (min, 50th, 75th, 95th,
99th, max) from Gatling `simulation.csv` files.

## Features

* **Exact Percentiles**: Uses NumPy over the full sample, so results are reproducible
* **Multiple Reports Support**: Process single reports or directories containing multiple simulation
runs
* **Easy Installation**: Install globally like a binary using `uv`
* **CSV Output**: Outputs percentile data as CSV to console
* **Interactive Plotting**: Generate interactive HTML plots with simulation and request filtering

## Installation

### Install from Git (Recommended)

Install directly from GitHub using `uv` without needing to clone the repository:

```sh
# Install latest release (recommended)
uv tool install git+https://github.com/dhis2/gatling-statistics

# Install specific version
uv tool install git+https://github.com/dhis2/gatling-statistics@v0.1.0

# Update to latest version
uv tool install --reinstall git+https://github.com/dhis2/gatling-statistics
```

Use the `gstat` command from anywhere. Check your installed version:

```sh
gstat --version
```

### Local Development

For development or contributing:

```sh
# Clone and install locally
git clone https://github.com/dhis2/gatling-statistics.git
cd gatling-statistics
uv tool install .

# Or run directly without installing
uv sync
uv run gstat <report_directory>
```

## Usage

Output percentiles per simulation, run and request name as CSV

```sh
gstat <report_directory>
```

* You must convert the binary `simulation.log` into a `simulation.csv`.
* You must point to a report directory created by Gatling like
`target/gatling/<simulation>_<timestamp>`. Either a single report directory or a directory
containing multiple report directories.

### CSV Output Format

* `simulation`: Name of the simulation extracted from directory name
* `run_timestamp`: Timestamp of the run extracted from directory name
* `request_name`: HTTP request name/endpoint
* `count`: Number of successful requests
* `min`: Minimum response time (ms)
* `50th`: 50th percentile response time (ms)
* `75th`: 75th percentile response time (ms)
* `95th`: 95th percentile response time (ms)
* `99th`: 99th percentile response time (ms)
* `max`: Maximum response time (ms)

```csv
simulation,run_timestamp,request_name,count,min,50th,75th,95th,99th,max
trackerexportertests,20250627064559771,events,38,320,357,380,557,1258,1258
trackerexportertests,20250627095400668,events,7,2138,2346,2383,3345,3345,3345
```

### Combining multiple runs

When the input has more than one report directory (e.g. five CI runs of the same scenario)
the default output is one row per (run, request). To collapse those into one row per request
with percentiles computed over the combined samples, pass `--combine`:

```sh
gstat --combine ./baseline                        # 5 runs → 1 row per request
gstat --combine --exclude warmup ./baseline       # drop warmup runs first
```

The combined output drops the `run_timestamp` column. `count` is the sum across runs.
Percentiles are computed over the combined response times, not averaged from per-run
percentiles.

### Percentiles

`gstat` uses
[`numpy.percentile`](https://numpy.org/doc/stable/reference/generated/numpy.percentile.html)
with the `linear` method (numpy default, also called "type 7"). It runs over the full
sample. Same definition as Prometheus and Grafana.

Gatling uses
[`AVLTreeDigest`](https://github.com/tdunning/t-digest) (a t-digest variant) via the
[`com.tdunning:t-digest` dependency pinned in Gatling](https://github.com/gatling/gatling/blob/main/project/Dependencies.scala).
t-digest is an approximation algorithm for percentiles. Its main benefit is that t-digests
built on different machines can be merged without losing accuracy.
[Gatling Enterprise](https://gatling.io/) uses this to combine partial results from
distributed load generators, and OSS Gatling inherits the same code path.

We run on a single machine with the full sample on disk, so we gain nothing from
mergeability and we pay two costs:

* **You can't predict how wrong it will be.** There is no formula that tells you the
maximum error of a t-digest result. How close it gets to the real percentile depends on the
data. See the [Apache DataSketches
notes](https://datasketches.apache.org/docs/tdigest/tdigest.html).
* **Same input, different output.** When two response times are equally close to a t-digest
bucket, `AVLTreeDigest` picks one at random. The randomness is not seeded, so running the
report twice on the same input can give different p99 values (we saw up to 5 ms drift at
n=1000). This is extra noise on top of whatever variance the system under test already has,
and it is avoidable.

Because of this `gstat` numbers will not exactly match the Gatling HTML table. That is on
purpose.

### Comparing runs

Generate a Markdown comparison table across two or more runs (first input is the baseline,
deltas are computed against it):

```sh
# Two-run baseline vs candidate
gstat compare ./baseline ./candidate

# Three runs compared
gstat compare \
  ./run-2.41.8 --label 2.41.8 \
  ./run-2.42.4 --label 2.42.4 \
  ./run-2.43.0 --label 2.43.0 \
  --percentile 95
```

Output is one Markdown table per percentile (default p50 and p95) with `Diff` and `Change`
columns per non-baseline input. If a run directory contains warmup subdirectories you want
to skip, pass `--exclude warmup`.

### Plotting

Generate interactive HTML plots instead of CSV output:

```sh
# Generate plot and open in browser
gstat ../samples/ --plot

# Save plot to file
gstat ../samples/ --plot --output plot.html
```

### Directory Structure

The tool automatically detects whether you're providing a single report or multiple reports:

* **Single Report**: Directory containing `simulation.csv` directly
* **Multiple Reports**: Directory containing subdirectories named `<simulation>-<timestamp>`, each with their own `simulation.csv`

Example multiple reports structure:
```
samples/
├── trackerexportertests-20250627064559771/
│   ├── simulation.csv
│   └── ...
└── trackerexportertests-20250627095400668/
    ├── simulation.csv
    └── ...
```

## Prerequisites

* **uv**: Python package and project manager https://docs.astral.sh/uv
* **Python**: Python 3.13 or higher (managed automatically by uv)
* **Binary Log Conversion**: Since Gatling 3.12 ([issue
#4596](https://github.com/gatling/gatling/issues/4596)), Gatling writes test results to binary
format. You must convert `simulation.log` to `simulation.csv` using our fork's CLI tool available
at https://github.com/dhis2/gatling/tree/glog-cli. Releases can be downloaded from
https://github.com/dhis2/gatling/releases.

## Shell Autocompletion

To enable tab completion for `gstat` commands and options:

### For zsh

```sh
# Enable bash completion compatibility and register gstat
echo 'autoload -U bashcompinit && bashcompinit' >> ~/.zshrc
echo 'eval "$(register-python-argcomplete gstat)"' >> ~/.zshrc

# Restart shell or reload config
source ~/.zshrc
```

### For bash

```sh
# Register gstat for autocompletion
echo 'eval "$(register-python-argcomplete gstat)"' >> ~/.bashrc

# Restart shell or reload config
source ~/.bashrc
```

### Global completion (all Python CLI tools)

For system-wide completion of all Python CLI tools with argcomplete support:

```sh
activate-global-python-argcomplete --user
```

After setup, you'll get autocompletion for:
* Command options: `gstat --<TAB>` → `--plot`, `--output`, `--help`
* Plot types: `gstat --plot <TAB>` → `distribution`, `stacked`, `scatter`
* File/directory path completion for report directories

## Development

### Setup

```sh
# Install Python 3.13 and create virtual environment
uv sync

# Install pre-commit hooks for code formatting
uv run pre-commit install
```

### Development Commands

```sh
# Run the tool locally
uv run gstat <report_directory>

# Run tests
uv run python tests/test_gstat.py

# Run tests with verbose output
uv run python tests/test_gstat.py -v

# Format code with ruff
uv run ruff format .

# Check and fix linting issues
uv run ruff check . --fix

# Run pre-commit hooks manually
uv run pre-commit run --all-files

# Install as global tool for testing (use --reinstall to update)
uv tool install .
```

### Pre-commit Hooks

This project uses pre-commit hooks to ensure code quality. The hooks automatically:

* Format code using `ruff format`
* Fix linting issues using `ruff check --fix`

These hooks run automatically on `git commit`. To bypass temporarily: `git commit --no-verify`

### Releasing New Versions

This project uses setuptools-scm for dynamic versioning from git tags. Version is automatically
generated at build/install time from git tags in format `v0.1.0` and can be checked with `gstat
--version`.

#### Creating a Release

Use the interactive release script:

```sh
./scripts/release.sh
```

The script will:

1. Check for uncommitted changes
2. Suggest the next version number (or you can specify your own)
3. Validate the version format
4. Create an annotated git tag
5. Push the tag to GitHub (required for users to install the release)

#### How Versioning Works

* **On a tagged commit**: `gstat --version` shows `0.2.0` (clean release version)
* **After commits**: `gstat --version` shows `0.2.1.dev1+g20bb26c` (development version with SHA)
* **With uncommitted changes**: Version includes `.dirty` suffix

setuptools-scm automatically generates the version at build time, so no version files need to be
committed to the repository.

