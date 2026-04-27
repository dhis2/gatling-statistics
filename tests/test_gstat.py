#!/usr/bin/env python3
"""End-to-end tests for gstat.

To run: uv run python tests/test_gstat.py
"""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from gstat import (
    collect_compare_input,
    format_compare_markdown,
    load_gatling_data,
    order_requests_gatling_html,
    plot_percentiles_stacked,
)

FIXTURE_DIR = (
    Path(__file__).parent / "fixtures" / "trackertest-20260424071214792-2.43.0-smoke-1u-1000req"
)
WARMUP_FIXTURE_DIR = (
    Path(__file__).parent
    / "fixtures"
    / "trackertest-20260424070546336-2.43.0-smoke-1u-1000req-warmup-1"
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
            run = gatling_data.get_runs(simulation)[0]
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
                data = gatling_data.get_request_data(simulation, run, full_path)
                self.assertEqual(data.count, expected_count, f"Wrong count for {full_path}")
                self.assertEqual(
                    data.response_times, expected_times, f"Wrong times for {full_path}"
                )
                self.assertAlmostEqual(
                    data.mean, expected_mean, places=2, msg=f"Wrong mean for {full_path}"
                )


class TestGatlingHtmlOrdering(unittest.TestCase):
    """Verify order_requests_gatling_html matches Gatling's HTML statistics table order.

    Input: the real glog-CSV at tests/fixtures/trackertest-20260424071214792-2.43.0-smoke-1u-1000req/
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


class TestCompare(unittest.TestCase):
    """End-to-end tests for `gstat compare`.

    Warmup-vs-main exercises both improvement (down-arrow) and regression (up-arrow) paths
    on real numbers; the synthetic tests cover request-set differences and merged row order.
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

        # Table column headers
        self.assertIn("| Scenario | Baseline | main | Diff | Change |", out)

        # Improvement: small absolute diff, sub-3% change. Exercises down-arrow + sign.
        self.assertIn("| ANC import | 44 | 43 | -1 | :arrow_down: -2.3% |", out)

        # Improvement: large negative diff, double-digit percent. Exercises down-arrow + double-digit.
        self.assertIn("| Login | 152 | 111 | -41 | :arrow_down: -26.9% |", out)

        # Regression: large positive diff, near-100%, comma-formatted four-digit value.
        # Exercises up-arrow + {:,.0f} comma + multi-percent.
        self.assertIn(
            "| Get Child Programme TEs / Search Birth events | 665 | 1,302 | +637 | :arrow_up: +95.8% |",
            out,
        )

        # Footer legend
        self.assertIn(
            "_:arrow_down: = faster (improvement), :arrow_up: = slower (regression)_", out
        )

    def test_compare_handles_request_set_difference(self):
        """When a request appears in only one input, the missing-side cells render as `-`
        (not `N/A`, not `0`). Exercises the `if oval is None or bval is None` branch."""
        # fmt: off
        # ruff: noqa: E501
        only_login = """record_type,scenario_name,group_hierarchy,request_name,status,start_timestamp,end_timestamp,response_time_ms,error_message,event_type,duration_ms,cumulated_response_time_ms,is_incoming
request,,,Login,OK,1762133595750,1762133595858,108,,,,,false
"""
        login_and_search = """record_type,scenario_name,group_hierarchy,request_name,status,start_timestamp,end_timestamp,response_time_ms,error_message,event_type,duration_ms,cumulated_response_time_ms,is_incoming
request,,,Login,OK,1762133595750,1762133595858,120,,,,,false
request,,,Search,OK,1762133595900,1762133595950,50,,,,,false
"""
        # fmt: on

        with tempfile.TemporaryDirectory() as tmpdir:
            a = Path(tmpdir) / "a-20250101010101010-test"
            b = Path(tmpdir) / "b-20250101010101010-test"
            a.mkdir()
            b.mkdir()
            (a / "simulation.csv").write_text(only_login)
            (b / "simulation.csv").write_text(login_and_search)

            baseline = collect_compare_input(a, label=None, exclude=None)
            candidate = collect_compare_input(b, label=None, exclude=None)

            out = format_compare_markdown([baseline, candidate], ["95th"], self.PERCENTILE_TITLES)

        # Login is in both: real numbers + diff/change
        self.assertIn("| Login | 108 | 120 | +12 | :arrow_up: +11.1% |", out)
        # Search is only in candidate: baseline cell `-`, but value/diff/change all `-`
        # because the function bails when either side is None.
        self.assertIn("| Search | - | - | - | - |", out)

    def test_compare_row_order_is_first_seen_across_inputs(self):
        """Row order in the compare table is "first seen across inputs", baseline first.
        Pins the `seen` set / `ordered_requests` accumulator behavior."""
        # fmt: off
        # ruff: noqa: E501
        a_csv = """record_type,scenario_name,group_hierarchy,request_name,status,start_timestamp,end_timestamp,response_time_ms,error_message,event_type,duration_ms,cumulated_response_time_ms,is_incoming
request,,,X,OK,1,2,1,,,,,false
request,,,Y,OK,3,4,1,,,,,false
"""
        b_csv = """record_type,scenario_name,group_hierarchy,request_name,status,start_timestamp,end_timestamp,response_time_ms,error_message,event_type,duration_ms,cumulated_response_time_ms,is_incoming
request,,,Y,OK,1,2,1,,,,,false
request,,,Z,OK,3,4,1,,,,,false
"""
        # fmt: on

        with tempfile.TemporaryDirectory() as tmpdir:
            a = Path(tmpdir) / "a-20250101010101010-test"
            b = Path(tmpdir) / "b-20250101010101010-test"
            a.mkdir()
            b.mkdir()
            (a / "simulation.csv").write_text(a_csv)
            (b / "simulation.csv").write_text(b_csv)

            baseline = collect_compare_input(a, label=None, exclude=None)
            candidate = collect_compare_input(b, label=None, exclude=None)

            out = format_compare_markdown([baseline, candidate], ["95th"], self.PERCENTILE_TITLES)

        # Expected order: X (only in baseline), Y (in both, first seen via baseline), Z (only in candidate).
        x_idx = out.index("| X |")
        y_idx = out.index("| Y |")
        z_idx = out.index("| Z |")
        self.assertLess(x_idx, y_idx)
        self.assertLess(y_idx, z_idx)


if __name__ == "__main__":
    unittest.main()
