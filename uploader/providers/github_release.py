from github import Github, GithubException
from .base import AssetProvider
import os
import logging
import threading

class GitHubReleaseProvider(AssetProvider):
    def __init__(self, repo_slug: str, token: str):
        self.github = Github(token)
        self.repo = self.github.get_repo(repo_slug)
        self._release_lock = threading.Lock()

    def _initialize_repo(self):
        """Check if the repo is empty and create an initial commit if it is."""
        try:
            logging.info(f"Checking commits for repo: {self.repo.full_name}")
            # This will now raise a GithubException with status 409 if the repo is empty
            commits = self.repo.get_commits()
            logging.info(f"Found {commits.totalCount} commits.")
        except GithubException as e:
            logging.error(f"Error checking for commits: {e.status} {e.data}")
            if e.status == 409 and "empty" in str(e.data).lower():
                logging.info("Repository is empty. Creating initial commit.")
                # Repo is empty, create an initial file
                self.repo.create_file(
                    path=".gitkeep",
                    message="Initial commit",
                    content="",  # Empty content
                    branch=self.repo.default_branch
                )
                logging.info("Initial commit created successfully.")
            else:
                raise # Re-raise other exceptions

    def upload_asset(self, file_path: str, release_version: str, release_notes: str) -> str:
        logging.info(f"Uploading asset {file_path} for release {release_version}")
        self._initialize_repo()  # Ensure repo is not empty
        tag_name = f"v{release_version}"

        with self._release_lock:
            # Ensure the tag exists before creating the release
            try:
                self.repo.get_git_ref(f"tags/{tag_name}")
            except GithubException as e:
                if e.status == 404:
                    logging.info(f"Tag {tag_name} not found. Creating it now.")
                    self.repo.create_git_ref(
                        ref=f"refs/tags/{tag_name}",
                        sha=self.repo.get_commits()[0].sha
                    )
                else:
                    raise

            try:
                release = self.repo.get_release(tag_name)
                logging.info(f"Found existing release: {release.title}")
            except GithubException as e:
                if e.status == 404:
                    logging.info(f"Release not found for tag {tag_name}. Creating new release.")
                    release = self.repo.create_git_release(
                        tag=tag_name,
                        name=f"Release {release_version}",
                        message=f"Automated release for version {release_version}\n\n{release_notes}",
                        make_latest="true"
                    )
                    logging.info(f"Created new release: {release.title}")
                else:
                    logging.error(f"Error getting release: {e.status} {e.data}")
                    raise e

        logging.info(f"Uploading asset to release '{release.title}'")
        asset = release.upload_asset(file_path, label=os.path.basename(file_path))
        logging.info(f"Asset uploaded successfully: {asset.browser_download_url}")
        return asset.browser_download_url

    def get_name(self) -> str:
        return "GitHub Releases"