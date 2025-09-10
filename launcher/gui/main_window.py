import customtkinter as ctk
import threading
from tkinter import filedialog, messagebox
import queue
import json
import logging
from pathlib import Path
from typing import Callable

from launcher.core.config import ConfigManager
from launcher.core.network import NetworkManager
from launcher.core.backup import BackupManager
from launcher.core.models import ReleaseInfo
from launcher.utils.logging import log_queue

# Custom colors for fly agaric theme
FLY_AGARIC_RED = "#A52A2A"
FLY_AGARIC_WHITE = "#F9F6EE"
FLY_AGARIC_BLACK = "#2C1810"


class App(ctk.CTk):
    def __init__(self, master=None):
        super().__init__(master)

        self.title("AOEngine Launcher")
        self.geometry("700x500")

        # Set up fly agaric theme
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self._create_widgets()

        # --- Backend Integration ---
        self.config_manager = ConfigManager()
        
        game_path = self.config_manager.get_config().game_path
        if not game_path or not Path(game_path).is_dir():
            # Auto-detect game path by checking if CWD is a valid game root
            current_path = Path.cwd()
            bin_path = current_path / "bin"
            if (bin_path.is_dir() and
                    (bin_path / "AnomalyDX9.exe").is_file() and
                    (bin_path / "AnomalyDX11.exe").is_file()):
                self.config_manager.update_config(game_path=str(current_path))
            else:
                self._prompt_for_game_path()
        
        # After potentially prompting, the game path should be valid.
        game_path = self.config_manager.get_config().game_path
        
        self.backup_manager = BackupManager(game_path)
        self.network_manager = NetworkManager()
        
        # --- Threading and Queue for UI updates ---
        self.gui_queue = queue.Queue()
        self.after(100, self._process_gui_queue)
        self.after(100, self._process_log_queue)

        # --- Initial State ---
        self.releases: list[ReleaseInfo] = []
        self.latest_release: ReleaseInfo | None = None
        self.installed_version: str | None = "None"

        # Start update check in a separate thread
        threading.Thread(target=self._check_for_updates, daemon=True).start()

        self.console_window = None

    def _prompt_for_game_path(self):
        """Prompts the user to select the game directory."""
        self.status_label.configure(text="Please select your Anomaly directory.")
        self.update_idletasks()
        game_path = filedialog.askdirectory(title="Select your Anomaly game directory")
        if game_path:
            self.config_manager.update_config(game_path=game_path)
        else:
            # Handle case where user closes the dialog
            self.destroy() # Or display an error and exit gracefully

    def _process_gui_queue(self):
        """Processes messages from other threads to update the GUI safely."""
        processed = 0
        max_per_call = 50  # Allow more messages for responsive progress updates
        try:
            while not self.gui_queue.empty() and processed < max_per_call:
                callback, args, kwargs = self.gui_queue.get_nowait()
                callback(*args, **kwargs)
                processed += 1
        except queue.Empty:
            pass
        finally:
            # More frequent processing for better responsiveness
            self.after(10, self._process_gui_queue)

    def _process_log_queue(self):
        """Processes messages from the logging queue to update the console."""
        try:
            while not log_queue.empty():
                message = log_queue.get_nowait()
                if self.console_window and self.console_window.winfo_exists():
                    self.console_window.log(message)
        except queue.Empty:
            pass
        finally:
            self.after(100, self._process_log_queue)

    def _queue_ui_update(self, callback, *args, **kwargs):
        """A thread-safe way to queue a GUI update."""
        self.gui_queue.put((callback, args, kwargs))


    def _check_for_updates(self):
        """(Worker Thread) Fetches release info and updates the GUI via queue."""
        try:
            logging.info("Fetching release information...")
            self._queue_ui_update(self.status_label.configure, text="Fetching release information...")
            self.releases = self.network_manager.fetch_all_release_info()
            if not self.releases:
                logging.warning("Could not fetch releases.")
                self._queue_ui_update(self.status_label.configure, text="Could not fetch releases.")
                return

            # Find the latest release using the 'latest' flag, fallback to the first entry
            self.latest_release = next((r for r in self.releases if r.latest), None)
            if not self.latest_release and self.releases:
                self.latest_release = self.releases[0]

            # Populate version dropdown with latest at top
            versions = [r.version for r in self.releases if not r.latest]
            # Put latest version at the top of the list
            versions.insert(0, self.latest_release.version)
            self._queue_ui_update(self.version_option_menu.configure, values=versions)
            self._queue_ui_update(self.version_option_menu.set, self.latest_release.version)

            self._refresh_installed_version()

            # Update release notes
            self._queue_ui_update(self.release_notes_textbox.configure, state="normal")
            self._queue_ui_update(self.release_notes_textbox.delete, "1.0", "end")
            self._queue_ui_update(self.release_notes_textbox.insert, "1.0", self.latest_release.release_notes)
            self._queue_ui_update(self.release_notes_textbox.configure, state="disabled")

        except Exception as e:
            logging.error(f"Error checking for updates: {e}", exc_info=True)
            self._queue_ui_update(self.status_label.configure, text=f"Error: {e}")

    def _refresh_installed_version(self):
        """Refreshes the installed version detection and updates the UI accordingly."""
        game_path_str = self.config_manager.get_config().game_path
        if not game_path_str:
            self._queue_ui_update(self.status_label.configure, text="Game path not set.")
            return

        game_path = Path(game_path_str)
        version_file = game_path / "bin" / "version.json"
        status_text = "Ready to install."

        if version_file.exists():
            with open(version_file, "r") as f:
                local_info = json.load(f)
            self.installed_version = local_info.get("version", "None")
            if hasattr(self, 'latest_release') and self.latest_release and self.installed_version == self.latest_release.version:
                status_text = "Game is up to date."
            elif hasattr(self, 'latest_release') and self.latest_release:
                status_text = f"Update to {self.latest_release.version} available!"
            self._queue_ui_update(self.action_button.configure, text="Update")
        else:
            self.installed_version = "None"
            self._queue_ui_update(self.action_button.configure, text="Install")

        if hasattr(self, 'latest_release') and self.latest_release:
            self._queue_ui_update(self.version_label.configure, text=f"Installed: {self.installed_version} | Latest: {self.latest_release.version}")
        else:
            self._queue_ui_update(self.version_label.configure, text=f"Installed: {self.installed_version}")
        self._queue_ui_update(self.status_label.configure, text=status_text)

    def _start_installation(self):
        """(Worker Thread) Runs the full installation workflow."""
        try:
            selected_version_str = self.version_option_menu.get()
            target_release = next((r for r in self.releases if r.version == selected_version_str), None)

            if not target_release:
                logging.error(f"Selected version {selected_version_str} not found in releases.")
                self._queue_ui_update(self.status_label.configure, text="Selected version not found.")
                return

            game_path_str = self.config_manager.get_config().game_path
            if not game_path_str:
                 logging.error("Game path not configured.")
                 self._queue_ui_update(self.status_label.configure, text="Game path not configured.")
                 return
            game_path = Path(game_path_str)
            bin_path = game_path / "bin"

            def progress_callback(progress_fraction):
                self._queue_ui_update(self.progress_bar.set, progress_fraction)

            # 1. Backup
            logging.info("Backing up 'bin' directory...")
            self._queue_ui_update(self.status_label.configure, text="Backing up 'bin' directory...")
            self._queue_ui_update(self.progress_bar.set, 0)
            backup_version = self.installed_version if self.installed_version != "None" else "initial"
            self.backup_manager.create_backup(version=backup_version, progress_callback=progress_callback)
            logging.info("Backup complete.")

            # 2. Download
            logging.info(f"Downloading {target_release.version}...")
            self._queue_ui_update(self.status_label.configure, text=f"Downloading {target_release.version}...")
            self._queue_ui_update(self.progress_bar.set, 0)
            
            def status_update_callback(message):
                logging.info(message)

            download_path = self.network_manager.download_file_with_fallback(
                target_release.download_urls,
                progress_callback=progress_callback,
                status_callback=status_update_callback
            )

            if not download_path:
                logging.error("Download failed from all sources.")
                self._queue_ui_update(self.status_label.configure, text="Download failed from all sources.")
                return
            
            logging.info(f"Download successful. File saved to: {download_path}")

            # 3. Verify
            logging.info("Verifying file integrity...")
            self._queue_ui_update(self.status_label.configure, text="Verifying file integrity...")
            verified = self.network_manager.verify_sha256(download_path, target_release.zip_sha256)
            if not verified:
                logging.error("Hash mismatch! Download may be corrupt.")
                self._queue_ui_update(self.status_label.configure, text="Hash mismatch! Download may be corrupt.")
                return
            logging.info("File verification successful.")
            self._queue_ui_update(self.progress_bar.set, 1) # File verification complete

            # 4. Extract
            logging.info(f"Extracting files to {bin_path}...")
            self._queue_ui_update(self.status_label.configure, text="Extracting files...")
            self._queue_ui_update(self.progress_bar.set, 0)
            self.network_manager.extract_zip(download_path, str(bin_path), progress_callback=progress_callback)
            logging.info("Extraction complete.")

            # 5. Create version.json
            version_file_path = bin_path / "version.json"
            # Get the canonical manifest URL
            manifest_url = target_release.manifest_urls.get("GitHub Git", list(target_release.manifest_urls.values())[0])
            with open(version_file_path, "w") as f:
                json.dump({"version": target_release.version, "manifest_url": manifest_url}, f, indent=4)
            logging.info(f"Created version.json for version {target_release.version}")

            self._queue_ui_update(self.status_label.configure, text="Installation complete!")
            self._queue_ui_update(self.progress_bar.set, 1)
            self.installed_version = target_release.version
            self._queue_ui_update(self.version_label.configure, text=f"Installed: {self.installed_version} | Latest: {self.latest_release.version}")
            logging.info("Installation complete!")

        except Exception as e:
            logging.error(f"Installation failed: {e}", exc_info=True)
            self._queue_ui_update(self.status_label.configure, text=f"Installation failed: {e}")
        finally:
            self._queue_ui_update(self.action_button.configure, state="normal")
            # Clean up downloaded file
            if 'download_path' in locals() and download_path:
                download_file = Path(download_path)
                if download_file.exists():
                    download_file.unlink()

    def _create_widgets(self):
        """Creates and lays out all the GUI widgets."""
        # --- Main Frame ---
        main_frame = ctk.CTkFrame(self, fg_color=FLY_AGARIC_BLACK,
                                  border_color=FLY_AGARIC_RED, border_width=2)
        main_frame.pack(pady=10, padx=10, fill="both", expand=True)

        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_rowconfigure(3, weight=1)

        # --- Version Info ---
        version_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        version_frame.grid(row=0, column=0, columnspan=2, pady=5, padx=10, sticky="ew")

        self.version_label = ctk.CTkLabel(version_frame, text="Installed: v0.0.0 | Latest: v0.0.0",
                                          font=ctk.CTkFont(size=12))
        self.version_label.pack(side="left")

        self.version_option_menu = ctk.CTkOptionMenu(version_frame, values=["v0.0.0"],
                                                     fg_color=FLY_AGARIC_RED,
                                                     button_color=FLY_AGARIC_RED,
                                                     button_hover_color=FLY_AGARIC_WHITE,
                                                     command=self._on_version_select)
        self.version_option_menu.pack(side="right")

        # --- Status Label ---
        self.status_label = ctk.CTkLabel(main_frame, text="Checking for updates...",
                                         font=ctk.CTkFont(size=14, weight="bold"))
        self.status_label.grid(row=1, column=0, pady=5, padx=10, sticky="ew")

        # --- Action Button ---
        self.action_button = ctk.CTkButton(main_frame, text="Install",
                                           command=self._on_action_button_click,
                                           fg_color=FLY_AGARIC_RED,
                                           hover_color=FLY_AGARIC_WHITE,
                                           text_color=FLY_AGARIC_WHITE,
                                           font=ctk.CTkFont(size=14, weight="bold"))
        self.action_button.grid(row=2, column=0, pady=10, padx=10, sticky="ew")

        # --- Release Notes ---
        self.release_notes_textbox = ctk.CTkTextbox(main_frame, wrap="word",
                                                    fg_color=FLY_AGARIC_WHITE,
                                                    text_color=FLY_AGARIC_BLACK,
                                                    border_color=FLY_AGARIC_RED,
                                                    border_width=2)
        self.release_notes_textbox.grid(row=3, column=0, pady=5, padx=10, sticky="nsew")
        self.release_notes_textbox.insert("1.0", "Release notes will be displayed here.")
        self.release_notes_textbox.configure(state="disabled")

        # --- Progress Bar ---
        self.progress_bar = ctk.CTkProgressBar(main_frame,
                                               progress_color=FLY_AGARIC_RED)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=4, column=0, pady=10, padx=10, sticky="ew")

        # --- Backup Management ---
        self.backup_button = ctk.CTkButton(main_frame, text="Manage Backups",
                                           command=self._open_backup_window,
                                           fg_color=FLY_AGARIC_RED,
                                           hover_color=FLY_AGARIC_WHITE,
                                           text_color=FLY_AGARIC_WHITE)
        self.backup_button.grid(row=5, column=0, pady=10, padx=10, sticky="ew")

        # --- Console Window ---
        self.console_button = ctk.CTkButton(main_frame, text="Console",
                                           command=self._open_console_window,
                                           fg_color=FLY_AGARIC_RED,
                                           hover_color=FLY_AGARIC_WHITE,
                                           text_color=FLY_AGARIC_WHITE)
        self.console_button.grid(row=6, column=0, pady=10, padx=10, sticky="ew")

    def _open_console_window(self):
        if self.console_window is None or not self.console_window.winfo_exists():
            self.console_window = ConsoleWindow(self)
        else:
            self.console_window.focus()

    def _open_backup_window(self):
        backup_window = BackupWindow(self, self.backup_manager)
        backup_window.grab_set()

    def _on_version_select(self, selected_version: str):
        """Updates the release notes when a different version is selected."""
        release = next((r for r in self.releases if r.version == selected_version), None)
        if release:
            self.release_notes_textbox.configure(state="normal")
            self.release_notes_textbox.delete("1.0", "end")
            self.release_notes_textbox.insert("1.0", release.release_notes)
            self.release_notes_textbox.configure(state="disabled")

    def _on_action_button_click(self):
        self.action_button.configure(state="disabled")
        threading.Thread(target=self._start_installation, daemon=True).start()


