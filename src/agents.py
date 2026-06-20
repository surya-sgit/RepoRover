import os
import re
import difflib
from typing import List, Optional, Dict
import ast

from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from src.state import AgentState
from e2b_code_interpreter import Sandbox

# --- 1. Strict Output Schemas (PRD §3.5, §6.2 structured output) ---
class CodeIssue(BaseModel):
    filepath: str = Field(description="The file where the issue was found")
    line_number: int = Field(description="Approximate line number of the issue")
    severity: str = Field(description="Critical, Warning, or Info")
    description: str = Field(description="Clear explanation of why this is bad")
    suggestion: str = Field(description="What needs to be fixed")

class ReviewOutput(BaseModel):
    summary: str = Field(description="High-level summary of the code intent")
    issues: List[CodeIssue] = Field(description="List of specific technical issues found")

class TestResult(BaseModel):
    final_test_code: str = Field(description="The complete pytest suite.")
    pypi_dependencies: List[str] = Field(
        description="Exact PyPI package names required to execute the target code and tests (e.g., ['pyyaml', 'requests']). Empty list if standard library only."
    )


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

def _build_context_skeleton(repo_files: Dict[str, str], current_file: str) -> str:
    """
    Parses full file contents into lightweight structural signatures 
    (Classes, Functions, and Docstrings) to save LLM context tokens.
    """
    skeleton_lines = []
    
    for filepath, content in repo_files.items():
        if filepath == current_file or not filepath.endswith(".py"):
            continue
            
        skeleton_lines.append(f"\n### File: {filepath} ###")
        try:
            tree = ast.parse(content)
            for node in tree.body:
                if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                    # Extract function signature
                    args = [a.arg for a in node.args.args]
                    skeleton_lines.append(f"def {node.name}({', '.join(args)}):")
                    if ast.get_docstring(node):
                        skeleton_lines.append(f"    \"\"\"{ast.get_docstring(node)}\"\"\"")
                        
                elif isinstance(node, ast.ClassDef):
                    # Extract class and its methods
                    skeleton_lines.append(f"class {node.name}:")
                    if ast.get_docstring(node):
                        skeleton_lines.append(f"    \"\"\"{ast.get_docstring(node)}\"\"\"")
                    for class_node in node.body:
                        if isinstance(class_node, ast.FunctionDef):
                            args = [a.arg for a in class_node.args.args] 
                            skeleton_lines.append(f"    def {class_node.name}({', '.join(args)}): pass")
        except SyntaxError:
            skeleton_lines.append("# (Syntax error parsing this file)")
            
    return "\n".join(skeleton_lines)


