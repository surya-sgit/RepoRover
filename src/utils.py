import os

def read_file(file_path: str) -> str:
    """Reads code from a file."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    with open(file_path, "r") as f:
        return f.read()

def write_file(file_path: str, content: str):
    """Overwrites the file with new code."""
    with open(file_path, "w") as f:
        f.write(content)
    print(f"💾 Saved changes to {file_path}")