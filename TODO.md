# TODO

Items below are in implementation order: smallest and most isolated first, deferred
items last. The "Feedback" section captures real release-note workflow pain that
informed the priorities; answers below the open questions are decisions, not
discussion.

## Feedback from release-note workflow (2.43 tracker performance, 2026-04)

Captured while regenerating every p95 table in the 2.43 release notes from `gstat`.

* **Add `req_per_sec` (throughput) column.** Both default and `--combine` CSV outputs, and
the `compare` Markdown, would benefit from a throughput column alongside `count`. Gatling
calls this `Cnt/s` and computes it as `count / run_duration_seconds` over the full
population. We'd compute the same way (over OK+KO since percentiles already are) and
expose it as `req_per_sec`. Skipped from this round because the run-duration math has its
own small design question (per-request time span vs. whole-run duration; Gatling uses
whole-run) that is worth resolving in its own commit.
  * **Workflow data point (2026-04-27).** Re-confirmed during the 2.43 release-note
regeneration: every concurrency-sweep, soak, and pool-comparison table needs a `req/s`
column next to `p95`. Today the author either eyeballs Gatling's HTML index page or
divides `count` by the configured run duration. For a 300s sweep this came out close to
Gatling's number but **not identical** (e.g. 2.43.0 6u Child p95 row: gstat
`count=3156`, naive 3156/300 = 10.52, but Gatling HTML/release-note value is 10.48 —
Gatling computes over the actual measured window, not the nominal `importDurationSec`).
That ~0.4% drift is enough to make hand-stitched tables disagree with Gatling's HTML by
1 in the second decimal, which is exactly the kind of small noise that erodes trust.
Strong argument for landing this column: same number, same source.

* **Add request filtering to `gstat compare`.** Two recurring needs collapse into one
flag pair: drop noise rows the user does not care about (e.g. `Login`, which most
release-note authors strip by hand), and narrow to a subset for focused tables (e.g.
"only import scenarios" or "only ANC paths"). A `--include <regex>` and
`--exclude-request <regex>` pair covers both. Subsumes the "skip Login" use case without
baking Gatling-specific defaults into the tool.
  * **Open**: match against bare `request_name`, or against the displayed full path
(e.g. `Get ANC events / Search by date range`)? Full path lets users narrow by group.
  * **Answer**: match against the displayed full path. The bare name has too many
collisions across groups (e.g. `Get first event` appears under both ANC and Child
scenarios with different semantics) to be useful as a filter target on its own. The
full path also lets users narrow by group with one anchor (`^Get ANC events`), which
is exactly the "only ANC paths" case from the release-note workflow. The bare-name
case (`--exclude-request '^Login$'`) is still trivial because the full path equals
the bare name when there is no group prefix.

* **Add Markdown table output to the default `gstat <dir>` command (in addition to CSV).**
Same data, different format. Useful for pasting into PR descriptions and Jira tickets
without the user having to invoke `gstat compare` against itself or pipe through a
CSV-to-Markdown converter. Should also work with `--combine`.
  * **Open**: flag shape `--format {csv,markdown}` (selector, scales if more formats land
later) or just `--markdown` (boolean, simpler for two formats)?
  * **Answer**: `--format {csv,markdown}`. Two reasons. (1) JSON is the obvious next
format request the moment anyone tries to pipe `gstat` into a script, and adding
`--json` next to `--markdown` reopens this discussion. (2) Booleans pile up:
`--markdown --json` is a malformed input that the parser has to reject explicitly,
whereas `--format` rejects the impossible by construction. The cost is one extra word
at invocation; cheap.
  * **Open**: emit the same column set as CSV, or auto-trim to the columns that read well
in Markdown (e.g. drop `directory`/`simulation` when they are constant)?
  * **Answer**: emit the same columns. Auto-trim is a "smart default" that surprises
users when a constant column suddenly disappears between runs. Pasting a Markdown
table from one run with `directory` present and another without it is exactly the kind
of small inconsistency that costs time to notice. If trimming is wanted, expose it as
a separate `--drop-constant-columns` flag later. Never trim implicitly.

* **Confidence cues for low-n cells.** When `count` is small (say <30) the percentile
is statistically noisy. Marking those cells (asterisk, footnote, or a `--min-samples
30` warning) helps readers calibrate trust without us flagging it manually in narrative.
Particularly load-bearing for bimodal distributions where a tiny shift in landing point
moves the value by orders of magnitude.
  * **Open**: are reader-time-saved cues worth the table noise? Release-note authors
