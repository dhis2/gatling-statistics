#!/usr/bin/env python3
"""Test trace mapping for stacked plots to prevent regression of overlapping traces bug.

This test suite was created to prevent regression of a bug where trace indices would overlap
when switching between requests in the stacked plot dropdown. The bug occurred because mean
lines were added in a separate loop after all bars, causing non-contiguous trace indices for
each request.

To run: uv run python test_trace_mapping.py
"""

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


if __name__ == "__main__":
    unittest.main()
