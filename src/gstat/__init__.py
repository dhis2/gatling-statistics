#!/usr/bin/env python3
"""
Gatling Statistics Calculator

Calculate statistics like percentiles from Gatling simulation.csv files.
"""

import argparse
import re
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import argcomplete
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from tdigest import TDigest

try:
    from ._version import __version__, commit_id

    # setuptools-scm provides commit_id in format 'gSHA' or None
    if commit_id:
        __git_sha__ = commit_id.lstrip("g")
    else:
        __git_sha__ = "release"
except ImportError:
    __version__ = "0.0.0+dev"
    __git_sha__ = "dev"

percentile_range_colors = {
    "0-50th": "#28a745",  # Green
    "50th-75th": "#A23B72",  # Purple
    "75th-95th": "#F18F01",  # Orange
    "95th-99th": "#C73E1D",  # Red
    "99th-max": "#8B0000",  # Dark red
}

percentile_line_colors = {
    "50th": "#28a745",  # Green
    "75th": "#A23B72",  # Purple
    "95th": "#F18F01",  # Orange
    "99th": "#C73E1D",  # Red
    "max": "#8B0000",  # Dark red
}

mean_color = "#2E86AB"  # Blue
line_width = 3  # Default line width for mean and percentile lines

dropdown_position_y = {
    "simulation": 1.25,
    "request": 1.2,
    "timestamp": 1.15,
}

# dropdown configurations for each plot type
dropdown_configs = {
    "stacked": ["simulation", "request"],
    "distribution": ["simulation", "request", "timestamp"],
    "scatter": ["simulation", "request", "timestamp"],
    "timeline": ["simulation", "request", "timestamp"],
}

# dark mode makes the active selection illegible
# https://github.com/plotly/plotly.js/issues/1428
updatemenus_default = {
    "direction": "down",
    "showactive": True,
    "x": 0.02,
    "xanchor": "left",
    "y": 1.08,
    "yanchor": "top",
    "bgcolor": "#d0d0d0",  # Light gray background for better hover contrast
    "bordercolor": "#555555",
    "borderwidth": 1,
    "font": {"size": 11, "color": "#000000"},
    "pad": {"r": 10, "t": 5, "b": 5, "l": 10},
}


def parse_simulation_csv(csv_path: Path) -> pd.DataFrame:
    """Parse simulation.csv and return successful requests.

    Example of a simulation.csv

    record_type,scenario_name,group_hierarchy,request_name,status,start_timestamp,end_timestamp,response_time_ms,error_message,event_type,duration_ms,cumulated_response_time_ms,is_incoming
    request,,,events,OK,1751199294083,1751199294256,173,,,,,false
    """
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"Error reading CSV file {csv_path}: {e}", file=sys.stderr)
        sys.exit(1)

    # only consider response times of successful requests (ignore group and user entries in csv)
    request_df = df[(df["record_type"] == "request") & (df["status"] == "OK")].copy()

    if request_df.empty:
        print(f"No successful request records found in {csv_path}", file=sys.stderr)
        sys.exit(1)

    # Ensure data types are as expected
    request_df["start_timestamp"] = pd.to_datetime(request_df["start_timestamp"], unit="ms")
    request_df["end_timestamp"] = pd.to_datetime(request_df["end_timestamp"], unit="ms")
    request_df["response_time_ms"] = pd.to_numeric(request_df["response_time_ms"])

    return request_df


def calculate_percentiles(response_times: list[float], method: str = "exact") -> dict[str, float]:
    if method == "tdigest":
        return calculate_percentiles_tdigest(response_times)
    else:
        return calculate_percentiles_exact(response_times)


def calculate_percentiles_exact(response_times: list[float]) -> dict[str, float]:
    """Calculate exact percentiles using numpy."""
    if not response_times:
        return {"min": 0, "50th": 0, "75th": 0, "95th": 0, "99th": 0, "max": 0}

    # https://numpy.org/doc/stable/reference/generated/numpy.percentile.html#numpy-percentile
    percentiles = np.percentile(response_times, [0, 50, 75, 95, 99, 100], method="nearest")

    return {
        "min": percentiles[0],
        "50th": percentiles[1],
        "75th": percentiles[2],
        "95th": percentiles[3],
        "99th": percentiles[4],
        "max": percentiles[5],
    }


def calculate_percentiles_tdigest(response_times: list[float]) -> dict[str, float]:
    """Calculate percentiles using T-Digest algorithm (like Gatling which uses https://github.com/tdunning/t-digest)."""
    if not response_times:
        return {"min": 0, "50th": 0, "75th": 0, "95th": 0, "99th": 0, "max": 0}

    digest = TDigest()
    for time in response_times:
        digest.update(time)

    return {
        "min": digest.percentile(0),
        "50th": digest.percentile(50),
        "75th": digest.percentile(75),
        "95th": digest.percentile(95),
        "99th": digest.percentile(99),
        "max": digest.percentile(100),
    }


class RequestData(NamedTuple):
    """Data for a specific request in a specific run."""

    response_times: list[float]
    timestamps: list[tuple[datetime, datetime]]  # (start, end)
    percentiles: dict[str, float]
    mean: float
    count: int


class RunData:
    """Data for a complete simulation run."""

    def __init__(self, raw_timestamp: str, directory: Path = None, suffix: str = ""):
        self.raw_timestamp = raw_timestamp
        self.formatted_timestamp = format_timestamp(raw_timestamp)
        self.datetime_timestamp = parse_gatling_directory_timestamp(raw_timestamp)
        self.directory = directory
        self.suffix = suffix
        self.requests: OrderedDict[str, RequestData] = OrderedDict()


