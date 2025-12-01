# 🚀 RepoRover: The Autonomous Enterprise Software Engineer

![RepoRover Banner](https://img.shields.io/badge/Status-Prototype-blue) ![Python](https://img.shields.io/badge/Python-3.10%2B-green) ![License](https://img.shields.io/badge/License-MIT-purple)

**Your autonomous AI teammate that reviews PRs, fixes bugs, and keeps documentation in sync.**

RepoRover is not just a coding assistant; it is a **multi-agent system** capable of reviewing GitHub Pull Requests, refactoring code, verifying fixes in a secure cloud sandbox (E2B), and updating documentation—all with strict human oversight.

---

## 🧐 The Problem
Traditional AI coding tools fail in complex enterprise environments due to two critical issues:
1.  **The Context Gap:** Agents analyze files in isolation (e.g., `main.py`) without seeing imported dependencies (e.g., `utils.py`), leading to "hallucinated" errors.
2.  **Lack of Verification:** "Zero-shot" code generation is probabilistic. Without running the code, there is no guarantee it actually works.

## 💡 The Solution: RepoRover
RepoRover solves this with a **Self-Healing "Think-Code-Run" Loop**.
* **Dependency Hydration:** Automatically fetches all imported files to build a complete mental model of the codebase.
* **Secure Sandboxing:** Executes code in an isolated E2B cloud environment to verify fixes.
* **Auto-Correction:** Catches runtime errors (like `ModuleNotFoundError`) and fixes them autonomously.

---

## 🏗️ Architecture
RepoRover utilizes **LangGraph** to orchestrate a cyclic workflow between three specialized agents.


<img width="1024" height="559" alt="image" src="https://github.com/user-attachments/assets/c408fa64-4929-4673-88b8-0b2d984dde11" />



## ✨ Key Features

### 1\. 🧠 Dependency Graph Hydration

Before touching a single line of code, RepoRover scans the Abstract Syntax Tree (AST) of the target file to identify imports. It then recursively crawls the GitHub repository to fetch all necessary dependency files, ensuring the agent has full context.

### 2\. 🛡️ E2B Sandbox Integration

Instead of unsafe local execution, RepoRover spins up a pristine Linux environment for every PR.

  * **Environment Mirroring:** Replicates the repo structure in the cloud.
  * **Self-Healing:** If a script fails due to missing libraries, the agent autonomously runs `pip install` and retries.

### 3\. 🚦 Human-in-the-Loop Safety

AI never merges code without permission. Before execution, the system pauses and presents the proposed fix.

  * **Approve:** Proceed to execution and documentation.
  * **Reject with Feedback:** "You missed an edge case." -\> Agent B retries.
  * **Skip:** Bypass execution but generate docs.

### 4\. 📝 Diff-Driven Documentation

Agent C (The Documenter) only runs after the code is **verified**. It analyzes the semantic changes and updates the `README.md` or docstrings, ensuring documentation never drifts from reality.

-----

## 🛠️ Installation & Setup

### Prerequisites

  * Python 3.10+
  * GitHub Account (and Personal Access Token)
  * [E2B](https://e2b.dev/) Account
  * Google Gemini API Key

### 1\. Clone the Repository

```bash
git clone [https://github.com/yourusername/reporover.git](https://github.com/yourusername/reporover.git)
cd reporover
```

### 2\. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3\. Configure Environment

Create a `.env` file in the root directory:

```env
GITHUB_TOKEN=ghp_your_github_token_here
E2B_API_KEY=e2b_your_api_key_here
GOOGLE_API_KEY=your_gemini_api_key_here
```

-----

## 🚀 Usage

1.  Open `main.py` and configure the target repository and PR number you want to review:

    ```python
    REPO_NAME = "owner/repository-name" 
    PR_NUMBER = 1 
    ```

2.  Run the agent:

    ```bash
    python -m src.main
    ```

3.  **Follow the flow:**

      * The agent will hydrate the context and propose a fix.
      * Review the code preview in the console.
      * Type `y` to approve, `n` to reject/provide feedback, or `v` to view the full code.

-----

## 📚 Technical Stack

  * **Orchestration:** [LangGraph](https://github.com/langchain-ai/langgraph) (Cyclic State Management)
  * **LLM:** Google Gemini 2.0 Flash (Reasoning & Code Gen)
  * **Sandbox:** [E2B Code Interpreter](https://e2b.dev/) (Secure Execution)
  * **Data:** [PyGithub](https://github.com/PyGithub/PyGithub) (Repository Interaction)

-----

## 🔮 Future Roadmap

  - [ ] **Multi-Language Support:** Extend E2B sandbox for Node.js/TypeScript.
  - [ ] **Vector Database (RAG):** Replace AST parsing with semantic search for massive monorepos.
  - [ ] **GitHub App:** Package as an installed bot that comments directly on PRs.

-----

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](https://www.google.com/search?q=LICENSE) file for details.

```
```
