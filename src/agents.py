import os
import traceback
import sys
import re
from io import StringIO
from typing import List
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from src.state import AgentState
from e2b_code_interpreter import Sandbox
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv
load_dotenv()

# --- 1. Define the Strict Output Schema for Agent A ---
class CodeIssue(BaseModel):
    filepath: str = Field(description="The file where the issue was found")
    line_number: int = Field(description="Approximate line number of the issue")
    severity: str = Field(description="Critical, Warning, or Info")
    description: str = Field(description="Clear explanation of why this is bad")
    suggestion: str = Field(description="What needs to be fixed")

class ReviewOutput(BaseModel):
    summary: str = Field(description="High-level summary of the code intent")
    issues: List[CodeIssue] = Field(description="List of specific technical issues found")

# --- 2. Initialize the Model ---
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0,  # Low temperature for strict analysis
    api_key=os.environ.get("GOOGLE_API_KEY")
)

# --- 3. Define the Reviewer Node Function ---
def call_agent_a(state: AgentState):
    # print(state)
    print("--- Agent A: Reviewing Code (Gemini) ---")
    
    code = state["original_code"]
    
    # We use "with_structured_output" to force Gemini to give us JSON
    structured_llm = llm.with_structured_output(ReviewOutput)
    
    system_prompt = """You are a Principal Software Architect. 
    Analyze the provided code for logic errors, security vulnerabilities, and code style issues.
    Do NOT focus on simple formatting. Focus on bugs and safety.
    """
    
    # Invoke the model
    response = structured_llm.invoke(f"{system_prompt}\n\nCode to Review:\n{code}")
    
    # Return updates to the state
    return {
        "intent_summary": response.summary,
        "review_issues": [issue.dict() for issue in response.issues]
    }


def call_agent_b(state: AgentState):
    # print(state)
    print("--- Agent B: Refactoring Code (Gemini) ---")
    
    code = state.get("refactored_code") or state.get("original_code")
    issues = state.get("review_issues", [])
    
    # --- THE FIX: Get the error logs ---
    execution_logs = state.get("execution_logs", "")
    
    # Construct a prompt that forces the Agent to look at the error
    prompt = f"""
    You are a Python Code Refactoring Agent.
    
    Here is the code you need to fix:
    ```python
    {code}
    ```
    
    CONTEXT:
    1. Static Analysis Issues: {issues}
    2. RUNTIME ERRORS (CRITICAL): {execution_logs}
    
    INSTRUCTIONS:
    - If there are Runtime Errors, you MUST fix the code to resolve them.
    - Specifically check for missing imports (like 'math') or syntax errors.
    - Return ONLY the fixed code. No markdown, no conversational text.
    - If the code is perfect and there are no errors, return the string "NO_CHANGES".
    """
    
    # Invoke the LLM
    response = llm.invoke([HumanMessage(content=prompt)])
    
    # Handle the response
    result_code = response.content.strip()
    
    # Clean up markdown tags if the LLM adds them
    if result_code.startswith("```python"):
        result_code = result_code.split("```python")[1].split("```")[0].strip()
    
    if result_code == "NO_CHANGES":
        print("Agent B: No changes needed.")
        return {"refactored_code": code} # Return existing code
        
    print("Agent B: Code refactored.")
    return {
        "refactored_code": result_code, 
        "iteration_count": state.get("iteration_count", 0) # Preserve count here
    }

def call_executor(state):
    print("⚙️ EXECUTOR: Running code in E2B Sandbox...")
    code_to_run = state.get("refactored_code") or state.get("original_code")
    current_count = state.get("iteration_count", 0)

    # Helper to run code and return result
    def run_in_sandbox(sbx, code):
        execution = sbx.run_code(code)
        if execution.error:
            return False, execution.error
        return True, execution.logs.stdout

    try:
        with Sandbox() as sbx:
            # --- ATTEMPT 1 ---
            success, result = run_in_sandbox(sbx, code_to_run)
            
            # --- AUTO-FIX DEPENDENCIES ---
            if not success and "ModuleNotFoundError" in result.name:
                # Extract package name (e.g., "No module named 'numpy'")
                match = re.search(r"No module named '(\w+)'", result.value)
                if match:
                    package_name = match.group(1)
                    print(f"   📦 Found missing dependency: {package_name}")
                    print(f"   ⬇️ Installing {package_name}...")
                    
                    # Install the package
                    sbx.commands.run(f"pip install {package_name}")
                    
                    # --- ATTEMPT 2 (Retry after install) ---
                    print("   🔄 Retrying execution...")
                    success, result = run_in_sandbox(sbx, code_to_run)

            # --- FINAL RESULT HANDLING ---
            if not success:
                print(f"   -> Execution Failed: {result.name}")
                error_details = f"Error: {result.name}: {result.value}\n{result.traceback}"
                return {
                    "execution_status": "FAILURE",
                    "execution_logs": error_details,
                    "iteration_count": current_count + 1
                }
            
            print("   -> Execution Successful")
            output_logs = "\n".join(result) if result else "Code ran successfully."
            return {
                "execution_status": "SUCCESS",
                "execution_logs": output_logs
            }

    except Exception as e:
        print(f"   -> Sandbox Infrastructure Error: {e}")
        return {
            "execution_status": "FAILURE",
            "execution_logs": str(e),
            "iteration_count": current_count + 1
        }
def call_agent_c(state: AgentState):
    # print(state)
    print("--- Agent C: Documenting Changes (Gemini) ---")
    
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
        "documentation_diff": doc_update
    }