class BackupWindow(ctk.CTkToplevel):
    def __init__(self, master, backup_manager: BackupManager):
        super().__init__(master)
        self.backup_manager = backup_manager
        self.master = master

        self.title("Backup Management")
        self.geometry("500x400")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # --- Title ---
        title_label = ctk.CTkLabel(self, text="Available Backups", font=ctk.CTkFont(size=16, weight="bold"))
        title_label.grid(row=0, column=0, pady=10, padx=10, sticky="ew")

        # --- Scrollable Frame for Backups ---
        self.scrollable_frame = ctk.CTkScrollableFrame(self, label_text="Backups",
                                                       fg_color=FLY_AGARIC_BLACK,
                                                       border_color=FLY_AGARIC_RED,
                                                       border_width=2)
        self.scrollable_frame.grid(row=1, column=0, pady=5, padx=10, sticky="nsew")

        # --- Progress Bar ---
        self.progress_bar = ctk.CTkProgressBar(self,
                                               progress_color=FLY_AGARIC_RED)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=2, column=0, pady=5, padx=10, sticky="ew")

        # --- Status Label ---
        self.status_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12))
        self.status_label.grid(row=3, column=0, pady=5, padx=10, sticky="ew")

        self._populate_backup_list()

    def _populate_backup_list(self):
        """Fetches and displays the list of backups."""
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()

        backups = self.backup_manager.get_available_backups()
        if not backups:
            no_backup_label = ctk.CTkLabel(self.scrollable_frame, text="No backups found.")
            no_backup_label.pack(pady=10)
            return

        for backup_name in backups:
            backup_frame = ctk.CTkFrame(self.scrollable_frame, fg_color="transparent")
            backup_frame.pack(fill="x", pady=5, padx=5)
            
            backup_frame.grid_columnconfigure(0, weight=1)

            backup_label = ctk.CTkLabel(backup_frame, text=backup_name)
            backup_label.grid(row=0, column=0, padx=10, sticky="w")

            button_frame = ctk.CTkFrame(backup_frame, fg_color="transparent")
            button_frame.grid(row=0, column=1, sticky="e")

            restore_button = ctk.CTkButton(button_frame, text="Restore",
                                           command=lambda name=backup_name: self._start_restore(name),
                                           fg_color=FLY_AGARIC_RED,
                                           hover_color=FLY_AGARIC_WHITE,
                                           text_color=FLY_AGARIC_WHITE,
                                           width=80)
            restore_button.pack(side="left", padx=5)

            delete_button = ctk.CTkButton(button_frame, text="Delete",
                                          command=lambda name=backup_name: self._confirm_delete(name),
                                          fg_color=FLY_AGARIC_WHITE,
                                          hover_color=FLY_AGARIC_RED,
                                          text_color=FLY_AGARIC_BLACK,
                                          width=80)
            delete_button.pack(side="left", padx=5)

    def _confirm_delete(self, backup_name: str):
        """Asks for confirmation before deleting a backup."""
        if messagebox.askyesno("Confirm Deletion", f"Are you sure you want to delete the backup '{backup_name}'?"):
            self._start_delete(backup_name)

    def _start_delete(self, backup_name: str):
        """Starts the delete process in a worker thread."""
        self._set_buttons_state("disabled")
        self.status_label.configure(text=f"Deleting {backup_name}...")
        threading.Thread(target=self._delete_worker, args=(backup_name,), daemon=True).start()

    def _delete_worker(self, backup_name: str):
        """(Worker Thread) Performs the delete operation."""
        try:
            self.backup_manager.delete_backup(backup_name)
            self.master._queue_ui_update(self.status_label.configure, text=f"Successfully deleted {backup_name}.")
            self.master._queue_ui_update(self._populate_backup_list)
        except Exception as e:
            self.master._queue_ui_update(self.status_label.configure, text=f"Error deleting backup: {e}")
        finally:
            self.master._queue_ui_update(self._set_buttons_state, "normal")


    def _start_restore(self, backup_name: str):
        """Starts the restore process in a worker thread."""
        def progress_callback(progress_fraction):
            self.master._queue_ui_update(self.progress_bar.set, progress_fraction)

        self._set_buttons_state("disabled")
        self.status_label.configure(text=f"Restoring {backup_name}...")
        self.progress_bar.set(0)
        threading.Thread(target=self._restore_worker, args=(backup_name, progress_callback), daemon=True).start()

    def _restore_worker(self, backup_name: str, progress_callback: Callable):
        """(Worker Thread) Performs the restore operation."""
        try:
            self.backup_manager.restore_backup(backup_name, progress_callback=progress_callback)
            # Refresh the main window's installed version after successful restore
            self.master._refresh_installed_version()
            self.master._queue_ui_update(self.status_label.configure, text=f"Successfully restored {backup_name}.")
        except Exception as e:
            self.master._queue_ui_update(self.status_label.configure, text=f"Error restoring backup: {e}")
        finally:
            self.master._queue_ui_update(self._set_buttons_state, "normal")

    def _set_buttons_state(self, state: str):
        """Enables or disables all buttons in the backup list."""
        for widget in self.scrollable_frame.winfo_children():
            if isinstance(widget, ctk.CTkFrame):
                for sub_widget in widget.winfo_children():
                     if isinstance(sub_widget, ctk.CTkFrame):
                        for button in sub_widget.winfo_children():
                            if isinstance(button, ctk.CTkButton):
                                button.configure(state=state)


class ConsoleWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Console Log")
        self.geometry("800x400")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.log_textbox = ctk.CTkTextbox(self, wrap="word",
                                          fg_color=FLY_AGARIC_BLACK,
                                          text_color=FLY_AGARIC_WHITE,
                                          border_color=FLY_AGARIC_RED,
                                          border_width=2,
                                          font=("Courier New", 12))
        self.log_textbox.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.log_textbox.configure(state="disabled")

    def log(self, message: str):
        """Appends a message to the log display."""
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", message + "\n")
        self.log_textbox.see("end") # Scroll to the end
        self.log_textbox.configure(state="disabled")