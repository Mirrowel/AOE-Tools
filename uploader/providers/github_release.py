from github import Github, GithubException
from .base import AssetProvider
import os

class GitHubReleaseProvider(AssetProvider):
    def __init__(self, repo_slug: str, token: str):
        self.github = Github(token)
        self.repo = self.github.get_repo(repo_slug)

    def upload_asset(self, file_path: str, release_version: str) -> str:
        tag_name = f"v{release_version}"
        try:
            release = self.repo.get_release(tag_name)
        except GithubException as e:
            if e.status == 404:
                release = self.repo.create_git_release(
                    tag=tag_name,
                    name=f"Release {release_version}",
                    message=f"Automated release for version {release_version}"
                )
            else:
                raise e

        asset = release.upload_asset(file_path, label=os.path.basename(file_path))
        return asset.browser_download_url

    def get_name(self) -> str:
        return "GitHub Releases"