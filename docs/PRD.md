# Product Requirements Document (PRD)

## RepoRover: Centralized AI Code Review Platform (Phase 1.0)

---

## 1. Product Overview & Core Objectives

### 1.1 Problem Statement

Modern multi-agent AI coding systems provide strong self-healing capabilities but are difficult to scale across engineering teams when limited to localized command-line interfaces. Conversely, existing browser-based solutions suffer from severe interface fragility due to continuous updates to frontend DOM structures.

### 1.2 Solution Summary

RepoRover Phase 1.0 is a centralized, multi-tenant SaaS GitHub App that performs automated, contextual, and sandbox-verified code reviews for Python codebases. It acts as an autonomous virtual team member that communicates natively inside GitHub Pull Requests via comments and chat-ops slash commands, eliminating the need for local execution tools or brittle browser extensions.

### 1.3 Strategic Value Pillars

* **Bring Your Own Key (BYOK):** Minimizes operational SaaS pricing overhead by utilizing the customer's own Google Gemini and E2B infrastructure keys.
* **Zero-Retention Footprint:** Guarantees total code privacy by holding proprietary repository contents strictly within ephemeral in-memory queues and sandboxes, ensuring zero source code is stored inside the database.
* **Contextual Evaluation:** Hydrates the AI agent's prompt space with complete repository import-dependency trees rather than evaluating files in isolated isolation.

---

## 2. System Architecture & Technical Stack

The architecture separates the synchronous web response layer, the asynchronous multi-agent execution thread, and the secure runtime validation environment.

```
                  ┌────────────────────────────────────────┐
                  │              GitHub API                │
                  └────┬──────────────────────────────▲────┘
                       │ Webhook                      │ API Calls /
                       │ Payloads                     │ PR Comments
                       ▼                              │
┌─────────────────────────────────────────────────────┴────┐
│                  Central Web Server                      │
│  ┌───────────────────────┐   ┌────────────────────────┐  │
│  │   Django Web App      │   │  PostgreSQL Database   │  │
│  │  (Webhook Intake &    │   │ (Tenant Config, Vault, │  │
│  │   OAuth Dashboard)    │   │  Session Metadata)     │  │
│  └───────────┬───────────┘   └────────────────────────┘  │
└──────────────│───────────────────────────────────────────┘
               │ Dispatch Job
               ▼
┌──────────────────────────────────────────────────────────┐
│              Asynchronous Processing Pool                │
│  ┌───────────────────────┐   ┌────────────────────────┐  │
│  │    Celery Workers     │   │     Redis Broker       │  │
│  │ (LangGraph Orchestra- │   │ (Task Distribution &   │  │
│  │  tion / Agent Loop)   │   │  State Invalidation)   │  │
│  └───────────┬───────────┘   └────────────────────────┘  │
└──────────────│───────────────────────────────────────────┘
               │ Provisions
               ▼
┌──────────────────────────────────────────────────────────┐
│              Ephemeral Execution Sandbox                 │
│  ┌────────────────────────────────────────────────────┐  │
│  │                 E2B Cloud Instance                 │  │
│  │  (Isolated Virtual Machine, Native Testing Engine) │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘

```

### Technical Stack Component Mapping

| Core Component | Technology | Responsibility |
| --- | --- | --- |
| **SaaS Framework & Web API** | Django 5.x | Webhook endpoint parsing, GitHub OAuth security, multi-tenant administrative dashboard. |
| **State Machine & Execution Routing** | Celery 5.x + Redis | Non-blocking execution of long-running agent workloads, rate-limiting control. |
| **Agent State Orchestration** | LangGraph | Managed cyclic transitions between analysis, refactoring, and verification states. |
| **Reasoning Engine** | Gemini 2.5 Flash | Structured technical evaluation, code issue extraction, semantic optimization. |
| **Verification Runtime** | E2B Code Interpreter SDK | Secure, ephemeral isolated virtualization for verifying Python scripts. |

---

## 3. Functional Specifications

### 3.1 Authentication & Multi-Tenant Management

* **Dashboard Access:** Users authenticate to the central administration panel exclusively via GitHub OAuth. No separate password identities are maintained.
* **Key Vault Infrastructure:** The dashboard provides configuration inputs for users to submit their personal `GOOGLE_API_KEY` and `E2B_API_KEY`. These parameters must undergo cryptographic encryption at rest before being committed to the database.

### 3.3 GitHub Webhook Orchestration

* **Ingress Filtering:** The server exposes a single `/webhooks/github/` endpoint that accepts inbound payloads from GitHub. The system processes exactly two core events:
* `pull_request` (specifically actions: `opened`, `synchronize`)
* `issue_comment` (specifically action: `created`)


* **Handshake Speed Guarantee:** The webhook ingestion route must immediately validate the cryptographic payload signature, enqueue the raw data into Redis, and issue an `HTTP 200 OK` response back to GitHub within **10 seconds** to avoid delivery timeout errors.

### 3.4 Context Hydration Strategy

