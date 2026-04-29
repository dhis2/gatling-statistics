#!/usr/bin/env python3
"""End-to-end tests for gstat.

To run: uv run python tests/test_gstat.py
"""

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path

import pandas as pd

from gstat import (
    CompareInput,
    collect_compare_input,
    format_compare_markdown,
    format_output,
    format_output_combined,
    load_gatling_data,
    order_requests_gatling_html,
    parse_gatling_directory_timestamp,
    plot_percentiles_stacked,
)

FIXTURES_ROOT = Path(__file__).parent / "fixtures"
FLAT_MULTI = FIXTURES_ROOT / "flat-multi"
FIXTURE_DIR = FLAT_MULTI / "trackertest-20260424071214792-2.43.0-smoke-1u-1000req"
WARMUP_FIXTURE_DIR = FLAT_MULTI / "trackertest-20260424070546336-2.43.0-smoke-1u-1000req-warmup-1"
FIXTURES_PARENT = FLAT_MULTI

# Real Gatling export run with mixed OK/KO requests. Used as a parity check
# against Gatling's own HTML statistics table (see TestReqPerSecGatlingParity).
WITH_KO_FIXTURE_DIR = (
    FIXTURES_ROOT
    / "with-ko"
    / "trackertest-20260420131959836-DHIS2-20965-export-2.42.4-4users-300s"
)


class TestTraceMapping(unittest.TestCase):
    """Stacked-plot dropdown wiring: trace indices must be contiguous, non-overlapping,
    and exactly 6 per request (5 percentile-range bars + 1 mean line). Originally written
    to catch a bug where mean lines were emitted in a separate loop after all bars,
    which made each request's trace indices non-contiguous and let dropdown selections
    leak traces from other requests."""

    @classmethod
    def setUpClass(cls):
        cls.gatling_data = load_gatling_data(FIXTURE_DIR)

    def test_trace_indices_are_non_overlapping(self):
        """Verify that trace index ranges for different requests don't overlap."""
        fig = plot_percentiles_stacked(self.gatling_data)

        # Extract trace mapping from the figure's updatemenus
        # The request dropdown is the second menu (index 1)
        request_dropdown = fig.layout.updatemenus[1]

        # Collect all trace indices that are set to True for each request
        trace_sets = []
        for button in request_dropdown.buttons:
            request_name = button.label
            visibility = button.args[0]["visible"]
            visible_indices = {i for i, v in enumerate(visibility) if v}
            trace_sets.append((request_name, visible_indices))

        # Verify no overlaps between any two requests
        for i, (name1, traces1) in enumerate(trace_sets):
            for name2, traces2 in trace_sets[i + 1 :]:
                overlap = traces1 & traces2
                self.assertEqual(
                    len(overlap),
                    0,
                    f"Trace indices overlap between '{name1}' and '{name2}': {overlap}",
                )

    def test_each_request_has_correct_number_of_traces(self):
        """Verify each request has exactly 6 traces (5 bars + 1 mean line)."""
        fig = plot_percentiles_stacked(self.gatling_data)

        # The request dropdown is the second menu (index 1)
        request_dropdown = fig.layout.updatemenus[1]

        for button in request_dropdown.buttons:
            request_name = button.label
            visibility = button.args[0]["visible"]
            visible_count = sum(visibility)

            # Each request should have 5 bar traces + 1 mean line = 6 traces
            self.assertEqual(
                visible_count,
                6,
                f"Request '{request_name}' should have 6 traces, got {visible_count}",
            )

    def test_trace_indices_are_contiguous(self):
        """Verify that trace indices for each request are contiguous."""
        fig = plot_percentiles_stacked(self.gatling_data)

        # The request dropdown is the second menu (index 1)
        request_dropdown = fig.layout.updatemenus[1]

        for button in request_dropdown.buttons:
            request_name = button.label
            visibility = button.args[0]["visible"]
            visible_indices = [i for i, v in enumerate(visibility) if v]

            # Check that indices are contiguous
            if len(visible_indices) > 0:
                expected_range = list(range(min(visible_indices), max(visible_indices) + 1))
                self.assertEqual(
                    visible_indices,
                    expected_range,
                    f"Trace indices for '{request_name}' are not contiguous: {visible_indices}",
                )


