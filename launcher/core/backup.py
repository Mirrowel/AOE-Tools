import os
import json
import shutil
import tarfile
import zstandard as zstd
from datetime import datetime
from typing import Callable, Optional, List

class BackupManager:
    """Manages backup and restore operations for the game files."""

    def __init__(self, game_path: str):
        """
        Initializes the BackupManager.
        Args:
            game_path: The path to the user's game directory.
        """
        self.game_path = game_path
        self.backup_root = os.path.join(self.game_path, "launcher_backups")
        self.bin_path = os.path.join(self.game_path, "bin")
        os.makedirs(self.backup_root, exist_ok=True)

    def create_backup(self, version: str = "initial", files_to_backup: Optional[List[str]] = None, progress_callback: Optional[Callable[[float], None]] = None):
        """
        Creates a zstandard-compressed tar backup of specified files or the entire 'bin' directory
        and an accompanying metadata file.
        Args:
            version: The version to associate with the backup.
            files_to_backup: A list of specific file paths to back up. If None, the entire 'bin' directory is backed up.
            progress_callback: An optional function to call with progress fraction.
        """
        if version == "initial":
            backup_name = "initial_vanilla_files"
        else:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            backup_name = f"v{version}_{timestamp}"

        backup_base_path = os.path.join(self.backup_root, backup_name)
        archive_path = f"{backup_base_path}.tar.zst"
        meta_path = f"{backup_base_path}.meta.json"

        if version == "initial" and os.path.exists(archive_path):
            return

        try:
            root = self.bin_path
            if files_to_backup:
                file_paths = [os.path.join(self.bin_path, f) for f in files_to_backup if os.path.exists(os.path.join(self.bin_path, f))]
            else:
                file_paths = [os.path.join(dp, f) for dp, dn, fn in os.walk(root) for f in fn]
            
            total_files = len(file_paths)

            # Create metadata file
            with open(meta_path, 'w') as f:
                json.dump({"total_files": total_files}, f)

            last_progress = 0
            step = 0.01  # Send updates every 1% of progress

            cctx = zstd.ZstdCompressor()
            with open(archive_path, 'wb') as f, cctx.stream_writer(f) as compressor, tarfile.open(fileobj=compressor, mode='w') as tar:
                for i, file_path in enumerate(file_paths):
                    arcname = os.path.relpath(file_path, root)
                    tar.add(file_path, arcname=arcname)
                    
                    current_progress = (i + 1) / total_files
                    if progress_callback and current_progress - last_progress >= step:
                        progress_callback(current_progress)
                        last_progress = current_progress

            if progress_callback:
                progress_callback(1.0)

        except (IOError, zstd.ZstdError) as e:
            print(f"Error creating backup: {e}")
            # Clean up partial files on failure
            if os.path.exists(archive_path):
                os.remove(archive_path)
            if os.path.exists(meta_path):
                os.remove(meta_path)
            raise

    def get_available_backups(self) -> list[str]:
        """
        Gets a list of available backup names (.tar.zst files).
        Returns:
            A list of strings, where each string is the name of a backup file.
        """
        try:
            return [f for f in os.listdir(self.backup_root) if f.endswith(".tar.zst")]
        except OSError as e:
            print(f"Error accessing backup directory: {e}")
            return []

    def restore_backup(self, backup_name: str, progress_callback: Optional[Callable[[float], None]] = None):
        """
        Restores the game files from a specified backup using a manifest for progress.
        Args:
            backup_name: The name of the backup to restore (e.g., 'v1.0_...tar.zst').
            progress_callback: An optional function to call with progress fraction.
        """
        archive_path = os.path.join(self.backup_root, backup_name)
        meta_path = archive_path.replace(".tar.zst", ".meta.json")

        if not os.path.exists(archive_path):
            raise FileNotFoundError(f"Backup archive '{backup_name}' not found.")
        if not os.path.exists(meta_path):
            raise FileNotFoundError(f"Backup metadata for '{backup_name}' not found.")

        try:
            if os.path.exists(self.bin_path):
                shutil.rmtree(self.bin_path)
            
            with open(meta_path, 'r') as f:
                meta = json.load(f)
            total_files = meta.get("total_files", 0)

            if total_files == 0: # Handle case with empty backup or missing key
                if progress_callback: progress_callback(1.0)
                return

            dctx = zstd.ZstdDecompressor()
            # The mode 'r|' is critical here. It tells tarfile to read from a non-seekable stream, preventing seek errors.
            with open(archive_path, 'rb') as f, dctx.stream_reader(f) as reader, tarfile.open(fileobj=reader, mode='r|') as tar:
                last_progress = 0
                step = 0.01
                for i, member in enumerate(tar):
                    # Security check to prevent path traversal attacks
                    member_path = os.path.join(self.bin_path, member.name)
                    if not os.path.normpath(member_path).startswith(os.path.normpath(self.bin_path)):
                         raise IOError(f"Attempted path traversal in backup detected: {member.name}")

                    tar.extract(member, path=self.bin_path)
                    current_progress = (i + 1) / total_files
                    if progress_callback and current_progress - last_progress >= step:
                        progress_callback(current_progress)
                        last_progress = current_progress
            
            if progress_callback:
                progress_callback(1.0)
        
        except (IOError, tarfile.TarError, zstd.ZstdError, json.JSONDecodeError) as e:
            print(f"Error restoring backup: {e}")
            raise

    def delete_backup(self, backup_name: str):
        """
        Deletes a specified backup archive and its metadata file.
        Args:
            backup_name: The name of the backup to delete (e.g., 'v1.0_...tar.zst').
        """
        archive_path = os.path.join(self.backup_root, backup_name)
        meta_path = archive_path.replace(".tar.zst", ".meta.json")
        
        if not os.path.exists(archive_path):
            raise FileNotFoundError(f"Backup archive '{backup_name}' not found.")
            
        try:
            os.remove(archive_path)
            if os.path.exists(meta_path):
                os.remove(meta_path)
        except OSError as e:
            print(f"Error deleting backup: {e}")
            raise