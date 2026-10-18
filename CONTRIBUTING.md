# Contributing

Thank you for contributing to MasterProDev's AI Assistant!

## Development Setup

1. Clone the repo
2. Create a virtual environment: python -m venv .venv
3. Activate: .venv\Scripts\Activate (Windows) or source .venv/bin/activate (Unix)
4. Install: pip install -e ".[dev]"
5. Copy .env.example to .env and fill in your secrets

## Before You Commit

`ash
# Format code
black src/ tests/

# Lint
ruff check src/ tests/ --fix

# Type check
mypy src/mpd_assistant

# Run tests
pytest tests/
`

## Commit Message Guidelines

- Use clear, descriptive messages
- Reference issue numbers: "Fix #123: brief description"
- Follow: 	ype(scope): subject (e.g., eat(agents): add concierge agent)
- Types: eat, ix, efactor, 	est, docs, chore

## Code Review

All PRs require:

1. Passing CI (lint, type check, tests, secret scan)
2. At least one approval
3. Updated docs if behavior changed
4. Eval metrics green (if applicable)

## Testing

- Unit tests for logic (mocked LLM)
- Integration tests for databases and APIs
- Eval tests for quality gates
- Security tests for injection and PII leaks

`ash
pytest tests/ -v --cov
`

## Questions?

- Open a discussion in GitHub Discussions
- Check the runbooks/ for operational guidance
- Email dev@masterprodev.com for security questions

## License

By contributing, you agree your work is under the MIT license.