class GatlingData:
    """Unified data structure for all Gatling performance data.

    Structure: {simulation: {run_timestamp: RunData}}
    All data is stored in sorted order for consistent presentation.
    """

    def __init__(self, report_directory: Path = None):
        self.data: OrderedDict[str, OrderedDict[str, RunData]] = OrderedDict()
        self.report_directory = report_directory

    def add_request_data(
        self,
        simulation: str,
        run_timestamp: str,
        request_name: str,
        request_data: RequestData,
        directory: Path = None,
        suffix: str = "",
    ) -> None:
        """Add request data maintaining sorted order."""
        if simulation not in self.data:
            self.data[simulation] = OrderedDict()

        if run_timestamp not in self.data[simulation]:
            self.data[simulation][run_timestamp] = RunData(run_timestamp, directory, suffix)

        self.data[simulation][run_timestamp].requests[request_name] = request_data

    def finalize_ordering(self) -> None:
        """Sort all data levels after loading is complete."""
        # Sort simulations alphabetically
        sorted_sims = OrderedDict(sorted(self.data.items()))

        # Sort run timestamps in ascending order (oldest first)
        for simulation in sorted_sims:
            sorted_runs = OrderedDict(sorted(sorted_sims[simulation].items()))
            sorted_sims[simulation] = sorted_runs

        self.data = sorted_sims

    def get_simulations(self) -> list[str]:
        """Get all simulation names in sorted order."""
        return list(self.data.keys())

    def get_runs(self, simulation: str) -> list[str]:
        """Get all run timestamps for a simulation in sorted order."""
        return list(self.data.get(simulation, {}).keys())

    def get_requests(self, simulation: str, run_timestamp: str) -> list[str]:
        """Get all request names for a simulation run in sorted order."""
        run_data = self.data.get(simulation, {}).get(run_timestamp)
        return list(run_data.requests.keys()) if run_data else []

    def get_request_data(
        self, simulation: str, run_timestamp: str, request_name: str
    ) -> RequestData | None:
        """Get request data for specific simulation/run/request."""
        run_data = self.data.get(simulation, {}).get(run_timestamp)
        return run_data.requests.get(request_name) if run_data else None

    def get_run_data(self, simulation: str, run_timestamp: str) -> RunData | None:
        """Get run data for specific simulation/run."""
        return self.data.get(simulation, {}).get(run_timestamp)


def parse_gating_directory_name(dir_name: str) -> tuple[str, str, str] | None:
    """Parse directory name to extract simulation name, timestamp, and optional suffix from Gatlings
    report directory naming convention of <simulation>-<timestamp>[-<suffix>]

    Returns: (simulation, timestamp, suffix) or None if format doesn't match
    """
    # Match pattern: simulation-timestamp or simulation-timestamp-suffix
    match = re.match(r"^(.+?)-(\d{17})(?:-(.+))?$", dir_name)
    if match:
        return match.group(1), match.group(2), match.group(3) or ""
    return None


def parse_gatling_directory_timestamp(timestamp_str: str) -> datetime:
    """Parse directory timestamp string to datetime object.

    Input: '20250627064559771' (YYYYMMDDHHMMSSmmm)
    Output: datetime object
    """
    try:
        year = timestamp_str[0:4]
        month = timestamp_str[4:6]
        day = timestamp_str[6:8]
        hour = timestamp_str[8:10]
        minute = timestamp_str[10:12]
        second = timestamp_str[12:14]
        milliseconds = timestamp_str[14:17] if len(timestamp_str) >= 17 else "000"

        dt = datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second),
            int(milliseconds) * 1000,
        )
        return dt
    except (ValueError, IndexError):
        return datetime.min


def format_timestamp(timestamp_str: str) -> str:
    """Convert timestamp string to human-readable format.

    Input: '20250627064559771' (YYYYMMDDHHMMSSmmm)
    Output: '2025-06-27 06:45:59'
    """
    dt = parse_gatling_directory_timestamp(timestamp_str)
    if dt == datetime.min:
        return timestamp_str
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def truncate_string(string: str, max_length: int = 25) -> str:
    """Truncate string to max_length characters, adding ... if truncated."""
    if len(string) <= max_length:
        return string
    return string[: max_length - 3] + "..."


def create_dropdown_buttons(
    dropdown_type: str,
    items: list[str],
    get_visibility_fn: callable,
    get_label_fn: callable = None,
) -> list[dict]:
    """Create dropdown buttons for a specific dropdown type."""
    buttons = []

    for item in items:
        visibility = get_visibility_fn(item)
        label = get_label_fn(item) if get_label_fn else truncate_string(item, 100)

        buttons.append(
            {
                "label": label,
                "method": "update",
                "args": [{"visible": visibility}],
            }
        )

    return buttons


def create_plot_dropdowns(
    plot_type: str,
    gatling_data: GatlingData,
    trace_mapping: dict,
    fig_data_length: int,
    defaults: dict,
) -> list[dict]:
    """Create all dropdown menus for a specific plot type."""
    dropdown_types = dropdown_configs[plot_type]
    updatemenus = []

    for dropdown_type in dropdown_types:
        if dropdown_type == "simulation":
            items = gatling_data.get_simulations()

            def get_visibility_fn(sim):
                return _get_simulation_visibility(
                    sim, gatling_data, trace_mapping, fig_data_length, defaults, plot_type
                )

            def get_label_fn(sim):
                return truncate_string(sim)

        elif dropdown_type == "request":
            items = _get_all_requests_for_plot(gatling_data, defaults, plot_type)

            def get_visibility_fn(req):
                return _get_request_visibility(
                    req, gatling_data, trace_mapping, fig_data_length, defaults, plot_type
                )

            def get_label_fn(req):
                return truncate_string(req, 100)

        elif dropdown_type == "timestamp":
            items = gatling_data.get_runs(defaults["simulation"])

            def get_visibility_fn(run):
                return _get_run_visibility(
                    run, gatling_data, trace_mapping, fig_data_length, defaults, plot_type
                )

            def get_label_fn(run):
                return _get_run_label(run, gatling_data, defaults["simulation"])

        buttons = create_dropdown_buttons(dropdown_type, items, get_visibility_fn, get_label_fn)

        menu = updatemenus_default | {
            "buttons": buttons,
            "y": dropdown_position_y[dropdown_type],
        }
        updatemenus.append(menu)

    return updatemenus


