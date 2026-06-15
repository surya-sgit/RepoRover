"""LangGraph assembly for the multi-agent verification circuit (PRD §3.5).

The graph is compiled lazily so importing this module never opens a database
connection (the web process may run without Postgres reachable). Celery workers
call :func:`get_app` to obtain a process-wide compiled graph backed by a durable
checkpointer, keyed by ``langgraph_thread_id`` so review state survives across
separate webhook invocations.
"""
from __future__ import annotations

import os
from typing import Literal

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from src.state import AgentState
from src.agents import call_agent_a, call_agent_b, call_executor, call_agent_c, call_agent_t


# --- Conditional routing after the executor (self-healing loop) ---
def route_after_executor(state: AgentState) -> Literal["documenter_node", "refactorer_node","test_engineer_node", "__end__"]:
    status = state.get("execution_status")
    count = state.get("iteration_count", 0)

    # 1. SUCCESS -> Document it
    if status == "SUCCESS":
        return "documenter_node"

    # 2. USER SKIP -> Document the changes anyway
    if status == "SKIPPED_TO_DOCS":
        print("--- User skipped execution. Generating docs... ---")
        return "documenter_node"

    # 3. FAILURE -> Retry loop, strict ceiling of 3 iterations (PRD §3.5)
    if status == "FAILURE":
        if count >= 3:
            print(f"--- MAX RETRIES REACHED ({count}). Terminating. ---")
            return END
        
        # Pull the intelligent routing decision made by the E2B Sandbox
        # (Defaults to refactorer_node if the state variable is missing)
        next_node = state.get("next_node", "refactorer_node")
        print(f"--- FAILED (Attempt {count}). Routing back to {next_node}... ---")
        return next_node

    # 4. MAX RETRIES or terminal end
    print("Process Ended.")
    return END


# --- Graph construction (uncompiled; reused by every compile target) ---
def build_workflow() -> StateGraph:
    workflow = StateGraph(AgentState)

    # 1. Add all nodes
    workflow.add_node("reviewer_node", call_agent_a)
    workflow.add_node("refactorer_node", call_agent_b)
    workflow.add_node("test_engineer_node", call_agent_t)  # <--- NEW: Add Agent T
    workflow.add_node("executor_tool_node", call_executor)
    workflow.add_node("documenter_node", call_agent_c)

    # 2. Define the Standard Linear Flow
    workflow.add_edge(START, "reviewer_node")
    workflow.add_edge("reviewer_node", "refactorer_node")
    workflow.add_edge("refactorer_node", "test_engineer_node")  # <--- NEW: Code is written -> Write tests
    workflow.add_edge("test_engineer_node", "executor_tool_node")  # <--- NEW: Tests written -> Send to E2B Sandbox

    # 3. Define the Self-Healing Routing (After the Sandbox)
    workflow.add_conditional_edges(
        "executor_tool_node", 
        route_after_executor,
        {
            "refactorer_node": "refactorer_node",        # Tests failed because code is broken
            "test_engineer_node": "test_engineer_node",  # Tests failed because coverage is too low
            "documenter_node": "documenter_node",        # Execution Success or User Skip
            END: END                                     # Max retries hit
        }
    )
    
    workflow.add_edge("documenter_node", END)

    return workflow


def compile_app(checkpointer):
    """Compile the graph with the given checkpointer.

    The graph always pauses *before* sandbox execution so the orchestration layer
    can post results to the PR and wait for a slash command (PRD §3.5, §3.6).
    """
    return build_workflow().compile(
        checkpointer=checkpointer,
        interrupt_before=["executor_tool_node"],
    )


# --- Checkpointer factory ---------------------------------------------------
# Selected via the CHECKPOINTER env var. "postgres" persists durable state for
# cross-invocation resume; "memory" is for local smoke testing only.
#
# NOTE (Zero-Retention, PRD §1): the Postgres checkpointer writes the full graph
# state — including source code held in `file_content` / `repo_files` — to the
# database. To uphold the zero-source-retention guarantee strictly, run with an
# ephemeral store (CHECKPOINTER=memory or a Redis instance with persistence
# disabled). The choice is left configurable here rather than hard-wired.

_app_singleton = None
_pg_pool = None


def _postgres_checkpointer():
    """Build (once) a PostgresSaver backed by a connection pool and run setup()."""
    global _pg_pool
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg_pool import ConnectionPool

    dsn = os.environ.get("POSTGRES_DSN")
    if not dsn:
        # Fall back to Django settings when running inside the app context.
        try:
            from django.conf import settings

            dsn = settings.POSTGRES_DSN
        except Exception as exc:  # pragma: no cover - misconfiguration guard
            raise RuntimeError("POSTGRES_DSN is not configured for the checkpointer.") from exc

    if _pg_pool is None:
        _pg_pool = ConnectionPool(
            conninfo=dsn,
            max_size=int(os.environ.get("CHECKPOINTER_POOL_SIZE", "10")),
            kwargs={"autocommit": True, "prepare_threshold": 0},
        )
    saver = PostgresSaver(_pg_pool)
    saver.setup()  # idempotent: creates checkpoint tables if absent
    return saver


def get_app():
    """Return the process-wide compiled graph (lazy singleton)."""
    global _app_singleton
    if _app_singleton is None:
        backend = os.environ.get("CHECKPOINTER", "postgres").lower()
        if backend == "memory":
            _app_singleton = compile_app(MemorySaver())
        else:
            _app_singleton = compile_app(_postgres_checkpointer())
    return _app_singleton


def build_local_app():
    """Compile a fresh graph with an in-memory checkpointer (CLI smoke test)."""
    return compile_app(MemorySaver())
