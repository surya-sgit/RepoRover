# Contributing to RepoRover

First off, thank you for considering contributing to RepoRover! It's people like you that make RepoRover such a great platform for autonomous enterprise code review.

This document outlines the process for contributing to the project and sets expectations for code quality and collaboration.

## 1. Where to Start

- **Bug Reports & Feature Requests:** Please use the issue tracker to report bugs or suggest new features. Before creating a new issue, search existing ones to avoid duplicates.
- **Discussions:** For architectural discussions or questions about the codebase, please open an issue or start a discussion.

## 2. Local Development Setup

To set up the project locally for development, please refer to the **Running the Phase 1.0 SaaS Platform (Local)** section in our `README.md`. 

**Key Development Tools:**
- **Dependency Management:** We use `uv`. Ensure you install development dependencies via `uv sync --extra dev`.
- **Testing:** We use `pytest`. You can run the test suite using `pytest`.

## 3. Making Changes

1. **Fork the Repository:** Create a fork of the `reporover` repository on GitHub.
2. **Create a Branch:** Create a new branch for your feature or bugfix. Use a descriptive name (e.g., `feature/add-node-sandbox-support` or `fix/celery-worker-timeout`).
3. **Write Code:** Implement your changes.
    - Follow PEP 8 guidelines for Python code.
    - Write unit tests for new functionality or bugfixes.
4. **Test:** Ensure all existing and new tests pass locally by running `pytest`.
5. **Commit:** Write clear, concise commit messages explaining the *why* behind your changes.

## 4. Submitting a Pull Request

1. Push your branch to your forked repository.
2. Open a Pull Request (PR) against the `main` branch of the upstream repository.
3. Fill out the provided **Pull Request Template** thoroughly. Provide context, link to relevant issues, and explain how you tested your changes.
4. Your PR will undergo review by the maintainers (and potentially RepoRover itself!). Be prepared to address feedback and iterate on your changes.

## 5. Code Review Expectations

We value constructive, respectful code reviews. Reviewers should focus on the logic, security, performance, and maintainability of the code.

Thank you for contributing!
