# Changelog

Notable changes to holdline. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Contributor setup: contributing guide, code of conduct, security policy, issue forms, pull request
  template, code owners, Dependabot for GitHub Actions.
- Lint job (ruff) in CI, and a release workflow that publishes to PyPI on version tags.

### Fixed
- The browser judge check confirms a copy on the button itself, not only in a toast.

## [0.2.0] - 2026-10-21

### Added
- `holdline compare`: gate result files from any eval tool (CSV, TSV, JSON, JSONL), with columns
  guessed by name or given as flags, and repeats from rows that share a case id.
- Browser judge check: kappa with an interval, false-pass rate, bias by group with sign reversal, and
  every disagreement, computed client-side; tested against the Python package.
- `holdline.load_results` in the public API.

### Changed
- Report stat bar keeps one row at laptop widths.

## [0.1.0] - 2026-10-21

### Added
- Tracing (`@holdline.tool`, `holdline.step`), JSONL and OpenTelemetry export.
- Checks: answer modes, outcome (answer, abstain, escalate), tool use and order, step and loop
  limits, JSON Schema tool arguments, custom checks, LLM judge.
- Runner with repeats, pass^k, flaky cases and case-level bootstrap intervals.
- Judge calibration against human labels.
- Gate: paired McNemar test, bootstrap interval, must-pass cases, abstention floor, budgets.
- CLI, single-file HTML reports, Markdown summaries, composite GitHub Action.

[Unreleased]: https://github.com/Aashan47/holdline/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Aashan47/holdline/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Aashan47/holdline/releases/tag/v0.1.0