def _get_all_requests_for_plot(
    gatling_data: GatlingData, defaults: dict, plot_type: str
) -> list[str]:
    """Get all request names for the plot type."""
    if plot_type == "stacked":
        # Stacked uses all requests across all simulations
        all_requests = set()
        for simulation in gatling_data.get_simulations():
            for run_timestamp in gatling_data.get_runs(simulation):
                all_requests.update(gatling_data.get_requests(simulation, run_timestamp))
        return sorted(all_requests)
    else:
        # Distribution/scatter use requests for default simulation/run
        return gatling_data.get_requests(defaults["simulation"], defaults["run"])


def _get_simulation_visibility(
    simulation: str,
    gatling_data: GatlingData,
    trace_mapping: dict,
    fig_data_length: int,
    defaults: dict,
    plot_type: str,
) -> list[bool]:
    """Get visibility array for selecting a simulation."""
    visibility = [False] * fig_data_length

    if plot_type == "stacked":
        # Show first request for this simulation
        all_requests = _get_all_requests_for_plot(gatling_data, defaults, plot_type)
        if all_requests:
            first_request = all_requests[0]
            key = (simulation, first_request)
            if key in trace_mapping:
                start_idx, end_idx = trace_mapping[key]
                for j in range(start_idx, end_idx):
                    if j < len(visibility):
                        visibility[j] = True
    else:
        # Distribution/scatter: show first run and first request for this simulation
        sim_runs = gatling_data.get_runs(simulation)
        if sim_runs:
            first_run = sim_runs[0]
            sim_requests = gatling_data.get_requests(simulation, first_run)
            if sim_requests:
                first_request = sim_requests[0]
                key = (simulation, first_run, first_request)
                if key in trace_mapping:
                    if plot_type == "distribution" or plot_type == "scatter":
                        start_idx, end_idx = trace_mapping[key]
                        for j in range(start_idx, end_idx):
                            if j < len(visibility):
                                visibility[j] = True

    return visibility


def _get_request_visibility(
    request: str,
    gatling_data: GatlingData,
    trace_mapping: dict,
    fig_data_length: int,
    defaults: dict,
    plot_type: str,
) -> list[bool]:
    """Get visibility array for selecting a request."""
    visibility = [False] * fig_data_length

    if plot_type == "stacked":
        key = (defaults["simulation"], request)
        if key in trace_mapping:
            start_idx, end_idx = trace_mapping[key]
            for j in range(start_idx, end_idx):
                if j < len(visibility):
                    visibility[j] = True
    else:
        # Distribution/scatter
        key = (defaults["simulation"], defaults["run"], request)
        if key in trace_mapping:
            if plot_type == "distribution" or plot_type == "scatter" or plot_type == "timeline":
                start_idx, end_idx = trace_mapping[key]
                for j in range(start_idx, end_idx):
                    if j < len(visibility):
                        visibility[j] = True

    return visibility


def _get_run_visibility(
    run: str,
    gatling_data: GatlingData,
    trace_mapping: dict,
    fig_data_length: int,
    defaults: dict,
    plot_type: str,
) -> list[bool]:
    """Get visibility array for selecting a run."""
    visibility = [False] * fig_data_length

    key = (defaults["simulation"], run, defaults["request"])
    if key in trace_mapping:
        if plot_type == "distribution" or plot_type == "scatter" or plot_type == "timeline":
            start_idx, end_idx = trace_mapping[key]
            for j in range(start_idx, end_idx):
                if j < len(visibility):
                    visibility[j] = True

    return visibility


def _get_run_label(run: str, gatling_data: GatlingData, simulation: str) -> str:
    """Get formatted label for a run timestamp, including suffix if present."""
    run_data = gatling_data.get_run_data(simulation, run)
    if not run_data:
        return run

    label = run_data.formatted_timestamp
    if run_data.suffix:
        label = f"{label} ({run_data.suffix})"
    return label


def is_multiple_reports_directory(directory: Path) -> bool:
    """Check if directory contains multiple simulation report subdirectories."""
    if not directory.is_dir():
        return False

    # if the directory itself contains simulation.csv = single report directory
    if (directory / "simulation.csv").exists():
        return False

    # Look for subdirectories with the pattern <simulation>_<timestamp>
    for subdir in directory.iterdir():
        if subdir.is_dir() and parse_gating_directory_name(subdir.name):
            if (subdir / "simulation.csv").exists():
                return True

    return False


def load_gatling_data(directory: Path, method: str = "exact", exclude: str = None) -> GatlingData:
    """Load all Gatling data from directory, handling both single and multi-directory cases."""
    gatling_data = GatlingData(directory)

    if is_multiple_reports_directory(directory):
        for subdir in directory.iterdir():
            if not subdir.is_dir():
                continue

            # Skip directories containing the exclude string
            if exclude and exclude in subdir.name:
                continue

            try:
                _load_single_directory(gatling_data, subdir, method)
            except Exception as e:
                print(f"Warning: Error processing {subdir}: {e}", file=sys.stderr)
                continue
    else:
        _load_single_directory(gatling_data, directory, method)

    gatling_data.finalize_ordering()

    if not gatling_data.data:
        print(f"No valid simulation data found in {directory}", file=sys.stderr)
        sys.exit(1)

    return gatling_data


def _load_single_directory(gatling_data: GatlingData, directory: Path, method: str) -> None:
    """Load Gatling data from a directory directly containing one simulation.csv"""
    parsed = parse_gating_directory_name(directory.name)
    if parsed:
        simulation, run_timestamp, suffix = parsed
    else:
        simulation = "unknown"
        run_timestamp = "unknown"
        suffix = ""
    simulation_csv = directory / "simulation.csv"
    if not simulation_csv.exists():
        raise FileNotFoundError(f"simulation.csv not found in {directory}")

    df = parse_simulation_csv(simulation_csv)

    # Group by both group_hierarchy and request_name to keep requests with the same name but
    # different hierarchies separate
    for (group_hierarchy, request_name), group in df.groupby(
        ["group_hierarchy", "request_name"], dropna=False
    ):
        # Create the full path for display/storage
        full_path = (
            f"{group_hierarchy}|{request_name}"
            if pd.notna(group_hierarchy) and group_hierarchy
            else request_name
        )
        response_times = group["response_time_ms"].tolist()
        timestamps = list(zip(group["start_timestamp"], group["end_timestamp"], strict=False))
        percentiles = calculate_percentiles(response_times, method)
        mean = np.mean(response_times)
        count = len(response_times)

        request_data = RequestData(
            response_times=response_times,
            timestamps=timestamps,
            percentiles=percentiles,
            mean=mean,
            count=count,
        )

        gatling_data.add_request_data(
            simulation, run_timestamp, full_path, request_data, directory, suffix
        )


