# Contributing to Work-Flow

Thanks for your interest in contributing! This guide will help you get started.

## Development Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- [Temporal CLI](https://docs.temporal.io/cli)

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
make dev  # Starts Temporal + Worker + FastAPI
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Running Tests

```bash
# Backend (624 tests)
cd backend
python -m pytest tests/ -q

# Frontend
cd frontend
npm test -- --run
```

## Code Style

### Python (Backend)

- Formatter: [Black](https://github.com/psf/black) (default settings)
- Linter: [Ruff](https://github.com/astral-sh/ruff)
- Type hints encouraged for public APIs
- Async/await for all I/O operations

### TypeScript (Frontend)

- ESLint + Next.js defaults
- Functional components with hooks
- Use semantic keys in list renders (no `key={index}`)

## Pull Request Process

1. **Fork & branch**: Create a feature branch from `main`
2. **Small PRs**: Keep changes focused — one feature or fix per PR
3. **Tests**: Add tests for new functionality; don't break existing ones
4. **Describe**: Write a clear PR description explaining what and why
5. **Review**: Wait for at least one approval before merging

### Branch Naming

- `feat/short-description` — new features
- `fix/short-description` — bug fixes
- `refactor/short-description` — code improvements
- `docs/short-description` — documentation

## Reporting Issues

- Use GitHub Issues for bugs and feature requests
- Include steps to reproduce for bugs
- Check existing issues before creating new ones

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
