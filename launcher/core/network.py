import hashlib
import tempfile
import tarfile
import zstandard as zstd
import requests
import os
import concurrent.futures
import logging
import time
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
            logging.info(f"Fetching versions from {self.VERSIONS_URL}")
            response = requests.get(self.VERSIONS_URL)
            response.raise_for_status()
            versions_data = response.json()
            logging.info("Successfully fetched and parsed versions.json")
            return [Version(**item) for item in versions_data]
        except requests.RequestException as e:
            logging.error(f"Error fetching versions file: {e}")
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
        is_manifest: bool = False
    ) -> Optional[str]:
        """
        Attempts to download a file from a dictionary of URLs with fallback and retries.
        Creates a temporary file to store the download.

        Args:
            urls: A dictionary of URLs to try.
            progress_callback: An optional function to call with progress fraction.
            status_callback: An optional function for status updates.
            is_manifest: A flag to indicate if the file is a manifest.

        Returns:
            The path to the downloaded file on success, None otherwise.
        """
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".zip" if not is_manifest else ".json")
        destination = temp_file.name
        temp_file.close()

        sorted_urls = self._get_sorted_urls(urls)

        for provider, url in sorted_urls:
            attempt = 0
            max_retries = 3
            while attempt < max_retries:
                try:
                    logging.info(f"Attempting to download from {provider} ({url}), attempt {attempt + 1}/{max_retries}...")
                    if status_callback:
                        status_callback(f"Trying {provider} (attempt {attempt + 1})...")
                    
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
                        
                        if progress_callback:
                            progress_callback(1.0) # Ensure 100% is reported
                    
                    logging.info("Download successful.")
                    return destination
                except requests.RequestException as e:
                    logging.error(f"Failed to download from {url} on attempt {attempt + 1}: {e}")
                    attempt += 1
                    if attempt < max_retries:
                        time.sleep(3) # Wait 3 seconds before retrying
                    else:
                        if status_callback:
                            status_callback(f"{provider} failed after {max_retries} attempts. Trying next mirror...")
                        break # Move to the next provider

        os.remove(destination)
        logging.error("All download URLs failed.")
        return None

    def verify_sha256(self, file_path: str, expected_hash: str) -> bool:
        """
        Verifies the SHA256 hash of a file.
        """
        logging.info(f"Verifying SHA256 hash for {file_path}")
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)

            calculated_hash = sha256_hash.hexdigest()
            is_valid = calculated_hash == expected_hash
            if is_valid:
                logging.info("SHA256 hash verification successful.")
            else:
                logging.error(f"SHA256 hash mismatch! Expected: {expected_hash}, Got: {calculated_hash}")
            return is_valid
        except FileNotFoundError:
            logging.error(f"File not found for hash verification: {file_path}")
            return False

    def extract_archive(self, archive_path: str, destination: str, manifest: Manifest, progress_callback: Optional[Callable[[float], None]] = None):
        """
        Extracts a .tar.zst archive to a specified destination using streaming.

        Args:
            archive_path: The path to the .tar.zst file.
            destination: The directory to extract the files to.
            manifest: The release manifest containing the file list for progress tracking.
            progress_callback: An optional function to call with progress fraction.
        """
        try:
            os.makedirs(destination, exist_ok=True)
            logging.info(f"Extracting '{archive_path}' to '{destination}'...")

            total_files = len(manifest.files)
            logging.info(f"Archive contains {total_files} files.")

            if total_files == 0:
                logging.warning("Manifest lists zero files; extraction will be skipped.")
                if progress_callback:
                    progress_callback(1.0)
                return

            dctx = zstd.ZstdDecompressor()
            with open(archive_path, "rb") as f:
                with dctx.stream_reader(f) as reader:
                    with tarfile.open(fileobj=reader, mode="r|") as tar:
                        for i, member in enumerate(tar):
                            tar.extract(member, path=destination)
                            logging.debug(f"Extracted {member.name}")
                            if progress_callback:
                                progress_callback((i + 1) / total_files)

            if progress_callback:
                progress_callback(1.0) # Ensure 100% is reported

            logging.info(f"Successfully extracted {archive_path} to {destination}")
        except tarfile.TarError as e:
            logging.error(f"Error: The file {archive_path} is not a valid tar archive or is corrupted: {e}")
        except zstd.ZstdError as e:
            logging.error(f"Error: Zstandard decompression failed for {archive_path}: {e}")
        except IOError as e:
            logging.error(f"Error reading or writing file during extraction: {e}")

    def _get_sorted_urls(self, urls: Dict[str, str]) -> List[tuple[str, str]]:
        """Sorts URLs to prioritize 'GitHub Git'."""
        sorted_urls = []
        if "GitHub Git" in urls:
            sorted_urls.append(("GitHub Git", urls["GitHub Git"]))
            for provider, url in urls.items():
                if provider != "GitHub Git":
                    sorted_urls.append((provider, url))
        else:
            sorted_urls = list(urls.items())
        return sorted_urls

    def fetch_manifest(self, version: Version, status_callback: Optional[Callable[[str], None]] = None) -> Optional[Manifest]:
        """
        Downloads and parses the manifest for a given version.
        """
        logging.info(f"Fetching manifest for version {version.version}")
        if status_callback:
            status_callback("Fetching release metadata...")

        downloaded_path = self.download_file_with_fallback(version.manifest_urls, is_manifest=True)
        if downloaded_path:
            try:
                with open(downloaded_path, "r") as f:
                    manifest_data = f.read()
                    logging.info(f"Successfully downloaded manifest for {version.version}")
                    return Manifest.model_validate_json(manifest_data)
            except Exception as e:
                logging.error(f"Error parsing manifest file: {e}")
                if status_callback:
                    status_callback(f"Error: Could not parse release metadata.")
                return None
            finally:
                os.remove(downloaded_path)

        if status_callback:
            status_callback(f"Error: Could not download release metadata.")
        return None

    def fetch_all_release_info(self) -> List[ReleaseInfo]:
        """
        Fetches all versions and their corresponding manifests, returning a list
        of combined ReleaseInfo objects.
        Downloads manifests in parallel for better performance.
        Releases are returned in the same order as in versions.json.
        """
        versions = self.fetch_versions()
        if not versions:
            return []

        # Download manifests in parallel while preserving order
        def download_manifest(version, index):
            manifest = self.fetch_manifest(version)
            return index, version, manifest

        releases = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(versions), 10)) as executor:
            # Submit all manifest downloads as futures
            futures = [executor.submit(download_manifest, version, index) for index, version in enumerate(versions)]
            future_to_index = {future: index for index, future in enumerate(futures)}
    
            # Collect results as they complete
            results = []
            logging.info(f"Downloading {len(futures)} manifests in parallel...")
            for future in concurrent.futures.as_completed(futures):
                index = future_to_index[future]
                index_from_result, version, manifest = future.result()
                if manifest:
                    logging.info(f"Successfully downloaded and parsed manifest for version {version.version}")
                    # Combine data from version and manifest using dictionary unpacking
                    release_data = {**version.model_dump(), **manifest.model_dump()}
                    results.append((index, ReleaseInfo(**release_data)))
                else:
                    logging.warning(f"Failed to process manifest for version {version.version}")

            # Sort by original index to maintain versions.json order
            results.sort(key=lambda x: x[0])
            releases = [release for _, release in results]

        return releases
