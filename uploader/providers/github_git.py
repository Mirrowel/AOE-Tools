import os
import json
import shutil
import git
from uploader.providers.base import IndexProvider

class GitHubGitProvider(IndexProvider):
    def __init__(self, clone_url: str, branch: str, local_folder: str, token: str):
        self.clone_url = clone_url
        self.branch = branch
        self.local_folder = local_folder
        self.token = token
        self.repo = self._init_repo()

    def _init_repo(self) -> git.Repo:
        if os.path.exists(self.local_folder):
            try:
                return git.Repo(self.local_folder)
            except git.InvalidGitRepositoryError:
                # Folder exists but is not a valid git repository, remove and re-clone
                print(f"Invalid git repository at {self.local_folder}. Removing and re-cloning...")
                shutil.rmtree(self.local_folder)

        # Add token to clone URL for authentication
        auth_url = self.clone_url.replace("https://", f"https://oauth2:{self.token}@")
        try:
            return git.Repo.clone_from(auth_url, self.local_folder, branch=self.branch)
        except git.GitCommandError as e:
            if "Remote branch" in str(e) and "not found" in str(e):
                # Branch doesn't exist (likely empty repo), clone without branch first
                print(f"Branch '{self.branch}' not found. Cloning without branch...")
                repo = git.Repo.clone_from(auth_url, self.local_folder)

                # Create and switch to the desired branch
                if self.branch not in repo.branches:
                    # Create the branch from the current state
                    repo.git.checkout('-b', self.branch)
                else:
                    repo.git.checkout(self.branch)

                return repo
            else:
                raise  # Re-raise if it's a different error

    def get_index_content(self) -> list:
        self.repo.remotes.origin.pull()
        index_path = os.path.join(self.local_folder, 'versions.json')
        if not os.path.exists(index_path):
            return []
        with open(index_path, 'r') as f:
            return json.load(f)

    def update_index_content(self, new_content: list):
        version = new_content.get("version", "unknown")
        index_path = os.path.join(self.local_folder, 'versions.json')
        with open(index_path, 'w') as f:
            json.dump(new_content, f, indent=4)
        
        self.repo.index.add([index_path])
        commit_message = f"Update versions.json for release v{version}"
        self.repo.index.commit(commit_message)
        self.repo.remotes.origin.push()