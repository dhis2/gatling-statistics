# TODO

* Add Markdown table output to the default `gstat <dir>` command (in addition to CSV).
Same data, different format. Useful for pasting into PR descriptions and Jira tickets
without the user having to invoke `gstat compare` against itself or pipe through a
CSV-to-Markdown converter. Decide how to opt in: a `--format {csv,markdown}` flag, or
a `--markdown` boolean. Should also work with `--combine`.