class TestNestedGroups(unittest.TestCase):
    """Test that requests with identical names but different group hierarchies are kept separate."""

    def test_duplicate_request_names_in_different_hierarchies(self):
        """Verify requests with same name but different hierarchies produce separate statistics.

        This test uses real TrackerTest data where "Get relationships for first event" appears in:
        * "Get a list of single events|Get one single event" (2 times: 5ms, 4ms)
        * "Get a list of TEs|Go to single enrollment|Get one event" (2 times: 3ms, 4ms)

        Without hierarchy-aware grouping, these would incorrectly merge into 4 requests with
        response times [5, 4, 3, 4] instead of staying separate.
        """
        # fmt: off
        # ruff: noqa: E501
        csv_content = """record_type,scenario_name,group_hierarchy,request_name,status,start_timestamp,end_timestamp,response_time_ms,error_message,event_type,duration_ms,cumulated_response_time_ms,is_incoming
user,Single Events,,,,1762133595734,,,,start,,,
request,,,Login,OK,1762133595750,1762133595858,108,,,,,false
request,,Get a list of single events,Go to first page of program VBqh0ynB2wv,OK,1762133595875,1762133595934,59,,,,,false
request,,"Get a list of single events|Get one single event",Get first event,OK,1762133596092,1762133596115,23,,,,,false
request,,"Get a list of single events|Get one single event",Get relationships for first event,OK,1762133596116,1762133596121,5,,,,,false
request,,"Get a list of single events|Get one single event",Get first event,OK,1762133596300,1762133596314,14,,,,,false
request,,"Get a list of single events|Get one single event",Get relationships for first event,OK,1762133596315,1762133596319,4,,,,,false
request,,Get a list of TEs,Get first page of TEs of program ur1Edk5Oe2n,OK,1762133614743,1762133614877,134,,,,,false
request,,"Get a list of TEs|Go to single enrollment",Get first enrollment,OK,1762133614909,1762133614916,7,,,,,false
request,,"Get a list of TEs|Go to single enrollment|Get one event",Get first event from enrollment,OK,1762133614925,1762133614938,13,,,,,false
request,,"Get a list of TEs|Go to single enrollment|Get one event",Get relationships for first event,OK,1762133614938,1762133614941,3,,,,,false
request,,"Get a list of TEs|Go to single enrollment|Get one event",Get first event from enrollment,OK,1762133615108,1762133615121,13,,,,,false
request,,"Get a list of TEs|Go to single enrollment|Get one event",Get relationships for first event,OK,1762133615121,1762133615125,4,,,,,false
user,Single Events,,,,1762133613933,,,,end,,,
"""
        # fmt: on

        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / "trackertest-20250101010101010-test"
            test_dir.mkdir()
            (test_dir / "simulation.csv").write_text(csv_content)

            gatling_data = load_gatling_data(Path(tmpdir))

            simulation = gatling_data.get_simulations()[0]
            run = gatling_data.get_run_timestamps(simulation)[0]
            actual_requests = gatling_data.get_requests(simulation, run)

            # Map of full_request_path -> (count, response_times, mean)
            expected_requests = {
                # Request without group hierarchy (NaN) - tests dropna=False
                "Login": (1, [108], 108.0),
                # Requests with single-level hierarchy
                "Get a list of single events / Go to first page of program VBqh0ynB2wv": (
                    1,
                    [59],
                    59.0,
                ),
                "Get a list of TEs / Get first page of TEs of program ur1Edk5Oe2n": (
                    1,
                    [134],
                    134.0,
                ),
                "Get a list of TEs / Go to single enrollment / Get first enrollment": (1, [7], 7.0),
                # Requests with nested hierarchy - same request_name, different contexts
                "Get a list of single events / Get one single event / Get first event": (
                    2,
                    [23, 14],
                    18.5,
                ),
                "Get a list of single events / Get one single event / Get relationships for first event": (
                    2,
                    [5, 4],
                    4.5,
                ),
                "Get a list of TEs / Go to single enrollment / Get one event / Get first event from enrollment": (
                    2,
                    [13, 13],
                    13.0,
                ),
                "Get a list of TEs / Go to single enrollment / Get one event / Get relationships for first event": (
                    2,
                    [3, 4],
                    3.5,
                ),
            }

            # Verify exact set of requests (no missing, no extra)
            self.assertEqual(set(actual_requests), set(expected_requests.keys()))

            # Verify statistics for each request
            for full_path, (
                expected_count,
                expected_times,
                expected_mean,
            ) in expected_requests.items():
                data = gatling_data.get_request(simulation, run, full_path)
                self.assertEqual(data.count, expected_count, f"Wrong count for {full_path}")
                self.assertEqual(
                    data.response_times, expected_times, f"Wrong times for {full_path}"
                )
                self.assertAlmostEqual(
                    data.mean, expected_mean, places=2, msg=f"Wrong mean for {full_path}"
                )


class TestLoader(unittest.TestCase):
    """Directory-discovery and CSV-parsing tests for load_gatling_data.

    Covers each shape under tests/fixtures/: flat-single, flat-multi, wrapped,
    plus the invalid/* fixtures that should error cleanly.
    """

    FLAT_SINGLE = FIXTURES_ROOT / "flat-single"
    FLAT_SINGLE_INNER = FLAT_SINGLE / "trackertest-20260424071214792-2.43.0-smoke-1u-1000req"
    WRAPPED = FIXTURES_ROOT / "wrapped"
    WRAPPED_INNER = (
        WRAPPED / "gatling-report-DHIS2-20965-load-2.43.0-6users-300s-24555271744-attempt-1"
    )
    INVALID_EMPTY = FIXTURES_ROOT / "invalid" / "empty-dir"
    INVALID_AMBIGUOUS = FIXTURES_ROOT / "invalid" / "ambiguous-wrappers"
    INVALID_TOO_DEEP = FIXTURES_ROOT / "invalid" / "too-deep"

    def test_flat_single_inner_dir_loads(self):
        """Pointing at a directory that contains simulation.csv directly works."""
        gatling_data = load_gatling_data(self.FLAT_SINGLE_INNER)
        self.assertEqual(gatling_data.get_simulations(), ["trackertest"])
        runs = gatling_data.get_run_timestamps("trackertest")
        self.assertEqual(len(runs), 1)

    def test_flat_single_parent_descends_one_level(self):
        """Pointing at a parent that contains exactly one trackertest-… dir
        descends into it."""
        gatling_data = load_gatling_data(self.FLAT_SINGLE)
        self.assertEqual(gatling_data.get_simulations(), ["trackertest"])
        # The outer dir has exactly one child report; descent picks it.
        self.assertEqual(len(gatling_data.get_run_timestamps("trackertest")), 1)

    def test_flat_multi_loads_all_runs(self):
        """A directory containing multiple trackertest-… dirs loads all of them."""
        gatling_data = load_gatling_data(FIXTURES_PARENT)
        self.assertEqual(len(gatling_data.get_run_timestamps("trackertest")), 2)

    def test_flat_multi_with_exclude_filters_at_leaf(self):
        """`exclude` matches against the leaf directory name, not the wrapper."""
        gatling_data = load_gatling_data(FIXTURES_PARENT, exclude="warmup")
        timestamps = gatling_data.get_run_timestamps("trackertest")
        self.assertEqual(len(timestamps), 1)
        # The remaining run is the non-warmup one.
        self.assertNotIn(
            "warmup", str(gatling_data.get_run("trackertest", timestamps[0]).directory)
        )

    def test_wrapped_layout_descends_through_wrapper(self):
        """Regression for the gh run download bug: an outer wrapper containing
        gatling-report-… containing two trackertest-… dirs must load both."""
        gatling_data = load_gatling_data(self.WRAPPED)
        self.assertEqual(len(gatling_data.get_run_timestamps("trackertest")), 2)

    def test_wrapped_layout_with_exclude(self):
        """`--exclude warmup` still works through descent."""
        gatling_data = load_gatling_data(self.WRAPPED, exclude="warmup")
        self.assertEqual(len(gatling_data.get_run_timestamps("trackertest")), 1)

    def test_wrapped_inner_path_also_works(self):
        """Pointing directly at the gatling-report-… dir bypasses descent."""
        gatling_data = load_gatling_data(self.WRAPPED_INNER)
        self.assertEqual(len(gatling_data.get_run_timestamps("trackertest")), 2)

    def test_unknown_directory_name_falls_back(self):
        """Directory whose name doesn't match <simulation>-<17-digit-timestamp>
        falls back to simulation='unknown', run_timestamp='unknown'."""
        # fmt: off
        # ruff: noqa: E501
        csv_content = """record_type,scenario_name,group_hierarchy,request_name,status,start_timestamp,end_timestamp,response_time_ms,error_message,event_type,duration_ms,cumulated_response_time_ms,is_incoming
request,,,Login,OK,1,2,1,,,,,false
"""
        # fmt: on
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / "no-timestamp-here"
            test_dir.mkdir()
            (test_dir / "simulation.csv").write_text(csv_content)
            gatling_data = load_gatling_data(test_dir)
            self.assertEqual(gatling_data.get_simulations(), ["unknown"])
            self.assertEqual(gatling_data.get_run_timestamps("unknown"), ["unknown"])

    def test_empty_directory_errors_cleanly(self):
        """A directory with no simulation.csv and no subdirectories exits 1
        with a message naming the directory."""
        err = io.StringIO()
        with self.assertRaises(SystemExit) as cm, redirect_stderr(err):
            load_gatling_data(self.INVALID_EMPTY)
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("empty-dir", err.getvalue())

    def test_ambiguous_wrappers_error(self):
        """Two non-matching subdirs at descent depth → error, no silent pick."""
        err = io.StringIO()
        with self.assertRaises(SystemExit) as cm, redirect_stderr(err):
            load_gatling_data(self.INVALID_AMBIGUOUS)
        self.assertEqual(cm.exception.code, 1)
        msg = err.getvalue()
        self.assertIn("ambiguous", msg)
        self.assertIn("gatling-report-A", msg)
        self.assertIn("gatling-report-B", msg)

    def test_too_deep_errors(self):
        """More than max_depth wrapper layers → error citing the depth limit."""
        err = io.StringIO()
        with self.assertRaises(SystemExit) as cm, redirect_stderr(err):
            load_gatling_data(self.INVALID_TOO_DEEP)
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("3 levels", err.getvalue())


