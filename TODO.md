# TODO

Items below are in implementation order: smallest and most isolated first, deferred
items last. The "Feedback" section captures real release-note workflow pain that
informed the priorities; answers below the open questions are decisions, not
discussion.

## Feedback from release-note workflow (2.43 tracker performance, 2026-04)

Captured while regenerating every p95 table in the 2.43 release notes from `gstat`.

* **Make the Diff (ms) and Change (%) columns selectable.** Release notes typically
carry one or the other, not both. A `--columns p95,change` (or similar) selector lets
the output drop straight into a release-note table without manual column deletion.
  * **Open**: flag shape `--no-diff` / `--no-change` (booleans, cheap, covers the actual
ask) or `--columns p50,change` (selector, more flexible, more parsing)?
  * **Answer**: `--no-diff` / `--no-change`. The actual asks are "drop one specific
column"; both are independent yes/no choices that compose cleanly. A `--columns`
selector forces users to also re-list every column they want to keep, which is more
typing for the same outcome. Reach for a selector only if a third toggle (or a
re-ordering need) appears.

* **Cell suppression policy for KO-only scenarios.** Today `gstat` omits the row entirely
when there are no OK samples. That's correct percentile semantics, but in a `compare`
table the row simply disappears and the reader can't see the "this version failed
completely" signal. Emitting the row with `-` (or a parameter such as
`--ko-policy=show`) would let release notes preserve the failure signal without manual
work.
  * **Open**: pick a sentinel for "all KO" that does not collide with `-` (used today for
"request not present in this run"). Candidates: `KO`, `failed`, `0/N`, `100% KO`.
  * **Answer**: `KO`. Three letters, matches Gatling's own terminology, fits in a
narrow column without ragged alignment. `failed` is wordier and not what Gatling
calls it. `0/N` and `100% KO` overload the cell with information that already lives
in the surrounding KO-counts text. Document the two sentinels together: `-` = "request
not present", `KO` = "request present, all attempts KO'd".
  * **Open**: row-level (whole row is `KO`) or cell-level (some runs OK, some KO)?
  * **Answer**: cell-level. The release-note matched-concurrency tables (Shape B
above) need rows where 2.41 has `KO` at 4u but real numbers at 2u; a row-level rule
would force splitting those into two tables. The cost is that a Markdown reader has to
glance across a row to assess it, but that is the natural reading direction anyway.
Implementation is the same either way; the choice only affects what we render.

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

* **Accept the run wrapper directory, not the inner `gatling-report-…/trackertest-…`
path.** Today `gstat compare` errors with "simulation.csv not found" when pointed at the
unzipped artifact directory. The wrapper is what `gh run download` produces and what
users actually have on disk; the inner dir is workflow plumbing. Composing
`"$run/$inner"` for ~30 invocations was the single biggest paper cut.
  * **Open**: reproduce the failure with a real `gh run download` artifact first. `gstat`
already has `is_multiple_reports_directory` for nested layouts; the bug may be in the
regex or the skip path rather than a missing feature.
  * **Answer**: reproduced. With a `gh run download` artifact at
`runs/2.43.0-load-6users-300s-24555271744/`, `gstat compare runs/2.43.0-load-6users-300s-24555271744 …`
errors with `Error: simulation.csv not found in 2.43.0-load-6users-300s-24555271744`,
which means `is_multiple_reports_directory` is rejecting that layout. The wrapper
contains exactly one child (`gatling-report-DHIS2-…-attempt-1/`) which itself contains
two `trackertest-…` dirs (one warmup, one measured). So the actual layout is
**three** levels deep: `wrapper / gatling-report-… / trackertest-…`. The detector
likely only walks one level. Fix is in detection, not a new feature: descend through
single-child dirs until a `trackertest-…` (or `simulation.csv`) is found, then treat
the inner dir as the report root. `--exclude warmup` continues to filter at the leaf
level. Add a regression test using a real artifact tree.

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

### Observations on percentile drift vs Gatling HTML

While regenerating the 2.43 tables we saw drift between Gatling's t-digest output and
`gstat`'s numpy-linear method scale predictably with two factors: **sample size** and
**tail shape**. Healthy populations (n > 1000, no bimodality) match within ±5 ms, exactly
what the README claims. Pathological cells diverge much more. The biggest single gap was
`Search Birth events` at 2.43 multi-user 2u: Gatling 4,106 ms → gstat 2,512 ms (−1,594 ms,
−39%) on n=33 with a strongly bimodal distribution (~90 ms vs ~3 s modes). Other
multi-second drifts clustered on the same scenario at other concurrency levels. Nothing
to fix in `gstat` — these are real artifacts of the underlying runs that t-digest happens
to smear over. Worth surfacing in the README as a worked example of why the method
matters; pairs naturally with the low-n confidence cues bullet above.