* **Upfront Dependency Optimization:** Upon parsing the code delta inside a PR, the background worker must look for standard dependency declaration maps (e.g., `requirements.txt` or `poetry.lock`). If identified, the sandbox executes a bulk package pre-installation sequence before running individual agents to optimize iteration speed.
* **AST Parsing Engine:** The background worker iterates through each modified Python file, passing its code through an Abstract Syntax Tree (AST) processor to extract non-standard import declarations. The worker dynamically constructs a file tree map by pulling these exact dependent modules from the GitHub repository API via short-lived installation access tokens.

### 3.5 The Multi-Agent Verification Circuit

```
       [Start Review Job]
                │
                ▼
      ┌──────────────────┐
      │ Agent A (Review) │ ──► Parsed logic, safety, and security bugs
      └─────────┬────────┘
                │
                ▼
      ┌──────────────────┐
      │ Agent B (Fix)    │ ──► Generates refactored patch
      └─────────┬────────┘
                │
                ▼
   [Post PR Comment & Intercept] ──► *Execution Paused*
                │
         (Slash Command)
                ├──────────────────────┐
                │ /reject [feedback]   │ /approve
                ▼                      ▼
      ┌──────────────────┐    ┌──────────────────┐
      │ Re-route back to │    │   E2B Sandbox    │ ──► Validates environment & code
      │    Agent B       │    └────────┬─────────┘
      └──────────────────┘             │
                                       ▼
                             [Runtime Evaluation]
                                       ├──────────────────────┐
                                       │ Failure (Attempts<3) │ Success
                                       ▼                      ▼
                             ┌──────────────────┐    ┌──────────────────┐
                             │ Capture Log &    │    │ Agent C (Docs)   │
                             │ Loop to Agent B  │    └────────┬─────────┘
                             └──────────────────┘             │
                                                              ▼
                                                     [Post Final Review]

```

* **Agent A (Reviewer):** Parses target code blocks using a strict JSON schema structure (`with_structured_output`), generating categorized evaluations across structural logic errors, security anti-patterns, and architectural flaws.
* **Agent B (Refactorer):** Synthesizes a corrective code modification based directly on Agent A's issue map or feedback captured from previous execution logs.
* **The Self-Healing Loop:** Code generated by Agent B is mounted inside the E2B sandbox environment alongside the context file map. If a `ModuleNotFoundError` is thrown at runtime, the system uses targeted regex to isolate the package string, runs `pip install`, and restarts the execution. The system permits a strict ceiling of **3 runtime iterations** before outputting a failure status.
* **Agent C (Documenter):** Executes only upon successful sandbox verification or an explicit human bypass. It maps changes semantically and generates updated inline docstrings or markdown additions.

### 3.6 Chat-Ops Slash Command Interface (Human-in-the-Loop)

The system suspends execution prior to sandbox initialization, outputting its intermediate results as an official PR review comment. The workflow wakes up and changes execution paths by monitoring thread responses for three precise commands:

* `/approve`: Restarts the state execution engine, allowing the E2B sandbox code environment to execute.
* `/reject [explicit feedback]`: Captures the text string appended to the slash command, re-routing it into the input parameters of Agent B to force a code revision.
* `/skip`: Terminates sandbox execution immediately and switches execution directly to Agent C to generate structural documentation artifacts.

---

## 4. Data Models & Database Schema

To strictly uphold the Zero-Retention configuration goal, the database acts solely as a multi-tenant permission mapper and process state coordinator.

```
┌─────────────────────────────────┐       ┌─────────────────────────────────┐
│     OrganizationConfig          │       │          RepoSettings           │
├─────────────────────────────────┤       ├─────────────────────────────────┤
│ id (PK)                         │       │ id (PK)                         │
│ github_installation_id [Int]    │──────►│ org_config (FK)                 │
│ encrypted_gemini_key [Binary]   │       │ repository_name [String]        │
│ encrypted_e2b_key [Binary]      │       │ ignored_directories [JSON]      │
│ created_at [DateTime]           │       │ max_concurrency [Int]           │
└─────────────────────────────────┘       └─────────────────────────────────┘
                                                           │
                                                           │
                                                           ▼
                                          ┌─────────────────────────────────┐
                                          │          ReviewSession          │
                                          ├─────────────────────────────────┤
                                          │ id (PK)                         │
                                          │ repo_settings (FK)              │
                                          │ pr_number [Int]                 │
                                          │ commit_sha [String]             │
                                          │ langgraph_thread_id [UUID]      │
                                          │ current_status [Enum]           │
                                          │ active_jobs [Int]               │
                                          │ updated_at [DateTime]           │
                                          └─────────────────────────────────┘

```

### 4.1 `OrganizationConfig`

Tracks top-level instance authorizations when an enterprise user links the app to their GitHub ecosystem.

* `id`: BigAutoField (Primary Key)
* `github_installation_id`: IntegerField (Unique identifier supplied by GitHub during app setup).
* `encrypted_gemini_key`: BinaryField (AES-256 encrypted BYOK parameter for LLM usage tracking).
* `encrypted_e2b_key`: BinaryField (AES-256 encrypted BYOK parameter for compute instance initialization).

