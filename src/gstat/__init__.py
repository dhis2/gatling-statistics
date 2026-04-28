"""Gatling Statistics Calculator.

Calculate statistics like percentiles from Gatling simulation.csv files.
"""

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

from .compare import (
    CompareInput,
    GatlingCombinedRequest,
    collect_compare_input,
    combine_request_data,
    format_change,
    format_compare_markdown,
    format_output,
    format_output_combined,
)
from .gatling import (
    GatlingRequest,
    GatlingRun,
    GatlingRuns,
    calculate_percentiles,
    find_report_root,
    is_multiple_reports_directory,
    load_gatling_data,
    order_requests_gatling_html,
    parse_gatling_directory_timestamp,
    parse_simulation_csv,
)
from .plots import (
    plot_percentiles,
    plot_percentiles_stacked,
    plot_scatter,
    plot_scatter_all,
    plot_timeline,
)

__all__ = [
    "__version__",
    "__git_sha__",
    "CompareInput",
    "GatlingCombinedRequest",
    "GatlingRequest",
    "GatlingRun",
    "GatlingRuns",
    "calculate_percentiles",
    "collect_compare_input",
    "combine_request_data",
    "find_report_root",
    "format_change",
    "format_compare_markdown",
    "format_output",
    "format_output_combined",
    "is_multiple_reports_directory",
    "load_gatling_data",
    "main",
    "order_requests_gatling_html",
    "parse_gatling_directory_timestamp",
    "parse_simulation_csv",
    "plot_percentiles",
    "plot_percentiles_stacked",
    "plot_scatter",
    "plot_scatter_all",
    "plot_timeline",
]


def main():
    """Console-script entry point. Imported lazily so `from gstat import X`
    doesn't pull in argparse/argcomplete for non-CLI consumers."""
    from .cli import main as _cli_main

    _cli_main()
