import os
import subprocess
import tempfile
import shutil
from github import Github, GithubIntegration, Auth
from typing import Dict, Any, List, Optional

class GitHubConnector:
    def __init__(self, repo_name: str = None, *, github_client: "Github" = None):
        """
        Initializes the connection to GitHub.

        :param repo_name: "owner/repo" string (e.g., "octocat/Hello-World")
        :param github_client: Pre-authenticated ``Github`` instance. When omitted,
            falls back to a ``GITHUB_TOKEN`` personal access token (local smoke
            testing only). Production callers should use
            :meth:`from_installation` to obtain a short-lived installation token
            (PRD §3.4, §6).
        """
        if github_client is not None:
            self.g = github_client
        else:
            token = os.environ.get("GITHUB_TOKEN")
            if not token:
                raise ValueError("GITHUB_TOKEN not found in environment variables.")
            self.g = Github(auth=Auth.Token(token))

        if repo_name:
            try:
                self.repo = self.g.get_repo(repo_name)
                print(f"Connected to: {self.repo.full_name}")
            except Exception as e:
                raise ValueError(f"Could not connect to repo {repo_name}: {e}")

    @classmethod
    def from_installation(
        cls,
        repo_name: str,
        installation_id: int,
        app_id: str,
        private_key: str,
    ) -> "GitHubConnector":
        """
        Build a connector authenticated as a GitHub App installation.

        Mints a short-lived installation access token (PRD §3.4, §6) — the bot
        never holds a long-lived personal token, and access is scoped strictly to
        the repositories the user granted at install time.
        """
        if not app_id or not private_key:
            raise ValueError("GitHub App credentials (app_id / private_key) are not configured.")
        auth = Auth.AppAuth(app_id, private_key)
        integration = GithubIntegration(auth=auth)
        access_token = integration.get_access_token(int(installation_id)).token
        client = Github(auth=Auth.Token(access_token))
        return cls(repo_name, github_client=client)

    def post_pr_comment(self, pr_number: int, body: str) -> int:
        """
        Post a comment on a pull request's conversation thread and return its id.

        Used by the orchestration layer to deliver review results and the
        Execution Paused notice straight into the PR (PRD §3.5, §5.2).
        """
        issue = self.repo.get_issue(pr_number)
        comment = issue.create_comment(body)
        return comment.id

    def post_inline_pr_comment(self, pr_number: int, commit_sha: str, file_path: str, body: str) -> int:
        """
        Attempts to post an inline review comment. Falls back to standard comment if the line position is invalid.
        """
        pr = self.repo.get_pull(pr_number)
        try:
            # Position 1 targets the first line of the diff patch
            comment = pr.create_review_comment(
                body=body,
                commit_id=commit_sha,
                path=file_path,
                position=1 
            )
            return comment.id
        except Exception as e:
            # Fallback if position=1 is rejected by GitHub API
            print(f"Inline comment failed for {file_path}, falling back to PR thread: {e}")
            fallback_body = f"**[Inline notice for `{file_path}`]**\n\n{body}"
            return self.post_pr_comment(pr_number, fallback_body)

    def get_latest_commit_sha(self, pr_number: int) -> str:
        """Return the head SHA of a PR, used to guard against stale executions (PRD §4.3)."""
        return self.repo.get_pull(pr_number).head.sha

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
                "status": file.status,
                "patch": file.patch,
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
            print(f"   Search failed for {filename_ending}: {e}")
            return None

    def get_repo_map(self, pr_files: List[dict], branch: str) -> Dict[str, str]:
        """
        Builds a dictionary of {filepath: content} for the sandbox.
        Includes files modified in the PR AND their imported dependencies.
        """
        repo_map = {}
        import ast

        print("Building Repository Map (Hydrating Context)...")
        
        # 1. Load files explicitly modified in the PR
        for f in pr_files:
            if f["filename"].endswith(".py") and f["status"] != "removed":
                try:
                    content = self.get_file_content(f["filename"], branch=branch)
                    repo_map[f["filename"]] = content
                    print(f"   Nodes loaded: {f['filename']}")
                except Exception as e:
                    print(f"   Failed to load {f['filename']}: {e}")

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
                    print(f"   Dependency loaded: {real_path}")
                except:
                    pass
        
        return repo_map
    
    def generate_conflict_markers(self, base_branch: str, head_branch: str, file_path: str) -> Optional[str]:
        """
        Option B: Uses a local shallow clone to force Git to generate exact conflict markers.
        Extremely fast and uses zero E2B credits.
        """
        # Extract the raw token to authenticate the subprocess clone
        token = self.g.get_user()._requester.auth.token
        clone_url = f"https://x-access-token:{token}@github.com/{self.repo.full_name}.git"
        
        temp_dir = tempfile.mkdtemp()
        try:
            # 1. Shallow clone the base branch
            subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", base_branch, clone_url, temp_dir],
                check=True, capture_output=True
            )
            
            # 2. Fetch the head branch
            subprocess.run(
                ["git", "fetch", "origin", head_branch, "--depth", "1"],
                cwd=temp_dir, check=True, capture_output=True
            )
            
            # 3. Configure dummy git user for the merge action
            subprocess.run(["git", "config", "user.email", "bot@reporover.com"], cwd=temp_dir)
            subprocess.run(["git", "config", "user.name", "RepoRover"], cwd=temp_dir)
            
            # 4. Attempt the merge (This will fail and generate markers if there is a conflict)
            subprocess.run(
                ["git", "merge", "FETCH_HEAD", "--no-commit", "--no-ff"],
                cwd=temp_dir, capture_output=True
            )
            
            # 5. Read the generated file with the markers
            full_path = os.path.join(temp_dir, file_path)
            if not os.path.exists(full_path):
                return None
                
            with open(full_path, "r", encoding="utf-8") as f:
                return f.read()
                
        except Exception as e:
            print(f"Error generating conflict markers: {e}")
            return None
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def push_commit(self, branch: str, file_path: str, content: str, commit_message: str) -> bool:
        """Pushes a direct commit to the branch to resolve the conflict."""
        try:
            # We need the SHA of the file we are replacing
            file_data = self.repo.get_contents(file_path, ref=branch)
            self.repo.update_file(
                path=file_path,
                message=commit_message,
                content=content,
                sha=file_data.sha,
                branch=branch
            )
            return True
        except Exception as e:
            print(f"Failed to push commit: {e}")
            return False