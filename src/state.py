from typing import TypedDict, List, Optional, Dict, Annotated
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    # --- Input Context ---
    repo_path: str
    file_path: str
    file_content: str
    original_code: str
    pr_description: str
    
    messages: Annotated[list, add_messages]
    
    repo_files: Dict[str, str] 
    next_node: str

    # --- Agent A Artifacts ---
    intent_summary: str
    review_issues: List[dict]
    refactoring_plan: str

    # --- Agent B Artifacts ---
    refactored_code: Optional[str]
    code_diff: Optional[str]

    # --- Agent D Artifacts (Conflict Resolution) ---
    conflict_file_content: Optional[str]

    # --- Executor Artifacts ---
    execution_status: str
    execution_logs: Optional[str]
    iteration_count: int
    sandbox_session_id: Optional[str]

    # --- Agent C Artifacts ---
    documentation_diff: Optional[str]
    updated_readme: Optional[str]

    # --- Agent T (Test Engineer) Artifacts ---
    existing_test_path: Optional[str]
    existing_test_code: Optional[str]
    final_test_code: Optional[str]
    coverage_score: Optional[float]
    pypi_dependencies: List[str]    

    # --- Human-in-the-Loop ---
    human_approval: bool