import hashlib
import tempfile
import zipfile
import requests
import os
from typing import List, Dict, Optional, Callable

from launcher.core.models import Version, Manifest, ReleaseInfo


class NetworkManager:
    """Handles all network-related operations for the launcher."""

    VERSIONS_URL = "https://raw.githubusercontent.com/Mirrowel/AOEngine-Manifest/main/versions.json"

    def fetch_versions(self) -> List[Version]:
        """
        Fetches the versions.json file and returns a list of Version objects.
        """
        try:
            response = requests.get(self.VERSIONS_URL)
            response.raise_for_status()
            versions_data = response.json()
            return [Version(**item) for item in versions_data]
        except requests.RequestException as e:
            print(f"Error fetching versions file: {e}")
            return []

    def find_latest_version(self, versions: List[Version]) -> Optional[Version]:
        """
        Finds the latest version from a list of Version objects.
        """
        for version in versions:
            if version.latest:
                return version
        return None

    def download_file_with_fallback(
        self,
        urls: Dict[str, str],
        progress_callback: Optional[Callable[[float], None]] = None,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> Optional[str]:
        """
        Attempts to download a file from a dictionary of URLs with fallback.
        Creates a temporary file to store the download.

        Args:
            urls: A dictionary of URLs to try.
            progress_callback: An optional function to call with progress fraction.

        Returns:
            The path to the downloaded file on success, None otherwise.
        """
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        destination = temp_file.name
        temp_file.close()

        for provider, url in urls.items():
            try:
                print(f"Attempting to download from {provider} ({url})...")
                if status_callback:
                    status_callback(f"Trying {provider}...")
                with requests.get(url, stream=True, timeout=10) as response:
                    response.raise_for_status()
                    total_size = int(response.headers.get("content-length", 0))
                    bytes_downloaded = 0
                    last_progress = 0
                    step = 0.01  # Send updates every 1% progress
                    with open(destination, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                            bytes_downloaded += len(chunk)
                            if progress_callback and total_size > 0:
                                current_progress = bytes_downloaded / total_size
                                if current_progress - last_progress >= step:
                                    progress_callback(current_progress)
                                    last_progress = current_progress
                        # Send final 100% update
                        if progress_callback and total_size > 0:
                            progress_callback(1.0)
                print("Download successful.")
                return destination
            except requests.RequestException as e:
                print(f"Failed to download from {url}: {e}")
                if status_callback:
                    status_callback(f"{provider} failed. Trying next mirror...")
                continue
        
        os.remove(destination)
        print("All download URLs failed.")
        return None

    def verify_sha256(self, file_path: str, expected_hash: str) -> bool:
        """
        Verifies the SHA256 hash of a file.
        """
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest() == expected_hash
        except FileNotFoundError:
            return False

    def extract_zip(self, zip_path: str, destination: str, progress_callback: Optional[Callable[[float], None]] = None):
        """
        Extracts a zip archive to a specified destination.

        Args:
            zip_path: The path to the zip file.
            destination: The directory to extract the files to.
            progress_callback: An optional function to call with progress fraction.
        """
        try:
            os.makedirs(destination, exist_ok=True)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                total_files = len(zip_ref.infolist())
                last_progress = 0
                step = 0.01  # Send updates every 1% progress
                for i, member in enumerate(zip_ref.infolist()):
                    zip_ref.extract(member, destination)
                    current_progress = (i + 1) / total_files
                    if progress_callback and current_progress - last_progress >= step:
                        progress_callback(current_progress)
                        last_progress = current_progress
                # Send final 100% update
                if progress_callback:
                    progress_callback(1.0)
            print(f"Successfully extracted {zip_path} to {destination}")
        except zipfile.BadZipFile:
            print(f"Error: The file {zip_path} is not a valid zip file or is corrupted.")
        except IOError as e:
            print(f"Error reading or writing file: {e}")

    def fetch_manifest(self, version: Version) -> Optional[Manifest]:
        """
        Downloads and parses the manifest for a given version.
        """
        downloaded_path = self.download_file_with_fallback(version.manifest_urls)
        if downloaded_path:
            try:
                with open(downloaded_path, "r") as f:
                    manifest_data = f.read()
                    return Manifest.model_validate_json(manifest_data)
            except Exception as e:
                print(f"Error parsing manifest file: {e}")
                return None
            finally:
                os.remove(downloaded_path)
        return None

    def fetch_all_release_info(self) -> List[ReleaseInfo]:
        """
        Fetches all versions and their corresponding manifests, returning a list
        of combined ReleaseInfo objects.
        """
        releases = []
        versions = self.fetch_versions()
        for version in versions:
            manifest = self.fetch_manifest(version)
            if manifest:
                # Combine data from version and manifest using dictionary unpacking
                release_data = {**version.model_dump(), **manifest.model_dump()}
                releases.append(ReleaseInfo(**release_data))
        return releases
