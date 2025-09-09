import os
import customtkinter as ctk
import logging
import queue
import threading
from tkinter import filedialog
from typing import Dict, List
from tkinterdnd2 import DND_FILES

from ..config import settings
from ..core.workflow import ReleaseWorkflow
from ..providers.base import AssetProvider, IndexProvider
from ..providers.catbox import CatboxProvider
from ..providers.github_git import GitHubGitProvider
from ..providers.github_release import GitHubReleaseProvider


class App(ctk.CTkToplevel):
    def __init__(self, master=None):
        super().__init__(master)

        self.title("AO Uploader")
        self.geometry("800x750")

        self._configure_providers()
        self._create_widgets()

        self.file_paths: List[str] = []
        self.feedback_queue = queue.Queue()
        self._process_feedback_queue()

    def _configure_providers(self):
        """Instantiates all configured providers."""
        self.index_provider: IndexProvider = GitHubGitProvider(
            token=settings.GITHUB_TOKEN_FOR_INDEX,
            clone_url=settings.INDEX_GIT_CLONE_URL,
            branch=settings.INDEX_GIT_BRANCH,
            local_folder=settings.INDEX_GIT_LOCAL_FOLDER,
        )

        self.asset_providers: List[AssetProvider] = []
        if settings.GITHUB_ASSET_REPO and settings.GITHUB_TOKEN_FOR_ASSETS:
            self.asset_providers.append(
                GitHubReleaseProvider(
                    token=settings.GITHUB_TOKEN_FOR_ASSETS,
                    repo_slug=settings.GITHUB_ASSET_REPO,
                )
            )
        if settings.CATBOX_USER_HASH:
            self.asset_providers.append(CatboxProvider(user_hash=settings.CATBOX_USER_HASH))

    def _create_widgets(self):
        """Creates and lays out all the GUI widgets."""
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(pady=20, padx=20, fill="both", expand=True)

        # --- Asset Provider Selection ---
        provider_frame = ctk.CTkFrame(main_frame)
        provider_frame.pack(pady=10, padx=10, fill="x")
        ctk.CTkLabel(provider_frame, text="Asset Providers").pack(pady=5, padx=10, anchor="w")

        self.provider_checkboxes: Dict[ctk.CTkCheckBox, AssetProvider] = {}
        for provider in self.asset_providers:
            var = ctk.StringVar()
            cb = ctk.CTkCheckBox(
                provider_frame,
                text=provider.get_name(),
                variable=var,
                onvalue=provider.get_name(),
                offvalue="",
                command=self._validate_inputs,
            )
            cb.pack(pady=5, padx=20, anchor="w")
            self.provider_checkboxes[cb] = provider

        # --- File Input ---
        file_frame = ctk.CTkFrame(main_frame)
        file_frame.pack(pady=10, padx=10, fill="both", expand=True)
        ctk.CTkLabel(file_frame, text="Files to Upload").pack(pady=5, padx=10, anchor="w")
        
        self.file_list_textbox = ctk.CTkTextbox(file_frame, height=100, state="disabled")
        self.file_list_textbox.pack(pady=5, padx=10, fill="x")

        # Enable drag and drop functionality
        self.file_list_textbox.drop_target_register(DND_FILES)
        self.file_list_textbox.dnd_bind('<<Drop>>', self._on_drop_files)

        btn_frame = ctk.CTkFrame(file_frame)
        btn_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(btn_frame, text="Browse Files", command=self._browse_files).pack(side="left")
        ctk.CTkButton(btn_frame, text="Clear", command=self._clear_files).pack(side="left", padx=10)


        # --- Metadata Input ---
        metadata_frame = ctk.CTkFrame(main_frame)
        metadata_frame.pack(pady=10, padx=10, fill="x")

        ctk.CTkLabel(metadata_frame, text="Release Version (e.g., 1.2.3)").pack(pady=5, padx=10, anchor="w")
        self.version_entry = ctk.CTkEntry(metadata_frame)
        self.version_entry.pack(pady=5, padx=10, fill="x")
        self.version_entry.bind("<KeyRelease>", self._validate_inputs)

        ctk.CTkLabel(metadata_frame, text="Release Notes").pack(pady=5, padx=10, anchor="w")
        self.notes_textbox = ctk.CTkTextbox(metadata_frame, height=100)
        self.notes_textbox.pack(pady=5, padx=10, fill="x")

        # --- Execution ---
        execution_frame = ctk.CTkFrame(main_frame)
        execution_frame.pack(pady=10, padx=10, fill="x")
        self.create_release_button = ctk.CTkButton(
            execution_frame, text="Create Release", state="disabled", command=self.start_release_process
        )
        self.create_release_button.pack(pady=10, padx=10, anchor="e")

        # --- Feedback ---
        feedback_frame = ctk.CTkFrame(main_frame)
        feedback_frame.pack(pady=10, padx=10, fill="both", expand=True)
        ctk.CTkLabel(feedback_frame, text="Progress Log").pack(pady=5, padx=10, anchor="w")
        self.feedback_textbox = ctk.CTkTextbox(feedback_frame, state="disabled")
        self.feedback_textbox.pack(pady=5, padx=10, fill="both", expand=True)

    def _browse_files(self):
        """Opens a dialog to select files and updates the list."""
        new_files = filedialog.askopenfilenames()
        if not new_files:
            return
        
        for f in new_files:
            if f not in self.file_paths:
                self.file_paths.append(f)
        self._update_file_list_display()
        self._validate_inputs()

    def _clear_files(self):
        """Clears the list of selected files."""
        self.file_paths.clear()
        self._update_file_list_display()
        self._validate_inputs()

    def _on_drop_files(self, event):
        """Handles files dropped onto the textbox."""
        # event.data contains dropped files, one per line or space-separated
        dropped_files = self._parse_drop_data(event.data)
        for f in dropped_files:
            f = f.strip('{}')  # Remove braces if any
            if f and os.path.isfile(f) and f not in self.file_paths:
                self.file_paths.append(f)
        self._update_file_list_display()
        self._validate_inputs()

    def _parse_drop_data(self, data: str) -> List[str]:
        """Parses the drop data into list of file paths."""
        import os
        # Split by space or newline, handle quoted paths
        paths = []
        current = ""
        in_quotes = False
        for char in data:
            if char == '"' and (not current or current[-1] != '\\'):
                in_quotes = not in_quotes
            elif char in [' ', '\n', '\r'] and not in_quotes:
                if current:
                    paths.append(current)
                    current = ""
            else:
                current += char
        if current:
            paths.append(current)
        return [p.strip('"') for p in paths if p.strip()]

    def _update_file_list_display(self):
        """Updates the text in the file list box."""
        self.file_list_textbox.configure(state="normal")
        self.file_list_textbox.delete("1.0", "end")
        if not self.file_paths:
            self.file_list_textbox.insert("1.0", "Drag files here or use Browse...")
        else:
            self.file_list_textbox.insert("1.0", "\n".join(self.file_paths))
        self.file_list_textbox.configure(state="disabled")

    def _validate_inputs(self, event=None):
        """Enable the release button only if all inputs are valid."""
        version_ok = bool(self.version_entry.get().strip())
        files_ok = bool(self.file_paths)
        provider_ok = any(cb.get() for cb in self.provider_checkboxes)

        if version_ok and files_ok and provider_ok:
            self.create_release_button.configure(state="normal")
        else:
            self.create_release_button.configure(state="disabled")
    
    def _toggle_ui_elements(self, enabled: bool):
        """Enable or disable all interactive UI elements."""
        state = "normal" if enabled else "disabled"
        self.create_release_button.configure(state=state)
        self.version_entry.configure(state=state)
        self.notes_textbox.configure(state=state)
        for cb in self.provider_checkboxes:
            cb.configure(state=state)
        # Also disable file buttons
        for child in self.winfo_children():
            if isinstance(child, ctk.CTkFrame):
                for btn in child.winfo_children():
                    if isinstance(btn, ctk.CTkButton):
                        btn.configure(state=state)

    def _log_status(self, message: str):
        """Thread-safe method to log a message to the feedback queue."""
        self.feedback_queue.put(message)

    def _process_feedback_queue(self):
        """Processes messages from the feedback queue and updates the GUI."""
        try:
            while True:
                message = self.feedback_queue.get_nowait()
                self.feedback_textbox.configure(state="normal")
                self.feedback_textbox.insert("end", f"{message}\n")
                self.feedback_textbox.yview_moveto(1.0)  # Auto-scroll
                self.feedback_textbox.configure(state="disabled")
        except queue.Empty:
            pass
        finally:
            self.after(100, self._process_feedback_queue)

    def start_release_process(self):
        """Starts the release workflow in a separate thread."""
        self._toggle_ui_elements(enabled=False)
        self.feedback_textbox.configure(state="normal")
        self.feedback_textbox.delete("1.0", "end")
        self.feedback_textbox.configure(state="disabled")

        selected_providers = [
            provider
            for cb, provider in self.provider_checkboxes.items()
            if cb.get()
        ]

        workflow = ReleaseWorkflow(
            version=self.version_entry.get().strip(),
            notes=self.notes_textbox.get("1.0", "end-1c"),
            file_paths=self.file_paths,
            asset_providers=selected_providers,
            index_provider=self.index_provider,
            status_callback=self._log_status,
        )

        thread = threading.Thread(target=self._run_workflow_in_thread, args=(workflow,))
        thread.start()

    def _run_workflow_in_thread(self, workflow: ReleaseWorkflow):
        """Wrapper to run the workflow and re-enable UI on completion."""
        try:
            workflow.run()
        except Exception as e:
            logging.error(f"Release workflow failed: {e}", exc_info=True)
            self._log_status(f"ERROR: An unexpected error occurred: {e}")
        finally:
            # Schedule the UI update to run in the main thread
            self.after(0, self._toggle_ui_elements, True)