def plot_percentiles_stacked(gatling_data: GatlingData) -> go.Figure:
    """Plot stacked bar chart of percentiles across runs."""

    if not gatling_data.data:
        return go.Figure()

    simulations = gatling_data.get_simulations()
    all_requests = set()
    for simulation in simulations:
        for run_timestamp in gatling_data.get_runs(simulation):
            all_requests.update(gatling_data.get_requests(simulation, run_timestamp))
    all_requests = sorted(all_requests)

    # Default to first simulation and first request
    default_simulation = simulations[0] if simulations else None
    default_request = all_requests[0] if all_requests else None

    if not default_simulation or not default_request:
        return go.Figure()

    fig = go.Figure()

    trace_mapping = {}
    trace_idx = 0

    for simulation in simulations:
        for request_name in all_requests:
            # Check if this simulation has this request
            runs_with_request = []
            for run_timestamp in gatling_data.get_runs(simulation):
                if request_name in gatling_data.get_requests(simulation, run_timestamp):
                    runs_with_request.append(run_timestamp)

            if not runs_with_request:
                continue

            # Prepare data for this simulation-request combination
            run_timestamps = []
            run_hover_labels = []
            run_directories = []
            run_directory_names = []
            run_numbers = []
            percentiles_data = {
                "min": [],
                "50th": [],
                "75th": [],
                "95th": [],
                "99th": [],
                "max": [],
            }

            for run_number, run_timestamp in enumerate(runs_with_request, 1):
                request_data = gatling_data.get_request_data(
                    simulation, run_timestamp, request_name
                )
                if request_data:
                    run_timestamps.append(run_timestamp)
                    run_data = gatling_data.get_run_data(simulation, run_timestamp)
                    hover_label = run_data.formatted_timestamp if run_data else run_timestamp
                    run_hover_labels.append(hover_label)
                    run_directories.append(str(run_data.directory.absolute()))
                    run_directory_names.append(run_data.directory.name)
                    run_numbers.append(run_number)
                    for key in percentiles_data:
                        percentiles_data[key].append(request_data.percentiles[key])

            if not run_timestamps:
                continue

            # Convert to numpy arrays for easier calculation
            min_vals = np.array(percentiles_data["min"])
            p50_vals = np.array(percentiles_data["50th"])
            p75_vals = np.array(percentiles_data["75th"])
            p95_vals = np.array(percentiles_data["95th"])
            p99_vals = np.array(percentiles_data["99th"])
            max_vals = np.array(percentiles_data["max"])

            # Calculate stack heights (differences between percentiles)
            range_0_50 = p50_vals - min_vals
            range_50_75 = p75_vals - p50_vals
            range_75_95 = p95_vals - p75_vals
            range_95_99 = p99_vals - p95_vals
            range_99_max = max_vals - p99_vals

            # Determine visibility
            is_default = simulation == default_simulation and request_name == default_request

            start_trace_idx = trace_idx

            # Create stacked bars for each percentile range
            ranges = [
                ("0-50th", range_0_50, min_vals),
                ("50th-75th", range_50_75, p50_vals),
                ("75th-95th", range_75_95, p75_vals),
                ("95th-99th", range_95_99, p95_vals),
                ("99th-max", range_99_max, p99_vals),
            ]

            for range_name, height_vals, base_vals in ranges:
                fig.add_trace(
                    go.Bar(
                        x=list(range(1, len(run_timestamps) + 1)),  # start run number at 1
                        y=height_vals,
                        base=base_vals,
                        name=range_name,
                        marker_color=percentile_range_colors[range_name],
                        visible=is_default,
                        showlegend=is_default,
                        hovertemplate=(
                            f"<b>{range_name}</b><br>"
                            "Range: %{base:.0f}ms - %{customdata[2]:.0f}ms<br>"
                            "Run number: %{customdata[0]}<br>"
                            "Run timestamp: %{customdata[1]}<br>"
                            "Run directory: %{customdata[4]}<br>"
                            "Click to copy run directory path<br>"
                            "<extra></extra>"
                        ),
                        customdata=list(
                            zip(
                                run_numbers,
                                run_hover_labels,
                                base_vals + height_vals,
                                run_directories,
                                run_directory_names,
                                strict=False,
                            )
                        ),
                    )
                )
                trace_idx += 1

            # Add mean line immediately after bars for this request
            mean_values = [
                gatling_data.get_request_data(simulation, run_timestamp, request_name).mean
                for run_timestamp in runs_with_request
            ]

            fig.add_trace(
                go.Scatter(
                    x=list(range(1, len(runs_with_request) + 1)),
                    y=mean_values,
                    mode="lines+markers",
                    line=dict(color=mean_color, width=line_width),
                    marker=dict(size=8, color=mean_color),
                    name="Mean",
                    visible=is_default,
                    showlegend=is_default,
                    hovertemplate="<b>Mean</b><br>" + "%{y:.0f}ms<br>" + "<extra></extra>",
                )
            )
            trace_idx += 1

            trace_mapping[(simulation, request_name)] = (start_trace_idx, trace_idx)

    defaults = {"simulation": default_simulation, "request": default_request}
    updatemenus = create_plot_dropdowns(
        "stacked", gatling_data, trace_mapping, len(fig.data), defaults
    )

    # Create x-axis title with directory path
    xaxis_title = "Runs"
    if gatling_data.report_directory:
        xaxis_title = f"Runs of {gatling_data.report_directory.name}"

    fig.update_layout(
        xaxis_title=xaxis_title,
        yaxis_title="Response Time (ms)",
        barmode="relative",  # this creates the stacking effect
        template="plotly_dark",
        font=dict(size=12),
        showlegend=True,
        legend=dict(
            orientation="v", yanchor="top", y=0.8, xanchor="left", x=1.02, title="Percentile Ranges"
        ),
        updatemenus=updatemenus,
    )

    return fig


