from typing import TypedDict, List, Optional, Dict

class AgentState(TypedDict):
    # --- Input Context ---
    repo_path: str
    file_path: str
    file_content: str
    original_code: str
    pr_description: str
    
    # NEW: Holds the entire relevant file system {"utils.py": "def foo()..."}
    repo_files: Dict[str, str] 

    # --- Agent A Artifacts ---
    intent_summary: str
    review_issues: List[dict]
    refactoring_plan: str

    # --- Agent B Artifacts ---
    refactored_code: Optional[str]
    execution_status: str
    execution_logs: Optional[str]
    iteration_count: int
    sandbox_session_id: Optional[str]

    # --- Agent C Artifacts ---
    documentation_diff: Optional[str]
    updated_readme: Optional[str]

    # --- Human-in-the-Loop ---
    human_approval: bool