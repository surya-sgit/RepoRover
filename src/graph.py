from langgraph.graph import StateGraph, START, END
from typing import Literal
from src.state import AgentState
from langgraph.checkpoint.memory import MemorySaver
from src.agents import call_agent_a, call_agent_b, call_executor, call_agent_c



# --- Conditional Logic ---
def should_continue(state: AgentState) -> Literal["documenter_node", "refactorer_node", "__end__"]:
    status = state.get("execution_status")
    count = state.get("iteration_count", 0)

    # 1. SUCCESS -> Document it
    if status == "SUCCESS":
        return "documenter_node"
    
    # 2. NEW: USER SKIP -> Document it (even if it failed, we want to record changes)
    if status == "SKIPPED_TO_DOCS":
        print("--- User skipped execution. Generating docs... ---")
        return "documenter_node"

    # 3. FAILURE -> Retry Loop
    if status == "FAILURE" and count < 3:
        print(f"--- FAILED (Attempt {count}). Looping back... ---")
        return "refactorer_node"
    
    # 4. MAX RETRIES or USER END
    print("🛑 Process Ended.")
    return END

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
memory = MemorySaver()
# 4. Compile
app = workflow.compile(checkpointer=memory, interrupt_before=["executor_tool_node"])
