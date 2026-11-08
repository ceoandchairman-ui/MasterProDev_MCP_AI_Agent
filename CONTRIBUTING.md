# Contributing

1. Create a virtual environment and run `pip install -e ".[dev]"`.
2. Copy `.env.example` to `.env`.
3. Before committing: `ruff check src tests` and `pytest`.
4. Commit messages: `type(scope): subject` (feat, fix, refactor, test, docs, chore).
5. Never commit secrets; see `SECURITY.md`.
6. Behavior changes need a test, and agent behavior changes need an eval case in `evals/`.
