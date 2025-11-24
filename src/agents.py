import os
import traceback
import sys
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
    print(state)
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
    print(state)
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
    print(state)
    print("⚙️ EXECUTOR: Running code in E2B Sandbox...")
    
    # 1. Get the code to run (prioritizing refactored code)
    code_to_run = state.get("refactored_code") or state.get("original_code")
    current_count = state.get("iteration_count", 0)

    # 2. Initialize Sandbox (Ephemeral)
    # Using 'with' ensures the sandbox closes automatically after execution, saving cost.
    try:
        with Sandbox() as sbx:
            # 3. Run the code
            execution = sbx.run_code(code_to_run)

            # 4. Check for Runtime Errors
            if execution.error:
                print(f"   -> Execution Failed: {execution.error.name}")
                
                # Combine stderr and the specific error object for context
                error_details = f"Error: {execution.error.name}: {execution.error.value}\n{execution.error.traceback}"
                
                return {
                    "execution_status": "FAILURE",
                    "execution_logs": error_details,
                    "iteration_count": current_count + 1
                }
            
            # 5. Success Case
            print("   -> Execution Successful")
            
            # Combine stdout into a single string for the logs
            output_logs = "\n".join(execution.logs.stdout) if execution.logs.stdout else "Code ran successfully with no output."
            
            return {
                "execution_status": "SUCCESS",
                "execution_logs": output_logs
            }

    except Exception as e:
        # Fallback for connection errors (e.g., API key missing, network issues)
        print(f"   -> Sandbox Connection Failed: {e}")
        return {
            "execution_status": "FAILURE",
            "execution_logs": f"Infrastructure Error: {str(e)}",
            "iteration_count": current_count + 1
        }

def call_agent_c(state: AgentState):
    print(state)
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