import os
import customtkinter as ctk
import logging
import queue
import threading
from tkinter import filedialog
from typing import Dict, List
from tkinterdnd2 import DND_FILES
from concurrent.futures import ThreadPoolExecutor
import requests
import json

from ..config import settings
from ..core.workflow import ReleaseWorkflow
from ..providers.base import AssetProvider, IndexProvider
from ..providers.catbox import CatboxProvider
from ..providers.github_git import GitHubGitProvider
from ..providers.github_release import GitHubReleaseProvider

# Set up fly agaric theme
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")  # Base for customization

# Custom colors for fly agaric theme
FLY_AGARIC_RED = "#A52A2A"
FLY_AGARIC_WHITE = "#F9F6EE"
FLY_AGARIC_BLACK = "#2C1810"


class NotesEditPopup(ctk.CTkToplevel):
    def __init__(self, master, current_notes, save_callback):
        super().__init__(master)

        self.title("🍄 Edit Release Notes")
        self.geometry("500x400")
        self.save_callback = save_callback

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.notes_textbox = ctk.CTkTextbox(self, wrap="word", height=300)
        self.notes_textbox.grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky="nsew")
        self.notes_textbox.insert("1.0", current_notes)

        self.save_button = ctk.CTkButton(self, text="Save", command=self._on_save)
        self.save_button.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        
        self.cancel_button = ctk.CTkButton(self, text="Cancel", command=self.destroy)
        self.cancel_button.grid(row=1, column=1, padx=10, pady=10, sticky="ew")
        
        self.grab_set() # Make the popup modal
        self.focus_force()

    def _on_save(self):
        updated_notes = self.notes_textbox.get("1.0", "end-1c")
        self.save_callback(updated_notes)
        self.destroy()

