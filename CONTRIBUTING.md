# Contributing to Olas Operate Middleware

This repository follows the Valory open-autonomy contribution workflow.

See **[open-autonomy/CONTRIBUTING.md](https://github.com/valory-xyz/open-autonomy/blob/main/CONTRIBUTING.md)**
for the canonical guide (PR checklist, pre-commit routine, linter and
test commands, coding style).

## Repo-specific notes

- **Clone with git hooks:** `git clone -c core.hooksPath=.githooks git@github.com:valory-xyz/olas-operate-middleware.git`
- **Install + sync deps:** `uv sync --all-groups --frozen`
- **Run unit tests:** `uv run tox -e unit-tests`
- **Run all linters:** `uv run tox -p -e flake8 -e pylint -e black-check -e isort-check -e bandit -e safety -e mypy`
- **Testing guide:** [TESTING.md](TESTING.md) covers test organisation,
  integration-test RPC setup, VCR cassettes, and coverage rules.
- **In-flight work:** [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) tracks
  remaining high-impact items (security fixes, dead-code removal,
  reliability work).
- **Security:** see [SECURITY.md](SECURITY.md) for reporting
  vulnerabilities.

For anything not covered above (PR title format, review process,
branch naming, etc.), follow the canonical guide.
