import os
import re
from typing import List, Optional

from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from src.state import AgentState
from e2b_code_interpreter import Sandbox

# --- 1. Strict Output Schema for Agent A (PRD §3.5, §6.2 structured output) ---
class CodeIssue(BaseModel):
    filepath: str = Field(description="The file where the issue was found")
    line_number: int = Field(description="Approximate line number of the issue")
    severity: str = Field(description="Critical, Warning, or Info")
    description: str = Field(description="Clear explanation of why this is bad")
    suggestion: str = Field(description="What needs to be fixed")

class ReviewOutput(BaseModel):
    summary: str = Field(description="High-level summary of the code intent")
    issues: List[CodeIssue] = Field(description="List of specific technical issues found")


# --- 2. Per-tenant credential plumbing (BYOK, PRD §3.1) ---
# Secrets are passed through the LangGraph ``config["configurable"]`` namespace at
# invocation time so they are decrypted only in-memory inside a worker and are
# never written into persisted graph state. They fall back to environment
# variables for local smoke testing.

def _configurable(config) -> dict:
    if isinstance(config, dict):
        return config.get("configurable", {}) or {}
    return {}


def _build_llm(config):
    """
    Dynamically resolves or builds a LangChain ChatModel instance.
    1. Checks for a pre-instantiated model instance under config['configurable']['llm'].
    2. Falls back to generating an instance from explicit runtime parameters.
    3. Drops back to standard provider environment keys for local smoke testing.
    """
    cfg = _configurable(config)
    
    # Priority 1: Direct injection of an initialized LangChain BaseChatModel object
    if "llm" in cfg and cfg["llm"] is not None:
        return cfg["llm"]
        
    # Priority 2: Extract orchestration fields to build on the fly
    provider = str(cfg.get("llm_provider", "gemini")).lower()
    model_name = cfg.get("llm_model_name") or cfg.get("gemini_model")
    
    if provider == "gemini":
        api_key = cfg.get("llm_key") or cfg.get("gemini_api_key") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("No Gemini API key available (tenant BYOK missing).")
        return ChatGoogleGenerativeAI(
            model=model_name or "gemini-2.5-flash",
            temperature=0,
            api_key=api_key,
        )
        
    elif provider == "openai":
        api_key = cfg.get("llm_key") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("No OpenAI API key available.")
        return ChatOpenAI(
            model=model_name or "gpt-4o-mini",
            temperature=0,
            api_key=api_key,
        )
        
    elif provider == "groq":
        api_key = cfg.get("llm_key") or os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ValueError("No Groq API key available.")
        return ChatOpenAI(
            model=model_name or "llama3-70b-8192",
            temperature=0,
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        
    elif provider in ["local", "ollama"]:
        base_url = cfg.get("llm_base_url") or os.environ.get("LOCAL_LLM_BASE_URL") or "http://localhost:11434/v1"
        return ChatOpenAI(
            model=model_name or "llama3",
            temperature=0,
            api_key="local-placeholder",  # Bypasses internal client validations
            base_url=base_url,
        )
        
    else:
        # Open routing loop for general OpenAI-compatible endpoints
        base_url = cfg.get("llm_base_url")
        if base_url:
            return ChatOpenAI(
                model=model_name or "custom-model",
                temperature=0,
                api_key=cfg.get("llm_key", "placeholder"),
                base_url=base_url,
            )
        raise ValueError(f"Unsupported or unconfigured LLM provider configuration: {provider}")


def _e2b_api_key(config) -> Optional[str]:
    return _configurable(config).get("e2b_api_key") or os.environ.get("E2B_API_KEY")


# --- 3. Agent A: Reviewer ---
def call_agent_a(state: AgentState, config=None):
    llm = _build_llm(config)
    print(f"--- Agent A: Reviewing Code ({llm.__class__.__name__}) ---")

    code = state["original_code"]

    # Native schema mapping enforced through the unified interface wrapper
    structured_llm = llm.with_structured_output(ReviewOutput)

    system_prompt = """You are a Principal Software Architect.
    Analyze the provided code for logic errors, security vulnerabilities, and code style issues.
    Do NOT focus on simple formatting. Focus on bugs and safety.
    """

    response = structured_llm.invoke(f"{system_prompt}\n\nCode to Review:\n{code}")

    return {
        "intent_summary": response.summary,
        "review_issues": [issue.model_dump() for issue in response.issues],
    }


# --- 4. Agent B: Refactorer ---
def call_agent_b(state: AgentState, config=None):
    llm = _build_llm(config)
    print(f"--- Agent B: Refactoring Code ({llm.__class__.__name__}) ---")

    code = state.get("refactored_code") or state.get("original_code")
    issues = state.get("review_issues", [])

    # Runtime / human-rejection logs steer the revision (PRD §3.5, §3.6).
    execution_logs = state.get("execution_logs", "")

    # Generate token-efficient context
    context_skeleton = _build_context_skeleton(repo_files, state["file_path"])

    # 1. FIX THE PROMPT: Demand full code, no diffs.
    prompt = f"""
    You are a Python Code Refactoring Agent.

    Here is the code you need to fix:
    ```python
    {code}
    ```

    CONTEXT:
    1. Static Analysis Issues: {issues}
    2. RUNTIME ERRORS (CRITICAL): {execution_logs}
    3. REPOSITORY CONTEXT (Available Imports & Signatures):
        The following structural context shows available classes and functions in the repo. 
        Use this to verify if the target code is calling imported functions correctly.
        {context_skeleton}

    INSTRUCTIONS:
    - If there are Runtime Errors, you MUST fix the code to resolve them.
    - Return the FULL, completely refactored Python code. 
    - DO NOT truncate, use placeholders, or omit any existing logic.
    - DO NOT format the output as a git diff. Just the raw python code.
    - If the code is perfect and there are no errors, return the string "NO_CHANGES".
    """

    response = llm.invoke([HumanMessage(content=prompt)])
    result_code = response.content.strip()

    # Strip markdown fences
    if result_code.startswith("```python"):
        result_code = result_code.split("```python")[1].split("```")[0].strip()
    elif result_code.startswith("```"):
        result_code = result_code.split("```")[1].split("```")[0].strip()

    if result_code == "NO_CHANGES":
        print("Agent B: No changes needed.")
        return {"refactored_code": code, "code_diff": None}

    # 2. GENERATE THE DIFF PROGRAMMATICALLY
    original_lines = state["original_code"].splitlines(keepends=True)
    new_lines = result_code.splitlines(keepends=True)
    
    diff_generator = difflib.unified_diff(
        original_lines, 
        new_lines, 
        fromfile=state["file_path"], 
        tofile=state["file_path"]
    )
    diff_string = "".join(diff_generator)

    print("Agent B: Code refactored and diff generated.")
    return {
        "refactored_code": result_code,
        "code_diff": diff_string, # <--- Pass diff to state
        "iteration_count": state.get("iteration_count", 0),
    }


# --- 5. Executor: E2B Sandbox with self-healing loop (PRD §3.5, §6.1) ---
def call_executor(state: AgentState, config=None):
    print("EXECUTOR: Running code in E2B Sandbox...")

    target_file = state["file_path"]
    code_to_run = state.get("refactored_code") or state.get("original_code")

    repo_files = dict(state.get("repo_files", {}))  # copy; don't mutate checkpointed state
    # Mount the latest refactored code so imports resolve to the fix.
    repo_files[target_file] = code_to_run

    current_count = state.get("iteration_count", 0)
    api_key = _e2b_api_key(config)

    def run_in_sandbox(sbx, code, files):
        # Hydrate the sandbox filesystem with the dependency map (PRD §3.4).
        print(f"   Hydrating sandbox with {len(files)} files...")
        for path, content in files.items():
            directory = os.path.dirname(path)
            if directory:
                sbx.commands.run(f"mkdir -p {directory}")
            sbx.files.write(path, content)

        execution = sbx.run_code(code)
        if execution.error:
            return False, execution.error
        return True, execution.logs.stdout

    try:
        # Sandbox hardening: only run_code + ModuleNotFoundError-driven pip
        # installs are permitted; no arbitrary shell from the model (PRD §6.1).
        with Sandbox(api_key=api_key) as sbx:
            success, result = run_in_sandbox(sbx, code_to_run, repo_files)

            # --- Auto-fix a single missing dependency, then retry ---
            if not success and "ModuleNotFoundError" in getattr(result, "name", ""):
                match = re.search(r"No module named '(\w+)'", result.value)
                if match:
                    package_name = match.group(1)
                    print(f"   Found missing dependency: {package_name}")
                    print(f"   Installing {package_name}...")
                    sbx.commands.run(f"pip install {package_name}")

                    print("   Retrying execution...")
                    success, result = run_in_sandbox(sbx, code_to_run, repo_files)

            if not success:
                print(f"   -> Execution Failed: {result.name}")
                error_details = f"Error: {result.name}: {result.value}\n{result.traceback}"
                print(error_details)
                return {
                    "execution_status": "FAILURE",
                    "execution_logs": error_details,
                    "iteration_count": current_count + 1,
                }

            print("   -> Execution Successful")
            output_logs = "\n".join(result) if result else "Code ran successfully."
            return {
                "execution_status": "SUCCESS",
                "execution_logs": output_logs,
            }

    except Exception as e:
        print(f"   -> Sandbox Infrastructure Error: {e}")
        return {
            "execution_status": "FAILURE",
            "execution_logs": str(e),
            "iteration_count": current_count + 1,
        }


# --- 6. Agent C: Documenter ---
def call_agent_c(state: AgentState, config=None):
    llm = _build_llm(config)
    print(f"--- Agent C: Documenting Changes ({llm.__class__.__name__}) ---")

    original_code = state.get("original_code")
    refactored_code = state.get("refactored_code")

    prompt = f"""
    You are a Senior Technical Writer.

    Original:
    {original_code}

    Refactored:
    {refactored_code}

    INSTRUCTIONS:
    1. Document the semantic changes.
    2. Return ONLY the Markdown documentation.
    """

    response = llm.invoke([HumanMessage(content=prompt)])
    doc_update = response.content.strip()

    return {
        "updated_readme": doc_update,
        "documentation_diff": doc_update,
    }
