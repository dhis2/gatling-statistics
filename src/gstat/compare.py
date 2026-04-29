"""CSV output and Markdown comparison rendering across runs."""

import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from .gatling import GatlingRuns, calculate_percentiles, load_gatling_data


class CompareInput(NamedTuple):
    """One run participating in a comparison."""

    path: Path
    label: str
    percentiles: dict[str, dict[str, float]]  # {request_name: {percentile_key: value}}
    ok_ko_counts: dict[str, tuple[int, int]]  # {request_name: (ok_count, ko_count)}
    req_per_sec: dict[str, float]  # {request_name: throughput}


@dataclass(slots=True)
class GatlingCombinedRequest:
    """Per-request data combined across all simulations and runs of one input.

    Mutable accumulator: combine_request_data extends `response_times` and
    increments the counts in place as it walks the runs.

    `duration_seconds` is the sum of the per-run measured windows for every run
    that contributed to this request. Summing (rather than max-end - min-start
    across runs) is the right denominator for throughput because runs are not
    contiguous in wall-clock time: a 5-minute warmup followed by a 10-minute
    main run is 15 minutes of "active load", not whatever gap separates the two.
    """

    response_times: list[float]
    ok_count: int
    ko_count: int
    duration_seconds: float

    @property
    def req_per_sec(self) -> float:
        if self.duration_seconds <= 0:
            return 0.0
        return len(self.response_times) / self.duration_seconds


def combine_request_data(gatling_data: GatlingRuns) -> dict[str, GatlingCombinedRequest]:
    """Combine response times and OK/KO counts across all simulations and runs.

    Walks request data in the order GatlingRuns provides (Gatling's HTML report
    order), so dict insertion order is preserved for consumers that iterate.
    """
    combined: dict[str, GatlingCombinedRequest] = {}
    for simulation in gatling_data.get_simulations():
        for run_timestamp in gatling_data.get_run_timestamps(simulation):
            run = gatling_data.get_run(simulation, run_timestamp)
            if run is None:
                continue
            for request_name in gatling_data.get_requests(simulation, run_timestamp):
                rd = run.requests.get(request_name)
                if rd is None:
                    continue
                acc = combined.get(request_name)
                if acc is None:
                    combined[request_name] = GatlingCombinedRequest(
                        response_times=list(rd.response_times),
                        ok_count=rd.ok_count,
                        ko_count=rd.ko_count,
                        duration_seconds=run.duration_seconds,
                    )
                else:
                    acc.response_times.extend(rd.response_times)
                    acc.ok_count += rd.ok_count
                    acc.ko_count += rd.ko_count
                    acc.duration_seconds += run.duration_seconds
    return combined


def collect_compare_input(path: Path, label: str | None, exclude: str | None) -> CompareInput:
    """Load one run and collapse it to {request_name: percentiles}.

    A run is a single Gatling report dir or a dir of them. If multiple report dirs
    remain after `exclude`, requests with the same name are merged by recomputing
    percentiles over the combined response times.
    """
    gatling_data = load_gatling_data(path, exclude)
    combined = combine_request_data(gatling_data)
    percentiles = {req: calculate_percentiles(c.response_times) for req, c in combined.items()}
    ok_ko_counts = {req: (c.ok_count, c.ko_count) for req, c in combined.items()}
    req_per_sec = {req: c.req_per_sec for req, c in combined.items()}

    return CompareInput(
        path=path,
        label=label or path.resolve().name,
        percentiles=percentiles,
        ok_ko_counts=ok_ko_counts,
        req_per_sec=req_per_sec,
    )


def format_change(diff: float, baseline: float) -> str:
    """Render the percent-change cell with a directional arrow.

    `:arrow_down:` means faster, `:arrow_up:` means slower.
    Returns `N/A` if baseline is 0 (percent is undefined).
    """
    if baseline == 0:
        return "N/A"
    pct = (diff / baseline) * 100
    pct_str = f"{pct:+.1f}%"
    if diff < 0:
        return f":arrow_down: {pct_str}"
    if diff > 0:
        return f":arrow_up: {pct_str}"
    return pct_str


