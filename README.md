# RepoRover: AI-Powered GitHub Automation Agent

RepoRover is an autonomous multi-agent system built with **LangGraph** and **Google Gemini** that automates the code review and refactoring lifecycle for GitHub Pull Requests. It reviews code, fixes bugs, validates changes in a secure **E2B Sandbox**, and updates documentation.

## 🚀 Features

* **🤖 Agent A (Reviewer):** Performs static analysis on PR code using **Gemini 2.5 Flash** to identify logic errors, security flaws, and style issues.
* **🛠️ Agent B (Refactorer):** Automatically fixes code based on review feedback and iteratively resolves runtime errors found during testing.
* **⚡ E2B Sandbox Execution:** Safely executes generated code in an isolated cloud sandbox to verify functionality before finalizing.
* **📝 Agent C (Documenter):** Automatically generates semantic updates for documentation based on code changes.
* **👤 Human-in-the-Loop:** Pauses for user approval before executing code, allowing for manual feedback and rejection handling.

## 🛠️ Architecture

The system operates on a State Graph with the following workflow:
1.  **Review:** Fetch PR content and analyze.
2.  **Refactor:** Apply fixes.
3.  **Human Check:** Pause for approval/feedback.
4.  **Execute:** Run in E2B Sandbox.
    * *If Failure:* Loop back to Refactor (Max 3 retries).
    * *If Success:* Proceed to Documentation.
5.  **Document:** Generate documentation diffs.

## 📋 Prerequisites

* Python 3.9+
* A GitHub Account & Personal Access Token
* Google AI Studio API Key (for Gemini)
* E2B API Key (for Code Interpreter Sandbox)

## ⚙️ Setup & Installation

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/your-username/reporover.git](https://github.com/your-username/reporover.git)
    cd reporover
    ```

2.  **Install dependencies:**
    ```bash
    pip install langgraph langchain-google-genai e2b-code-interpreter PyGithub python-dotenv pydantic
    ```

3.  **Environment Variables:**
    Create a `.env` file in the root directory and add your keys:
    ```env
    GOOGLE_API_KEY=your_gemini_api_key
    GITHUB_TOKEN=your_github_token
    E2B_API_KEY=your_e2b_api_key
    ```

## 🏃 Usage

1.  **Configure Target:**
    Open `main.py` and set the repository and PR number you wish to automate:
    ```python
    # main.py
    REPO_NAME = "surya-sgit/RepoRover" # Your target repo
    PR_NUMBER = 1                      # The PR to process
    ```

2.  **Run the Agent:**
    ```bash
    python main.py
    ```

3.  **Interaction:**
    * The agent will print the "Proposed Refactored Code".
    * Type `y` to approve and run in the sandbox.
    * Type `n` to reject. You will be asked for a reason (e.g., "Syntax error on line 5"), which Agent B will use to attempt a new fix.

## 📂 File Structure

* `src/graph.py`: Defines the LangGraph workflow, nodes, and conditional edges.
* `src/agents.py`: Contains the logic for Agents A, B, and C, and the E2B Executor tool.
* `src/github_tools.py`: Handles GitHub API interactions (fetching PRs/content).
* `src/state.py`: Defines the shared `AgentState` schema.
* `main.py`: Entry point for the application.