class TestGatlingHtmlOrdering(unittest.TestCase):
    """Verify order_requests_gatling_html matches Gatling's HTML statistics table order.

    Input: the real glog-CSV at tests/fixtures/flat-multi/trackertest-20260424071214792-2.43.0-smoke-1u-1000req/
    (downloaded from the CI run gatling-report-2.43.0-smoke-1u-1000req-24876465016-attempt-1).
    Expected output: the order extracted from that run's index.html (subgroups
    before leaves at each level; within each bucket the order of first
    appearance in simulation.csv).
    """

    GOLDEN_ORDER = [
        ("Get ANC events|Get one event", "Get first event"),
        ("Get ANC events|Get one event", "Get relationships for first event"),
        ("Get ANC events", "Go to first page"),
        ("Get ANC events", "Go to second page"),
        ("Get ANC events", "Search not assigned"),
        ("Get ANC events", "Search by date range"),
        (
            "Get Child Programme TEs|Go to single enrollment|Get one event",
            "Get first event from enrollment",
        ),
        (
            "Get Child Programme TEs|Go to single enrollment|Get one event",
            "Get relationships for first event",
        ),
        ("Get Child Programme TEs|Go to single enrollment", "Get first tracked entity"),
        ("Get Child Programme TEs|Go to single enrollment", "Get first enrollment"),
        (
            "Get Child Programme TEs|Go to single enrollment",
            "Get relationships for first tracked entity",
        ),
        ("Get Child Programme TEs", "Not found TE by name with like operator"),
        ("Get Child Programme TEs", "Not found TE by name with eq operator"),
        ("Get Child Programme TEs", "Search TE by name with like operator"),
        ("Get Child Programme TEs", "Search TE by name with eq operator"),
        ("Get Child Programme TEs", "Search Birth events"),
        ("Get Child Programme TEs", "Get TEs from events"),
        ("Get Child Programme TEs", "Get first page of TEs"),
        ("Get Child Programme TEs", "Get TEs with enrollment status"),
        ("", "Login"),
        ("", "MNCH import"),
        ("", "Child Programme import"),
        ("", "ANC import"),
    ]

    def test_order_matches_gatling_html(self):
        df = pd.read_csv(FIXTURE_DIR / "simulation.csv")
        df = df[(df["record_type"] == "request") & (df["status"] == "OK")].copy()
        df["group_hierarchy"] = df["group_hierarchy"].fillna("")

        actual = order_requests_gatling_html(df)
        self.assertEqual(actual, self.GOLDEN_ORDER)

    def test_synthetic_subgroups_before_leaves(self):
        """Minimal synthetic case: subgroups render before leaves at each level,
        and within each bucket the order of first appearance in the CSV wins."""
        # CSV-append order is whatever Gatling wrote. Here leaf "login" appears
        # before the subgroup rows, but HTML order puts the subgroup first.
        df = pd.DataFrame(
            [
                {"group_hierarchy": "", "request_name": "login"},
                {"group_hierarchy": "A", "request_name": "leaf-a1"},
                {"group_hierarchy": "A|B", "request_name": "leaf-ab1"},
                {"group_hierarchy": "A|B", "request_name": "leaf-ab2"},
                {"group_hierarchy": "A", "request_name": "leaf-a2"},
                {"group_hierarchy": "", "request_name": "logout"},
            ]
        )

        expected = [
            # A (subgroup of root) rendered before root's leaves
            ("A|B", "leaf-ab1"),  # A/B (subgroup of A) before A's leaves
            ("A|B", "leaf-ab2"),
            ("A", "leaf-a1"),
            ("A", "leaf-a2"),
            ("", "login"),
            ("", "logout"),
        ]
        self.assertEqual(order_requests_gatling_html(df), expected)


