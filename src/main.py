from src.graph import app  # Import your compiled graph 'app'
from dotenv import load_dotenv
load_dotenv()

## This code looks okay, but it's missing 'import math'
tricky_code = """
def calculate_circle_area(radius):
    return math.pi * (radius ** 2)
print(f"Area: {calculate_circle_area(5)}")
"""

config = {"configurable": {"thread_id": "1"}}
initial_state = {
    "repo_path": "./dummy",
    "file_content": tricky_code,
    "original_code": tricky_code,
    "pr_description": "Add circle area calculation",
    "iteration_count": 0
}

# Run the graph
print("🚀 Starting RepoRover with E2B Sandbox...")
print("\n--- Phase 1: Review & Refactor ---")

# Initial run to get to the first pause
for event in app.stream(initial_state, config=config):
    for key, value in event.items():
        print(f" -> Finished: {key}")

# --- THE NEW LOOPING LOGIC ---
while True:
    # 1. Inspect the State at the Pause
    snapshot = app.get_state(config)
    
    # If the graph has stopped completely (e.g., max retries), break
    if not snapshot.next:
        print("🛑 Graph has finished processing.")
        break

    print("\n🛑 PAUSED before Execution")
    print("--- Proposed Refactored Code ---")
    current_code = snapshot.values.get("refactored_code", "No code generated")
    print(current_code)
    print("-------------------------------")

    # 2. Human Decision
    user_input = input("⚠️  Approve execution? (y/n): ")

    if user_input.lower() == "y":
        print("\n--- Phase 2: Execution & Documentation ---")
        # Resume and finish
        for event in app.stream(None, config=config):
             for key, value in event.items():
                print(f" -> Finished: {key}")
        
        # Show Final Output
        final_state = app.get_state(config).values
        print("\n=== FINAL OUTPUT ===")
        print(f"Review Summary: {final_state.get('intent_summary')}")
        print("Documentation:\n", final_state.get('documentation_diff'))
        break # Exit the loop on success

    else:
        # Handle Rejection
        print("\n❌ Execution Denied.")
        feedback = input("   Reason for rejection (e.g., 'Missing import'): ")
        print("🔄 Sending feedback to Agent B...")
        
        # Inject feedback as a "Fake Error" to trigger Agent B
        app.update_state(
            config,
            {
                "execution_status": "FAILURE", 
                "execution_logs": f"HUMAN REJECTION: {feedback}", # Ensure this key matches agents.py
                "iteration_count": snapshot.values.get("iteration_count", 0)
            },
            as_node="executor_tool_node" 
        )
        
        # Run until the NEXT pause (Agent B will run, then it pauses again)
        print("--- Agent B is attempting to fix... ---")
        for event in app.stream(None, config=config):
            for key, value in event.items():
                print(f" -> Finished: {key}")
        
        # The loop will now repeat, showing you the NEW code!
print("\n=== FINAL OUTPUT ===")
print(f"Review Summary: {final_state['intent_summary']}")
print(f"Issues Found: {len(final_state['review_issues'])}")
print("Refactored Code:\n", final_state['refactored_code'])
print("Documentation:\n",final_state['documentation_diff'])