def plot_percentiles(gatling_data: GatlingData) -> go.Figure:
    """Plot histogram of response times highlighting percentile ranges."""
    fig = make_subplots(rows=1, cols=1)

    if not gatling_data.data:
        return fig

    # Get all simulations, runs, and requests (already sorted)
    simulations = gatling_data.get_simulations()

    # Default to first simulation, first run, first request for initial display
    default_simulation = simulations[0] if simulations else None
    default_run = None
    default_request = None

    if default_simulation:
        runs = gatling_data.get_runs(default_simulation)
        default_run = runs[0] if runs else None

        if default_run:
            requests = gatling_data.get_requests(default_simulation, default_run)
            default_request = requests[0] if requests else None

    if not default_simulation or not default_run or not default_request:
        return fig

    # Create traces for all combinations (initially all hidden except default)
    trace_mapping = {}  # Maps (simulation, run, request) to trace indices
    trace_idx = 0

    for simulation in simulations:
        for run_timestamp in gatling_data.get_runs(simulation):
            for request_name in gatling_data.get_requests(simulation, run_timestamp):
                request_data = gatling_data.get_request_data(
                    simulation, run_timestamp, request_name
                )

                if not request_data or not request_data.response_times:
                    continue

                response_times = request_data.response_times
                percentiles = request_data.percentiles

                # Determine if this should be initially visible
                is_default = (
                    simulation == default_simulation
                    and run_timestamp == default_run
                    and request_name == default_request
                )

                # Calculate histogram
                counts, bin_edges = np.histogram(response_times, bins=50)
                bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2

                # Get run directory for click-to-copy functionality
                run_data = gatling_data.get_run_data(simulation, run_timestamp)
                run_directory = str(run_data.directory.absolute())

                # Calculate percentage for each bucket
                bucket_percentages = [(count / len(response_times)) * 100 for count in counts]

                # Create bar trace
                fig.add_trace(
                    go.Bar(
                        x=bin_centers,
                        y=counts,
                        width=np.diff(bin_edges),
                        name=f"{simulation}_{run_timestamp}_{request_name}_histogram",
                        visible=is_default,
                        opacity=0.7,
                        marker_color="lightblue",
                        hovertemplate="<b>%{x:.0f}ms</b><br>"
                        + f"Requests in bucket: %{{customdata[0]}}/{len(response_times)} "
                        + "(%{customdata[2]:.0f}%)<br>"
                        + "Click to copy run directory path<br>"
                        + "<extra></extra>",
                        customdata=list(
                            zip(
                                counts,
                                [run_directory] * len(counts),
                                bucket_percentages,
                                strict=False,
                            )
                        ),
                        showlegend=False,
                    )
                )

                start_trace_idx = trace_idx
                trace_idx += 1

                for percentile_name, color in percentile_line_colors.items():
                    if percentile_name in percentiles:
                        fig.add_trace(
                            go.Scatter(
                                x=[percentiles[percentile_name], percentiles[percentile_name]],
                                y=[0, max(counts) if counts.size > 0 else 100],
                                mode="lines",
                                line=dict(color=color, width=line_width, dash="dash"),
                                name=f"{percentile_name}: {percentiles[percentile_name]:.0f}ms",
                                visible=is_default,
                                hovertemplate=f"<b>{percentile_name} Percentile</b><br>"
                                + f"{percentiles[percentile_name]:.0f}ms<br>"
                                + "<extra></extra>",
                                showlegend=False,
                            )
                        )
                        trace_idx += 1

                # Add mean line
                mean_value = request_data.mean
                fig.add_trace(
                    go.Scatter(
                        x=[mean_value, mean_value],
                        y=[0, max(counts) if counts.size > 0 else 100],
                        mode="lines",
                        line=dict(color=mean_color, width=line_width, dash="solid"),
                        name=f"Mean: {mean_value:.0f}ms",
                        visible=is_default,
                        hovertemplate="<b>Mean</b><br>"
                        + f"{mean_value:.0f}ms<br>"
                        + "<extra></extra>",
                        showlegend=False,
                    )
                )
                trace_idx += 1

                trace_mapping[(simulation, run_timestamp, request_name)] = (
                    start_trace_idx,
                    trace_idx,
                )

    defaults = {
        "simulation": default_simulation,
        "run": default_run,
        "request": default_request,
    }
    updatemenus = create_plot_dropdowns(
        "distribution", gatling_data, trace_mapping, len(fig.data), defaults
    )

    # Create x-axis title with directory path
    xaxis_title = "Response Time (ms)"
    if gatling_data.report_directory:
        xaxis_title = f"Response Time (ms) of {gatling_data.report_directory.name}"

    fig.update_layout(
        xaxis_title=xaxis_title,
        yaxis_title="Number of requests",
        template="plotly_dark",
        showlegend=False,
        font=dict(size=14),
        xaxis=dict(
            title=dict(font=dict(size=16)),
            showticklabels=True,
            tickmode="linear",
            tick0=0,
            dtick=10,
            tickfont=dict(size=12),
            ticks="outside",
            ticklen=5,
            tickwidth=1,
            tickcolor="white",
        ),
        yaxis=dict(title=dict(font=dict(size=16))),
        updatemenus=updatemenus,
    )

    return fig


