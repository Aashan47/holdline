# Contributing to holdline

Thanks for helping. holdline is small on purpose, so contributions are easiest to land when they
keep it that way. This page covers setup, the few rules the project lives by, and how a change gets
merged.

## Good first contributions

- **Tell us where the gate or the judge check gets it wrong.** A result file (with private data
  removed) and what you expected is one of the most useful issues you can open.
- **Import results from another eval tool.** `holdline compare` reads CSV, JSON and JSONL with
  guessed columns; an example or a small adapter for a tool you use (promptfoo, DeepEval, Inspect,
  LangSmith or Braintrust exports) helps everyone using it.
- **Adapters for agent frameworks** that map their callbacks to `holdline.step()`.
- **Docs and examples**: a short example for a real use case beats a long explanation.

Issues labelled `good first issue` are scoped for a first pull request. If you want to take one,
say so in the issue so two people don't do the same work.

## Set up

```bash
git clone https://github.com/<you>/holdline && cd holdline
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" ruff
pytest -q            # all tests pass before you start
ruff check src tests examples
```

The browser judge check (`site/judge/`) has a parity test against the Python package that needs
Node.js on your PATH; without Node it is skipped.

## The rules the project lives by

1. **No runtime dependencies.** The package uses the Python standard library only, so it installs
   into anyone's agent environment without conflicts. Optional extras (like `yaml`) are fine.
2. **Python 3.9 and up.** CI runs 3.9, 3.11 and 3.13.
3. **Statistics before verdicts.** Anything that reports a rate reports its uncertainty, resampling is
   seeded, and new statistics come with a test against known values.
4. **The browser and Python agree.** If you change the judge maths in `src/holdline/judge.py` or
   `stats.py`, change `site/judge/judge.js` the same way; `tests/test_judge_page.py` checks they match.
5. **Reports stay self-contained.** HTML reports make no network requests and work offline.
6. **Plain language** in messages and docs: say what happened and what to do next.

## Making a change

1. Open an issue first for anything bigger than a small fix, so we can agree on the shape before you
   spend time on it.
2. Branch from `main`, keep the pull request to one change, and add or update tests.
3. Run `pytest -q` and `ruff check src tests examples` before pushing.
4. Add a line under **Unreleased** in `CHANGELOG.md` if users would notice the change.
5. Open the pull request; the template asks for the few things a reviewer needs.

CI must pass and a maintainer reviews every pull request. Expect questions rather than silence; if
nobody has replied in a week, a polite nudge on the pull request is welcome.

## Reporting a security problem

Please don't open a public issue. See [SECURITY.md](SECURITY.md).

## For maintainers: releasing

1. Move the **Unreleased** notes in `CHANGELOG.md` under the new version and bump the version in
   `pyproject.toml` and `src/holdline/__init__.py`.
2. Merge to `main`, then tag: `git tag -a vX.Y.Z -m "holdline X.Y.Z" && git push origin vX.Y.Z`.
3. The release workflow checks that the tag matches the version, runs the tests, builds, publishes
   to PyPI through trusted publishing, and creates the GitHub release.

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE)
and that you'll follow the [Code of Conduct](CODE_OF_CONDUCT.md).
