# TODO

* Add Markdown table output to the default `gstat <dir>` command (in addition to CSV).
Same data, different format. Useful for pasting into PR descriptions and Jira tickets
without the user having to invoke `gstat compare` against itself or pipe through a
CSV-to-Markdown converter. Decide how to opt in: a `--format {csv,markdown}` flag, or
a `--markdown` boolean. Should also work with `--combine`.

## Feedback from release-note workflow (2.43 tracker performance, 2026-04)

Captured while regenerating every p95 table in the 2.43 release notes from `gstat`. Listed
in rough priority order; items 1, 3 and 6 are the highest leverage, items 8 and 9 are
feature ideas rather than polish.

1. **Accept the run wrapper directory, not the inner `gatling-report-…/trackertest-…`
path.** Today `gstat compare` errors with "simulation.csv not found" when pointed at the
unzipped artifact directory. The wrapper is what `gh run download` produces and what
users actually have on disk; the inner dir is workflow plumbing. Composing
`"$run/$inner"` for ~30 invocations was the single biggest paper cut.

2. **Replace `--exclude warmup` with a built-in `--no-warmup` flag.** The string-match
approach is general but every run from `performance-tests.yml` uses the literal
`warmup-1` suffix; codifying it removes a class of typos.

3. **Add scenario filtering to `gstat compare`.** I had to grep `Login` (and the rest of
the noise rows) out of the markdown by hand. A `--include`/`--exclude-scenario` (regex)
on `gstat compare` would let release-note authors say "only the import scenarios" or
"only the ANC paths" and skip the post-edit step.

4. **Per-group output for `gstat compare`.** It currently emits one big table per
percentile, but most reports need rows by sub-scope: per-program for imports, per-user
for export. Either a `--group-by users` mode or a `--pivot` to swap row/column meaning
would have saved hand-stitching three per-version tables into one matched-concurrency
view.

5. **Make the Diff (ms) and Change (%) columns selectable.** Release notes typically
carry one or the other, not both. A `--columns p95,change` (or similar) selector lets
the output drop straight into a release-note table without manual column deletion.

6. **Skip the `Login` row by default.** Gatling-specific: every run starts with a Login.
It is effectively warmup-of-the-login itself and almost never a release-note signal. A
built-in skip (or a default convention) would help — most users will want it gone.

7. **Cell suppression policy for KO-only scenarios.** Today `gstat` omits the row entirely
when there are no OK samples. That's correct percentile semantics, but in a `compare`
table the row simply disappears and the reader can't see the "this version failed
completely" signal. Emitting the row with `-` (or a parameter such as
`--ko-policy=show`) would let release notes preserve the failure signal without manual
work. Document the chosen convention so readers know what `-` means.

8. **Confidence cues for low-n cells.** When `count` is small (say <30) the percentile
is statistically noisy. Marking those cells (asterisk, footnote, or a `--min-samples
30` warning) helps readers calibrate trust without us flagging it manually in narrative.
Particularly load-bearing for bimodal distributions where a tiny shift in landing point
moves the value by orders of magnitude.

9. **Multi-baseline `gstat compare` framing.** The output assumes one fixed baseline.
Release-note authoring usually wants "compare new against multiple olds simultaneously"
— e.g., 2.43 against 2.42 and against 2.41 separately. An `--against <pattern>` mode
that computes per-baseline deltas in one column block each would directly produce the
shape the 2.43 release notes ended up with.

10. **Header customizability.** The `Baseline` literal in the output header is fine but
respecting `--label baseline=<name>` (or simply using the supplied `--label` for the
baseline column) would let the table read more naturally without post-editing.

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
matters; pairs naturally with item 8 above (low-n confidence cues).