def plot_scatter(gatling_data: GatlingData) -> go.Figure:
    """Plot response times."""

    fig = go.Figure()

    if not gatling_data.data:
        return fig

    simulations = gatling_data.get_simulations()

    # Default to first simulation, first run, first request for initial display
    default_simulation = simulations[0] if simulations else None
    default_run = None
    default_request = None

    if default_simulation:
        runs = gatling_data.get_runs(default_simulation)
        default_run = runs[0] if runs else None

        if default_run:
            requests = gatling_data.get_requests(default_simulation, default_run)
            default_request = requests[0] if requests else None

    if not default_simulation or not default_run or not default_request:
        return fig

    # Create traces for all combinations (initially all hidden except default)
    trace_mapping = {}  # Maps (simulation, run, request) to trace index
    trace_idx = 0

    for simulation in simulations:
        for run_timestamp in gatling_data.get_runs(simulation):
            for request_name in gatling_data.get_requests(simulation, run_timestamp):
                request_data = gatling_data.get_request_data(
                    simulation, run_timestamp, request_name
                )

                if not request_data or not request_data.timestamps:
                    continue

                # Extract start timestamps, end timestamps and response times
                start_timestamps, end_timestamps = zip(*request_data.timestamps, strict=False)
                response_times = request_data.response_times

                # Get run directory for click-to-copy functionality
                run_data = gatling_data.get_run_data(simulation, run_timestamp)
                run_directory = str(run_data.directory.absolute())

                # Create request numbers (1-indexed)
                request_numbers = list(range(1, len(response_times) + 1))

                # Determine if this should be initially visible
                is_default = (
                    simulation == default_simulation
                    and run_timestamp == default_run
                    and request_name == default_request
                )

                start_trace_idx = trace_idx

                fig.add_trace(
                    go.Scatter(
                        x=end_timestamps,
                        y=response_times,
                        mode="markers",
                        name=f"{simulation}_{run_timestamp}_{request_name}",
                        visible=is_default,
                        marker=dict(size=6, opacity=0.7, color="lightblue"),
                        hovertemplate=(
                            "<b>%{y:.0f}ms</b><br>"
                            "Request number: %{customdata[0]}<br>"
                            "Request end time: %{x}<br>"
                            "Click to copy run directory path<br>"
                            "<extra></extra>"
                        ),
                        customdata=list(
                            zip(
                                request_numbers,
                                [run_directory] * len(response_times),
                                strict=False,
                            )
                        ),
                        showlegend=False,
                    )
                )
                trace_idx += 1

                # Add percentile lines (horizontal)
                percentiles = request_data.percentiles
                x_range = [min(end_timestamps), max(end_timestamps)]

                for percentile_name, color in percentile_line_colors.items():
                    if percentile_name in percentiles:
                        fig.add_trace(
                            go.Scatter(
                                x=x_range,
                                y=[percentiles[percentile_name], percentiles[percentile_name]],
                                mode="lines",
                                line=dict(color=color, width=line_width, dash="dash"),
                                name=f"{percentile_name}: {percentiles[percentile_name]:.0f}ms",
                                visible=is_default,
                                hovertemplate=f"<b>{percentile_name} Percentile</b><br>"
                                + f"{percentiles[percentile_name]:.0f}ms<br>"
                                + "<extra></extra>",
                                showlegend=False,
                            )
                        )
                        trace_idx += 1

                # Add mean line (horizontal)
                mean_value = request_data.mean
                fig.add_trace(
                    go.Scatter(
                        x=x_range,
                        y=[mean_value, mean_value],
                        mode="lines",
                        line=dict(color=mean_color, width=line_width, dash="solid"),
                        name=f"Mean: {mean_value:.0f}ms",
                        visible=is_default,
                        hovertemplate="<b>Mean</b><br>"
                        + f"{mean_value:.0f}ms<br>"
                        + "<extra></extra>",
                        showlegend=False,
                    )
                )
                trace_idx += 1

                trace_mapping[(simulation, run_timestamp, request_name)] = (
                    start_trace_idx,
                    trace_idx,
                )

    defaults = {
        "simulation": default_simulation,
        "run": default_run,
        "request": default_request,
    }
    updatemenus = create_plot_dropdowns(
        "scatter", gatling_data, trace_mapping, len(fig.data), defaults
    )

    # Create x-axis title with directory path
    xaxis_title = "Time"
    if gatling_data.report_directory:
        xaxis_title = f"End time of requests of {gatling_data.report_directory.name}"

    fig.update_layout(
        xaxis_title=xaxis_title,
        yaxis_title="Response Time (ms)",
        template="plotly_dark",
        showlegend=False,
        font=dict(size=14),
        xaxis=dict(
            title=dict(font=dict(size=16)),
            tickformat="%H:%M:%S",
            tickangle=45,
            showgrid=True,
            gridcolor="rgba(128, 128, 128, 0.3)",
        ),
        yaxis=dict(title=dict(font=dict(size=16))),
        updatemenus=updatemenus,
    )

    return fig


