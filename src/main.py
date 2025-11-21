from src.graph import app  # Import your compiled graph 'app'
from dotenv import load_dotenv
load_dotenv()

## This code looks okay, but it's missing 'import math'
tricky_code = """
def calculate_circle_area(radius):
    import math
    return math.pi * (radius ** 2)
print(f"Area: {calculate_circle_area(5)}")
"""

initial_state = {
    "repo_path": "./dummy",
    "file_content": tricky_code,
    "original_code": tricky_code,
    "pr_description": "Add circle area calculation",
    "iteration_count": 0
}

# Run the graph
print("🚀 Starting RepoRover with E2B Sandbox...")
final_state = app.invoke(initial_state)

print("\n=== FINAL OUTPUT ===")
print(f"Review Summary: {final_state['intent_summary']}")
print(f"Issues Found: {len(final_state['review_issues'])}")
print("Refactored Code:\n", final_state['refactored_code'])
print("Documentation:\n",final_state['documentation_diff'])