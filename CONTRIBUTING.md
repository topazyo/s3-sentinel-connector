# Contributing to S3 to Sentinel Log Connector

## Code of Conduct

This project adheres to the Contributor Covenant code of conduct. By participating, you are expected to uphold this code.

## How Can I Contribute?

### Reporting Bugs

- Use the bug report template
- Include detailed steps to reproduce
- Provide environment details
- Include relevant logs

### Suggesting Enhancements

- Use the feature request template
- Explain the use case
- Describe expected behavior
- Provide example code if possible

### Pull Requests

1. Follow the coding style
2. Add tests for new features
3. Update documentation
4. Write meaningful commit messages
5. Reference related issues
6. Ensure CI passes: `pytest`, `black --check .`, `isort --check-only .`, `ruff check .` (GitHub Actions runs these checks automatically).

## Development Setup

1. Fork the repository
2. Set up development environment
	- See the Quickstart in `README.md` for a minimal local setup.
3. Create feature branch
4. Make your changes
5. Run tests
6. Submit pull request

## Style Guidelines

- Follow PowerShell and Python best practices
- Use meaningful variable names
- Add comments for complex logic
- Keep functions focused and small

## Testing

- Write unit tests for new features
- Ensure all tests pass locally
- Include integration tests where needed
- Maintain test coverage above 80%