from src.graph import app 
from src.github_tools import GitHubConnector
from dotenv import load_dotenv
load_dotenv()


# --- CONFIGURATION ---
# Use a public repo for testing (or your own private one)
REPO_NAME = "surya-sgit/PortfolioOptimisation" 
PR_NUMBER = 1 # Pick any closed PR number to test, or create a dummy PR in your own repo

print("--- 1. Connecting to GitHub ---")
try:
    gh = GitHubConnector(REPO_NAME)
    
    # Fetch real PR data
    print(f"📥 Fetching PR #{PR_NUMBER}...")
    pr_data = gh.get_pr_details(PR_NUMBER)
    
    # For this demo, we'll focus on the first Python file modified in the PR
    target_file = None
    for f in pr_data["files"]:
        if f["filename"].endswith(".py"):
            target_file = f
            break
            
    if target_file:
        full_content = gh.get_file_content(target_file["filename"])
        
        initial_state = {
            "repo_path": REPO_NAME,
            "file_content": full_content,     # The full file (for Context)
            "original_code": full_content,
            "pr_description": f"Title: {pr_data['title']}\nDesc: {pr_data['description']}", # Intent Analysis
            "iteration_count": 0
        }
        print(f"✅ Loaded: {target_file['filename']}")
    else:
        print("❌ No Python files found in this PR.")
        exit()

except Exception as e:
    print(f"❌ Connection Failed: {e}")
    exit()


config = {"configurable": {"thread_id": "1"}}
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