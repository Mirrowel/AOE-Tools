import os
import shutil
import zipfile
from datetime import datetime
from typing import Callable, Optional

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

    def create_backup(self, version: str = "initial", progress_callback: Optional[Callable[[float], None]] = None):
        """
        Creates a zipped backup of the 'bin' directory.
        Args:
            version: The version to associate with the backup. "initial" creates a special backup.
            progress_callback: An optional function to call with progress fraction.
        """
        if version == "initial":
            backup_name = "initial_vanilla_files"
        else:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            backup_name = f"v{version}_{timestamp}"

        backup_path = os.path.join(self.backup_root, f"{backup_name}.zip")
        
        if version == "initial" and os.path.exists(backup_path):
            return

        try:
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                root = self.bin_path
                file_paths = []
                for dirpath, _, filenames in os.walk(root):
                    for filename in filenames:
                        file_paths.append(os.path.join(dirpath, filename))
                
                total_files = len(file_paths)
                for i, file_path in enumerate(file_paths):
                    arcname = os.path.relpath(file_path, root)
                    zipf.write(file_path, arcname)
                    if progress_callback:
                        progress_callback((i + 1) / total_files)

        except IOError as e:
            print(f"Error creating backup: {e}")
            raise

    def get_available_backups(self) -> list[str]:
        """
        Gets a list of available backup names (zip files).
        Returns:
            A list of strings, where each string is the name of a backup file.
        """
        try:
            return [f for f in os.listdir(self.backup_root) if f.endswith(".zip")]
        except OSError as e:
            print(f"Error accessing backup directory: {e}")
            return []

    def restore_backup(self, backup_name: str, progress_callback: Optional[Callable[[float], None]] = None):
        """
        Restores the game files from a specified backup.
        Args:
            backup_name: The name of the backup to restore.
            progress_callback: An optional function to call with progress fraction.
        """
        backup_path = os.path.join(self.backup_root, backup_name)
        if not os.path.exists(backup_path):
            raise FileNotFoundError(f"Backup '{backup_name}' not found.")

        try:
            if os.path.exists(self.bin_path):
                shutil.rmtree(self.bin_path)
            
            with zipfile.ZipFile(backup_path, 'r') as zip_ref:
                total_files = len(zip_ref.infolist())
                for i, member in enumerate(zip_ref.infolist()):
                    zip_ref.extract(member, self.bin_path)
                    if progress_callback:
                        progress_callback((i + 1) / total_files)

        except IOError as e:
            print(f"Error restoring backup: {e}")
            raise

    def delete_backup(self, backup_name: str):
        """
        Deletes a specified backup file.
        Args:
            backup_name: The name of the backup to delete.
        """
        backup_path = os.path.join(self.backup_root, backup_name)
        if not os.path.exists(backup_path):
            raise FileNotFoundError(f"Backup '{backup_name}' not found.")
        try:
            os.remove(backup_path)
        except OSError as e:
            print(f"Error deleting backup: {e}")
            raise