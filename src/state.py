from typing import TypedDict, List, Optional

class AgentState(TypedDict):
    """
    The shared state of the Code Review Graph.
    Acts as the central memory/blackboard for all agents.
    """
    # --- Input Context ---
    repo_path: str
    file_content: str
    original_code: str
    pr_description: str

    # --- Agent A Artifacts ---
    intent_summary: str
    review_issues: List[dict]  # JSON list of issues
    refactoring_plan: str

    # --- Agent B Artifacts ---
    refactored_code: Optional[str]
    execution_status: str  # "PENDING", "SUCCESS", "FAILURE"
    execution_logs: Optional[str]
    iteration_count: int
    sandbox_session_id: Optional[str]

    # --- Agent C Artifacts ---
    documentation_diff: Optional[str]
    updated_readme: Optional[str]

    # --- Human-in-the-Loop ---
    human_approval: bool