import sys
from src.graph import app 
from src.github_tools import GitHubConnector
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- CONFIGURATION ---
REPO_NAME = "abhayk-gupta/test_multi_file" 
PR_NUMBER = 1

print("--- 1. Connecting to GitHub ---")
try:
    gh = GitHubConnector(REPO_NAME)
    
    # Fetch real PR data
    print(f"📥 Fetching PR #{PR_NUMBER}...")
    pr_data = gh.get_pr_details(PR_NUMBER)
    
    # 1. FETCH EVERYTHING UPFRONT
    print("--- Phase 0: Context Hydration ---")
    try:
        # Use the new method to get ALL relevant files
        repo_context_map = gh.get_repo_map(pr_data["files"], pr_data["head_branch"])
        print(f"✅ Hydration Complete. Loaded {len(repo_context_map)} files into memory.")
    except Exception as e:
        print(f"❌ Failed to hydrate context: {e}")
        exit()
    # 1. Filter for ALL Python files (exclude deleted files)
    target_files = [
        f for f in pr_data["files"] 
        if f["filename"].endswith(".py") and f["status"] != "removed"
    ]
            
    if not target_files:
        print("❌ No Python files found in this PR.")
        sys.exit()
    
    print(f"📦 Found {len(target_files)} Python files to process.")

except Exception as e:
    print(f"❌ Connection Failed: {e}")
    sys.exit()

# --- OUTER LOOP: Process Each File Individually ---
print("🚀 Starting RepoRover with E2B Sandbox...")

for i, target_file in enumerate(target_files):
    filename = target_file['filename']
    print(f"\n" + "="*60)
    print(f"📂 PROCESSING FILE {i+1}/{len(target_files)}: {filename}")
    print("="*60)

    # 1. Fetch File Content
    try:
        print(f"📥 Fetching content from branch: {pr_data['head_branch']}")
        # We grab the content from our pre-loaded map
        full_content = repo_context_map.get(filename, "")
        
        if not full_content:
            print("⚠️ Content missing, fetching fallback...")
            full_content = gh.get_file_content(filename, branch=pr_data["head_branch"])
    except ValueError as e:
        print(f"⚠️ Error reading {filename}: {e}")
        print("⏩ Skipping to next file...")
        continue

    # 2. Initialize State for THIS specific file
    initial_state = {
        "repo_path": REPO_NAME,
        "file_path": filename,
        "file_content": full_content,
        "original_code": full_content,
        "repo_files": repo_context_map,  # <--- PASS THE FULL MAP HERE
        "pr_description": f"Title: {pr_data['title']}\nDesc: {pr_data['description']}",
        "iteration_count": 0
    }

    # 3. Unique Thread ID per file
    config = {"configurable": {"thread_id": f"pr_{PR_NUMBER}_file_{i}"}}

    print(f"\n--- Phase 1: Review & Refactor ({filename}) ---")
    
    # Initial run to get to the first pause
    for event in app.stream(initial_state, config=config):
        for key, value in event.items():
            print(f" -> Finished: {key}")

    # --- INNER LOOP: Human-in-the-Loop for the current file ---
    file_processing_complete = False
    
    while not file_processing_complete:
        # 1. Inspect State
        snapshot = app.get_state(config)
        
        # A. IF GRAPH IS DONE (No next steps) -> Success!
        if not snapshot.next:
            final_state = snapshot.values
            print(f"\n=== FINAL OUTPUT for {filename} ===")
            print(f"Review Summary: {final_state.get('intent_summary')}")
            # print(f"Docs: {final_state.get('documentation_diff')}")
            print(f"✅ Finished processing {filename}.")
            break

        # B. IF GRAPH IS PAUSED -> Show Code & Ask Permission
        print(f"\n🛑 PAUSED: Reviewing changes for {filename}")
        
        # Check if this is a Retry
        iteration = snapshot.values.get("iteration_count", 0)
        if iteration > 0:
            print(f"⚠️  (Attempt #{iteration + 1}) Previous run failed or was rejected.")

        print("--- Proposed Refactored Code (Preview) ---")
        current_code = snapshot.values.get("refactored_code", "No code generated")
        
        # Smart Preview
        preview_lines = current_code.split('\n')[:15]
        print('\n'.join(preview_lines))
        if len(preview_lines) < len(current_code.split('\n')):
            print(f"... ({len(current_code.split('\n')) - 15} lines hidden) ...")
        print("-------------------------------")

        # 2. Human Decision
        user_input = input(f"⚠️  Approve execution for {filename}? (y / n / v [view full]): ").strip().lower()

        # --- OPTION V: VIEW FULL CODE ---
        if user_input == "v":
            print(f"\n📜 FULL CODE FOR {filename}:")
            print("="*40)
            print(current_code)
            print("="*40 + "\n")
            continue 

        # --- OPTION Y: APPROVE ---
        elif user_input == "y":
            print(f"\n--- Phase 2: Execution & Documentation ({filename}) ---")
            
            # Resume execution
            for event in app.stream(None, config=config):
                 for key, value in event.items():
                    print(f" -> Finished: {key}")
            
            # --- CRITICAL FIX HERE ---
            # Don't break yet! The loop will restart, check 'snapshot.next'.
            # If it's empty -> It finishes (Step A).
            # If it's paused again (Retry) -> It asks you again (Step B).
            pass 

        # --- OPTION N: REJECT ---
        else:
            print("\n❌ Execution Denied. Select an action:")
            print("   [1] Give Feedback & Retry (Default)")
            print("   [2] Skip Execution & Generate Docs (Agent C)")
            print("   [3] Force Stop (Exit Program)")
            
            choice = input("   Enter choice (1/2/3): ").strip()
            
            if choice == "2":
                print("⏩ Skipping execution. Proceeding to Agent C...")
                app.update_state(
                    config,
                    {"execution_status": "SKIPPED_TO_DOCS", "execution_logs": "User skipped."},
                    as_node="executor_tool_node"
                )
                for event in app.stream(None, config=config):
                     for key, value in event.items():
                        print(f" -> Finished: {key}")
                # Loop will restart and catch the "Finished" state

            elif choice == "3":
                print("🛑 Terminating RepoRover.")
                sys.exit() 

            else:
                feedback = input("   Reason for rejection: ")
                print("🔄 Sending feedback to Agent B...")
                
                app.update_state(
                    config,
                    {
                        "execution_status": "FAILURE", 
                        "execution_logs": f"HUMAN REJECTION: {feedback}",
                        "iteration_count": snapshot.values.get("iteration_count", 0)
                    },
                    as_node="executor_tool_node" 
                )
                
                print(f"--- Agent B is attempting to fix {filename}... ---")
                for event in app.stream(None, config=config):
                    for key, value in event.items():
                        print(f" -> Finished: {key}")
                
                # Loop will restart, catch the new Pause, and show you the new code!

print("\n✅ All files processed successfully.")