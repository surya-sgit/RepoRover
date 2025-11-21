from langgraph.graph import StateGraph, START, END
from src.state import AgentState
from src.agents import call_agent_b, call_executor

# --- 1. Define a Shortcut Graph ---
# We rebuild the graph manually here to control the entry point.
workflow = StateGraph(AgentState)

# Add only the nodes we care about for this test
workflow.add_node("refactorer_node", call_agent_b)
workflow.add_node("executor_tool_node", call_executor)

# --- 2. THE FIX: Start directly at Refactorer (Agent B) ---
# This completely ignores Agent A
workflow.add_edge(START, "refactorer_node")
workflow.add_edge("refactorer_node", "executor_tool_node")

# --- 3. Define Logic to handle success/failure ---
def simple_conditional(state: AgentState):
    status = state.get("execution_status")
    count = state.get("iteration_count", 0)
    
    if status == "SUCCESS":
        print("✅ Success! Ending test.")
        return END
    
    if status == "FAILURE" and count < 3:
        print(f"🔄 Failed (Attempt {count}). Looping back to Agent B...")
        return "refactorer_node"
    
    print("🛑 Max retries reached. Ending.")
    return END

workflow.add_conditional_edges(
    "executor_tool_node",
    simple_conditional
)

test_app = workflow.compile()

# --- 4. The Buggy Code ---
# This code crashes because math.pi is not a function
buggy_code = """
import math
def calculate_circumference(radius):
    return 2 * math.pi() * radius
print(calculate_circumference(5))
"""

# We cheat and say "No issues" so Agent B blindly runs it
initial_state = {
    "repo_path": "./dummy",
    "original_code": buggy_code,
    "review_issues": [], 
    "iteration_count": 0
}

print("🚀 Starting Bypass Test (Agent A is skipped)...")
final_state = test_app.invoke(initial_state)

print("\n=== FINAL RESULT ===")
print(f"Refactored Code:\n{final_state.get('refactored_code')}")