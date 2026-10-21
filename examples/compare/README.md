# Compare results from any eval tool

`holdline compare` gates two result files without holdline running your agent. Each file is one
row per case and run (CSV, TSV, JSON or JSONL), with a case id and a pass/fail or score column.
Rows that share an id are repeats.

These two files are the real helpdesk-agent runs from `examples/helpdesk/results/`, exported to a
plain CSV, the shape most eval tools can produce:

```bash
holdline compare helpdesk-5-samples.csv helpdesk-1-sample.csv --html report.html
```

Columns are guessed by name (`case_id`, `passed`, `run`, `group`); pass `--id-col`, `--pass-col`,
`--repeat-col` and `--threshold` (for scores) when yours differ.
