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

This project uses `uv` for dependency management. Install the dependencies by running:

```bash
uv sync
```

*(To include development dependencies, use `uv sync --extra dev`)*

### 3. Configure Environment Variables

Copy the provided example configuration file and fill in the required values:

```bash
cp .env.example .env
```

*Note: For the local CLI smoke test, you must uncomment and set `GITHUB_TOKEN`, `E2B_API_KEY`, and `GOOGLE_API_KEY` in the `.env` file. The SaaS platform has additional requirements (detailed below).*

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

## Running the Phase 1.0 SaaS Platform (Local)

Phase 1.0 runs RepoRover as a multi-tenant GitHub App: a Django web service
ingests webhooks, Celery workers run the LangGraph agent loop, and all
interaction happens inside PR comments via slash commands. The single-PR CLI in
`src/main.py` remains only as a developer smoke test.

### Prerequisites

- Python 3.10+, PostgreSQL, and Redis running locally
- A registered **GitHub App** (with webhook URL, a webhook secret, a private
  key, and OAuth client credentials) plus per-tenant Gemini and E2B keys (BYOK)

### Setup

```bash
uv sync
cp .env.example .env          # then fill in every value
# Generate the BYOK master key and paste it into FERNET_KEY:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
python manage.py migrate
```

### Run the stack (separate terminals)

```bash
python manage.py runserver 8000             # Django web + webhook intake
celery -A reporover worker -l info          # agent execution workers
ngrok http 8000                             # public tunnel for GitHub webhooks
```

Point your GitHub App's **Webhook URL** at `https://<ngrok-id>.ngrok-free.app/webhooks/github/`
and its **Setup/Callback URL** at `/dashboard/setup/`. Visit
`http://localhost:8000/dashboard/` to log in with GitHub and store your BYOK keys
and per-repo settings.

### The review loop

1. Open or update a PR with a Python change → RepoRover posts a review + proposed
   patch and pauses.
2. Reply in the PR with a slash command:
   - `/approve` — run the fix in the E2B sandbox (self-heals missing deps, ≤3 tries), then document it.
   - `/reject <feedback>` — send feedback to the refactorer for a new attempt.
   - `/skip` — skip the sandbox and generate documentation directly.

## Technical Stack

| Component | Technology |
|---|---|
| SaaS Framework & Web API | Django 5.x — Webhook intake, OAuth dashboard, multi-tenant config |
| Task Queue & Routing | Celery 5.x + Redis — Non-blocking agent execution, concurrency limits |
| Agent Orchestration | [LangGraph](https://github.com/langchain-ai/langgraph) — Cyclic State Management |
| Persistence | PostgreSQL — Tenant config, encrypted BYOK vault, session state |
| Language Model | Google Gemini 2.5 Flash — Reasoning & Code Generation |
| Execution Sandbox | [E2B Code Interpreter](https://e2b.dev/) — Secure Cloud Execution |
| Repository Access | [PyGithub](https://github.com/PyGithub/PyGithub) — GitHub App API Integration |

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
