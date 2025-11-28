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