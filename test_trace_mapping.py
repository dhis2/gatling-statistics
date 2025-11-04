#!/usr/bin/env python3
"""Test trace mapping for stacked plots to prevent regression of overlapping traces bug.

This test suite was created to prevent regression of a bug where trace indices would overlap
when switching between requests in the stacked plot dropdown. The bug occurred because mean
lines were added in a separate loop after all bars, causing non-contiguous trace indices for
each request.

To run: uv run python test_trace_mapping.py
"""

import tempfile
import unittest
from pathlib import Path

from gstat import load_gatling_data, plot_percentiles_stacked


class TestTraceMapping(unittest.TestCase):
    """Test that trace indices don't overlap when switching requests in stacked plots."""

    @classmethod
    def setUpClass(cls):
        """Load example data once for all tests."""
        example_dir = Path(__file__).parent / "example"
        if not example_dir.exists():
            raise unittest.SkipTest(f"Example directory not found: {example_dir}")
        cls.gatling_data = load_gatling_data(example_dir)

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
                "Get a list of single events|Go to first page of program VBqh0ynB2wv": (
                    1,
                    [59],
                    59.0,
                ),
                "Get a list of TEs|Get first page of TEs of program ur1Edk5Oe2n": (1, [134], 134.0),
                "Get a list of TEs|Go to single enrollment|Get first enrollment": (1, [7], 7.0),
                # Requests with nested hierarchy - same request_name, different contexts
                "Get a list of single events|Get one single event|Get first event": (
                    2,
                    [23, 14],
                    18.5,
                ),
                "Get a list of single events|Get one single event|Get relationships for first event": (
                    2,
                    [5, 4],
                    4.5,
                ),
                "Get a list of TEs|Go to single enrollment|Get one event|Get first event from enrollment": (
                    2,
                    [13, 13],
                    13.0,
                ),
                "Get a list of TEs|Go to single enrollment|Get one event|Get relationships for first event": (
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


if __name__ == "__main__":
    unittest.main()