typically copy the table and would have to scrub the asterisks. May be enough to keep
this out of the output and just bold "watch the count column" in the README.
  * **Answer**: skip the in-cell cues. The release-note workflow confirmed the
problem (a 39% gap on n=33), but the fix is editorial, not mechanical: the author
needs to flag that *row* in narrative, and the `count` column is already there to
tell them when. Adding asterisks would mean every release-note author starts every
table by stripping them. Two non-output changes capture the value without the cost:
**(a)** keep the `count` column visible in `gstat compare` output (it is) and lead
the README's percentile-method discussion with a worked example of what low-n drift
looks like (done in the README rewrite); **(b)** if a reminder is wanted, add a
`--warn-min-samples N` flag that emits a stderr line listing rows below the
threshold without touching the table itself.

* **Per-group output for `gstat compare`.** It currently emits one big table per
percentile, but most reports need rows by sub-scope: per-program for imports, per-user
for export. Either a `--group-by users` mode or a `--pivot` to swap row/column meaning
would have saved hand-stitching three per-version tables into one matched-concurrency
view.
  * **Open**: needs concrete examples. Paste one or two release-note tables you wish
had come straight out of `gstat` so we know what "per-group" should produce.
  * **Answer**: two shapes recurred in the 2.43 release notes.

    **Shape A: concurrency sweep, per program × users** (one table per program,
columns are user counts within the same version). From [tracker-performance.md
Concurrency sweep](https://github.com/dhis2/dhis2-releases/blob/main/releases/2.43/tracker-performance.md#concurrency-sweep):

    ```
    MNCH / PNC import (2.43.0):
    | users | req/s | p95 (ms) | run        |
    | 1     | 1.30  | 1214     | 24566167645 |
    | 2     | 1.97  | 1785     | 24555265579 |
    | 4     | 2.52  | 3372     | 24555267507 |
    | 6     | 3.78  | 2897     | 24555271744 |
    ```

    Today this is hand-built by running `gstat` once per concurrency level and
extracting one row each. A `--group-by users` (or `--rows users`) on a multi-run input
would emit this directly. The grouping key has to come from outside the
`simulation.csv` (concurrency is not in the file), so accept it as either a CLI
parameter (`--label 1u --label 2u …` already exists) or auto-extract from a directory
naming convention (regex on basename).

    **Shape B: matched-concurrency comparison, per request × version** (one table,
columns are versions at one fixed concurrency). From [tracker-performance.md
Multi-user export Summary](https://github.com/dhis2/dhis2-releases/blob/main/releases/2.43/tracker-performance.md#multi-user-export-same-seeded-db):

    ```
    | Request                  | 2.43 2u | 2.42 2u | 2.41 2u | 2.43 4u | 2.42 4u | 2.41 4u |
    | Go to first page         | 12      | -       | 39,952  | 19      | 59,796  | -       |
    | ...                      | ...     | ...     | ...     | ...     | ...     | ...     |
    ```

    This is `gstat compare` output stitched across two concurrency levels. A `--pivot`
or `--columns-per-run versionXusers` mode that takes 2N runs and produces 2N columns
keyed by (label, users) would replace the manual stitching.

    Recommend tackling Shape A first; it has a cleaner contract (one input, one
grouping key) and covers the more common release-note table layout. Shape B can wait
until multi-baseline framing (item below) lands, since they share the same N-version
shape.

* **Multi-baseline `gstat compare` framing.** The output assumes one fixed baseline.
Release-note authoring usually wants "compare new against multiple olds simultaneously"
— e.g., 2.43 against 2.42 and against 2.41 separately. An `--against <pattern>` mode
that computes per-baseline deltas in one column block each would directly produce the
shape the 2.43 release notes ended up with.
  * **Open**: defer until the simpler items above ship; you can fake it today by running
`compare` three times. Revisit if it is still painful after filtering and column
selection are in.
  * **Answer**: defer, with one caveat. Faking it via three `compare` invocations
worked for the 2.43 release notes once filtering was on the manual side, but the
manual stitching produced exactly Shape B above. So when Shape B lands as a feature
(per-group per-version pivot), multi-baseline framing falls out for free: the same
mechanism that emits "p95 per (version, users)" can emit "p95 per (version, baseline)
with deltas". No need for a separate `--against <pattern>` flag if the pivot lands
first. Revisit only if Shape B does not generalise.

