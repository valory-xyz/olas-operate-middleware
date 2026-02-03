# Contributing to Olas Operate Middleware

Thank you for your interest in contributing to **Olas Operate Middleware**! This document provides guidelines and instructions for developers who want to contribute to this project.

For general information about the project, installation, and basic usage, see [README.md](README.md).

## Table of Contents

- [Development Environment Setup](#development-environment-setup)
- [Development Workflow](#development-workflow)
- [Code Standards](#code-standards)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Security](#security)
- [Troubleshooting](#troubleshooting)

## Development Environment Setup

### Key Components

#### 1. **CLI Module** (`operate/cli.py`)
The main entry point for the application. Provides commands like:
- `daemon`: Start the background service
- `quickstart`: User account management

#### 2. **Services** (`operate/services/`)
Manages autonomous agent services:
- `service.py`: Core service class
- `manager.py`: Service manager for multiple services
- `protocol.py`: For interacting with the OLAS protocol
- `agent_runner.py`: Handles agent_runner binary
- `deployment_runner.py`: Handles running the binary deployment
- `funding_manager.py`: Manages wallet funding
- `health_checker.py`: Monitors service health

#### 3. **Wallet Management** (`operate/wallet/`)
Handles cryptocurrency wallet operations:
- `master.py`: Main Ethereum wallet (EOA and Safe)
- `wallet_recovery_manager.py`: Recovery mechanisms

#### 4. **HTTP API** (`operate/operate_http/`)
REST API server built with FastAPI:
- Authentication endpoints
- Service management endpoints
- Wallet and account endpoints
- Settings and configuration endpoints

#### 5. **Bridge Management** (`operate/bridge/`)
Handles cross-chain token transfers via bridge providers

## Development Workflow

### Creating a Feature Branch

1. **Start from the main branch:**
   ```bash
   git checkout main
   git pull origin main
   ```

2. **Create a feature branch:**
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/your-bug-fix
   ```

   **Branch naming conventions:**
   - `feature/description`: New feature
   - `fix/description`: Bug fix
   - `docs/description`: Documentation updates
   - `refactor/description`: Code refactoring
   - `test/description`: Test improvements
   - `chore/description`: Configuration/maintenance

3. **Make your changes:**
   - Keep commits focused and atomic
   - Write clear commit messages
   - Test your changes frequently

### Making Changes

#### Code Guidelines

- **Follow PEP 8**: Python style guide
- **Type hints**: Use type annotations throughout
- **Docstrings**: Add docstrings to all public functions/classes
- **Comments**: Explain complex logic with comments

## Code Standards

### Code Quality Tools

The project uses several tools to maintain code quality. All are configured in `tox.ini`:

1. **Black**: Code formatting
   ```bash
   tox -e black      # Format code
   tox -e black-check # Check formatting
   ```

2. **isort**: Import sorting
   ```bash
   tox -e isort       # Sort imports
   tox -e isort-check # Check imports
   ```

3. **Flake8**: Linting
   ```bash
   tox -e flake8
   ```

4. **MyPy**: Type checking
   ```bash
   tox -e mypy
   ```

5. **Pylint**: Code analysis
   ```bash
   tox -e pylint
   ```

6. **Bandit**: Security checks
   ```bash
   tox -e bandit
   ```

7. **Safety**: Dependency vulnerability checks
   ```bash
   tox -e safety
   ```

### Running All Checks

```bash
# Format code
tox -p -e black -e isort

# Run all quality checks
tox -p -e isort-check -e black-check -e flake8 -e pylint -e mypy -e bandit -e safety
```

**Note**: Some areas (like `operate/data`) are excluded from certain checks. Respect these exclusions.

### Writing Tests

Tests use **pytest** with fixtures defined in `conftest.py`.

## Pull Request Process

### Before Submitting

1. **Update your branch:**
   ```bash
   git fetch origin
   git rebase origin/main
   ```

2. **Run all checks locally:**
   ```bash
   # Format code
   tox -p -e black -e isort
   
   # Run quality checks
   tox -p -e isort-check -e black-check -e flake8 -e pylint -e mypy -e bandit -e safety
   ```

3. **Ensure relavent tests pass:**
   ```bash
   pytest -v tests/path/to/your/test_file.py
   ```

### Submitting a Pull Request

1. **Push your branch:**
   ```bash
   git push origin feature/your-feature-name
   ```

2. **Open a PR on GitHub:**
   - Use a clear, descriptive title
   - Reference any related issues: "Fixes #123"
   - Provide a detailed description of changes
   - Include screenshots/demos if applicable

3. **PR Title Format:**
   ```
   [TYPE] Brief description
   
   Examples:
   - [FEATURE] Add cross-chain bridge support
   - [FIX] Resolve wallet synchronization issue
   - [DOCS] Update API documentation
   - [REFACTOR] Simplify service management code
   ```

4. **PR Description Template:**
   ```markdown
   ## Description
   Brief description of what this PR does.
   
   ## Related Issues
   Fixes #123
   Related to #456
   
   ## Changes
   - Change 1
   - Change 2
   
   ## Testing
   - [ ] Unit tests added/updated
   - [ ] Manual testing completed
   - [ ] Integration tests pass
   
   ## Checklist
   - [ ] Code follows style guidelines
   - [ ] All tests pass
   - [ ] Documentation updated
   - [ ] No new warnings generated
   ```

### Review Process

- At least one reviewer approval required
- All CI checks must pass
- Address any requested changes promptly
- Use "Re-request review" after making changes

### After Approval

- A maintainer will merge your PR
- Your branch will be deleted after merge
- Your contribution will be part of the next release

## Troubleshooting

### Issue: Import errors after `poetry install`
**Solution**: Make sure you've activated the virtual environment:
```bash
poetry shell
```

### Issue: Tests fail with "OPERATE home directory not found"
**Solution**: Tests use temporary directories. Ensure `tmp_path` fixtures are being used.

### Issue: Type checking fails
**Solution**: Run `tox -e mypy` to see detailed type errors:
```bash
tox -e mypy
```

### Getting Help

For general questions:
- Check existing [GitHub Issues](https://github.com/valory-xyz/olas-operate-middleware/issues)
- Review [API Reference](docs/api.md)
- See [Security Policy](SECURITY.md) for security-related questions

For reporting bugs:
- [Open a GitHub Issue](https://github.com/valory-xyz/olas-operate-middleware/issues/new)
- Include reproduction steps and environment details

---

Thank you for contributing to Olas Operate Middleware! 🎉
