import os
from github import Github, Auth
from typing import Dict, Any, List

class GitHubConnector:
    def __init__(self, repo_name: str = None):
        """
        Initializes the connection to GitHub.
        :param repo_name: "owner/repo" string (e.g., "octocat/Hello-World")
        """
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise ValueError("❌ GITHUB_TOKEN not found in environment variables.")
        
        auth = Auth.Token(token)
        self.g = Github(auth=auth)
        
        if repo_name:
            try:
                self.repo = self.g.get_repo(repo_name)
                print(f"✅ Connected to: {self.repo.full_name}")
            except Exception as e:
                raise ValueError(f"Could not connect to repo {repo_name}: {e}")

    def get_pr_details(self, pr_number: int) -> Dict[str, Any]:
        """
        Fetches the 'Intent' context: Title, Description, and the Diff.
        Crucial for Agent A's semantic analysis.
        """
        pr = self.repo.get_pull(pr_number)
        
        # Get the files changed in this PR
        files_changed = []
        for file in pr.get_files():
            files_changed.append({
                "filename": file.filename,
                "status": file.status, # added, modified, removed
                "patch": file.patch,   # The actual diff (changes)
                "raw_url": file.raw_url
            })
            
        return {
            "title": pr.title,
            "description": pr.body,
            "author": pr.user.login,
            "files": files_changed,
            "base_branch": pr.base.ref,
            "head_branch": pr.head.ref
        }

    def get_file_content(self, file_path: str, branch: str = None) -> str:
        """
        Fetches raw file content. Raises an error if failed.
        """
        try:
            ref = branch if branch else self.repo.default_branch
            contents = self.repo.get_contents(file_path, ref=ref)
            return contents.decoded_content.decode("utf-8")
        except Exception as e:
            # RAISING the error ensures we never confuse an error message with file content
            raise ValueError(f"Failed to fetch {file_path} from {ref}: {e}")

    def list_files_in_folder(self, folder_path: str) -> List[str]:
        """
        Scans the file tree. 
        Required for 'Context Compaction' to find relevant imported files.
        """
        try:
            contents = self.repo.get_contents(folder_path)
            return [content.path for content in contents if content.type == "file"]
        except Exception:
            return []
        
    def find_file_in_repo(self, filename_ending: str, branch: str = None) -> str:
        """
        Recursively searches the repo for a file matching the ending.
        Example: input 'utils.py' -> returns 'src/utils.py'
        """
        try:
            # efficient way to get all file paths without downloading content
            ref = branch if branch else self.repo.default_branch
            # Get the full tree recursively
            sha = self.repo.get_branch(ref).commit.sha
            tree = self.repo.get_git_tree(sha, recursive=True)
            
            for element in tree.tree:
                if element.type == "blob": # blobs are files
                    # Check if path ends with our target (e.g. "src/utils.py" ends with "utils.py")
                    if element.path.endswith(filename_ending) or element.path.endswith(f"/{filename_ending}"):
                        return element.path
            return None
        except Exception as e:
            print(f"   ⚠️ Search failed for {filename_ending}: {e}")
            return None

    def get_repo_map(self, pr_files: List[dict], branch: str) -> Dict[str, str]:
        """
        Builds a dictionary of {filepath: content} for the sandbox.
        Includes files modified in the PR AND their imported dependencies.
        """
        repo_map = {}
        import ast

        print("📦 Building Repository Map (Hydrating Context)...")
        
        # 1. Load files explicitly modified in the PR
        for f in pr_files:
            if f["filename"].endswith(".py") and f["status"] != "removed":
                try:
                    content = self.get_file_content(f["filename"], branch=branch)
                    repo_map[f["filename"]] = content
                    print(f"   Nodes loaded: {f['filename']}")
                except Exception as e:
                    print(f"   ⚠️ Failed to load {f['filename']}: {e}")

        # 2. Scan for missing dependencies (Imports)
        # We look at the content we just fetched to see what else they need
        missing_imports = set()
        
        # Snapshot keys to avoid runtime error while modifying dict
        current_files = list(repo_map.items()) 
        
        for filename, content in current_files:
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    # Handle 'from x import y'
                    if isinstance(node, ast.ImportFrom) and node.module:
                        # Convert 'src.utils' -> 'utils.py' for searching
                        # We search for the *file name*, not the full path yet
                        target_name = node.module.split('.')[-1] + ".py"
                        missing_imports.add(target_name)
                        
                    # Handle 'import x'
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            target_name = alias.name.split('.')[-1] + ".py"
                            missing_imports.add(target_name)
            except SyntaxError:
                pass # Skip broken code

        # 3. Fetch missing dependencies
        # Filter out standard library (naive list) to save time
        std_lib = {'math.py', 'os.py', 'sys.py', 'json.py', 're.py', 'ast.py', 'typing.py'}
        
        for imp_name in missing_imports:
            if imp_name in std_lib: 
                continue

            # Try to find the full path in the repo
            real_path = self.find_file_in_repo(imp_name, branch=branch)
            
            # Only fetch if we found it and don't have it yet
            if real_path and real_path not in repo_map:
                try:
                    content = self.get_file_content(real_path, branch=branch)
                    repo_map[real_path] = content
                    print(f"   🔗 Dependency loaded: {real_path}")
                except:
                    pass
        
        return repo_map