def plot_timeline(gatling_data: GatlingData) -> go.Figure:
    """Plot timeline chart showing request duration as horizontal bars."""

    fig = go.Figure()

    if not gatling_data.data:
        return fig

    simulations = gatling_data.get_simulations()

    # Default to first simulation, first run, first request for initial display
    default_simulation = simulations[0] if simulations else None
    default_run = None
    default_request = None

    if default_simulation:
        runs = gatling_data.get_runs(default_simulation)
        default_run = runs[0] if runs else None

        if default_run:
            requests = gatling_data.get_requests(default_simulation, default_run)
            default_request = requests[0] if requests else None

    if not default_simulation or not default_run or not default_request:
        return fig

    # Create traces for all combinations (initially all hidden except default)
    trace_mapping = {}  # Maps (simulation, run, request) to trace index
    trace_idx = 0
    max_duration = 0

    for simulation in simulations:
        for run_timestamp in gatling_data.get_runs(simulation):
            for request_name in gatling_data.get_requests(simulation, run_timestamp):
                request_data = gatling_data.get_request_data(
                    simulation, run_timestamp, request_name
                )

                # Extract start timestamps, end timestamps and response times
                start_timestamps, end_timestamps = zip(*request_data.timestamps, strict=False)
                response_times = request_data.response_times

                # Get run directory for click-to-copy functionality
                run_data = gatling_data.get_run_data(simulation, run_timestamp)
                run_directory = str(run_data.directory.absolute())

                # Create request numbers (1-indexed)
                request_numbers = list(range(1, len(response_times) + 1))

                # Determine if this should be initially visible
                is_default = (
                    simulation == default_simulation
                    and run_timestamp == default_run
                    and request_name == default_request
                )

                start_trace_idx = trace_idx

                # Get first request start time for this specific run
                run_start_time = start_timestamps[0]

                # Calculate max duration for tick generation
                last_request_end = (end_timestamps[-1] - run_start_time).total_seconds() * 1000
                max_duration = max(max_duration, last_request_end)

                # Create horizontal bars for each request
                fig.add_trace(
                    go.Bar(
                        base=[
                            (start - run_start_time).total_seconds() * 1000
                            for start in start_timestamps
                        ],
                        x=[
                            (end - start).total_seconds() * 1000
                            for start, end in request_data.timestamps
                        ],
                        y=request_numbers,
                        orientation="h",
                        name=f"{simulation}_{run_timestamp}_{request_name}",
                        visible=is_default,
                        marker=dict(color="lightblue", opacity=0.7),
                        hovertemplate=(
                            "Response time (ms): %{customdata[0]:.0f}ms<br>"
                            "Request start time: %{customdata[1]}<br>"
                            "Request end time: %{customdata[2]}<br>"
                            "Click to copy run directory path<br>"
                            "<extra></extra>"
                        ),
                        customdata=list(
                            zip(
                                response_times,
                                start_timestamps,
                                end_timestamps,
                                [run_directory] * len(response_times),
                                strict=False,
                            )
                        ),
                        showlegend=False,
                    )
                )
                trace_idx += 1

                trace_mapping[(simulation, run_timestamp, request_name)] = (
                    start_trace_idx,
                    trace_idx,
                )

    defaults = {
        "simulation": default_simulation,
        "run": default_run,
        "request": default_request,
    }
    updatemenus = create_plot_dropdowns(
        "timeline", gatling_data, trace_mapping, len(fig.data), defaults
    )

    fig.update_layout(
        xaxis_title="Duration (s)",
        yaxis_title="Request Number",
        template="plotly_dark",
        showlegend=False,
        font=dict(size=14),
        xaxis=dict(
            title=dict(font=dict(size=16)),
            showgrid=True,
            gridcolor="rgba(128, 128, 128, 0.3)",
            tickvals=list(range(0, int(max_duration) + 1000, 500)),
            ticktext=[f"{i / 1000:.1f}s" for i in range(0, int(max_duration) + 1000, 500)],
        ),
        yaxis=dict(
            title=dict(font=dict(size=16)),
        ),
        updatemenus=updatemenus,
    )

    return fig


def plot_scatter_all(gatling_data: GatlingData) -> go.Figure:
    """Plot response times for all runs, each run with different color."""

    fig = go.Figure()

    if not gatling_data.data:
        return fig

    simulations = gatling_data.get_simulations()

    if not simulations:
        return fig

    for simulation in simulations:
        for run_number, run_timestamp in enumerate(gatling_data.get_runs(simulation), 1):
            for request_name in gatling_data.get_requests(simulation, run_timestamp):
                request_data = gatling_data.get_request_data(
                    simulation, run_timestamp, request_name
                )

                if not request_data or not request_data.timestamps:
                    continue

                # Get response times (x-axis will be auto-generated as ordinal)
                response_times = request_data.response_times

                # Get run directory and formatted timestamp for click-to-copy functionality
                run_data = gatling_data.get_run_data(simulation, run_timestamp)
                run_directory = str(run_data.directory.absolute())
                run_directory_name = run_data.directory.name
                run_hover_label = run_data.formatted_timestamp if run_data else run_timestamp

                # Create request numbers (1-indexed)
                request_numbers = list(range(1, len(response_times) + 1))

                fig.add_trace(
                    go.Scatter(
                        y=response_times,
                        mode="markers",
                        name=f"{simulation}_{run_timestamp}_{request_name}",
                        marker=dict(size=3, opacity=0.6),
                        hovertemplate=(
                            "<b>%{y:.0f}ms</b><br>"
                            "Request number: %{customdata[0]}<br>"
                            "Run number: %{customdata[2]}<br>"
                            "Run timestamp: %{customdata[1]}<br>"
                            "Run directory: %{customdata[4]}<br>"
                            "Click to copy run directory path<br>"
                            "<extra></extra>"
                        ),
                        customdata=list(
                            zip(
                                request_numbers,
                                [run_hover_label] * len(response_times),
                                [run_number] * len(response_times),
                                [run_directory] * len(response_times),
                                [run_directory_name] * len(response_times),
                                strict=False,
                            )
                        ),
                        showlegend=False,
                    )
                )

    # Create x-axis title with directory path
    xaxis_title = "Request Number"
    if gatling_data.report_directory:
        xaxis_title = f"Request Number of {gatling_data.report_directory.name}"

    fig.update_layout(
        xaxis_title=xaxis_title,
        yaxis_title="Response Time (ms)",
        template="plotly_dark",
        showlegend=False,
        font=dict(size=14),
        xaxis=dict(
            title=dict(font=dict(size=16)),
            showgrid=True,
            gridcolor="rgba(128, 128, 128, 0.3)",
            tickmode="linear",
            tick0=0,
            dtick=10,
        ),
        yaxis=dict(title=dict(font=dict(size=16))),
    )

    return fig


def format_output(gatling_data: GatlingData) -> None:
    """Format and print results as CSV."""
    print("directory,simulation,run_timestamp,request_name,count,min,50th,75th,95th,99th,max")

    # Data is already sorted by GatlingData.finalize_ordering()
    for simulation in gatling_data.get_simulations():
        for run_timestamp in gatling_data.get_runs(simulation):
            run_data = gatling_data.get_run_data(simulation, run_timestamp)
            if run_data:
                for request_name, request_data in run_data.requests.items():
                    directory = f"{simulation}-{run_timestamp}"

                    print(
                        f"{directory},{simulation},{run_data.formatted_timestamp},{request_name},{request_data.count},"
                        f"{request_data.percentiles['min']:.0f},"
                        f"{request_data.percentiles['50th']:.0f},"
                        f"{request_data.percentiles['75th']:.0f},"
                        f"{request_data.percentiles['95th']:.0f},"
                        f"{request_data.percentiles['99th']:.0f},"
                        f"{request_data.percentiles['max']:.0f}"
                    )


