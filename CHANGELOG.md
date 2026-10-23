# Changelog

Notable changes to holdline. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Add a CI guide (`docs/ci-guide.md`) covering the GitHub Action, `holdline compare` for results from other eval tools, guard rails, baseline refresh, and troubleshooting.

## [0.2.1] - 2026-10-23

### Added
- Contributor setup: contributing guide, code of conduct, security policy, issue forms, pull request
  template, code owners, Dependabot for GitHub Actions.
- Lint job (ruff) in CI, and a release workflow that publishes to PyPI on version tags.

### Changed
- GitHub Actions used by the workflows updated (checkout 7, setup-python 6, upload-artifact 7,
  download-artifact 8).
- Lint fixes across the code (import order, an unused import, clearer variable names).

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

[Unreleased]: https://github.com/Aashan47/holdline/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/Aashan47/holdline/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Aashan47/holdline/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Aashan47/holdline/releases/tag/v0.1.0