def format_compare_markdown(
    inputs: list[CompareInput],
    percentile_keys: list[str],
    percentile_titles: dict[str, str],
    show_diff: bool = True,
    show_change: bool = True,
) -> str:
    """Render one Markdown table per percentile, plus a header naming each input."""
    if len(inputs) < 2:
        raise ValueError("compare requires at least two inputs")

    baseline = inputs[0]
    others = inputs[1:]

    lines: list[str] = []

    def header_for(role: str, label: str, dir_name: str) -> str:
        # Omit the redundant label when it defaults to the dir basename.
        if label == dir_name:
            return f"> {role}: `{dir_name}`"
        return f"> {role} ({label}): `{dir_name}`"

    lines.append(header_for("Baseline", baseline.label, baseline.path.name))
    for i, other in enumerate(others, start=2):
        lines.append(header_for(f"Run {i}", other.label, other.path.name))

    # Row order: each request appears in the order it first shows up across the
    # inputs (baseline first, then each other input's unique requests). That
    # preserves simulation.csv order rather than re-sorting by magnitude.
    ordered_requests: list[str] = []
    seen: set[str] = set()
    for inp in inputs:
        for req in inp.percentiles.keys():
            if req not in seen:
                seen.add(req)
                ordered_requests.append(req)

    def ko_pct_cell(inp: CompareInput, req: str) -> str:
        ok, ko = inp.ok_ko_counts.get(req, (0, 0))
        total = ok + ko
        if total == 0:
            return "-"
        return f"{(ko / total) * 100:.1f}%"

    def rps_cell(inp: CompareInput, req: str) -> str:
        rps = inp.req_per_sec.get(req)
        if rps is None:
            return "-"
        return f"{rps:.2f}"

    for pkey in percentile_keys:
        title = percentile_titles[pkey]

        # Header. For each input, render value | req/s | KO% so throughput sits
        # next to the percentile it describes (matches the release-note shape).
        header_cells = ["Requests", baseline.label, "req/s", "KO%"]
        align_cells = [":---", "---:", "---:", "---:"]
        for other in others:
            header_cells.extend([other.label, "req/s", "KO%"])
            align_cells.extend(["---:", "---:", "---:"])
            if show_diff:
                header_cells.append("Diff (ms)")
                align_cells.append("---:")
            if show_change:
                header_cells.append("Change")
                align_cells.append(":---")

        lines.append("")
        lines.append(f"### {title} (ms)")
        lines.append("")
        lines.append("| " + " | ".join(header_cells) + " |")
        lines.append("|" + "|".join(align_cells) + "|")

        for req in ordered_requests:
            bval = baseline.percentiles.get(req, {}).get(pkey)
            row = [req]
            row.append("-" if bval is None else f"{bval:,.0f}")
            row.append(rps_cell(baseline, req))
            row.append(ko_pct_cell(baseline, req))
            for other in others:
                oval = other.percentiles.get(req, {}).get(pkey)
                row.append("-" if oval is None else f"{oval:,.0f}")
                row.append(rps_cell(other, req))
                row.append(ko_pct_cell(other, req))
                if oval is None or bval is None:
                    if show_diff:
                        row.append("-")
                    if show_change:
                        row.append("-")
                else:
                    diff = oval - bval
                    if show_diff:
                        row.append(f"{diff:+,.0f}")
                    if show_change:
                        row.append(format_change(diff, bval))
            lines.append("| " + " | ".join(row) + " |")

    if show_change:
        lines.append("")
        lines.append("_:arrow_down: = faster, :arrow_up: = slower_")
    lines.append("")
    lines.append(
        "_Percentiles use the inclusive definition (e.g. p95 = X means 95% of "
        "requests responded in X ms or less) and are computed over OK + KO responses._"
    )
    return "\n".join(lines) + "\n"


def format_output(gatling_data: GatlingRuns) -> None:
    """Format and print results as CSV."""
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(
        [
            "directory",
            "simulation",
            "run_timestamp",
            "request_name",
            "count",
            "ok_count",
            "ko_count",
            "req_per_sec",
            "min",
            "50th",
            "75th",
            "95th",
            "99th",
            "max",
        ]
    )

    for simulation in gatling_data.get_simulations():
        for run_timestamp in gatling_data.get_run_timestamps(simulation):
            run_data = gatling_data.get_run(simulation, run_timestamp)
            if run_data:
                for request_name, request_data in run_data.requests.items():
                    p = request_data.percentiles
                    writer.writerow(
                        [
                            run_data.directory.name,
                            simulation,
                            run_data.formatted_timestamp,
                            request_name,
                            request_data.count,
                            request_data.ok_count,
                            request_data.ko_count,
                            f"{request_data.req_per_sec:.2f}",
                            f"{p['min']:.0f}",
                            f"{p['50th']:.0f}",
                            f"{p['75th']:.0f}",
                            f"{p['95th']:.0f}",
                            f"{p['99th']:.0f}",
                            f"{p['max']:.0f}",
                        ]
                    )


def format_output_combined(gatling_data: GatlingRuns) -> None:
    """Format and print combined results as CSV (one row per request).

    Combines response times across all (simulation, run, request) tuples by request
    name and computes percentiles over the combined samples. Schema differs from the
    per-run output: no `run_timestamp` column, `directory` is the input the user
    passed, `count` is the total sample count.
    """
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(
        [
            "directory",
            "simulation",
            "request_name",
            "count",
            "ok_count",
            "ko_count",
            "req_per_sec",
            "min",
            "50th",
            "75th",
            "95th",
            "99th",
            "max",
        ]
    )

    combined = combine_request_data(gatling_data)
    if not combined:
        return

    # All runs in one input share a simulation in practice; pick the first.
    simulation = gatling_data.get_simulations()[0] if gatling_data.get_simulations() else ""
    directory = gatling_data.report_directory.name if gatling_data.report_directory else ""

    for request_name, c in combined.items():
        p = calculate_percentiles(c.response_times)
        writer.writerow(
            [
                directory,
                simulation,
                request_name,
                len(c.response_times),
                c.ok_count,
                c.ko_count,
                f"{c.req_per_sec:.2f}",
                f"{p['min']:.0f}",
                f"{p['50th']:.0f}",
                f"{p['75th']:.0f}",
                f"{p['95th']:.0f}",
                f"{p['99th']:.0f}",
                f"{p['max']:.0f}",
            ]
        )