class TestPercentilesOutput(unittest.TestCase):
    """End-to-end tests for the percentiles output (default and `--combine`).

    Per-run output emits one row per (run, request); combined output combines response
    times across all runs of a request and emits one row per request, with percentiles
    recomputed over the combined samples. Both share the same Gatling HTML row order.
    Tests assert against the committed fixture pair (warmup + main) so a real two-run
    combine is exercised.
    """

    # Hand-checked snapshot of `gstat --combine ./tests/fixtures/`. Numbers are
    # numpy.percentile(..., method="linear") over the combined warmup + main response
    # times for each request. Distinguishes "combine samples then compute" from
    # "average per-run percentiles": e.g. ANC import warmup p99=50, main p99=87, but
    # the combined p99 below is 58 (computed over 2000 samples), not 68.5 (average).
    COMBINED_OUTPUT_BOTH_RUNS = """\
directory,simulation,request_name,count,ok_count,ko_count,req_per_sec,min,50th,75th,95th,99th,max
flat-multi,trackertest,Get ANC events / Get one event / Get first event,200,200,0,0.23,13,15,16,42,67,99
flat-multi,trackertest,Get ANC events / Get one event / Get relationships for first event,200,200,0,0.23,2,3,3,4,6,39
flat-multi,trackertest,Get ANC events / Go to first page,200,200,0,0.23,9,87,147,150,159,2837
flat-multi,trackertest,Get ANC events / Go to second page,200,200,0,0.23,10,87,147,150,159,2723
flat-multi,trackertest,Get ANC events / Search not assigned,200,200,0,0.23,9,91,147,151,158,169
flat-multi,trackertest,Get ANC events / Search by date range,200,200,0,0.23,10,356,693,703,714,717
flat-multi,trackertest,Get Child Programme TEs / Go to single enrollment / Get one event / Get first event from enrollment,200,200,0,0.23,20,21,22,25,29,41
flat-multi,trackertest,Get Child Programme TEs / Go to single enrollment / Get one event / Get relationships for first event,200,200,0,0.23,2,3,4,5,8,17
flat-multi,trackertest,Get Child Programme TEs / Go to single enrollment / Get first tracked entity,200,200,0,0.23,16,17,18,28,34,39
flat-multi,trackertest,Get Child Programme TEs / Go to single enrollment / Get first enrollment,200,200,0,0.23,7,8,9,19,26,35
flat-multi,trackertest,Get Child Programme TEs / Go to single enrollment / Get relationships for first tracked entity,200,200,0,0.23,3,4,4,5,7,15
flat-multi,trackertest,Get Child Programme TEs / Not found TE by name with like operator,200,200,0,0.23,52,68,69,71,81,155
flat-multi,trackertest,Get Child Programme TEs / Not found TE by name with eq operator,200,200,0,0.23,3,4,5,6,7,9
flat-multi,trackertest,Get Child Programme TEs / Search TE by name with like operator,200,200,0,0.23,65,111,113,118,137,146
flat-multi,trackertest,Get Child Programme TEs / Search TE by name with eq operator,200,200,0,0.23,14,15,16,25,38,51
flat-multi,trackertest,Get Child Programme TEs / Search Birth events,200,200,0,0.23,56,664,1286,1296,1318,1900
flat-multi,trackertest,Get Child Programme TEs / Get TEs from events,200,200,0,0.23,5,6,6,9,11,16
flat-multi,trackertest,Get Child Programme TEs / Get first page of TEs,200,200,0,0.23,19,68,104,108,112,114
flat-multi,trackertest,Get Child Programme TEs / Get TEs with enrollment status,200,200,0,0.23,75,127,129,133,140,155
flat-multi,trackertest,Login,10,10,0,0.01,92,98,105,141,159,163
flat-multi,trackertest,MNCH import,2000,2000,0,2.31,56,96,106,129,220,1296
flat-multi,trackertest,Child Programme import,2000,2000,0,2.31,65,68,71,76,86,338
flat-multi,trackertest,ANC import,2000,2000,0,2.31,33,36,38,44,58,587
"""

    # Snapshot of `gstat --combine --exclude warmup ./tests/fixtures/`. With warmup
    # dropped, only the main run survives, so `count` and percentiles match what the
    # per-run output emits for the main fixture alone.
    COMBINED_OUTPUT_MAIN_ONLY = """\
directory,simulation,request_name,count,ok_count,ko_count,req_per_sec,min,50th,75th,95th,99th,max
flat-multi,trackertest,Get ANC events / Get one event / Get first event,100,100,0,0.21,13,14,15,40,53,67
flat-multi,trackertest,Get ANC events / Get one event / Get relationships for first event,100,100,0,0.21,2,3,3,3,4,7
flat-multi,trackertest,Get ANC events / Go to first page,100,100,0,0.21,9,147,148,151,159,165
flat-multi,trackertest,Get ANC events / Go to second page,100,100,0,0.21,10,147,148,153,159,161
flat-multi,trackertest,Get ANC events / Search not assigned,100,100,0,0.21,9,147,148,153,159,169
flat-multi,trackertest,Get ANC events / Search by date range,100,100,0,0.21,10,693,695,709,715,717
flat-multi,trackertest,Get Child Programme TEs / Go to single enrollment / Get one event / Get first event from enrollment,100,100,0,0.21,20,21,22,23,26,27
flat-multi,trackertest,Get Child Programme TEs / Go to single enrollment / Get one event / Get relationships for first event,100,100,0,0.21,2,3,3,4,5,8
flat-multi,trackertest,Get Child Programme TEs / Go to single enrollment / Get first tracked entity,100,100,0,0.21,16,17,17,19,26,27
flat-multi,trackertest,Get Child Programme TEs / Go to single enrollment / Get first enrollment,100,100,0,0.21,7,8,9,18,26,26
flat-multi,trackertest,Get Child Programme TEs / Go to single enrollment / Get relationships for first tracked entity,100,100,0,0.21,3,4,4,4,5,7
flat-multi,trackertest,Get Child Programme TEs / Not found TE by name with like operator,100,100,0,0.21,67,69,70,75,81,108
flat-multi,trackertest,Get Child Programme TEs / Not found TE by name with eq operator,100,100,0,0.21,3,4,4,6,6,7
flat-multi,trackertest,Get Child Programme TEs / Search TE by name with like operator,100,100,0,0.21,111,113,114,122,137,146
flat-multi,trackertest,Get Child Programme TEs / Search TE by name with eq operator,100,100,0,0.21,14,15,15,17,26,29
flat-multi,trackertest,Get Child Programme TEs / Search Birth events,100,100,0,0.21,86,1286,1290,1302,1321,1900
flat-multi,trackertest,Get Child Programme TEs / Get TEs from events,100,100,0,0.21,5,6,6,7,8,9
flat-multi,trackertest,Get Child Programme TEs / Get first page of TEs,100,100,0,0.21,19,104,105,109,114,114
flat-multi,trackertest,Get Child Programme TEs / Get TEs with enrollment status,100,100,0,0.21,127,129,130,134,140,144
flat-multi,trackertest,Login,5,5,0,0.01,94,98,99,111,113,114
flat-multi,trackertest,MNCH import,1000,1000,0,2.05,56,94,103,119,174,626
flat-multi,trackertest,Child Programme import,1000,1000,0,2.05,65,68,70,75,84,251
flat-multi,trackertest,ANC import,1000,1000,0,2.05,33,36,38,43,87,587
"""

    @staticmethod
    def _capture(fn, *args, **kwargs) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            fn(*args, **kwargs)
        return buf.getvalue()

    def test_per_run_output(self):
        """With both fixtures present, default output emits 23 requests x 2 runs = 46 data
        rows. We assert structure (header, count, both timestamps) rather than a full
        snapshot because the per-run rows include long auto-generated `directory` names."""
        gatling_data = load_gatling_data(FIXTURES_PARENT)
        out = self._capture(format_output, gatling_data)

        header, *rows = [line for line in out.splitlines() if line]
        self.assertEqual(
            header,
            "directory,simulation,run_timestamp,request_name,"
            "count,ok_count,ko_count,req_per_sec,min,50th,75th,95th,99th,max",
        )
        self.assertEqual(len(rows), 46)
        timestamps = {row.split(",")[2] for row in rows}
        self.assertEqual(timestamps, {"2026-04-24 07:05:46", "2026-04-24 07:12:14"})

        # req_per_sec column (index 7) must be a non-negative number for every
        # row, formatted with two decimals.
        for row in rows:
            cells = row.split(",")
            rps = cells[7]
            self.assertRegex(rps, r"^\d+\.\d{2}$", msg=f"bad req_per_sec cell: {rps!r}")

        # Pin one main-run "import" row: 1000 requests / actual measured window
        # (~487.59s) ≈ 2.05 req/s. Picks an unambiguous request_name so the
        # assertion is stable against fixture ordering.
        main_mnch_rows = [
            row
            for row in rows
            if row.split(",")[2] == "2026-04-24 07:12:14" and row.split(",")[3] == "MNCH import"
        ]
        self.assertEqual(len(main_mnch_rows), 1)
        self.assertEqual(main_mnch_rows[0].split(",")[7], "2.05")

    def test_combined_output_combines_runs(self):
        """`--combine` combines warmup + main response times by request name and
        recomputes percentiles. Full-output snapshot pins every value."""
        gatling_data = load_gatling_data(FIXTURES_PARENT)
        out = self._capture(format_output_combined, gatling_data)
        self.assertEqual(out, self.COMBINED_OUTPUT_BOTH_RUNS)

    def test_combined_output_with_exclude(self):
        """`--exclude warmup` drops the warmup fixture before combining; the resulting
        rows match what the main run produces alone."""
        gatling_data = load_gatling_data(FIXTURES_PARENT, exclude="warmup")
        out = self._capture(format_output_combined, gatling_data)
        self.assertEqual(out, self.COMBINED_OUTPUT_MAIN_ONLY)

    def test_combined_output_row_order_matches_per_run(self):
        """Combined and per-run outputs share the same Gatling HTML row order."""
        gatling_data = load_gatling_data(FIXTURES_PARENT, exclude="warmup")
        per_run = self._capture(format_output, gatling_data)
        combined = self._capture(format_output_combined, gatling_data)

        # request_name is column 3 in per-run, column 2 in combined.
        per_run_requests = [
            row.split(",")[3]
            for row in per_run.splitlines()
            if row and not row.startswith("directory,")
        ]
        combined_requests = [
            row.split(",")[2]
            for row in combined.splitlines()
            if row and not row.startswith("directory,")
        ]
        self.assertEqual(per_run_requests, combined_requests)

    def test_req_per_sec_uses_actual_measured_window(self):
        """`req_per_sec = count / (max(end_timestamp) - min(start_timestamp))`,
        computed over the whole run (matches Gatling's `Cnt/s`). The TODO note
        from the 2.43 release-note workflow recorded the trap this guards: a
        300s sweep with count=3156 gives 10.52 against the nominal duration but
        Gatling reports 10.48 against the actual measured window. Synthetic CSV
        below pins the same shape: nominal 4s window, actual 4.5s, three
        requests → 0.67 req/s, not 0.75."""
        # fmt: off
        # ruff: noqa: E501
        csv_content = """record_type,scenario_name,group_hierarchy,request_name,status,start_timestamp,end_timestamp,response_time_ms,error_message,event_type,duration_ms,cumulated_response_time_ms,is_incoming
request,,,FastReq,OK,1000,1100,100,,,,,false
request,,,FastReq,OK,3000,3100,100,,,,,false
request,,,FastReq,OK,5000,5500,500,,,,,false
"""
            # fmt: on
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = Path(tmpdir) / "trackertest-20250101010101010-test"
            test_dir.mkdir()
            (test_dir / "simulation.csv").write_text(csv_content)

            gatling_data = load_gatling_data(test_dir)

            # Whole-run window: end_max=5500, start_min=1000 → 4.5s. Three requests
            # → 0.6667 req/s rounded to 0.67.
            run = gatling_data.get_run("trackertest", "20250101010101010")
            self.assertAlmostEqual(run.duration_seconds, 4.5, places=3)

            out = self._capture(format_output, gatling_data)
            rows = [line for line in out.splitlines() if line and not line.startswith("directory,")]
            self.assertEqual(len(rows), 1)
            cells = rows[0].split(",")
            # count=3, ok=3, ko=0, req_per_sec=0.67 (3 / 4.5).
            self.assertEqual(cells[4], "3")
            self.assertEqual(cells[7], "0.67")

    def test_req_per_sec_matches_gatling_html_with_mixed_ok_ko(self):
        """End-to-end parity check against Gatling's own HTML statistics table.

        Fixture: a real export run from DHIS2-20965 (2.42.4, 4 users, 300s) where
        `MNCH import` has mixed OK/KO (990 OK + 10 KO). Reference values copied
        verbatim from the run's `index.html` (col-2=Total, col-3=OK, col-4=KO,
        col-6=Cnt/s). Pinning the same numbers gstat produces guards two
        invariants the TODO calls out:

        * `req_per_sec` denominator is the actual measured window, so the
          number matches Gatling's `Cnt/s` rather than `count / nominal_duration`.
        * `count` and the throughput numerator both include KO requests, so a
          mixed row reports the same throughput Gatling does.

        If Gatling ever changes its rounding or denominator, this test will
        catch the drift instead of letting release-note tables diverge silently.
        """
        gatling_data = load_gatling_data(WITH_KO_FIXTURE_DIR)
        out = self._capture(format_output, gatling_data)

        # Header order is stable: count is column 4, ok=5, ko=6, req_per_sec=7.
        rows = {
            row.split(",")[3]: row.split(",")
            for row in out.splitlines()
            if row and not row.startswith("directory,")
        }

        # (request_name, count, ok, ko, req_per_sec) tuples lifted from index.html.
        gatling_reference = [
            # Mixed OK/KO row — the load-bearing case for this test.
            ("MNCH import", "1000", "990", "10", "0.13"),
            # All-OK rows at the same nominal rate (sanity that 0.13 isn't a fluke
            # of the mixed row).
            ("ANC import", "1000", "1000", "0", "0.13"),
            ("Child Programme import", "1000", "1000", "0", "0.13"),
            # Low-count row Gatling rounds to 0.00 — pins the rounding contract,
            # not a particular non-zero value.
            ("Login", "11", "11", "0", "0.00"),
        ]
        for name, count, ok, ko, rps in gatling_reference:
            cells = rows[name]
            self.assertEqual(cells[4], count, f"{name}: count")
            self.assertEqual(cells[5], ok, f"{name}: ok_count")
            self.assertEqual(cells[6], ko, f"{name}: ko_count")
            self.assertEqual(cells[7], rps, f"{name}: req_per_sec vs Gatling Cnt/s")

    def test_req_per_sec_combined_sums_per_run_durations(self):
        """When `--combine` merges multiple runs, the throughput denominator is
        the sum of per-run measured windows. Two runs each carrying 100 requests
        over 100s → 200/200 = 1.00 req/s, regardless of the wall-clock gap
        between them."""
        # fmt: off
        # ruff: noqa: E501
        csv_run_a = """record_type,scenario_name,group_hierarchy,request_name,status,start_timestamp,end_timestamp,response_time_ms,error_message,event_type,duration_ms,cumulated_response_time_ms,is_incoming
""" + "\n".join(
            f"request,,,Search,OK,{1000 + i},{1000 + i + 1},1,,,,,false"
            for i in range(0, 100_000, 1000)
        ) + "\n"
        # Second run starts well after the first ends; the gap must not show up
        # as "active duration" in the combined denominator.
        csv_run_b = """record_type,scenario_name,group_hierarchy,request_name,status,start_timestamp,end_timestamp,response_time_ms,error_message,event_type,duration_ms,cumulated_response_time_ms,is_incoming
""" + "\n".join(
            f"request,,,Search,OK,{1_000_000 + i},{1_000_000 + i + 1},1,,,,,false"
            for i in range(0, 100_000, 1000)
        ) + "\n"
        # fmt: on
        with tempfile.TemporaryDirectory() as tmpdir:
            parent = Path(tmpdir)
            for ts, csv in [
                ("20250101010101010", csv_run_a),
                ("20250101020202020", csv_run_b),
            ]:
                d = parent / f"trackertest-{ts}-test"
                d.mkdir()
                (d / "simulation.csv").write_text(csv)

            gatling_data = load_gatling_data(parent)
            out = self._capture(format_output_combined, gatling_data)

            rows = [line for line in out.splitlines() if line and not line.startswith("directory,")]
            self.assertEqual(len(rows), 1)
            cells = rows[0].split(",")
            # count=200; per-run windows are each 99.001s (start_min=1000 to
            # end_max=100001 in run A, etc.), summed = 198.002s; 200 / 198.002 ≈ 1.01.
            self.assertEqual(cells[3], "200")
            self.assertEqual(cells[6], "1.01")


