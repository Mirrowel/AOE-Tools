import abc

class IndexProvider(abc.ABC):
    @abc.abstractmethod
    def get_index_content(self) -> list:
        """This method should retrieve the raw content of the `versions.json` index."""
        pass

    @abc.abstractmethod
    def update_index_content(self, new_content: list):
        """This method should commit and push the updated `versions.json` content."""
        pass

    @abc.abstractmethod
    def save_index_content(self, new_content: list):
        """This method should save the entire index file with a generic commit message."""
        pass

    @abc.abstractmethod
    def save_all_changes(self, versions_content: list, manifests_to_update: dict):
        """Saves versions.json and any modified manifests in a single commit."""
        pass

class AssetProvider(abc.ABC):
    @abc.abstractmethod
    def upload_asset(self, file_path: str, release_version: str) -> str:
        """This method should upload a single asset (like the `.zip` or `manifest.json`) and return its public URL."""
        pass

    @abc.abstractmethod
    def get_name(self) -> str:
        """A simple method to return a human-readable name for the provider (e.g., "GitHub Releases"), which will be used in the GUI and logging."""
        pass