### 4.2 `RepoSettings`

Configures behavioral parameters per repository through the centralized web dashboard.

* `id`: BigAutoField (Primary Key)
* `org_config`: ForeignKey (`OrganizationConfig`, Cascade Delete).
* `repository_name`: CharField (e.g., `"owner/repository-name"`).
* `ignored_directories`: JSONField (Array of directory strings to skip during AST parsing, e.g., `["/tests/*", "/migrations/*"]`).
* `max_concurrency`: IntegerField (Defaults to `2`. Defines the maximum allowable overlapping active executions).

### 4.3 `ReviewSession`

Coordinates non-blocking asynchronous state reconstruction across disparate webhook invocations.

* `id`: BigAutoField (Primary Key)
* `repo_settings`: ForeignKey (`RepoSettings`, Cascade Delete).
* `pr_number`: IntegerField (Tracks target pull request context).
* `commit_sha`: CharField (Enforces validity tracking so actions only execute on the latest code push).
* `langgraph_thread_id`: UUIDField (The pointer key utilized by Celery workers to recall agent checkpoint memory states).
* `current_status`: CharField/Enum (`ANALYZING`, `AWAITING_HUMAN`, `EXECUTING`, `COMPLETED`).

---

## 5. Non-Functional Specifications

### 5.1 Concurrency Limits & Queue Rate Limiting

* **SaaS Traffic Governance:** To shield backend infrastructure and user API accounts from resource exhaustion during bulk commit activity, the Django ingestion routing logic must verify active counts against `RepoSettings.max_concurrency`.
* **Throttle Queueing:** If a repository hits its maximum execution cap, incoming requests are delayed into a FIFO queue via Celery, waiting for an active `ReviewSession` to transition to `AWAITING_HUMAN` or `COMPLETED`.

### 5.2 Error Propagation & BYOK Quota UX Fail-safes

* **Graceful API Degradation:** If an invalid key string is provided, or if the user's personal Gemini/E2B account encounters a credit exhaustion or rate limit block, the system must immediately capture the response code.
* **Native Notification Transparency:** The backend halts processing, clears active queue elements for that PR session, updates `ReviewSession.current_status` to `COMPLETED`, and posts a unified comment block directly onto the PR:
> ### ⚠️ RepoRover Execution Paused
> 
> 
> The automated code review cycle could not complete due to an infrastructure authentication or usage quota error from your configured provider account.
> **Diagnostic Log:** `[Provider Error Code / Subtext String]`
> *Please verify your credentials inside the RepoRover Central Web Dashboard to resume processing.*



---

## 6. Security & Threat Mitigation Architecture

### 6.1 Defense Against Malicious Configuration Exploitation

* **Isolating Configuration Modifications:** Attackers may attempt to alter repository runtime behaviors by modifying dashboard settings or submitting changes to control configurations within the PR itself. To prevent this, the bot must query repo-level definitions exclusively from the database settings configured via the secure, OAuth-authenticated central dashboard, ignoring configuration changes introduced within the PR being reviewed.
* **Sandbox Execution Hardening:** The platform blocks all direct execution of arbitrary shell arrays. The E2B virtual runtime environment is only allowed to perform specific python module verification routines (`sbx.run_code`) and install dependencies discovered through core exceptions (`ModuleNotFoundError`).

### 6.2 Prompt Injection Neutralization

* **Structured Output Enforcement:** Raw text payloads generated by arbitrary commits are never exposed to high-privilege processing prompts. Agent A interacts exclusively with structured constraints (`with_structured_output`). The Django backend enforces strict string sanitation on the resulting arrays, checking for validity before converting components into markdown formatting for GitHub delivery.

---

## 7. Developer Validation & Local Testing Strategy

Because production webhooks require a public domain destination, local platform testing is executed through an end-to-end proxy architecture.

```
┌──────────────┐                  ┌──────────────┐                  ┌───────────────────────┐
│  GitHub PR   │ ──(Webhook)───►  │   ngrok /    │ ──(Forward)───►  │  Local Dev Machine    │
│ Interaction  │                  │   smee.io    │                  │  (localhost:8000/     │
└──────────────┘                  └──────────────┘                  │   webhooks/github/)   │
                                                                    └───────────────────────┘

```

1. **Local Proxy Loop:** Developers execute a secure public reverse-proxy tunnel locally:
```bash
ngrok http 8000

```



2. **Webhook Endpoint Mapping:** The resulting ephemeral URL string (e.g., `[https://abc-123.ngrok-free.app](https://abc-123.ngrok-free.app)`) is configured inside the GitHub App Developer portal as the targeted Webhook URL destination, routing payloads seamlessly to the local Django web service.
3. **Execution Verification:** Developers can validate webhook intake parsing, Celery task distribution, LangGraph tracking logic, and E2B cloud setup functionality directly from their local terminal output and database instances.