def make_compare_input(
    label: str,
    rows: dict[str, dict],
    path_name: str | None = None,
) -> CompareInput:
    """Build a CompareInput from a compact `{request_name: {pXX: value, "ok": int, "ko": int, "rps": float}}`.

    Keeps rendering tests focused on inputs and expected output rather than CSV bytes.
    """
    percentiles = {
        req: {k: v for k, v in stats.items() if k not in ("ok", "ko", "rps")}
        for req, stats in rows.items()
    }
    ok_ko_counts = {req: (stats.get("ok", 0), stats.get("ko", 0)) for req, stats in rows.items()}
    req_per_sec = {req: stats.get("rps", 0.0) for req, stats in rows.items()}
    has_ko = any(stats.get("ko", 0) > 0 for stats in rows.values())
    return CompareInput(
        path=Path(path_name or label),
        label=label,
        percentiles=percentiles,
        ok_ko_counts=ok_ko_counts,
        req_per_sec=req_per_sec,
        has_ko=has_ko,
    )


class TestCompare(unittest.TestCase):
    """End-to-end tests for `gstat compare`.

    `test_compare_warmup_vs_main_p95` pins loader+formatter together on real fixtures.
    Other tests build CompareInput directly to keep rendering logic isolated.
    """

    PERCENTILE_TITLES = {
        "50th": "Median Response Time (p50)",
        "75th": "75th Percentile Response Time (p75)",
        "95th": "95th Percentile Response Time (p95)",
        "99th": "99th Percentile Response Time (p99)",
    }

    def test_compare_warmup_vs_main_p95(self):
        """Real warmup-vs-main p95 comparison. Hand-typed expected rows pin specific
        numeric output so changes to percentile method, row formatting, or arrow
        semantics fail loudly."""
        baseline = collect_compare_input(WARMUP_FIXTURE_DIR, label="warmup", exclude=None)
        candidate = collect_compare_input(FIXTURE_DIR, label="main", exclude=None)

        out = format_compare_markdown([baseline, candidate], ["95th"], self.PERCENTILE_TITLES)

        # Header
        self.assertIn(
            "> Baseline (warmup): `trackertest-20260424070546336-2.43.0-smoke-1u-1000req-warmup-1`",
            out,
        )
        self.assertIn(
            "> Run 2 (main): `trackertest-20260424071214792-2.43.0-smoke-1u-1000req`", out
        )

        # Section header for p95 only
        self.assertIn("### 95th Percentile Response Time (p95) (ms)", out)
        self.assertNotIn("### Median Response Time", out)

        # Table column headers (req/s per run; KO% hidden because no failures).
        self.assertIn("| Requests | warmup | req/s | main | req/s | Diff (ms) | Change |", out)
        self.assertNotIn("KO%", out)

        # Improvement: small absolute diff, sub-3% change. Exercises down-arrow + sign.
        # 1000 imports / warmup window (~377.89s) ≈ 2.65 req/s; / main window
        # (~487.59s) ≈ 2.05 req/s. Pins both throughputs alongside the percentile.
        self.assertIn(
            "| ANC import | 44 | 2.65 | 43 | 2.05 | -1 | :arrow_down: -2.3% |",
            out,
        )

        # Improvement: large negative diff, double-digit percent. Exercises down-arrow + double-digit.
        # Login fires 5 times per run; req/s ≈ 0.01 in both windows.
        self.assertIn(
            "| Login | 152 | 0.01 | 111 | 0.01 | -41 | :arrow_down: -26.9% |",
            out,
        )

        # Regression: large positive diff, near-100%, comma-formatted four-digit value.
        # Exercises up-arrow + {:,.0f} comma + multi-percent. 100 hits per run:
        # 100/377.89 ≈ 0.26, 100/487.59 ≈ 0.21.
        self.assertIn(
            "| Get Child Programme TEs / Search Birth events | 665 | 0.26 | 1,302 | 0.21 | +637 | :arrow_up: +95.8% |",
            out,
        )

        # Footer legend
        self.assertIn("_:arrow_down: = faster, :arrow_up: = slower_", out)
        self.assertIn("inclusive definition", out)

    def test_compare_handles_request_set_difference(self):
        """When a request appears in only one input, the missing-side cells render as `-`
        (not `N/A`, not `0`). Exercises the `if oval is None or bval is None` branch."""
        baseline = make_compare_input(
            "a",
            {"Login": {"95th": 108, "ok": 1, "rps": 1.5}},
            path_name="a-20250101010101010-test",
        )
        candidate = make_compare_input(
            "b",
            {
                "Login": {"95th": 120, "ok": 1, "rps": 1.4},
                "Search": {"95th": 50, "ok": 1, "rps": 0.8},
            },
            path_name="b-20250101010101010-test",
        )

        out = format_compare_markdown([baseline, candidate], ["95th"], self.PERCENTILE_TITLES)

        # Login is in both: real numbers + diff/change. KO% column hidden (no failures).
        self.assertIn("| Login | 108 | 1.50 | 120 | 1.40 | +12 | :arrow_up: +11.1% |", out)
        # Search is only in candidate: baseline value/req/s `-`,
        # candidate value/req/s real, but diff/change `-` because baseline is None.
        self.assertIn("| Search | - | - | 50 | 0.80 | - | - |", out)

    def test_compare_no_diff_drops_diff_column_only(self):
        """`--no-diff` removes the Diff column but keeps the candidate value and Change."""
        baseline = make_compare_input("warmup", {"Login": {"95th": 152, "ok": 1, "rps": 0.5}})
        candidate = make_compare_input("main", {"Login": {"95th": 111, "ok": 1, "rps": 0.6}})

        out = format_compare_markdown(
            [baseline, candidate], ["95th"], self.PERCENTILE_TITLES, show_diff=False
        )

        # Diff column header is gone; Change is still there. req/s stays per run.
        # KO% hidden because no failures in either input.
        self.assertIn("| Requests | warmup | req/s | main | req/s | Change |", out)
        self.assertNotIn("Diff", out)

        # Row loses the -41 Diff cell but keeps the req/s cells.
        self.assertIn("| Login | 152 | 0.50 | 111 | 0.60 | :arrow_down: -27.0% |", out)

        # Arrow legend stays because Change column is present.
        self.assertIn("_:arrow_down: = faster, :arrow_up: = slower_", out)

    def test_compare_no_change_drops_change_column_and_legend(self):
        """`--no-change` removes the Change column and the arrow legend; Diff stays."""
        baseline = make_compare_input("warmup", {"Login": {"95th": 152, "ok": 1, "rps": 0.5}})
        candidate = make_compare_input("main", {"Login": {"95th": 111, "ok": 1, "rps": 0.6}})

        out = format_compare_markdown(
            [baseline, candidate], ["95th"], self.PERCENTILE_TITLES, show_change=False
        )

        # Change column header is gone; Diff is still there. req/s stays per run.
        # KO% hidden because no failures in either input.
        self.assertIn("| Requests | warmup | req/s | main | req/s | Diff (ms) |", out)
        self.assertNotIn("Change", out)
        self.assertNotIn(":arrow_down:", out)
        self.assertNotIn(":arrow_up:", out)

        # Row keeps the Diff cell, drops the Change cell.
        self.assertIn("| Login | 152 | 0.50 | 111 | 0.60 | -41 |", out)

    def test_compare_no_diff_no_change_leaves_only_value_columns(self):
        """Both toggles together collapse each candidate to value + req/s columns
        (KO% hidden when there are no failures)."""
        baseline = make_compare_input("warmup", {"Login": {"95th": 152, "ok": 1, "rps": 0.5}})
        candidate = make_compare_input("main", {"Login": {"95th": 111, "ok": 1, "rps": 0.6}})

        out = format_compare_markdown(
            [baseline, candidate],
            ["95th"],
            self.PERCENTILE_TITLES,
            show_diff=False,
            show_change=False,
        )

        self.assertIn("| Requests | warmup | req/s | main | req/s |", out)
        self.assertNotIn("Diff", out)
        self.assertNotIn("Change", out)
        self.assertIn("| Login | 152 | 0.50 | 111 | 0.60 |", out)

    def test_compare_ko_rows_contribute_to_percentile_and_ko_pct(self):
        """KO rows are included in the percentile and reported in the KO% column.
        Pins the "don't filter, surface KO%" choice: a KO row's response_time is in the
        sample, the KO% column lets the reader gate trust.

        Numbers reproduce the percentile calculation done by the loader:
        * Baseline: 4 OK at 100 ms → p95 = 100.
        * Candidate: 4 OK at 100 ms + 1 KO at 60,000 ms → p95 = 48,020 (linear interp).
        * KO% in candidate = 1 / 5 = 20.0%.
        """
        baseline = make_compare_input("clean", {"Search": {"95th": 100, "ok": 4, "rps": 0.10}})
        candidate = make_compare_input(
            "failing", {"Search": {"95th": 48020, "ok": 4, "ko": 1, "rps": 0.05}}
        )

        out = format_compare_markdown([baseline, candidate], ["95th"], self.PERCENTILE_TITLES)

        # KO% column is shown because the candidate has ko > 0.
        self.assertIn(
            "| Requests | clean | req/s | KO% | failing | req/s | KO% | Diff (ms) | Change |", out
        )
        self.assertIn(
            "| Search | 100 | 0.10 | 0.0% | 48,020 | 0.05 | 20.0% | +47,920 | :arrow_up: +47920.0% |",
            out,
        )

    def test_compare_row_order_is_first_seen_across_inputs(self):
        """Row order in the compare table is "first seen across inputs", baseline first.
        Pins the `seen` set / `ordered_requests` accumulator behavior."""
        baseline = make_compare_input("a", {"X": {"95th": 1, "ok": 1}, "Y": {"95th": 1, "ok": 1}})
        candidate = make_compare_input("b", {"Y": {"95th": 1, "ok": 1}, "Z": {"95th": 1, "ok": 1}})

        out = format_compare_markdown([baseline, candidate], ["95th"], self.PERCENTILE_TITLES)

        # Expected order: X (only in baseline), Y (in both, first seen via baseline), Z (only in candidate).
        x_idx = out.index("| X |")
        y_idx = out.index("| Y |")
        z_idx = out.index("| Z |")
        self.assertLess(x_idx, y_idx)
        self.assertLess(y_idx, z_idx)


