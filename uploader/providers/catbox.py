import requests

from .base import AssetProvider


class CatboxProvider(AssetProvider):
    def __init__(self, user_hash: str = None):
        self._user_hash = user_hash  # Can be None for anonymous uploads
        self._api_url = "https://catbox.moe/user/api.php"

    def upload_asset(self, file_path: str, release_version: str) -> str:
        try:
            with open(file_path, "rb") as f:
                files = {"fileToUpload": (file_path, f)}
                data = {
                    "reqtype": "fileupload",
                }
                # Only include userhash if provided (for non-anonymous uploads)
                if self._user_hash:
                    data["userhash"] = self._user_hash

                response = requests.post(self._api_url, files=files, data=data)
                response.raise_for_status()
                return response.text
        except FileNotFoundError:
            raise Exception(f"File not found at {file_path}")
        except requests.exceptions.RequestException as e:
            raise Exception(f"Failed to upload to Catbox: {e}")

    def get_name(self) -> str:
        provider_name = "Catbox"
        if not self._user_hash:
            provider_name += " (Anonymous)"
        return provider_name