def show_plot_with_clipboard(
    fig: go.Figure, report_directory: Path = None, output_file: str = None
):
    """Show plot with clipboard functionality for both interactive and HTML output modes."""
    click_js = ""
    if report_directory:
        click_js = """
        document.addEventListener('DOMContentLoaded', function() {
            var plotlyDiv = document.getElementsByClassName('plotly-graph-div')[0];
            if (plotlyDiv) {
                plotlyDiv.on('plotly_click', function(data) {
                    if (data.points.length > 0) {
                        var point = data.points[0];
                        var dirPath = point.customdata[3] || point.customdata[1] ||
                            point.customdata[0];
                        navigator.clipboard.writeText(dirPath).then(function() {
                            console.log('Run directory path copied: ' + dirPath);
                            // Show temporary notification
                            var notification = document.createElement('div');
                            notification.innerHTML = 'Directory path copied to clipboard!';
                            notification.style.cssText =
                                'position: fixed; top: 20px; right: 20px; ' +
                                'background: #4CAF50; color: white; padding: 10px; ' +
                                'border-radius: 5px; z-index: 1000; ' +
                                'font-family: Arial; font-size: 14px;';
                            document.body.appendChild(notification);
                            setTimeout(function() {
                                if (document.body.contains(notification)) {
                                    document.body.removeChild(notification);
                                }
                            }, 2000);
                        }).catch(function(err) {
                            console.error('Failed to copy directory path: ', err);
                        });
                    }
                });
            }
        });
        """

    if output_file:
        fig.write_html(output_file, post_script=click_js if click_js else None)
        print(f"Plot saved to {output_file}")
    else:
        # For interactive mode, create a temporary HTML file with JavaScript
        if click_js:
            import tempfile
            import webbrowser

            with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as tmp:
                fig.write_html(tmp.name, post_script=click_js)
                webbrowser.open(f"file://{tmp.name}")
                print(f"Interactive plot opened in browser: {tmp.name}")
        else:
            fig.show()


def main():
    """CLI entry point - can be called as 'gstat' command."""
    try:
        _main()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _main():
    """Internal main function."""
    parser = argparse.ArgumentParser(
        description="Calculate percentiles from Gatling simulation.csv files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Plot Types:
  distribution   Histogram showing the full distribution of response times with percentile lines.
                 Good for: Understanding the shape of your distribution, identifying clusters
                 and outliers, seeing which response times are most common.

  stacked        Stacked bar chart showing differences between percentiles (0th, 50th, 75th,
                 95th, 99th, 100th) across multiple runs.
                 Good for: Comparing performance across runs, spotting regressions, identifying
                 tail latency trends, visualizing consistency (taller = more variable).
                 Note: Boxes disappear when percentiles have identical values.

  scatter        Scatter plot of individual response times over the duration of a run.
                 Good for: Identifying patterns over time, spotting warmup periods, detecting
                 gradual degradation, finding sudden spikes or drops in performance.

  scatter-all    Overlay scatter plot showing all runs on the same chart, color-coded by run.
                 Good for: Comparing patterns across multiple runs, spotting systematic
                 differences, identifying which runs had outliers or different behavior.

  timeline       Horizontal bar chart showing when each request started and how long it took.
                 Good for: Understanding request concurrency, visualizing load patterns, seeing
                 gaps between requests, analyzing request scheduling and overlap.

Examples:
  # Output CSV statistics
  gstat ./samples/

  # Single report directory with plot
  gstat --plot distribution ./samples/trackerexportertests-20250627064559771

  # Multiple report directories with distribution plot
  gstat --plot distribution ./samples/

  # Stacked percentile bar chart
  gstat --plot stacked ./samples/

  # Scatter plot of response times over time
  gstat --plot scatter ./samples/

  # Timeline plot showing request duration bars
  gstat --plot timeline ./samples/

  # Exclude directories containing a specific string
  gstat --exclude warmup ./samples/
  gstat --plot stacked --exclude warmup ./samples/
        """,
    )
    parser.add_argument(
        "report_directory",
        type=Path,
        help="Directory containing simulation.csv file, or directory with multiple reports",
    )
    parser.add_argument(
        "--plot",
        choices=["distribution", "stacked", "scatter", "scatter-all", "timeline"],
        help="Generate interactive plot instead of CSV output",
    )
    parser.add_argument(
        "--output", "-o", type=Path, help="Output file for plot (default: show in browser)"
    )
    parser.add_argument(
        "--method",
        choices=["exact", "tdigest"],
        default="exact",
        help="Percentile calculation method (default: exact)",
    )
    parser.add_argument(
        "--exclude",
        type=str,
        help="Exclude directories containing this string (e.g., 'warmup')",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"gstat {__version__} (git: {__git_sha__})",
    )
    argcomplete.autocomplete(parser)
    args = parser.parse_args()

    if not args.report_directory.exists():
        print(f"Directory does not exist: {args.report_directory}", file=sys.stderr)
        sys.exit(1)

    if not args.report_directory.is_dir():
        print(f"Path is not a directory: {args.report_directory}", file=sys.stderr)
        sys.exit(1)

    gatling_data = load_gatling_data(args.report_directory, args.method, args.exclude)

    if args.plot:
        match args.plot:
            case "stacked":
                fig = plot_percentiles_stacked(gatling_data)
            case "scatter":
                fig = plot_scatter(gatling_data)
            case "scatter-all":
                fig = plot_scatter_all(gatling_data)
            case "timeline":
                fig = plot_timeline(gatling_data)
            case _:
                fig = plot_percentiles(gatling_data)

        show_plot_with_clipboard(fig, gatling_data.report_directory, args.output)
    else:
        format_output(gatling_data)


if __name__ == "__main__":
    main()
