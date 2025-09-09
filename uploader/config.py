import os
from dotenv import load_dotenv

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
        self.GITHUB_ASSET_REPO: str = os.getenv("GITHUB_ASSET_REPO")
        self.GITHUB_TOKEN_FOR_ASSETS: str = os.getenv("GITHUB_TOKEN_FOR_ASSETS")
        self.CATBOX_USER_HASH: str = os.getenv("CATBOX_USER_HASH")

# Create a single instance of the settings to be used throughout the application
settings = Settings()