from langgraph.graph import StateGraph, START, END
from typing import Literal
from src.state import AgentState
from src.agents import call_agent_a, call_agent_b, call_executor, call_agent_c

# --- Mock Nodes (Placeholders for Day 1) ---
def reviewer_node(state: AgentState):
    print("--- Agent A: Reviewing Code ---")
    return {"review_issues": [{"error": "mock_error"}]}

def refactorer_node(state: AgentState):
    print("--- Agent B: Refactoring Code ---")
    return {"refactored_code": "print('hello')", "iteration_count": state.get("iteration_count", 0) + 1}

def executor_tool_node(state: AgentState):
    print("--- Tool: Executing Code in E2B ---")
    # Simulate a failure on the first try, success on the second
    if state.get("iteration_count", 0) < 2:
        return {"execution_status": "FAILURE", "error_logs": "SyntaxError"}
    return {"execution_status": "SUCCESS", "error_logs": None}

def documenter_node(state: AgentState):
    print("--- Agent C: Updating Documentation ---")
    return {"updated_readme": "Updated content"}

# --- Conditional Logic ---
def should_continue(state: AgentState) -> Literal["documenter_node", "refactorer_node", "__end__"]:
    status = state.get("execution_status")
    count = state.get("iteration_count", 0)

    if status == "SUCCESS":
        return "documenter_node"
    
    # Retry Limit (Max 3 retries)
    if status == "FAILURE" and count < 3:
        print(f"--- FAILED (Attempt {count}). Looping back... ---")
        return "refactorer_node"
    
    if count >= 3:
        print("🛑 Max retries reached.")
        return END
    
    return "__end__"

# --- Graph Construction ---
workflow = StateGraph(AgentState)

# 1. Add Nodes
workflow.add_node("reviewer_node", call_agent_a)
workflow.add_node("refactorer_node", call_agent_b)
workflow.add_node("executor_tool_node", call_executor)
workflow.add_node("documenter_node", call_agent_c)

# 2. Add Edges
workflow.add_edge(START, "reviewer_node")
workflow.add_edge("reviewer_node", "refactorer_node")
workflow.add_edge("refactorer_node", "executor_tool_node")

# 3. Add Conditional Edges
workflow.add_conditional_edges(
    "executor_tool_node",
    should_continue
)
workflow.add_edge("documenter_node", END)

# 4. Compile
app = workflow.compile()
