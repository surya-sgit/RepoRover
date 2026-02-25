# RepoRover: Autonomous Enterprise Code Review System

![Status](https://img.shields.io/badge/Status-Prototype-blue) ![Python](https://img.shields.io/badge/Python-3.10%2B-green) ![License](https://img.shields.io/badge/License-MIT-purple)

RepoRover is a multi-agent AI system designed for enterprise-grade Pull Request review, automated code refactoring, sandbox-verified execution, and documentation synchronization — all governed by strict human oversight.

---

## Table of Contents

- [Problem Statement](#problem-statement)
- [Solution Overview](#solution-overview)
- [Architecture](#architecture)
- [Key Features](#key-features)
- [Installation & Setup](#installation--setup)
- [Usage](#usage)
- [Technical Stack](#technical-stack)
- [Roadmap](#roadmap)
- [License](#license)

---

## Problem Statement

Conventional AI coding assistants fall short in complex enterprise environments due to two fundamental limitations:

1. **Context Isolation:** Agents typically analyze files in isolation (e.g., `main.py`) without access to imported dependencies (e.g., `utils.py`), resulting in incomplete analysis and erroneous suggestions.
2. **Absence of Verification:** Zero-shot code generation is inherently probabilistic. Without runtime verification, there is no guarantee that generated code is functionally correct.

---

## Solution Overview

RepoRover addresses these limitations through a self-healing **Think → Code → Run** feedback loop:

- **Dependency Hydration:** Prior to analysis, RepoRover automatically identifies and fetches all imported files to construct a complete representation of the codebase.
- **Secure Sandboxed Execution:** All generated code is executed within an isolated E2B cloud environment for runtime verification before any changes are proposed to the user.
- **Autonomous Error Correction:** Runtime failures (e.g., `ModuleNotFoundError`) are detected and remediated automatically, without requiring human intervention.

---

## Architecture

RepoRover is orchestrated via **LangGraph**, coordinating a cyclic workflow across three specialized agents.

<img width="1024" height="559" alt="RepoRover Architecture Diagram" src="https://github.com/user-attachments/assets/c408fa64-4929-4673-88b8-0b2d984dde11" />

---

## Key Features

### 1. Dependency Graph Hydration

Before modifying any code, RepoRover performs a static analysis of the target file's Abstract Syntax Tree (AST) to identify all import statements. It then recursively fetches the corresponding files from the GitHub repository, ensuring the agent operates with complete contextual awareness.

### 2. E2B Sandbox Integration

Code execution is performed exclusively within a secure, ephemeral E2B cloud environment — never on the host machine.

- **Environment Mirroring:** The repository structure is replicated within the sandbox to accurately simulate the production environment.
- **Self-Healing Execution:** If execution fails due to missing dependencies, the system autonomously installs the required packages and retries without human intervention.

### 3. Human-in-the-Loop Approval

No code is merged or applied without explicit human authorization. Upon generating a proposed fix, the system pauses and presents the changes for review. The reviewer may:

- **Approve** — Proceed to sandboxed execution and documentation generation.
- **Reject with Feedback** — Provide a reason for rejection; the agent will incorporate the feedback and regenerate the fix.
- **Skip Execution** — Bypass sandboxed execution and proceed directly to documentation generation.

### 4. Diff-Driven Documentation

Documentation is updated only after code changes have been verified through successful sandbox execution. Agent C (the Documenter) performs a semantic analysis of the applied changes and updates the relevant `README.md` sections or inline docstrings accordingly, ensuring documentation remains consistent with the codebase at all times.

---

## Installation & Setup

### Prerequisites

- Python 3.10 or higher
- A GitHub account with a valid Personal Access Token
- An [E2B](https://e2b.dev/) account and API key
- A Google Gemini API key

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/reporover.git
cd reporover
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the project root directory with the following contents:

```env
GITHUB_TOKEN=ghp_your_github_token_here
E2B_API_KEY=e2b_your_api_key_here
GOOGLE_API_KEY=your_gemini_api_key_here
```

---

## Usage

1. Open `main.py` and specify the target repository and Pull Request number:

    ```python
    REPO_NAME = "owner/repository-name"
    PR_NUMBER = 1
    ```

2. Execute the agent:

    ```bash
    python -m src.main
    ```

3. Follow the interactive review process:

    - The agent will hydrate the dependency context and propose a refactored solution.
    - A preview of the proposed changes will be displayed in the console.
    - Enter `y` to approve, `n` to reject and provide feedback, or `v` to view the complete code.

---

## Technical Stack

| Component | Technology |
|---|---|
| Agent Orchestration | [LangGraph](https://github.com/langchain-ai/langgraph) — Cyclic State Management |
| Language Model | Google Gemini 2.0 Flash — Reasoning & Code Generation |
| Execution Sandbox | [E2B Code Interpreter](https://e2b.dev/) — Secure Cloud Execution |
| Repository Access | [PyGithub](https://github.com/PyGithub/PyGithub) — GitHub API Integration |

---

## Roadmap

| Priority | Feature | Description |
|---|---|---|
| Medium | Multi-Language Support | Extend sandbox capabilities to support Node.js and TypeScript projects |
| Medium | Semantic Search via RAG | Replace AST-based parsing with vector database retrieval for large monorepos |
| High | GitHub App Integration | Package RepoRover as an installable GitHub App that comments directly on Pull Requests |

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
