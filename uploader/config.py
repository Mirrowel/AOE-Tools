import os
from dotenv import load_dotenv, set_key, find_dotenv
from typing import Optional

class Settings:
    """Loads and provides access to application settings from a .env file."""

    def __init__(self):
        # Load environment variables from a .env file if it exists
        load_dotenv()

        # --- Index Provider Configuration ---
        self.INDEX_GIT_CLONE_URL: str = os.getenv("INDEX_GIT_CLONE_URL")
        self.INDEX_GIT_BRANCH: str = os.getenv("INDEX_GIT_BRANCH")
        self.INDEX_GIT_LOCAL_FOLDER: str = os.getenv("INDEX_GIT_LOCAL_FOLDER")
        self.GITHUB_TOKEN_FOR_INDEX: str = os.getenv("GITHUB_TOKEN_FOR_INDEX")

        # --- Asset Provider Configuration ---
        # --- Asset Provider Configuration ---
        self.GITHUB_ASSET_REPO: str = os.getenv("GITHUB_ASSET_REPO")
        self.GITHUB_TOKEN_FOR_ASSETS: str = os.getenv("GITHUB_TOKEN_FOR_ASSETS")
        self.CATBOX_USER_HASH: str = os.getenv("CATBOX_USER_HASH")
        
        # --- UI State Configuration ---
        self.UI_USE_SINGLE_TOKEN: bool = os.getenv("UI_USE_SINGLE_TOKEN", "True").lower() == "true"
        self.UI_CATBOX_ANONYMOUS: bool = os.getenv("UI_CATBOX_ANONYMOUS", "True").lower() == "true"


    def save_settings(self,
                     index_git_clone_url: Optional[str] = None,
                     index_git_branch: Optional[str] = None,
                     index_git_local_folder: Optional[str] = None,
                     github_token_for_index: Optional[str] = None,
                     github_asset_repo: Optional[str] = None,
                     github_token_for_assets: Optional[str] = None,
                     catbox_user_hash: Optional[str] = None,
                     ui_use_single_token: Optional[bool] = None,
                     ui_catbox_anonymous: Optional[bool] = None):
        """Update settings and save to .env file"""
        env_path = find_dotenv() or ".env"

        # Update instance variables and save to .env
        if index_git_clone_url is not None:
            self.INDEX_GIT_CLONE_URL = index_git_clone_url
            set_key(env_path, "INDEX_GIT_CLONE_URL", index_git_clone_url or "")

        if index_git_branch is not None:
            self.INDEX_GIT_BRANCH = index_git_branch
            set_key(env_path, "INDEX_GIT_BRANCH", index_git_branch or "")

        if index_git_local_folder is not None:
            self.INDEX_GIT_LOCAL_FOLDER = index_git_local_folder
            set_key(env_path, "INDEX_GIT_LOCAL_FOLDER", index_git_local_folder or "")

        if github_token_for_index is not None:
            self.GITHUB_TOKEN_FOR_INDEX = github_token_for_index
            set_key(env_path, "GITHUB_TOKEN_FOR_INDEX", github_token_for_index or "")

        if github_asset_repo is not None:
            self.GITHUB_ASSET_REPO = github_asset_repo
            set_key(env_path, "GITHUB_ASSET_REPO", github_asset_repo or "")

        if github_token_for_assets is not None:
            self.GITHUB_TOKEN_FOR_ASSETS = github_token_for_assets
            set_key(env_path, "GITHUB_TOKEN_FOR_ASSETS", github_token_for_assets or "")

        if catbox_user_hash is not None:
            self.CATBOX_USER_HASH = catbox_user_hash
            set_key(env_path, "CATBOX_USER_HASH", catbox_user_hash or "")
        
        if ui_use_single_token is not None:
            self.UI_USE_SINGLE_TOKEN = ui_use_single_token
            set_key(env_path, "UI_USE_SINGLE_TOKEN", str(ui_use_single_token))
            
        if ui_catbox_anonymous is not None:
            self.UI_CATBOX_ANONYMOUS = ui_catbox_anonymous
            set_key(env_path, "UI_CATBOX_ANONYMOUS", str(ui_catbox_anonymous))
# Create a single instance of the settings to be used throughout the application
settings = Settings()