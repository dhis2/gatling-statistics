"""Gatling domain: report types and the parsers/loaders that produce them."""

import re
import sys
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd


def parse_simulation_csv(csv_path: Path) -> pd.DataFrame:
    """Parse simulation.csv and return all request records (OK and KO).

    Percentiles are computed over the full population on purpose: when KOs are
    present the percentile shifts regardless of which subset you'd pick (OK-only
    biases toward survivors, KO-only is a failure-mode artifact). Surfacing the
    KO count alongside lets the reader judge whether a row is comparable.

    Example of a simulation.csv

    record_type,scenario_name,group_hierarchy,request_name,status,start_timestamp,end_timestamp,response_time_ms,error_message,event_type,duration_ms,cumulated_response_time_ms,is_incoming
    request,,,events,OK,1751199294083,1751199294256,173,,,,,false
    """
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"Error reading CSV file {csv_path}: {e}", file=sys.stderr)
        sys.exit(1)

    request_df = df[df["record_type"] == "request"].copy()

    if request_df.empty:
        print(f"No request records found in {csv_path}", file=sys.stderr)
        sys.exit(1)

    request_df["start_timestamp"] = pd.to_datetime(request_df["start_timestamp"], unit="ms")
    request_df["end_timestamp"] = pd.to_datetime(request_df["end_timestamp"], unit="ms")
    request_df["response_time_ms"] = pd.to_numeric(request_df["response_time_ms"])

    return request_df


def calculate_percentiles(response_times: list[float]) -> dict[str, float]:
    """Calculate percentiles over the full sample using numpy.

    Uses the linear interpolation method (numpy default, also known as "type 7"),
    which is what Prometheus, Grafana, and most monitoring tools use.
    Percentiles may be fractional (e.g. 950.05 ms) since they interpolate between
    adjacent observations.
    """
    if not response_times:
        return {"min": 0, "50th": 0, "75th": 0, "95th": 0, "99th": 0, "max": 0}

    # https://numpy.org/doc/stable/reference/generated/numpy.percentile.html#numpy-percentile
    percentiles = np.percentile(response_times, [0, 50, 75, 95, 99, 100], method="linear")

    return {
        "min": percentiles[0],
        "50th": percentiles[1],
        "75th": percentiles[2],
        "95th": percentiles[3],
        "99th": percentiles[4],
        "max": percentiles[5],
    }


class GatlingRequest(NamedTuple):
    """Data for a specific request in a specific run.

    `req_per_sec` is `count / run.duration_seconds` (the request's share of the
    whole-run measured window). Matches Gatling's HTML `Cnt/s` column. Computed
    once at load time so consumers don't need to know the divisor.
    """

    response_times: list[float]
    timestamps: list[tuple[datetime, datetime]]  # (start, end)
    percentiles: dict[str, float]
    mean: float
    count: int
    ok_count: int
    ko_count: int
    req_per_sec: float


@dataclass(frozen=True, slots=True)
class GatlingRun:
    """Data for a complete simulation run.

    Constructed once by the loader with all requests already in Gatling HTML
    report order. Treat as read-only.

    `duration_seconds` is the actual measured window of the run (max end_timestamp
    minus min start_timestamp across every request in the run, OK + KO). This is
    the same denominator Gatling's HTML uses for `Cnt/s`, so dividing a request's
    `count` by this value matches the throughput Gatling reports.
    """

    raw_timestamp: str
    formatted_timestamp: str
    datetime_timestamp: datetime
    directory: Path
    suffix: str
    requests: OrderedDict[str, GatlingRequest]
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class GatlingRuns:
    """Unified data structure for all Gatling performance data.

    Structure: {simulation: {run_timestamp: GatlingRun}}, sorted at construction.
    Treat as read-only.
    """

    report_directory: Path | None
    data: OrderedDict[str, OrderedDict[str, GatlingRun]]

    def get_simulations(self) -> list[str]:
        """Get all simulation names in sorted order."""
        return list(self.data.keys())

    def get_run_timestamps(self, simulation: str) -> list[str]:
        """Get all run timestamps for a simulation in sorted order."""
        return list(self.data.get(simulation, {}).keys())

    def get_requests(self, simulation: str, run_timestamp: str) -> list[str]:
        """Get all request names for a simulation run in sorted order."""
        run_data = self.data.get(simulation, {}).get(run_timestamp)
        return list(run_data.requests.keys()) if run_data else []

    def get_request(
        self, simulation: str, run_timestamp: str, request_name: str
    ) -> GatlingRequest | None:
        """Get request data for specific simulation/run/request."""
        run_data = self.data.get(simulation, {}).get(run_timestamp)
        return run_data.requests.get(request_name) if run_data else None

    def get_run(self, simulation: str, run_timestamp: str) -> GatlingRun | None:
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