class TestParseGatlingDirectoryTimestamp(unittest.TestCase):
    """Pin the timestamp parser. The 17-digit form ends in 3 milliseconds digits,
    not microseconds. strptime's %f would otherwise misinterpret '771' as 771 µs
    instead of 771,000 µs - the conversion is the trap this suite guards."""

    def test_canonical_17_digit_form_with_milliseconds(self):
        self.assertEqual(
            parse_gatling_directory_timestamp("20250627064559771"),
            datetime(2025, 6, 27, 6, 45, 59, 771_000),
        )

    def test_milliseconds_are_milliseconds_not_microseconds(self):
        # 1 ms must become 1,000 µs. If %f were applied naively to "001"
        # it would parse as 1 µs.
        self.assertEqual(
            parse_gatling_directory_timestamp("20260101000000001"),
            datetime(2026, 1, 1, 0, 0, 0, 1_000),
        )

    def test_zero_milliseconds(self):
        self.assertEqual(
            parse_gatling_directory_timestamp("20260101000000000"),
            datetime(2026, 1, 1, 0, 0, 0, 0),
        )

    def test_max_milliseconds(self):
        self.assertEqual(
            parse_gatling_directory_timestamp("20260101000000999"),
            datetime(2026, 1, 1, 0, 0, 0, 999_000),
        )

    def test_14_digit_form_without_milliseconds(self):
        self.assertEqual(
            parse_gatling_directory_timestamp("20260101000000"),
            datetime(2026, 1, 1, 0, 0, 0, 0),
        )

    def test_invalid_calendar_date_returns_min(self):
        # Non-leap-year Feb 29.
        self.assertEqual(
            parse_gatling_directory_timestamp("20260229000000000"),
            datetime.min,
        )

    def test_invalid_month_returns_min(self):
        self.assertEqual(
            parse_gatling_directory_timestamp("20261301000000000"),
            datetime.min,
        )

    def test_non_digit_input_returns_min(self):
        self.assertEqual(
            parse_gatling_directory_timestamp("not-a-timestamp"),
            datetime.min,
        )

    def test_empty_input_returns_min(self):
        self.assertEqual(parse_gatling_directory_timestamp(""), datetime.min)


if __name__ == "__main__":
    unittest.main()
