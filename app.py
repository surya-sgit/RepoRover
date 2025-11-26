import chainlit as cl
from src.graph import app
from src.state import AgentState

# We keep the thread_id constant for this session
config = {"configurable": {"thread_id": "1"}}

async def run_graph(inputs=None):
    """
    Runs the LangGraph agent. 
    """
    async with cl.Step(name="RepoRover Agent") as main_step:
        # Stream events. If inputs is None, it resumes previous state.
        async for event in app.astream(inputs, config, stream_mode="values"):
            
            # --- Agent A ---
            if "review_issues" in event and event["review_issues"]:
                main_step.input = "Agent A finished reviewing."

            # --- Agent B (Refactorer) ---
            if "refactored_code" in event:
                code = event["refactored_code"]
                iteration = event.get("iteration_count", 0)
                main_step.input = f"Agent B finished refactoring (Attempt {iteration})."
                
                await cl.Message(
                    content=f"**Proposed Refactor (Iteration {iteration}):**\n```python\n{code}\n```"
                ).send()

            # --- Agent C (Documenter) ---
            if "updated_readme" in event:
                await cl.Message(content="✅ **Documentation Updated.** Process Complete.").send()

    # Check for Interrupts (Human-in-the-Loop)
    snapshot = app.get_state(config)
    if snapshot.next and "executor_tool_node" in snapshot.next:
        # The graph is paused before execution
        actions = [
            cl.Action(name="approve", value="yes", label="✅ Approve & Run"),
            cl.Action(name="reject", value="no", label="❌ Reject / Request Changes")
        ]
        await cl.Message(content="The code is ready for the Sandbox. Proceed?", actions=actions).send()

@cl.on_chat_start
async def start():
    res = await cl.AskUserMessage(content="Enter Repo Name (e.g., owner/repo):", timeout=600).send()
    if not res: return
    repo_name = res['output']

    res = await cl.AskUserMessage(content="Enter PR Number:", timeout=600).send()
    if not res: return
    pr_number = int(res['output'])

    await cl.Message(content=f"🚀 Starting RepoRover on {repo_name} PR #{pr_number}...").send()

    # Initialize state
    initial_state = {"repo_name": repo_name, "pr_number": pr_number, "iteration_count": 0}
    await run_graph(initial_state)

@cl.action_callback("approve")
async def on_approve(action: cl.Action):
    await action.remove()
    await cl.Message(content="✅ Approved. Running code in E2B Sandbox...").send()
    # Resume normally
    await run_graph(None)

@cl.action_callback("reject")
async def on_reject(action: cl.Action):
    await action.remove()
    
    # 1. Ask user for feedback
    res = await cl.AskUserMessage(content="Please explain what needs to be fixed:", timeout=600).send()
    if not res: return
    feedback = res['output']
    
    await cl.Message(content=f"⚠️ Sending feedback to Agent B: '{feedback}'").send()

    # 2. Update the graph state explicitly
    # We pretend the 'executor_tool_node' ran and produced a FAILURE with the user's feedback.
    # This triggers the conditional edge in graph.py to loop back to 'refactorer_node'.
    app.update_state(
        config,
        {
            "execution_status": "FAILURE", 
            "error_logs": f"User Rejected: {feedback}",
            "iteration_count": 1 # Increment logic handled by graph, but ensuring it's not 0
        },
        as_node="executor_tool_node" 
    )

    # 3. Resume the graph (it will now see the update and move to Refactorer)
    await run_graph(None)