class App(ctk.CTkToplevel):
    def __init__(self, master=None):
        super().__init__(master)

        self.title("🍄 AOEngine Uploader")
        self.geometry("900x800")

        # Graceful shutdown flag
        self.is_closing = False
        self.is_fetching_releases = False
        self.catbox_user_hash_value = "" # Persist hash during UI toggles

        # Initialize progress tracking
        self.progress_value = 0.0
        self.last_status_message = ""
        self.NOTES_PLACEHOLDER = "Add your release notes here..."

        self.file_paths: List[str] = []
        self.feedback_queue = queue.Queue()

        self._configure_providers()
        self._create_widgets()
        self._process_feedback_queue()

        # Load initial values from settings now that UI is ready
        self._load_settings_from_env()

        # Handle window closing
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

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
        # Catbox is always available, user_hash can be None
        self.asset_providers.append(CatboxProvider(user_hash=settings.CATBOX_USER_HASH))

    def _create_widgets(self):
        """Creates and lays out all the GUI widgets with tab-based interface."""
        # Main tabview container
        self.tabview = ctk.CTkTabview(self, width=850, height=700)
        self.tabview.pack(pady=10, padx=10, fill="both", expand=True)

        # Create tabs
        self.tabview.add("Upload")
        self.tabview.add("Manage Releases")
        self.tabview.add("Settings")

        # Apply custom styling to tabs
        self.tabview.configure(fg_color=FLY_AGARIC_BLACK,
                             border_width=2,
                             border_color=FLY_AGARIC_RED)

        # Set up Upload tab
        self._create_upload_tab()

        # Set up Manage Releases tab
        self._create_manage_releases_tab()

        # Set up Settings tab
        self._create_settings_tab()

    def _create_upload_tab(self):
        """Creates the upload tab with all main functionality."""
        upload_tab = self.tabview.tab("Upload")

        # Create a scrollable frame to contain all upload widgets
        scrollable_frame = ctk.CTkScrollableFrame(upload_tab, fg_color="transparent")
        scrollable_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # --- Asset Provider Selection ---
        provider_frame = ctk.CTkFrame(scrollable_frame, fg_color=FLY_AGARIC_BLACK,
                                    border_color=FLY_AGARIC_RED, border_width=2)
        provider_frame.pack(pady=5, padx=10, fill="x")
        ctk.CTkLabel(provider_frame, text="🍄 Asset Providers",
                    font=ctk.CTkFont(size=14, weight="bold")).pack(pady=5, padx=10, anchor="w")

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
                font=ctk.CTkFont(size=12),
                fg_color=FLY_AGARIC_RED,
                hover_color=FLY_AGARIC_WHITE
            )
            cb.pack(pady=5, padx=20, anchor="w")
            self.provider_checkboxes[cb] = provider

        # --- File Input ---
        file_frame = ctk.CTkFrame(scrollable_frame, fg_color=FLY_AGARIC_BLACK,
                                border_color=FLY_AGARIC_RED, border_width=2)
        file_frame.pack(pady=5, padx=10, fill="both", expand=True)
        ctk.CTkLabel(file_frame, text="📁 Files to Upload",
                    font=ctk.CTkFont(size=14, weight="bold")).pack(pady=5, padx=10, anchor="w")

        self.file_list_textbox = ctk.CTkTextbox(
            file_frame,
            height=100,
            state="disabled",
            fg_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_BLACK,
            border_color=FLY_AGARIC_RED,
            border_width=2
        )
        self.file_list_textbox.pack(pady=5, padx=10, fill="both", expand=True)
        self._update_file_list_display()  # Set initial placeholder

        # Enable drag and drop functionality
        self.file_list_textbox.drop_target_register(DND_FILES)
        self.file_list_textbox.dnd_bind('<<Drop>>', self._on_drop_files)

        btn_frame = ctk.CTkFrame(file_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=5)
        ctk.CTkButton(btn_frame, text="Browse Files",
                     command=self._browse_files,
                     fg_color=FLY_AGARIC_RED,
                     hover_color=FLY_AGARIC_WHITE,
                     text_color=FLY_AGARIC_WHITE).pack(side="left")
        ctk.CTkButton(btn_frame, text="Clear",
                     command=self._clear_files,
                     fg_color=FLY_AGARIC_BLACK,
                     hover_color=FLY_AGARIC_RED,
                     border_color=FLY_AGARIC_RED,
                     border_width=2).pack(side="left", padx=10)


        # --- Metadata Input ---
        metadata_frame = ctk.CTkFrame(scrollable_frame, fg_color=FLY_AGARIC_BLACK,
                                    border_color=FLY_AGARIC_RED, border_width=2)
        metadata_frame.pack(pady=5, padx=10, fill="x")

        ctk.CTkLabel(metadata_frame, text="📝 Release Version (e.g., 1.2.3)",
                    font=ctk.CTkFont(size=14, weight="bold")).pack(pady=5, padx=10, anchor="w")
        self.version_entry = ctk.CTkEntry(
            metadata_frame,
            fg_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_BLACK,
            border_color=FLY_AGARIC_RED,
            placeholder_text="Enter version (e.g., 1.2.3)"
        )
        self.version_entry.pack(pady=5, padx=10, fill="x")
        self.version_entry.bind("<KeyRelease>", self._validate_inputs)

        ctk.CTkLabel(metadata_frame, text="📝 Release Notes",
                    font=ctk.CTkFont(size=14, weight="bold")).pack(pady=5, padx=10, anchor="w")
        self.notes_textbox = ctk.CTkTextbox(
            metadata_frame,
            height=100,
            fg_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_BLACK,
            border_color=FLY_AGARIC_RED,
            border_width=2
        )
        self.notes_textbox.pack(pady=5, padx=10, fill="x")
        self.notes_textbox.insert("1.0", self.NOTES_PLACEHOLDER)
        self.notes_textbox.configure(text_color="grey")
        self.notes_textbox.bind("<FocusIn>", self._on_notes_focus_in)
        self.notes_textbox.bind("<FocusOut>", self._on_notes_focus_out)

        # --- Execution ---
        execution_frame = ctk.CTkFrame(scrollable_frame, fg_color="transparent")
        execution_frame.pack(pady=5, padx=10, fill="x")
        self.create_release_button = ctk.CTkButton(
            execution_frame, text="🚀 Create Release",
            state="disabled",
            command=self.start_release_process,
            fg_color=FLY_AGARIC_RED,
            hover_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_WHITE,
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.create_release_button.pack(pady=2, padx=10, anchor="e")

        # --- Progress Log ---
        progress_frame = ctk.CTkFrame(scrollable_frame, fg_color=FLY_AGARIC_BLACK,
                                    border_color=FLY_AGARIC_RED, border_width=2)
        progress_frame.pack(pady=5, padx=10, fill="both", expand=True)

        ctk.CTkLabel(progress_frame, text="📋 Log",
                    font=ctk.CTkFont(size=14, weight="bold")).pack(pady=5, padx=10, anchor="w")
        self.feedback_textbox = ctk.CTkTextbox(
            progress_frame,
            state="disabled",
            height=100,  # Set a larger default height
            fg_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_BLACK,
            border_color=FLY_AGARIC_RED,
            border_width=2
        )
        self.feedback_textbox.pack(pady=5, padx=10, fill="both", expand=True)

    def _create_manage_releases_tab(self):
        """Creates the tab for managing existing releases."""
        manage_tab = self.tabview.tab("Manage Releases")

        # Main frame for the tab
        main_frame = ctk.CTkFrame(manage_tab, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_rowconfigure(1, weight=1)

        # Action buttons
        action_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        action_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        self.refresh_releases_button = ctk.CTkButton(
            action_frame,
            text="🔄 Refresh Releases",
            command=self._start_fetch_releases,
            fg_color=FLY_AGARIC_RED,
            hover_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_WHITE
        )
        self.refresh_releases_button.pack(side="left")
        
        self.save_changes_button = ctk.CTkButton(
            action_frame,
            text="💾 Save Changes",
            command=self._save_release_changes,
            state="disabled",
            fg_color=FLY_AGARIC_BLACK,
            hover_color=FLY_AGARIC_RED,
            border_color=FLY_AGARIC_RED,
            border_width=2
        )
        self.save_changes_button.pack(side="right")

        # Scrollable frame for release list
        self.releases_scroll_frame = ctk.CTkScrollableFrame(
            main_frame,
            label_text="Available Releases",
            orientation="horizontal"
        )
        self.releases_scroll_frame.grid(row=1, column=0, sticky="nsew")

        self.release_widgets = [] # To hold references to the widgets for each release

    def _create_settings_tab(self):
        """Creates the settings tab with configuration options."""
        settings_tab = self.tabview.tab("Settings")

        # Create a scrollable frame to contain all settings widgets
        scrollable_frame = ctk.CTkScrollableFrame(settings_tab, fg_color="transparent")
        scrollable_frame.pack(fill="both", expand=True, padx=5, pady=5)


        # Initialize GUI settings widgets
        self.settings_widgets = {}

        # Index Configuration Section
        index_frame = ctk.CTkFrame(scrollable_frame, fg_color=FLY_AGARIC_BLACK,
                                  border_color=FLY_AGARIC_RED, border_width=2)
        index_frame.pack(pady=10, padx=10, fill="x")

        ctk.CTkLabel(index_frame, text="📁 Index Repository Configuration",
                    font=ctk.CTkFont(size=14, weight="bold")).pack(pady=5, padx=10, anchor="w")

        # Clone URL
        ctk.CTkLabel(index_frame, text="Git Clone URL:").pack(pady=2, padx=10, anchor="w")
        self.settings_widgets['index_git_clone_url'] = ctk.CTkEntry(
            index_frame,
            fg_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_BLACK,
            placeholder_text="https://github.com/YourUser/AOEngine-Manifest.git"
        )
        self.settings_widgets['index_git_clone_url'].pack(pady=2, padx=10, fill="x")

        # Branch
        ctk.CTkLabel(index_frame, text="Branch:").pack(pady=2, padx=10, anchor="w")
        self.settings_widgets['index_git_branch'] = ctk.CTkEntry(
            index_frame,
            fg_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_BLACK,
            placeholder_text="main"
        )
        self.settings_widgets['index_git_branch'].pack(pady=2, padx=10, fill="x")

        # Local Folder
        ctk.CTkLabel(index_frame, text="Local Folder Name:").pack(pady=2, padx=10, anchor="w")
        self.settings_widgets['index_git_local_folder'] = ctk.CTkEntry(
            index_frame,
            fg_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_BLACK,
            placeholder_text="_index_repo_data"
        )
        self.settings_widgets['index_git_local_folder'].pack(pady=2, padx=10, fill="x")

        # Token Settings Section
        tokens_frame = ctk.CTkFrame(scrollable_frame, fg_color=FLY_AGARIC_BLACK,
                                   border_color=FLY_AGARIC_RED, border_width=2)
        tokens_frame.pack(pady=10, padx=10, fill="x")

        ctk.CTkLabel(tokens_frame, text="🔐 Authentication Tokens",
                    font=ctk.CTkFont(size=14, weight="bold")).pack(pady=5, padx=10, anchor="w")

        # Single Token Checkbox and Field
        self.use_single_token_var = ctk.BooleanVar(value=True)
        single_token_cb = ctk.CTkCheckBox(
            tokens_frame,
            text="Use single token for both Index and Assets",
            variable=self.use_single_token_var,
            command=self._toggle_token_fields,
            fg_color=FLY_AGARIC_RED,
            hover_color=FLY_AGARIC_WHITE
        )
        single_token_cb.pack(pady=5, padx=10, anchor="w")

        ctk.CTkLabel(tokens_frame, text="GitHub Token:").pack(pady=2, padx=10, anchor="w")
        self.settings_widgets['github_token_single'] = ctk.CTkEntry(
            tokens_frame,
            show="*",
            fg_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_BLACK,
            placeholder_text="ghp_YourGitHubToken"
        )
        self.settings_widgets['github_token_single'].pack(pady=2, padx=10, fill="x")

        # Index Token (separate field)
        self.index_token_label = ctk.CTkLabel(tokens_frame, text="Index Repository Token:")
        self.settings_widgets['github_token_for_index'] = ctk.CTkEntry(
            tokens_frame,
            show="*",
            fg_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_BLACK,
            placeholder_text="ghp_IndexRepoToken"
        )

        # Assets Token (separate field)
        self.assets_token_label = ctk.CTkLabel(tokens_frame, text="Assets Repository Token:")
        self.settings_widgets['github_token_for_assets'] = ctk.CTkEntry(
            tokens_frame,
            show="*",
            fg_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_BLACK,
            placeholder_text="ghp_AssetRepoToken"
        )
        
        # Provider Settings Section
        provider_frame = ctk.CTkFrame(scrollable_frame, fg_color=FLY_AGARIC_BLACK,
                                     border_color=FLY_AGARIC_RED, border_width=2)
        provider_frame.pack(pady=10, padx=10, fill="x")

        ctk.CTkLabel(provider_frame, text="🗂️ Asset Provider Settings",
                    font=ctk.CTkFont(size=14, weight="bold")).pack(pady=5, padx=10, anchor="w")

        ctk.CTkLabel(provider_frame, text="GitHub Assets Repository:").pack(pady=2, padx=10, anchor="w")
        self.settings_widgets['github_asset_repo'] = ctk.CTkEntry(
            provider_frame,
            fg_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_BLACK,
            placeholder_text="user/assets-repo"
        )
        self.settings_widgets['github_asset_repo'].pack(pady=2, padx=10, fill="x")

        # Catbox Settings Section
        catbox_frame = ctk.CTkFrame(scrollable_frame, fg_color=FLY_AGARIC_BLACK,
                                   border_color=FLY_AGARIC_RED, border_width=2)
        catbox_frame.pack(pady=10, padx=10, fill="x")

        ctk.CTkLabel(catbox_frame, text="📦 Catbox Configuration",
                    font=ctk.CTkFont(size=14, weight="bold")).pack(pady=5, padx=10, anchor="w")

        # Anonymous upload checkbox
        self.catbox_anonymous_var = ctk.BooleanVar()
        catbox_anon_cb = ctk.CTkCheckBox(
            catbox_frame,
            text="Use anonymous uploads (no user hash required)",
            variable=self.catbox_anonymous_var,
            command=self._toggle_catbox_fields,
            fg_color=FLY_AGARIC_RED,
            hover_color=FLY_AGARIC_WHITE
        )
        catbox_anon_cb.pack(pady=5, padx=10, anchor="w")

        self.catbox_hash_label = ctk.CTkLabel(catbox_frame, text="User Hash (optional):")
        self.catbox_hash_label.pack(pady=2, padx=10, anchor="w")
        self.settings_widgets['catbox_user_hash'] = ctk.CTkEntry(
            catbox_frame,
            show="*",
            fg_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_BLACK,
            placeholder_text="Leave empty for anonymous uploads"
        )
        self.settings_widgets['catbox_user_hash'].pack(pady=2, padx=10, fill="x")

        # Action Buttons
        button_frame = ctk.CTkFrame(scrollable_frame, fg_color="transparent")
        button_frame.pack(pady=10, padx=10, fill="x")
        self.save_settings_button = ctk.CTkButton(
            button_frame,
            text="💾 Save Settings",
            command=self._save_settings,
            fg_color=FLY_AGARIC_RED,
            hover_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_WHITE
        )
        self.save_settings_button.pack(side="right", padx=5)

        self.load_settings_button = ctk.CTkButton(
            button_frame,
            text="🔄 Reload Settings",
            command=self._load_settings_from_env,
            fg_color=FLY_AGARIC_BLACK,
            hover_color=FLY_AGARIC_RED,
            border_color=FLY_AGARIC_RED,
            border_width=2
        )
        self.load_settings_button.pack(side="right", padx=5)


    def _toggle_token_fields(self):
        """Show/hide separate token fields based on checkbox."""
        use_single = self.use_single_token_var.get()
        
        # Single token field
        single_token_widget = self.settings_widgets['github_token_single']
        
        # Separate token fields
        index_label = self.index_token_label
        index_widget = self.settings_widgets['github_token_for_index']
        assets_label = self.assets_token_label
        assets_widget = self.settings_widgets['github_token_for_assets']

        if use_single:
            if not single_token_widget.winfo_ismapped():
                single_token_widget.pack(pady=2, padx=10, fill="x")
            
            index_label.pack_forget()
            index_widget.pack_forget()
            assets_label.pack_forget()
            assets_widget.pack_forget()
        else:
            single_token_widget.pack_forget()

            if not index_label.winfo_ismapped():
                index_label.pack(pady=2, padx=10, anchor="w")
                index_widget.pack(pady=2, padx=10, fill="x")
                assets_label.pack(pady=2, padx=10, anchor="w")
                assets_widget.pack(pady=2, padx=10, fill="x")

    def _toggle_catbox_fields(self):
        """Enable/disable catbox hash field based on anonymous checkbox."""
        is_anonymous = self.catbox_anonymous_var.get()
        hash_widget = self.settings_widgets['catbox_user_hash']
        
        if is_anonymous:
            current_text = hash_widget.get().strip()
            # If the field contains a real hash, store it before overwriting
            if current_text and current_text != "Anonymous upload":
                self.catbox_user_hash_value = current_text
            
            hash_widget.configure(show="")  # Make text visible
            hash_widget.delete(0, 'end')
            hash_widget.insert(0, "Anonymous upload")
            hash_widget.configure(state="disabled")
        else:
            hash_widget.configure(state="normal", show="*")  # Mask text
            hash_widget.delete(0, 'end')
            # Restore the stored hash
            hash_widget.insert(0, self.catbox_user_hash_value)

    def _save_settings(self):
        """Save current GUI settings to .env file."""
        try:
            # --- Save field values ---
            # Get token values non-destructively
            use_single_token = self.use_single_token_var.get()
            if use_single_token:
                token = self._get_entry_text('github_token_single')
                github_token_for_index = token
                github_token_for_assets = token
            else:
                github_token_for_index = self._get_entry_text('github_token_for_index')
                github_token_for_assets = self._get_entry_text('github_token_for_assets')

            # Prepare settings payload
            settings_to_save = {
                'index_git_clone_url': self._get_entry_text('index_git_clone_url'),
                'index_git_branch': self._get_entry_text('index_git_branch'),
                'index_git_local_folder': self._get_entry_text('index_git_local_folder'),
                'github_token_for_index': github_token_for_index,
                'github_asset_repo': self._get_entry_text('github_asset_repo'),
                'github_token_for_assets': github_token_for_assets,
                'ui_use_single_token': self.use_single_token_var.get(),
                'ui_catbox_anonymous': self.catbox_anonymous_var.get()
            }

            # Only add the catbox hash to the payload if anonymous is OFF.
            # If anonymous is ON, the key is omitted, and the saved value is untouched.
            if not self.catbox_anonymous_var.get():
                settings_to_save['catbox_user_hash'] = self.settings_widgets['catbox_user_hash'].get().strip()

            settings.save_settings(**settings_to_save)
            # Re-configure providers with new settings
            self._configure_providers()
            self._log_status("Settings saved successfully!")
        except Exception as e:
            logging.error(f"Failed to save settings: {e}", exc_info=True)
            self._log_status(f"ERROR: Failed to save settings: {e}")

    def _load_settings_from_env(self):
        """Load current settings into GUI fields."""
        # --- Index Repo ---
        self._set_entry_text('index_git_clone_url', settings.INDEX_GIT_CLONE_URL)
        self._set_entry_text('index_git_branch', settings.INDEX_GIT_BRANCH)
        self._set_entry_text('index_git_local_folder', settings.INDEX_GIT_LOCAL_FOLDER)
        
        # --- Tokens ---
        self._set_entry_text('github_token_for_index', settings.GITHUB_TOKEN_FOR_INDEX)
        self._set_entry_text('github_token_for_assets', settings.GITHUB_TOKEN_FOR_ASSETS)
        self._set_entry_text('github_token_single', settings.GITHUB_TOKEN_FOR_INDEX) # Default to index token
        
        # --- Asset Repo ---
        self._set_entry_text('github_asset_repo', settings.GITHUB_ASSET_REPO)
        
        # --- Catbox ---
        self.catbox_user_hash_value = settings.CATBOX_USER_HASH or ""
        catbox_widget = self.settings_widgets.get('catbox_user_hash')
        if catbox_widget:
            catbox_widget.delete(0, 'end')
            catbox_widget.insert(0, self.catbox_user_hash_value)
        
        # --- UI State ---
        self.use_single_token_var.set(settings.UI_USE_SINGLE_TOKEN)
        self.catbox_anonymous_var.set(settings.UI_CATBOX_ANONYMOUS)

        # Update UI visibility based on loaded state
        self._toggle_token_fields()
        self._toggle_catbox_fields()
        self._log_status("Settings loaded from .env file!")


    def _get_entry_text(self, widget_key):
        """Get text from a settings entry widget, return empty string if empty."""
        widget = self.settings_widgets.get(widget_key)
        return widget.get().strip() if widget else ""

    def _set_entry_text(self, widget_key, text):
        """Set text for a settings entry widget."""
        widget = self.settings_widgets.get(widget_key)
        if widget and text is not None:
            widget.delete(0, 'end')
            widget.insert(0, text)

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
            self.file_list_textbox.insert("1.0", "🐛 Drag files here or use Browse...")
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

    def _on_notes_focus_in(self, event=None):
        """Removes placeholder text on focus."""
        if self.notes_textbox.get("1.0", "end-1c").strip() == self.NOTES_PLACEHOLDER:
            self.notes_textbox.delete("1.0", "end")
            self.notes_textbox.configure(text_color=FLY_AGARIC_BLACK)

    def _on_notes_focus_out(self, event=None):
        """Adds placeholder text if entry is empty."""
        if not self.notes_textbox.get("1.0", "end-1c").strip():
            self.notes_textbox.insert("1.0", self.NOTES_PLACEHOLDER)
            self.notes_textbox.configure(text_color="grey")
    
    def _toggle_ui_elements(self, enabled: bool):
        """Enable or disable all interactive UI elements."""
        state = "normal" if enabled else "disabled"

        # Main interaction elements
        self.create_release_button.configure(state=state)
        self.version_entry.configure(state=state)
        self.notes_textbox.configure(state=state)

        # Provider checkboxes
        for cb in self.provider_checkboxes:
            cb.configure(state=state)

        # File manipulation buttons
        try:
            # These buttons are embedded in the tab structure, so we need to find them
            self._find_and_toggle_file_buttons(state)
        except Exception as e:
            logging.warning(f"Could not toggle file buttons: {e}")

    def _find_and_toggle_file_buttons(self, state):
        """Helper method to find and toggle file action buttons."""
        upload_tab = self.tabview.tab("Upload")

        # Recursively search for buttons in the upload tab
        def toggle_buttons_in_frame(frame, new_state):
            for child in frame.winfo_children():
                if isinstance(child, ctk.CTkButton) and ("Browse" in child.cget("text") or "Clear" in child.cget("text")):
                    child.configure(state=new_state)
                elif isinstance(child, ctk.CTkFrame):
                    toggle_buttons_in_frame(child, new_state)

        toggle_buttons_in_frame(upload_tab, state)

    def _log_status(self, message: str):
        """Thread-safe method to log a message to the feedback queue."""
        self.feedback_queue.put(message)

    def _process_feedback_queue(self):
        """Processes messages from the feedback queue and updates the GUI."""
        if self.is_closing:
            return

        try:
            while True:
                message = self.feedback_queue.get_nowait()
                # Check if widgets still exist before updating
                if self.feedback_textbox.winfo_exists():
                    self.feedback_textbox.configure(state="normal")
                    self.feedback_textbox.insert("end", f"{message}\n")
                    self.feedback_textbox.see("end")  # Scroll to the end
                    self.feedback_textbox.configure(state="disabled")

        except queue.Empty:
            pass
        finally:
            self.after(100, self._process_feedback_queue)

    def _on_closing(self):
        """Handle the window closing event."""
        self.is_closing = True
        self.master.destroy()  # Destroy the root window to ensure the app exits

    def start_release_process(self):
        """Starts the release workflow in a separate thread."""
        self._toggle_ui_elements(enabled=False)
        self.feedback_textbox.configure(state="normal")
        self.feedback_textbox.delete("1.0", "end")
        self.feedback_textbox.configure(state="disabled")

        self._log_status("🚀 Launching release process...")

        selected_providers = [
            provider
            for cb, provider in self.provider_checkboxes.items()
            if cb.get()
        ]

        notes_text = self.notes_textbox.get("1.0", "end-1c")
        if notes_text.strip() == self.NOTES_PLACEHOLDER:
            notes_text = ""

        workflow = ReleaseWorkflow(
            version=self.version_entry.get().strip(),
            notes=notes_text,
            file_paths=self.file_paths,
            asset_providers=selected_providers,
            index_provider=self.index_provider,
            status_callback=self._log_status,
        )

        thread = threading.Thread(target=self._run_workflow_in_thread, args=(workflow,))
        thread.daemon = True  # Ensure thread doesn't block app exit
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

    def _start_fetch_releases(self):
        """Fetches release data in a background thread."""
        if self.is_fetching_releases:
            self._log_status("A refresh is already in progress.")
            return

        self._log_status("Fetching release information...")
        self.is_fetching_releases = True
        self.refresh_releases_button.configure(state="disabled")

        thread = threading.Thread(target=self._fetch_releases_thread)
        thread.daemon = True
        thread.start()

    def _fetch_releases_thread(self):
        """The actual fetching and processing of release data."""
        try:
            versions_data = self.index_provider.get_index_content()
            
            # Use a thread pool to fetch manifest files in parallel
            with ThreadPoolExecutor(max_workers=10) as executor:
                # Create a future for each manifest URL
                future_to_version = {
                    executor.submit(self._fetch_manifest, url): version
                    for version in versions_data
                    for url in version.get("manifest_urls", {}).values()
                }

                full_release_data = []
                for future in future_to_version:
                    version_info = future_to_version[future]
                    try:
                        manifest_data = future.result()
                        # Keep data sources separate to avoid contamination
                        full_release_data.append({
                            "version_data": version_info,
                            "manifest_data": manifest_data
                        })
                    except Exception as e:
                        logging.error(f"Failed to fetch manifest for {version_info.get('version')}: {e}")

            # Schedule the UI update on the main thread
            self.after(0, self._update_releases_ui, full_release_data)

        except Exception as e:
            logging.error(f"Failed to fetch versions.json: {e}", exc_info=True)
            self._log_status(f"ERROR: Failed to fetch release index: {e}")
        finally:
            # Re-enable the refresh button and reset the flag
            self.after(0, lambda: self.refresh_releases_button.configure(state="normal"))
            self.is_fetching_releases = False

    def _fetch_manifest(self, url: str) -> dict:
        """Fetches and parses a single manifest file from a URL."""
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()

    def _update_releases_ui(self, release_data: List[dict]):
        """Clears and rebuilds the releases UI from fetched data into a table format."""
        # Clear existing widgets
        for widget_info in self.release_widgets:
            # Unpack all widgets in the row and destroy them
            for widget in widget_info.values():
                if isinstance(widget, ctk.CTkBaseClass):
                    widget.destroy()
        self.release_widgets.clear()

        if not release_data:
            # Check if a 'no releases' label already exists
            if not hasattr(self, '_no_releases_label') or not self._no_releases_label.winfo_exists():
                self._no_releases_label = ctk.CTkLabel(self.releases_scroll_frame, text="No releases found.")
                self._no_releases_label.pack(pady=10)
            return
        elif hasattr(self, '_no_releases_label') and self._no_releases_label.winfo_exists():
            self._no_releases_label.destroy()

        # Configure grid columns for the table
        self.releases_scroll_frame.grid_columnconfigure(0, weight=0, minsize=50)   # Checkbox
        self.releases_scroll_frame.grid_columnconfigure(1, weight=1, minsize=100)  # Version
        self.releases_scroll_frame.grid_columnconfigure(2, weight=2, minsize=150)  # Upload Date
        self.releases_scroll_frame.grid_columnconfigure(3, weight=1, minsize=150)  # SHA
        self.releases_scroll_frame.grid_columnconfigure(4, weight=3, minsize=200)  # Release Notes


        # Create Header
        header_font = ctk.CTkFont(weight="bold")
        headers = ["Latest", "Version", "Upload Date", "SHA256", "Release Notes"]
        for col, header_text in enumerate(headers):
            header = ctk.CTkLabel(self.releases_scroll_frame, text=header_text, font=header_font)
            header.grid(row=0, column=col, padx=10, pady=5, sticky="w")

        # Create Table Rows
        for i, release_entry in enumerate(release_data):
            row_index = i + 1  # Start after header row
            
            version_data = release_entry.get("version_data", {})
            manifest_data = release_entry.get("manifest_data", {})

            version = version_data.get("version", "N/A")
            upload_date = manifest_data.get("upload_date", "N/A")
            sha = manifest_data.get("zip_sha256", "N/A")
            is_latest = version_data.get("latest", False)
            release_notes = manifest_data.get("release_notes", "")


            # Latest Checkbox
            latest_var = ctk.BooleanVar(value=is_latest)
            checkbox = ctk.CTkCheckBox(
                self.releases_scroll_frame,
                text="",
                variable=latest_var,
                command=lambda var=latest_var: self._on_latest_checkbox_change(var),
                fg_color=FLY_AGARIC_RED
            )
            checkbox.grid(row=row_index, column=0, padx=10, pady=5)

            # Version Label (not editable)
            version_label = ctk.CTkLabel(self.releases_scroll_frame, text=version)
            version_label.grid(row=row_index, column=1, padx=10, pady=5, sticky="ew")

            # Upload Date Entry
            date_entry = ctk.CTkEntry(self.releases_scroll_frame)
            date_entry.insert(0, upload_date)
            date_entry.grid(row=row_index, column=2, padx=10, pady=5, sticky="ew")
            date_entry.bind("<KeyRelease>", self._on_widget_change)
            
            # SHA Label (not editable)
            sha_label = ctk.CTkLabel(self.releases_scroll_frame, text=sha[:12] + "...")
            sha_label.grid(row=row_index, column=3, padx=10, pady=5, sticky="ew")

            # Release Notes Button
            notes_button = ctk.CTkButton(
                self.releases_scroll_frame,
                text="Edit Notes",
                command=lambda i=i: self._open_notes_popup(i)
            )
            notes_button.grid(row=row_index, column=4, padx=10, pady=5, sticky="ew")

            # Hidden notes entry to store the value
            notes_var = ctk.StringVar(value=release_notes)


            self.release_widgets.append({
                "checkbox": checkbox,
                "version_label": version_label,
                "date_entry": date_entry,
                "sha_label": sha_label,
                "notes_button": notes_button,
                "notes_var": notes_var,
                "version_data": version_data,
                "manifest_data": manifest_data,
                "latest_var": latest_var
            })
        self._log_status("Release information updated.")
    
    def _open_notes_popup(self, index: int):
        """Opens a popup to edit the release notes for a specific release."""
        widget_info = self.release_widgets[index]
        current_notes = widget_info['notes_var'].get()

        def save_callback(new_notes):
            widget_info['notes_var'].set(new_notes)
            self._on_widget_change() # Trigger save button enablement

        NotesEditPopup(self, current_notes, save_callback)

    def _on_latest_checkbox_change(self, changed_var):
        """Ensures only one 'latest' checkbox is selected at a time."""
        # If the checkbox was checked, uncheck all others.
        if changed_var.get():
            for widget_info in self.release_widgets:
                if widget_info['latest_var'] is not changed_var:
                    widget_info['latest_var'].set(False)
        self._on_widget_change()

    def _on_widget_change(self, event=None):
        """Enables the save button when any editable widget is changed."""
        self.save_changes_button.configure(state="normal")
    
    def _save_release_changes(self):
        """Saves all changes from the 'Manage Releases' tab to versions.json and manifest files."""
        self._log_status("Saving release changes...")
        
        updated_versions_content = []
        manifests_to_update = {}

        for widget_info in self.release_widgets:
            original_version_data = widget_info['version_data']
            original_manifest_data = widget_info['manifest_data']
            version = original_version_data.get("version")

            # --- Reconstruct manifest data ---
            new_manifest_data = {
                "version": original_manifest_data.get("version"),
                "release_notes": widget_info['notes_var'].get(),
                "upload_date": widget_info['date_entry'].get(),
                "zip_sha256": original_manifest_data.get("zip_sha256") # Not editable
            }

            # Only add manifest to the update list if it has actually changed
            if new_manifest_data != original_manifest_data:
                manifests_to_update[version] = new_manifest_data

            # --- Reconstruct versions.json entry ---
            version_entry = original_version_data.copy() # Start with original data
            is_latest = widget_info['latest_var'].get()

            if is_latest:
                version_entry["latest"] = True
            else:
                # Ensure the 'latest' key is removed if the box is unchecked
                version_entry.pop("latest", None)
            
            updated_versions_content.append(version_entry)

        try:
            self.index_provider.save_all_changes(updated_versions_content, manifests_to_update)
            self._log_status("Successfully saved all changes!")
            self.save_changes_button.configure(state="disabled")
            # Refresh the data to show the latest state
            self._start_fetch_releases()
        except Exception as e:
            logging.error(f"Failed to save changes: {e}", exc_info=True)
            self._log_status(f"ERROR: Failed to save changes: {e}")