# --- 3. Agent A: Reviewer ---
def call_agent_a(state: AgentState, config=None):
    llm = _build_llm(config)
    print(f"--- Agent A: Reviewing Code ({llm.__class__.__name__}) ---")

    code = state["original_code"]
    repo_files = state.get("repo_files", {})

    # Generate token-efficient context
    context_skeleton = _build_context_skeleton(repo_files, state["file_path"])

    # Native schema mapping enforced through the unified interface wrapper
    structured_llm = llm.with_structured_output(ReviewOutput)

    system_prompt = f"""You are a Principal Software Architect.
    Analyze the provided code for logic errors, security vulnerabilities, and code style issues.
    Do NOT focus on simple formatting. Focus on bugs and safety.

    --- REPOSITORY CONTEXT (Available Imports & Signatures) ---
    The following structural context shows available classes and functions in the repo. 
    Use this to verify if the target code is calling imported functions correctly.
    {context_skeleton}
    -----------------------------------------------------------
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
    repo_files = state.get("repo_files", {})

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
    - DO NOT add demonstrative examples, simulated data, or print statements to show how your fix works. Only return the minimal production code.
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
        "code_diff": diff_string, 
        "iteration_count": state.get("iteration_count", 0),
    }

# --- 5. Executor: E2B Sandbox with self-healing loop (PRD §3.5, §6.1) ---
def call_executor(state: AgentState, config=None):
    print("EXECUTOR: Running pytest with Coverage in E2B Sandbox...")

    target_file = state["file_path"]
    code_to_run = state.get("refactored_code") or state.get("original_code")
    test_code = state.get("final_test_code")
    test_path = state.get("existing_test_path") or f"test_{target_file.split('/')[-1]}"
    dependencies = state.get("pypi_dependencies", [])
    
    if not test_code:
        return {
            "execution_status": "FAILURE", 
            "execution_logs": "No tests provided.", 
            "next_node": "test_engineer_node"
        }

    repo_files = dict(state.get("repo_files", {}))
    repo_files[target_file] = code_to_run
    repo_files[test_path] = test_code

    current_count = state.get("iteration_count", 0)
    api_key = _e2b_api_key(config)

    def run_tests_in_sandbox(sbx, files):
        # 1. Hydrate sandbox
        print(f"   Hydrating sandbox with {len(files)} files...")
        for path, content in files.items():
            directory = os.path.dirname(path)
            if directory:
                sbx.commands.run(f"mkdir -p {directory}")
            sbx.files.write(path, content)

        # 2. Install agent-declared dependencies directly (Fixes Bug E)
        if dependencies:
            deps_string = " ".join(dependencies)
            print(f"   Installing PyPI dependencies: {deps_string}")
            sbx.commands.run(f"pip install {deps_string}")

        # 3. Install testing requirements
        sbx.commands.run("pip install pytest pytest-cov")

        # 4. Execute tests with Coverage thresholds
        cov_module = target_file.replace("/", ".").replace(".py", "")
        cmd = f"python -m pytest {test_path} --cov={cov_module} --cov-report=term-missing --cov-fail-under=80"
        
        print(f"   Executing: {cmd}")
        execution = sbx.commands.run(cmd)
        
        return execution

    try:
        with Sandbox(api_key=api_key) as sbx:
            execution = run_tests_in_sandbox(sbx, repo_files)
            logs = execution.stdout + "\n" + execution.stderr

            # Exit Code 0: Tests pass AND coverage > 80%
            if execution.exit_code == 0:
                print("   -> Execution Successful (Tests Passed & Coverage Met)")
                return {
                    "execution_status": "SUCCESS", 
                    "execution_logs": logs,
                    "next_node": "documenter_node" 
                }

            # If it fails, determine WHY and set the next_node
            failure_reason = ""
            if "ModuleNotFoundError" in logs:
                failure_reason = "DEPENDENCY ERROR: A required module was missing. Update your pypi_dependencies list!"
                next_agent = "test_engineer_node" # Send back to Test Engineer
            elif "Coverage failure" in logs or "Required test coverage of" in logs:
                failure_reason = "COVERAGE_TOO_LOW: You did not test enough of the code."
                next_agent = "test_engineer_node" # Send back to Test Engineer
            else:
                failure_reason = "TESTS_FAILED: The refactored code broke the tests."
                next_agent = "refactorer_node" # Send back to Refactorer

            return {
                "execution_status": "FAILURE",
                "execution_logs": f"{failure_reason}\n\n{logs}",
                "iteration_count": current_count + 1,
                "next_node": next_agent  # <--- Explicitly say where to go
            }

    except Exception as e:
        return {"execution_status": "FAILURE", "execution_logs": str(e), "next_node": "refactorer_node"}


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

# --- 7. Agent T: Test Engineer (Bug E Fix) ---
def call_agent_t(state: AgentState, config=None):
    llm = _build_llm(config)
    print(f"--- Agent T: Writing/Modifying Tests & Resolving Dependencies ({llm.__class__.__name__}) ---")

    refactored_code = state.get("refactored_code") or state.get("original_code")
    existing_test = state.get("existing_test_code")
    execution_logs = state.get("execution_logs", "")
    
    structured_llm = llm.with_structured_output(TestResult)

    prompt = f"""
    You are a Senior SDET (Software Development Engineer in Test). Ensure the following code runs.
    Agent B has just refactored the following file ({state['file_path']}):
    
    ```python
    {refactored_code}
    ```
    
    PREVIOUS TEST EXECUTION LOGS (If any tests failed or dependencies were missing, fix them):
    {execution_logs}
    """

    if existing_test:
        prompt += f"""
        EXISTING TEST SUITE FOUND ({state.get('existing_test_path')}):
        ```python
        {existing_test}
        ```
        INSTRUCTIONS:
        1. MODIFY this existing test suite to handle the new implementation.
        2. Ensure you do not break the tests for unrelated functions in this file.
        3. Add new `pytest` functions for the specific logic that was changed.
        4. Return the FULL, modified test suite.
        """
    else:
        prompt += """
        No existing tests were found.
        INSTRUCTIONS:
        1. Create a brand new `pytest` suite for this file.
        2. Use `unittest.mock` to mock all external network/DB calls.
        3. Return the FULL test script.
        """

    response = structured_llm.invoke([HumanMessage(content=prompt)])

    return {
        "final_test_code": response.final_test_code,
        "pypi_dependencies": response.pypi_dependencies
    }

# --- 8 Agent D: The Diplomat (Conflict Resolver) ---
def call_agent_d_diplomat(state: AgentState, config=None):
    llm = _build_llm(config)
    print(f"--- Agent D: Resolving Merge Conflicts ({llm.__class__.__name__}) ---")

    conflict_content = state.get("conflict_file_content")
    execution_logs = state.get("execution_logs", "")

    prompt = f"""
    You are an Expert Git Conflict Resolver. 
    The following file contains standard git merge conflict markers (`<<<<<<< HEAD`, `=======`, `>>>>>>>`).

    FILE:
    ```python
    {conflict_content}
    ```

    PREVIOUS ERRORS (If this is a retry):
    {execution_logs}

    INSTRUCTIONS:
    1. Semantically merge the two conflicting blocks. 
    2. Understand the intent of both the HEAD (new feature) and the base branch changes. Do not simply delete one side if both logics are necessary.
    3. Remove ALL git conflict markers from your output.
    4. Return the FULL, executable, and resolved Python file. Do not use formatting diffs.
    """

    response = llm.invoke([HumanMessage(content=prompt)])
    result_code = response.content.strip()

    if result_code.startswith("```python"):
        result_code = result_code.split("```python")[1].split("```")[0].strip()
    elif result_code.startswith("```"):
        result_code = result_code.split("```")[1].split("```")[0].strip()

    return {
        "refactored_code": result_code,
        "iteration_count": state.get("iteration_count", 0),
    }