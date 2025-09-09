import hashlib
import json
import logging
import os
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable, Dict, List, Tuple

from uploader.providers.base import AssetProvider, IndexProvider


class ReleaseWorkflow:
    def __init__(
        self,
        version: str,
        notes: str,
        file_paths: List[str],
        asset_providers: List[AssetProvider],
        index_provider: IndexProvider,
        status_callback: Callable[[str], None],
    ):
        self.version = version
        self.notes = notes
        self.file_paths = file_paths
        self.asset_providers = asset_providers
        self.index_provider = index_provider
        self.status_callback = status_callback

    def _log(self, message: str):
        logging.info(message)
        self.status_callback(message)

    def _calculate_sha256(self, file_path: str) -> str:
        """Calculates the SHA256 hash of a file."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _create_zip_archive(self, temp_dir: str) -> str:
        """Creates a zip archive from the provided files."""
        zip_filename = f"AOEngine-v{self.version}.zip"
        zip_path = os.path.join(temp_dir, zip_filename)
        self._log(f"Creating zip archive at: {zip_path}")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in self.file_paths:
                arcname = os.path.basename(file_path)
                zipf.write(file_path, arcname=arcname)
        self._log("Zip archive created successfully.")
        return zip_path

    def _create_manifest(self, temp_dir: str, zip_hash: str) -> str:
        """Creates the manifest.json file."""
        manifest_path = os.path.join(temp_dir, f"manifest-v{self.version}.json")
        manifest_data = {
            "version": self.version,
            "release_notes": self.notes,
            "zip_sha256": zip_hash,
            "upload_date": datetime.now(timezone.utc).isoformat(),
        }
        self._log(f"Creating manifest.json at: {manifest_path}")
        with open(manifest_path, "w") as f:
            json.dump(manifest_data, f, indent=4)
        self._log("manifest.json created successfully.")
        return manifest_path

    def _upload_asset(
        self, provider: AssetProvider, file_path: str, version: str, notes: str
    ) -> Tuple[str, str, str]:
        """Wrapper for uploading a single asset to a single provider."""
        provider_name = provider.get_name()
        file_name = os.path.basename(file_path)
        self._log(f"Uploading '{file_name}' to {provider_name}...")
        try:
            if provider_name == "GitHub Releases":
                url = provider.upload_asset(file_path, version, notes)
            else:
                url = provider.upload_asset(file_path, version)
            self._log(f"Successfully uploaded '{file_name}' to {provider_name}: {url}")
            return provider_name, file_name, url
        except Exception as e:
            logging.error(f"Failed to upload to {provider_name}: {e}", exc_info=True)
            self._log(f"ERROR: Failed to upload '{file_name}' to {provider_name}: {e}")
            return provider_name, file_name, None

    def run(self):
        """Executes the entire release workflow."""
        self._log(f"Starting release process for version {self.version}...")
        temp_dir = tempfile.mkdtemp(prefix="aouploader-")
        self._log(f"Created temporary directory: {temp_dir}")

        try:
            # Step 1: Package & Hash
            zip_path = self._create_zip_archive(temp_dir)
            zip_hash = self._calculate_sha256(zip_path)
            self._log(f"Calculated SHA256 hash for zip: {zip_hash}")

            # Step 2: Generate manifest.json
            manifest_path = self._create_manifest(temp_dir, zip_hash)

            # Step 3: Parallel Asset Upload
            self._log("Starting parallel asset uploads...")
            download_urls: Dict[str, str] = {}
            manifest_urls: Dict[str, str] = {}
            files_to_upload = [zip_path, manifest_path]

            with ThreadPoolExecutor(max_workers=len(self.asset_providers) * 2) as executor:
                futures = [
                    executor.submit(self._upload_asset, provider, file_path, self.version, self.notes)
                    for provider in self.asset_providers
                    for file_path in files_to_upload
                ]
                
                for future in as_completed(futures):
                    provider_name, file_name, url = future.result()
                    if url:
                        if file_name.endswith(".zip"):
                            download_urls[provider_name] = url
                        elif file_name.endswith(".json"):
                            # Exclude manifest URL from GitHub Releases provider to avoid rate limits
                            if provider_name != "GitHub Releases":
                                manifest_urls[provider_name] = url
            
            # The manifest from the index provider is canonical, so we only need the zip from asset providers.
            if not download_urls:
                raise RuntimeError("Failed to upload zip archive to any provider. Aborting.")
            
            self._log("Parallel asset uploads completed.")

            # Step 4: Commit manifest to index repo
            self._log("Committing manifest to index repository...")
            manifest_index_url = self.index_provider.commit_manifest_file(manifest_path, self.version)
            self._log(f"Manifest committed to index repo: {manifest_index_url}")
            
            # Step 5: Update Version Index
            self._log("Updating version index...")
            current_index = self.index_provider.get_index_content()
            
            # Add the URL from the index repo to the manifest_urls dictionary
            # This makes it the canonical source, but we still track mirrors
            manifest_urls[self.index_provider.get_name()] = manifest_index_url

            # Ensure no other entry is marked as latest
            for entry in current_index:
                entry.pop("latest", None)

            new_entry = {
                "version": self.version,
                "release_notes": self.notes,
                "manifest_urls": manifest_urls,
                "download_urls": download_urls,
                "latest": True,
            }

            # Add the new release to the top of the list
            current_index.insert(0, new_entry)
            
            self.index_provider.update_index_content(current_index)
            self._log("Version index updated successfully.")

        finally:
            # Step 6: Cleanup
            self._log("Cleaning up temporary files...")
            if temp_dir and os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir)
            self._log("Cleanup complete.")

        self._log(f"Successfully completed release for version {self.version}!")
