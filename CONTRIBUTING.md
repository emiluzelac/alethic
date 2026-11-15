# Contributing to Alethic

Thank you for your interest in contributing to Alethic! We welcome contributions, feedback, and ideas from the community.

## Code of Conduct

Be respectful, inclusive, and professional. We're building trust in AI systems together.

## How to Contribute

### Reporting Issues

- **Bugs**: Describe the problem, steps to reproduce, and expected vs. actual behavior
- **Feature Requests**: Explain the use case and how it benefits the framework
- **Documentation**: Point out unclear sections or suggest improvements

### Making Changes

1. **Fork and branch**
   ```bash
   git clone https://github.com/YOUR_USERNAME/alethic.git
   cd alethic
   git checkout -b feature/your-feature-name
   ```

2. **Set up development environment**
   ```bash
   pip install -e ".[dev]"
   ```

3. **Make your changes**
   - Keep changes focused and minimal
   - Follow existing code style (implicit via mypy strict mode)
   - Add tests for new functionality
   - Update documentation as needed

4. **Run tests and type checking**
   ```bash
   pytest tests/ -v
   mypy --strict src
   ```

5. **Commit with clear messages**
   ```bash
   git commit -m "Brief description of change"
   ```

6. **Push and open a pull request**
   ```bash
   git push origin feature/your-feature-name
   ```

## Where a pull request lands

This GitHub repository is a mirror. Since 2026-11-15 the maintainer's canonical
repository is private and copies every change here, so a pull request is not
merged on GitHub: once it is reviewed and its checks pass, the maintainer
applies it to the canonical repository (your authorship is kept) and the mirror
brings it to `main` here, which closes the pull request.

## Pull Request Guidelines

- **Title**: Concise, descriptive (e.g., "Add belief TTL validation", "Fix SimulatorWorker condition parsing")
- **Description**: Explain what changed, why, and any design decisions
- **Tests**: Include tests for new functionality or bug fixes
- **Documentation**: Update docs if behavior changes
- **CI**: All tests and type checks must pass

## Development Conventions

### Code Style

- Use type hints throughout (mypy strict mode is enforced)
- Use dataclasses for data objects
- Use `@dataclass` with `from __future__ import annotations`
- Follow PEP 8

### Testing

- Write tests in `tests/` with names prefixed `test_`
- Use fixtures from `tests/conftest.py` where appropriate
- Preserve or improve coverage for every behavior you change

### Documentation

- Update docstrings for new public APIs
- Update relevant `.md` files in `docs/`
- Keep `README.md` examples working
- Include architecture rationale for non-obvious design choices

## Project Structure

```
src/       Installable `alethic` package root
tests/     Test suite
docs/      Architecture and API documentation
examples/  Domain-neutral examples
```

## Key Areas for Contribution

- **Store backends**: Implement new `StoreProtocol` implementations (e.g., PostgreSQL)
- **Workers**: Improve the domain-neutral worker and orchestration protocols
- **Documentation**: Tutorials, examples, deployment guides
- **Performance**: Optimize kernel operations or store queries
- **Type safety**: Improve type coverage or migrate from `Any` to specific types

## Questions?

- Open an issue for discussion
- Check existing issues and documentation first
- Link to relevant academic work or external resources when applicable

## Acknowledgments

Alethic builds on well-established patterns from systems engineering and cognitive science. Key inspirations:

- Blackboard architectures (e.g., HEARSAY-II)
- Evidence-based decision systems
- Role-based access control in distributed systems
- Propose-commit protocols in database transactions

See [From Fragile Glue to Governed Cognition](https://doi.org/10.5281/zenodo.18691808) for the full scholarly context.