def is_multiple_reports_directory(directory: Path) -> bool:
    """Check if directory contains multiple Gatling report subdirectories.

    Looks one level down. The descent through wrapper directories is handled
    by find_report_root before this is called.
    """
    if not directory.is_dir():
        return False

    # if the directory itself contains simulation.csv = single report directory
    if (directory / "simulation.csv").exists():
        return False

    # Look for subdirectories with the pattern <simulation>-<17-digit-timestamp>
    for subdir in directory.iterdir():
        if subdir.is_dir() and parse_gating_directory_name(subdir.name):
            if (subdir / "simulation.csv").exists():
                return True

    return False


MAX_WRAPPER_DEPTH = 3


def find_report_root(directory: Path, max_depth: int = MAX_WRAPPER_DEPTH) -> Path:
    """Descend through wrapper directories to the actual Gatling report root.

    A "wrapper" is a directory that has neither simulation.csv nor any
    Gatling report subdirectory (matching <simulation>-<17-digit-timestamp>
    with simulation.csv inside) but contains exactly one non-matching
    subdirectory. Common case: `gh run download` artifacts that wrap the
    Gatling report tree under one or more outer directories.

    Stops as soon as the current directory is a single report (has
    simulation.csv) or a multi-report parent (rule 2).

    Errors when:
      * the user-provided directory is not a directory
      * descent finds multiple non-matching subdirs (ambiguous; we cannot
        guess which one the user meant)
      * descent exceeds max_depth without resolving

    Symlinks encountered during descent are not followed; an explicitly
    user-provided symlinked root is the user's choice and is honored.
    """
    if not directory.is_dir():
        raise FileNotFoundError(f"not a directory: {directory}")

    current = directory
    for _ in range(max_depth + 1):
        if (current / "simulation.csv").exists():
            return current
        if is_multiple_reports_directory(current):
            return current

        # Neither rule 1 nor rule 2 fires. Look for exactly one non-matching
        # real (non-symlink) subdirectory to descend into.
        candidates = [sub for sub in current.iterdir() if sub.is_dir() and not sub.is_symlink()]
        if not candidates:
            raise FileNotFoundError(
                f"no Gatling report found in {directory}: {current} has no "
                f"simulation.csv and no <simulation>-<timestamp> subdirectories"
            )
        if len(candidates) > 1:
            names = ", ".join(sorted(c.name for c in candidates))
            raise FileNotFoundError(
                f"ambiguous directory layout at {current}: found multiple "
                f"subdirectories ({names}); point gstat at one of them or at "
                f"a parent containing <simulation>-<timestamp> directories directly"
            )
        current = candidates[0]

    raise FileNotFoundError(
        f"no Gatling report found in {directory}: descended {max_depth} "
        f"levels without reaching a simulation.csv or a directory of "
        f"<simulation>-<timestamp> subdirectories"
    )


def load_gatling_data(directory: Path, exclude: str = None) -> GatlingRuns:
    """Load all Gatling data from directory, handling both single and multi-directory cases.

    Accepts:
      * a single Gatling report directory (containing simulation.csv directly), or
      * a directory containing one or more <simulation>-<timestamp> report
        subdirectories, or
      * an outer wrapper directory (e.g. `gh run download` output) that nests
        one of the above up to a few levels deep.

    Builds an immutable GatlingRuns with simulations and runs sorted; consumers
    can rely on the data being complete and ordered.
    """
    try:
        report_root = find_report_root(directory)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    raw: dict[str, dict[str, GatlingRun]] = {}

    def ingest(subdir: Path) -> None:
        loaded = _load_single_directory(subdir)
        if loaded is None:
            return
        simulation, run_timestamp, run_data = loaded
        raw.setdefault(simulation, {})[run_timestamp] = run_data

    if is_multiple_reports_directory(report_root):
        for subdir in report_root.iterdir():
            if not subdir.is_dir():
                continue

            # Skip directories containing the exclude string
            if exclude and exclude in subdir.name:
                continue

            try:
                ingest(subdir)
            except Exception as e:
                print(f"Warning: Error processing {subdir}: {e}", file=sys.stderr)
                continue
    else:
        ingest(report_root)

    if not raw:
        print(f"No valid simulation data found in {directory}", file=sys.stderr)
        sys.exit(1)

    sorted_data: OrderedDict[str, OrderedDict[str, GatlingRun]] = OrderedDict(
        (sim, OrderedDict(sorted(runs.items()))) for sim, runs in sorted(raw.items())
    )
    return GatlingRuns(report_directory=directory, data=sorted_data)


