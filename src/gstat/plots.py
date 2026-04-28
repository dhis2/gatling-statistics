"""Plotly figure builders and dropdown wiring for Gatling reports."""

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .gatling import GatlingRuns

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
    gatling_data: GatlingRuns,
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
            items = gatling_data.get_run_timestamps(defaults["simulation"])

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
    gatling_data: GatlingRuns, defaults: dict, plot_type: str
) -> list[str]:
    """Get all request names for the plot type."""
    if plot_type == "stacked":
        # Stacked uses all requests across all simulations
        all_requests = set()
        for simulation in gatling_data.get_simulations():
            for run_timestamp in gatling_data.get_run_timestamps(simulation):
                all_requests.update(gatling_data.get_requests(simulation, run_timestamp))
        return sorted(all_requests)
    else:
        # Distribution/scatter use requests for default simulation/run
        return gatling_data.get_requests(defaults["simulation"], defaults["run"])


def _get_simulation_visibility(
    simulation: str,
    gatling_data: GatlingRuns,
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
        sim_runs = gatling_data.get_run_timestamps(simulation)
        if sim_runs:
            first_run = sim_runs[0]
            sim_requests = gatling_data.get_requests(simulation, first_run)
            if sim_requests:
                first_request = sim_requests[0]
                key = (simulation, first_run, first_request)
                if key in trace_mapping:
                    if (
                        plot_type == "distribution"
                        or plot_type == "scatter"
                        or plot_type == "timeline"
                    ):
                        start_idx, end_idx = trace_mapping[key]
                        for j in range(start_idx, end_idx):
                            if j < len(visibility):
                                visibility[j] = True

    return visibility


def _get_request_visibility(
    request: str,
    gatling_data: GatlingRuns,
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
    gatling_data: GatlingRuns,
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


def _get_run_label(run: str, gatling_data: GatlingRuns, simulation: str) -> str:
    """Get formatted label for a run timestamp, including suffix if present."""
    run_data = gatling_data.get_run(simulation, run)
    if not run_data:
        return run

    label = run_data.formatted_timestamp
    if run_data.suffix:
        label = f"{label} ({run_data.suffix})"
    return label


def plot_percentiles_stacked(gatling_data: GatlingRuns) -> go.Figure:
    """Plot stacked bar chart of percentiles across runs."""

    if not gatling_data.data:
        return go.Figure()

    simulations = gatling_data.get_simulations()
    all_requests = set()
    for simulation in simulations:
        for run_timestamp in gatling_data.get_run_timestamps(simulation):
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
            for run_timestamp in gatling_data.get_run_timestamps(simulation):
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
                request_data = gatling_data.get_request(simulation, run_timestamp, request_name)
                if request_data:
                    run_timestamps.append(run_timestamp)
                    run_data = gatling_data.get_run(simulation, run_timestamp)
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
                gatling_data.get_request(simulation, run_timestamp, request_name).mean
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


def plot_percentiles(gatling_data: GatlingRuns) -> go.Figure:
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
        runs = gatling_data.get_run_timestamps(default_simulation)
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
        for run_timestamp in gatling_data.get_run_timestamps(simulation):
            for request_name in gatling_data.get_requests(simulation, run_timestamp):
                request_data = gatling_data.get_request(simulation, run_timestamp, request_name)

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
                run_data = gatling_data.get_run(simulation, run_timestamp)
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


def plot_scatter(gatling_data: GatlingRuns) -> go.Figure:
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
        runs = gatling_data.get_run_timestamps(default_simulation)
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
        for run_timestamp in gatling_data.get_run_timestamps(simulation):
            for request_name in gatling_data.get_requests(simulation, run_timestamp):
                request_data = gatling_data.get_request(simulation, run_timestamp, request_name)

                if not request_data or not request_data.timestamps:
                    continue

                # Extract start timestamps, end timestamps and response times
                start_timestamps, end_timestamps = zip(*request_data.timestamps, strict=False)
                response_times = request_data.response_times

                # Get run directory for click-to-copy functionality
                run_data = gatling_data.get_run(simulation, run_timestamp)
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


def plot_timeline(gatling_data: GatlingRuns) -> go.Figure:
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
        runs = gatling_data.get_run_timestamps(default_simulation)
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
        for run_timestamp in gatling_data.get_run_timestamps(simulation):
            for request_name in gatling_data.get_requests(simulation, run_timestamp):
                request_data = gatling_data.get_request(simulation, run_timestamp, request_name)

                if not request_data or not request_data.timestamps:
                    continue

                # Extract start timestamps, end timestamps and response times
                start_timestamps, end_timestamps = zip(*request_data.timestamps, strict=False)
                response_times = request_data.response_times

                # Get run directory for click-to-copy functionality
                run_data = gatling_data.get_run(simulation, run_timestamp)
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


def plot_scatter_all(gatling_data: GatlingRuns) -> go.Figure:
    """Plot response times for all runs, each run with different color."""

    fig = go.Figure()

    if not gatling_data.data:
        return fig

    simulations = gatling_data.get_simulations()

    if not simulations:
        return fig

    for simulation in simulations:
        for run_number, run_timestamp in enumerate(gatling_data.get_run_timestamps(simulation), 1):
            for request_name in gatling_data.get_requests(simulation, run_timestamp):
                request_data = gatling_data.get_request(simulation, run_timestamp, request_name)

                if not request_data or not request_data.timestamps:
                    continue

                # Get response times (x-axis will be auto-generated as ordinal)
                response_times = request_data.response_times

                # Get run directory and formatted timestamp for click-to-copy functionality
                run_data = gatling_data.get_run(simulation, run_timestamp)
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
