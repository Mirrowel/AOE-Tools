import os
import json
import shutil
import git
import time
import logging
from functools import wraps
from uploader.providers.base import IndexProvider

def git_retry(max_retries=3, delay=2.0):
    """Decorator that retries a function call in case of GitCommandError or GithubException."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (git.GitCommandError, Exception) as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logging.warning(f"Git operation failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {delay} seconds...")
                        time.sleep(delay)
                    else:
                        logging.error(f"Git operation failed after {max_retries} attempts: {e}")
                        raise last_exception
            raise last_exception
        return wrapper
    return decorator

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

    @git_retry()
    def update_index_content(self, new_content: list):
        # Assuming the latest version is the first in the list
        version = new_content[0].get("version", "unknown") if new_content else "unknown"
        index_path = os.path.abspath(os.path.join(self.local_folder, 'versions.json'))
        with open(index_path, 'w') as f:
            json.dump(new_content, f, indent=4)
        
        self.repo.index.add([index_path])
        commit_message = f"Update versions.json for release v{version}"
        self.repo.index.commit(commit_message)
        self.repo.remotes.origin.push()

    @git_retry()
    def commit_manifest_file(self, file_path: str, version: str) -> str:
        """Commits a manifest file to a 'manifests' directory and returns its URL."""
        manifests_dir = os.path.abspath(os.path.join(self.local_folder, 'manifests'))
        os.makedirs(manifests_dir, exist_ok=True)
        
        new_manifest_path = os.path.join(manifests_dir, f"manifest-v{version}.json")
        shutil.copy(file_path, new_manifest_path)
        
        self.repo.index.add([new_manifest_path])
        commit_message = f"Add manifest for release v{version}"
        self.repo.index.commit(commit_message)
        self.repo.remotes.origin.push()
        
        # Construct the raw GitHub URL
        # Assumes the clone URL is in the format https://github.com/user/repo.git
        base_url = self.clone_url.replace(".git", "")
        # This is a bit of a hack. A more robust solution might use the GitHub API
        # to get the raw URL, but this is simpler for now.
        raw_url = f"{base_url}/raw/{self.branch}/manifests/manifest-v{version}.json"
        
        return raw_url

    def save_index_content(self, new_content: list):
        """Saves the entire index file with a generic commit message."""
        index_path = os.path.abspath(os.path.join(self.local_folder, 'versions.json'))
        with open(index_path, 'w') as f:
            json.dump(new_content, f, indent=4)
        
        self.repo.index.add([index_path])
        commit_message = "Update versions.json from AO Uploader"
        self.repo.index.commit(commit_message)
        self.repo.remotes.origin.push()

    @git_retry()
    def save_all_changes(self, versions_content: list, manifests_to_update: dict):
        """Saves versions.json and any modified manifests in a single commit."""
        self.repo.remotes.origin.pull()

        paths_to_add = []

        # Write versions.json
        index_path = os.path.abspath(os.path.join(self.local_folder, 'versions.json'))
        with open(index_path, 'w') as f:
            json.dump(versions_content, f, indent=4)
        paths_to_add.append(index_path)

        # Write any modified manifests
        if manifests_to_update:
            manifests_dir = os.path.abspath(os.path.join(self.local_folder, 'manifests'))
            for version, manifest_data in manifests_to_update.items():
                manifest_path = os.path.join(manifests_dir, f"manifest-v{version}.json")
                if os.path.exists(manifests_dir):
                    with open(manifest_path, 'w') as f:
                        json.dump(manifest_data, f, indent=4)
                    paths_to_add.append(manifest_path)

        if not paths_to_add:
            logging.warning("No changes to commit.")
            return

        self.repo.index.add(paths_to_add)
        commit_message = "Update release data from AO Uploader"
        self.repo.index.commit(commit_message)
        self.repo.remotes.origin.push()

    def get_name(self) -> str:
        return "GitHub Git"