def order_requests_gatling_html(df: pd.DataFrame) -> list[tuple[str, str]]:
    """Return (group_hierarchy, request_name) keys in Gatling HTML report order.

    Gatling's HTML statistics table renders, at each group level, all nested
    subgroups first (recursively) and then leaf requests. Within each bucket the
    order is the order of first appearance in simulation.csv: glog-cli writes
    one CSV row per record in simulation.log, in log order, which is the same
    order Gatling's own LinkedHashMap-backed GroupContainer ingests them for
    the HTML report. Top-level (groupless) requests come last, after every
    hierarchy has been rendered, matching how the root GroupContainer is walked.

    `df` must have `group_hierarchy` (pipe-separated, "" for no group) and
    `request_name` columns, in CSV order.
    """

    class Node:
        __slots__ = ("subgroups", "leaves", "_seen_leaves")

        def __init__(self):
            self.subgroups: OrderedDict[str, Node] = OrderedDict()
            self.leaves: list[str] = []
            self._seen_leaves: set[str] = set()

    root = Node()
    for gh, rn in zip(df["group_hierarchy"], df["request_name"], strict=False):
        parts = gh.split("|") if gh else []
        node = root
        for part in parts:
            if part not in node.subgroups:
                node.subgroups[part] = Node()
            node = node.subgroups[part]
        if rn not in node._seen_leaves:
            node._seen_leaves.add(rn)
            node.leaves.append(rn)

    ordered: list[tuple[str, str]] = []

    def walk(node: Node, hierarchy: list[str]) -> None:
        for name, child in node.subgroups.items():
            walk(child, hierarchy + [name])
        gh = "|".join(hierarchy)
        for leaf in node.leaves:
            ordered.append((gh, leaf))

    walk(root, [])
    return ordered


def _load_single_directory(directory: Path) -> tuple[str, str, GatlingRun] | None:
    """Load Gatling data from a directory directly containing one simulation.csv.

    Returns (simulation, run_timestamp, GatlingRun) ready to be inserted into
    GatlingRuns, or None if the directory has no simulation.csv to read.
    """
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

    # Iterate in Gatling HTML report order. See order_requests_gatling_html.
    df["group_hierarchy"] = df["group_hierarchy"].fillna("")
    ordered_keys = order_requests_gatling_html(df)
    groups = dict(list(df.groupby(["group_hierarchy", "request_name"], sort=False)))

    # Actual measured window for the whole run (matches Gatling's `Cnt/s` denominator).
    duration_seconds = (df["end_timestamp"].max() - df["start_timestamp"].min()).total_seconds()

    requests: OrderedDict[str, GatlingRequest] = OrderedDict()
    for group_hierarchy, request_name in ordered_keys:
        group = groups[(group_hierarchy, request_name)]
        # Compose the display path using Gatling's HTML separator (" / "), with
        # the inner "|" from glog's CSV (nested groups) swapped to " / " as well.
        full_path = (
            f"{group_hierarchy.replace('|', ' / ')} / {request_name}"
            if group_hierarchy
            else request_name
        )
        response_times = group["response_time_ms"].tolist()
        timestamps = list(zip(group["start_timestamp"], group["end_timestamp"], strict=False))
        percentiles = calculate_percentiles(response_times)
        mean = np.mean(response_times)
        count = len(response_times)
        ok_count = int((group["status"] == "OK").sum())
        ko_count = count - ok_count
        req_per_sec = count / duration_seconds if duration_seconds > 0 else 0.0

        requests[full_path] = GatlingRequest(
            response_times=response_times,
            timestamps=timestamps,
            percentiles=percentiles,
            mean=mean,
            count=count,
            ok_count=ok_count,
            ko_count=ko_count,
            req_per_sec=req_per_sec,
        )

    run_data = GatlingRun(
        raw_timestamp=run_timestamp,
        formatted_timestamp=format_timestamp(run_timestamp),
        datetime_timestamp=parse_gatling_directory_timestamp(run_timestamp),
        directory=directory,
        suffix=suffix,
        requests=requests,
        duration_seconds=duration_seconds,
    )
    return simulation, run_timestamp, run_data
