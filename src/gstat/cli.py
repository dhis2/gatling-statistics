"""argparse-based command-line entry points for gstat."""

import argparse
import sys
from pathlib import Path

import argcomplete
import plotly.graph_objects as go

from . import __git_sha__, __version__
from .compare import (
    collect_compare_input,
    format_compare_markdown,
    format_output,
    format_output_combined,
)
from .gatling import load_gatling_data
from .plots import (
    plot_percentiles,
    plot_percentiles_stacked,
    plot_scatter,
    plot_scatter_all,
    plot_timeline,
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


COMPARE_HELP = """\
Usage: gstat compare <baseline-dir> [--label NAME] <other-dir> [--label NAME] ... [options]

Compare percentiles across two or more Gatling runs as Markdown tables.
The first run is the baseline. Each non-baseline run gets three columns:
the percentile value, Diff (other - baseline, in ms), and Change
((other - baseline) / baseline * 100, in %).

Each input may be followed by --label NAME to override the column header
(default: the directory's basename).

Each input directory follows the same accepted shapes as `gstat <dir>`:
a directory with simulation.csv, a directory of <simulation>-<timestamp>
reports, or a `gh run download` wrapper that nests one of the above
up to 3 levels deep.

Options:
  --percentile {50,75,95,99}  Percentile(s) to render. Repeat for multiple. Default: 50 and 95.
  --exclude STRING            Exclude report directories containing this string (e.g. 'warmup').
  --no-diff                   Omit the Diff (ms) column from each candidate run.
  --no-change                 Omit the Change (%) column (and arrow legend) from each candidate.
  -h, --help                  Show this help.

Examples:
  gstat compare ./baseline ./candidate
  gstat compare ./a --label baseline ./b --label candidate --percentile 95
  gstat compare ./run-2.41.8 --label 2.41.8 \\
                ./run-2.42.4 --label 2.42.4 \\
                ./run-2.43.0 --label 2.43.0
"""


def _main_compare(argv: list[str]) -> None:
    """Run the `compare` subcommand.

    Hand-parses argv so per-input `--label` flags stay bound to the preceding
    positional input. argparse can't express that binding with nargs="+".
    """
    if argv and argv[0] in ("-h", "--help"):
        print(COMPARE_HELP, end="")
        return

    inputs: list[tuple[Path, str | None]] = []
    exclude: str | None = None
    percentile_keys: list[str] = []
    show_diff = True
    show_change = True

    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--label":
            if not inputs:
                print("Error: --label must follow an input directory", file=sys.stderr)
                sys.exit(2)
            if i + 1 >= len(argv):
                print("Error: --label requires a value", file=sys.stderr)
                sys.exit(2)
            path, _ = inputs[-1]
            inputs[-1] = (path, argv[i + 1])
            i += 2
        elif token == "--exclude":
            if i + 1 >= len(argv):
                print("Error: --exclude requires a value", file=sys.stderr)
                sys.exit(2)
            exclude = argv[i + 1]
            i += 2
        elif token == "--percentile":
            if i + 1 >= len(argv) or argv[i + 1] not in ("50", "75", "95", "99"):
                print("Error: --percentile requires one of: 50, 75, 95, 99", file=sys.stderr)
                sys.exit(2)
            percentile_keys.append(argv[i + 1])
            i += 2
        elif token == "--no-diff":
            show_diff = False
            i += 1
        elif token == "--no-change":
            show_change = False
            i += 1
        elif token in ("-h", "--help"):
            print(COMPARE_HELP, end="")
            return
        elif token.startswith("--"):
            print(f"Error: unknown option {token}", file=sys.stderr)
            sys.exit(2)
        else:
            inputs.append((Path(token), None))
            i += 1

    if len(inputs) < 2:
        print("Error: compare requires at least two input directories", file=sys.stderr)
        print("", file=sys.stderr)
        print(COMPARE_HELP, end="", file=sys.stderr)
        sys.exit(2)

    for path, _ in inputs:
        if not path.exists():
            print(f"Directory does not exist: {path}", file=sys.stderr)
            sys.exit(1)
        if not path.is_dir():
            print(f"Path is not a directory: {path}", file=sys.stderr)
            sys.exit(1)

    if not percentile_keys:
        percentile_keys = ["50", "95"]

    pkey_to_field = {"50": "50th", "75": "75th", "95": "95th", "99": "99th"}
    fields = [pkey_to_field[p] for p in percentile_keys]
    titles = {
        "50th": "Median Response Time (p50)",
        "75th": "75th Percentile Response Time (p75)",
        "95th": "95th Percentile Response Time (p95)",
        "99th": "99th Percentile Response Time (p99)",
    }

    collected = [collect_compare_input(path, label, exclude) for path, label in inputs]

    print(
        format_compare_markdown(
            collected, fields, titles, show_diff=show_diff, show_change=show_change
        ),
        end="",
    )


def _main():
    """Internal main function."""
    if len(sys.argv) > 1 and sys.argv[1] == "compare":
        _main_compare(sys.argv[2:])
        return

    parser = argparse.ArgumentParser(
        description="Calculate percentiles from Gatling simulation.csv files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Subcommands:
  compare       Render a Markdown comparison table across two or more runs. See
                `gstat compare --help` for usage.

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

  # Combine multiple runs into one row per request (combined samples)
  gstat --combine --exclude warmup ./samples/
        """,
    )
    parser.add_argument(
        "report_directory",
        type=Path,
        help=(
            "Path to a Gatling report. Accepts: a directory with simulation.csv, "
            "a directory of <simulation>-<timestamp> reports, or a `gh run download` "
            "wrapper that nests one of the above up to 3 levels deep."
        ),
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
        "--exclude",
        type=str,
        help="Exclude directories containing this string (e.g., 'warmup')",
    )
    parser.add_argument(
        "--combine",
        action="store_true",
        help=(
            "Combine response times across all runs in the input directory and emit "
            "one row per request. Useful when comparing multi-run baselines."
        ),
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

    gatling_data = load_gatling_data(args.report_directory, args.exclude)

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
    elif args.combine:
        format_output_combined(gatling_data)
    else:
        format_output(gatling_data)


if __name__ == "__main__":
    main()
