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
from ..utils.logging import log_queue, log_history
from shared.localization import init_translator, get_translator

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

        self.title(get_translator().get("edit_release_notes_title"))
        self.geometry("500x400")
        self.save_callback = save_callback

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.notes_textbox = ctk.CTkTextbox(self, wrap="word", height=300)
        self.notes_textbox.grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky="nsew")
        self.notes_textbox.insert("1.0", current_notes)

        self.save_button = ctk.CTkButton(self, text=get_translator().get("save_button"), command=self._on_save)
        self.save_button.grid(row=1, column=0, padx=10, pady=10, sticky="ew")
        
        self.cancel_button = ctk.CTkButton(self, text=get_translator().get("cancel_button"), command=self.destroy)
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

        # --- Localization ---
        self.translator = init_translator("uploader/locale", settings.UI_LANGUAGE)

        self.title(self.translator.get("app_title"))
        self.geometry("900x800")

        # Graceful shutdown flag
        self.is_closing = False
        self.is_fetching_releases = False
        self.catbox_user_hash_value = "" # Persist hash during UI toggles
        self.NOTES_PLACEHOLDER = self.translator.get("notes_placeholder")

        # Initialize progress tracking
        self.progress_value = 0.0
        self.last_status_message = ""

        self.file_paths: List[str] = []
        self.feedback_queue = queue.Queue()

        self._configure_providers()
        self._create_widgets()
        self._update_ui_text() # Set initial text
        self._process_feedback_queue()

        # Load initial values from settings now that UI is ready
        self._load_settings_from_env()

        # Handle window closing
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        self.console_window = None
        self.after(100, self._process_log_queue)

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
        self.tabview.add("upload")
        self.tabview.add("manage_releases")
        self.tabview.add("settings")
        self.tabview.add("info")

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

        # Set up Info tab
        self._create_info_tab()

    def _create_upload_tab(self):
        """Creates the upload tab with all main functionality."""
        upload_tab = self.tabview.tab("upload")

        # Create a scrollable frame to contain all upload widgets
        scrollable_frame = ctk.CTkScrollableFrame(upload_tab, fg_color="transparent")
        scrollable_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # --- Asset Provider Selection ---
        provider_frame = ctk.CTkFrame(scrollable_frame, fg_color=FLY_AGARIC_BLACK,
                                    border_color=FLY_AGARIC_RED, border_width=2)
        provider_frame.pack(pady=5, padx=10, fill="x")
        self.provider_frame_label = ctk.CTkLabel(provider_frame, text=self.translator.get("asset_providers_label"),
                    font=ctk.CTkFont(size=14, weight="bold"))
        self.provider_frame_label.pack(pady=5, padx=10, anchor="w")

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
        self.files_to_upload_label = ctk.CTkLabel(file_frame, text=self.translator.get("files_to_upload_label"),
                    font=ctk.CTkFont(size=14, weight="bold"))
        self.files_to_upload_label.pack(pady=5, padx=10, anchor="w")

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
        self.browse_files_button = ctk.CTkButton(btn_frame, text=self.translator.get("browse_files_button"),
                     command=self._browse_files,
                     fg_color=FLY_AGARIC_RED,
                     hover_color=FLY_AGARIC_WHITE,
                     text_color=FLY_AGARIC_WHITE)
        self.browse_files_button.pack(side="left")
        self.clear_button = ctk.CTkButton(btn_frame, text=self.translator.get("clear_button"),
                     command=self._clear_files,
                     fg_color=FLY_AGARIC_BLACK,
                     hover_color=FLY_AGARIC_RED,
                     border_color=FLY_AGARIC_RED,
                     border_width=2)
        self.clear_button.pack(side="left", padx=10)


        # --- Metadata Input ---
        metadata_frame = ctk.CTkFrame(scrollable_frame, fg_color=FLY_AGARIC_BLACK,
                                    border_color=FLY_AGARIC_RED, border_width=2)
        metadata_frame.pack(pady=5, padx=10, fill="x")

        self.release_version_label = ctk.CTkLabel(metadata_frame, text=self.translator.get("release_version_label"),
                    font=ctk.CTkFont(size=14, weight="bold"))
        self.release_version_label.pack(pady=5, padx=10, anchor="w")
        self.version_entry = ctk.CTkEntry(
            metadata_frame,
            fg_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_BLACK,
            border_color=FLY_AGARIC_RED,
            placeholder_text=self.translator.get("release_version_placeholder")
        )
        self.version_entry.pack(pady=5, padx=10, fill="x")
        self.version_entry.bind("<KeyRelease>", self._validate_inputs)

        self.profiler_checkbox = ctk.CTkCheckBox(
            metadata_frame,
            text=self.translator.get("profiler_build_checkbox"),
            fg_color=FLY_AGARIC_RED,
            hover_color=FLY_AGARIC_WHITE
        )
        self.profiler_checkbox.pack(pady=5, padx=10, anchor="w")

        release_notes_frame = ctk.CTkFrame(metadata_frame, fg_color="transparent")
        release_notes_frame.pack(fill="x", padx=10, pady=5)
        
        self.release_notes_label = ctk.CTkLabel(release_notes_frame, text=self.translator.get("release_notes_label"),
                    font=ctk.CTkFont(size=14, weight="bold"))
        self.release_notes_label.pack(side="left")

        self.edit_in_new_window_button = ctk.CTkButton(release_notes_frame, text=self.translator.get("edit_in_new_window_button"),
                     command=self._open_upload_notes_popup,
                     fg_color=FLY_AGARIC_BLACK,
                     hover_color=FLY_AGARIC_RED,
                     border_color=FLY_AGARIC_RED,
                     border_width=2)
        self.edit_in_new_window_button.pack(side="right")

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
            execution_frame, text=self.translator.get("create_release_button"),
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

        log_header_frame = ctk.CTkFrame(progress_frame, fg_color="transparent")
        log_header_frame.pack(fill="x", padx=10, pady=5)

        self.log_label = ctk.CTkLabel(log_header_frame, text=self.translator.get("log_label"),
                    font=ctk.CTkFont(size=14, weight="bold"))
        self.log_label.pack(side="left", anchor="w")
        
        self.open_in_new_window_button = ctk.CTkButton(log_header_frame, text=self.translator.get("open_in_new_window_button"),
                     command=self._open_console_window,
                     fg_color=FLY_AGARIC_BLACK,
                     hover_color=FLY_AGARIC_RED,
                     border_color=FLY_AGARIC_RED,
                     border_width=2)
        self.open_in_new_window_button.pack(side="right")

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
        manage_tab = self.tabview.tab("manage_releases")

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
            text=self.translator.get("refresh_releases_button"),
            command=self._start_fetch_releases,
            fg_color=FLY_AGARIC_RED,
            hover_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_WHITE
        )
        self.refresh_releases_button.pack(side="left")
        
        self.save_changes_button = ctk.CTkButton(
            action_frame,
            text=self.translator.get("save_changes_button"),
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
            label_text=self.translator.get("available_releases_label"),
            orientation="horizontal"
        )
        self.releases_scroll_frame.grid(row=1, column=0, sticky="nsew")

        self.release_widgets = [] # To hold references to the widgets for each release
        self.header_labels = []  # Initialize header labels list

    def _create_settings_tab(self):
        """Creates the settings tab with configuration options."""
        settings_tab = self.tabview.tab("settings")

        # Create a scrollable frame to contain all settings widgets
        scrollable_frame = ctk.CTkScrollableFrame(settings_tab, fg_color="transparent")
        scrollable_frame.pack(fill="both", expand=True, padx=5, pady=5)


        # Initialize GUI settings widgets
        self.settings_widgets = {}

        # Index Configuration Section
        index_frame = ctk.CTkFrame(scrollable_frame, fg_color=FLY_AGARIC_BLACK,
                                  border_color=FLY_AGARIC_RED, border_width=2)
        index_frame.pack(pady=10, padx=10, fill="x")

        self.index_repo_config_label = ctk.CTkLabel(index_frame, text=self.translator.get("index_repo_config_label"),
                    font=ctk.CTkFont(size=14, weight="bold"))
        self.index_repo_config_label.pack(pady=5, padx=10, anchor="w")

        # Clone URL
        self.git_clone_url_label = ctk.CTkLabel(index_frame, text=self.translator.get("git_clone_url_label"))
        self.git_clone_url_label.pack(pady=2, padx=10, anchor="w")
        self.settings_widgets['index_git_clone_url'] = ctk.CTkEntry(
            index_frame,
            fg_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_BLACK,
            placeholder_text="https://github.com/YourUser/AOEngine-Manifest.git"
        )
        self.settings_widgets['index_git_clone_url'].pack(pady=2, padx=10, fill="x")

        # Branch
        self.branch_label = ctk.CTkLabel(index_frame, text=self.translator.get("branch_label"))
        self.branch_label.pack(pady=2, padx=10, anchor="w")
        self.settings_widgets['index_git_branch'] = ctk.CTkEntry(
            index_frame,
            fg_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_BLACK,
            placeholder_text="main"
        )
        self.settings_widgets['index_git_branch'].pack(pady=2, padx=10, fill="x")

        # Local Folder
        self.local_folder_label = ctk.CTkLabel(index_frame, text=self.translator.get("local_folder_label"))
        self.local_folder_label.pack(pady=2, padx=10, anchor="w")
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

        self.auth_tokens_label = ctk.CTkLabel(tokens_frame, text=self.translator.get("auth_tokens_label"),
                    font=ctk.CTkFont(size=14, weight="bold"))
        self.auth_tokens_label.pack(pady=5, padx=10, anchor="w")

        # Single Token Checkbox and Field
        self.use_single_token_var = ctk.BooleanVar(value=True)
        self.use_single_token_checkbox = ctk.CTkCheckBox(
            tokens_frame,
            text=self.translator.get("use_single_token_checkbox"),
            variable=self.use_single_token_var,
            command=self._toggle_token_fields,
            fg_color=FLY_AGARIC_RED,
            hover_color=FLY_AGARIC_WHITE
        )
        self.use_single_token_checkbox.pack(pady=5, padx=10, anchor="w")

        self.github_token_label = ctk.CTkLabel(tokens_frame, text=self.translator.get("github_token_label"))
        self.github_token_label.pack(pady=2, padx=10, anchor="w")
        self.settings_widgets['github_token_single'] = ctk.CTkEntry(
            tokens_frame,
            show="*",
            fg_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_BLACK,
            placeholder_text="ghp_YourGitHubToken"
        )
        self.settings_widgets['github_token_single'].pack(pady=2, padx=10, fill="x")

        # Index Token (separate field)
        self.index_token_label = ctk.CTkLabel(tokens_frame, text=self.translator.get("index_repo_token_label"))
        self.settings_widgets['github_token_for_index'] = ctk.CTkEntry(
            tokens_frame,
            show="*",
            fg_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_BLACK,
            placeholder_text="ghp_IndexRepoToken"
        )

        # Assets Token (separate field)
        self.assets_token_label = ctk.CTkLabel(tokens_frame, text=self.translator.get("assets_repo_token_label"))
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

        self.asset_provider_settings_label = ctk.CTkLabel(provider_frame, text=self.translator.get("asset_provider_settings_label"),
                    font=ctk.CTkFont(size=14, weight="bold"))
        self.asset_provider_settings_label.pack(pady=5, padx=10, anchor="w")

        self.github_assets_repo_label = ctk.CTkLabel(provider_frame, text=self.translator.get("github_assets_repo_label"))
        self.github_assets_repo_label.pack(pady=2, padx=10, anchor="w")
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

        self.catbox_config_label = ctk.CTkLabel(catbox_frame, text=self.translator.get("catbox_config_label"),
                    font=ctk.CTkFont(size=14, weight="bold"))
        self.catbox_config_label.pack(pady=5, padx=10, anchor="w")

        # Anonymous upload checkbox
        self.catbox_anonymous_var = ctk.BooleanVar()
        self.catbox_anonymous_checkbox = ctk.CTkCheckBox(
            catbox_frame,
            text=self.translator.get("catbox_anonymous_checkbox"),
            variable=self.catbox_anonymous_var,
            command=self._toggle_catbox_fields,
            fg_color=FLY_AGARIC_RED,
            hover_color=FLY_AGARIC_WHITE
        )
        self.catbox_anonymous_checkbox.pack(pady=5, padx=10, anchor="w")

        self.catbox_hash_label = ctk.CTkLabel(catbox_frame, text=self.translator.get("catbox_user_hash_label"))
        self.catbox_hash_label.pack(pady=2, padx=10, anchor="w")
        self.settings_widgets['catbox_user_hash'] = ctk.CTkEntry(
            catbox_frame,
            show="*",
            fg_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_BLACK,
            placeholder_text=self.translator.get('catbox_user_hash_placeholder') if hasattr(self, 'translator') else 'Leave empty for anonymous uploads'
        )
        self.settings_widgets['catbox_user_hash'].pack(pady=2, padx=10, fill="x")

        # --- Language Switcher ---
        language_frame = ctk.CTkFrame(scrollable_frame, fg_color="transparent")
        language_frame.pack(pady=5, padx=10, fill="x", anchor="w")

        self.language_label = ctk.CTkLabel(language_frame, text=self.translator.get("language_switcher_label"))
        self.language_label.pack(side="left", padx=(0, 10))

        self.language_option_menu = ctk.CTkOptionMenu(language_frame,
                                                     values=["en", "ru"],
                                                     command=self._on_language_select)
        self.language_option_menu.set(self.translator.current_lang)
        self.language_option_menu.pack(side="left")

        # Action Buttons
        button_frame = ctk.CTkFrame(scrollable_frame, fg_color="transparent")
        button_frame.pack(pady=10, padx=10, fill="x")
        self.save_settings_button = ctk.CTkButton(
            button_frame,
            text=self.translator.get("save_settings_button"),
            command=self._save_settings,
            fg_color=FLY_AGARIC_RED,
            hover_color=FLY_AGARIC_WHITE,
            text_color=FLY_AGARIC_WHITE
        )
        self.save_settings_button.pack(side="right", padx=5)

        self.load_settings_button = ctk.CTkButton(
            button_frame,
            text=self.translator.get("reload_settings_button"),
            command=self._load_settings_from_env,
            fg_color=FLY_AGARIC_BLACK,
            hover_color=FLY_AGARIC_RED,
            border_color=FLY_AGARIC_RED,
            border_width=2
        )
        self.load_settings_button.pack(side="right", padx=5)

    def _create_info_tab(self):
        """Creates the info tab with application details."""
        info_tab = self.tabview.tab("info")

        # Create a scrollable frame to contain all settings widgets
        scrollable_frame = ctk.CTkScrollableFrame(info_tab, fg_color="transparent")
        scrollable_frame.pack(fill="both", expand=True, padx=5, pady=5)

        main_frame = ctk.CTkFrame(scrollable_frame, fg_color=FLY_AGARIC_BLACK,
                                  border_color=FLY_AGARIC_RED, border_width=2)
        main_frame.pack(pady=10, padx=10, fill="x")
        main_frame.grid_columnconfigure(0, weight=1)

        # App Description
        self.uploader_description_label = ctk.CTkLabel(main_frame, text=self.translator.get("uploader_description"), wraplength=780, justify="left")
        self.uploader_description_label.grid(row=0, column=0, padx=15, pady=10, sticky="ew")

        # Creator Info
        self.creator_label = ctk.CTkLabel(main_frame, text=f"{self.translator.get('creator_label')}: Mirrowel", justify="left")
        self.creator_label.grid(row=1, column=0, padx=15, pady=5, sticky="ew")

        # GitHub Link
        self.github_link = ctk.CTkLabel(main_frame, text=self.translator.get('github_link_label'), text_color="#6495ED", cursor="hand2")
        self.github_link.grid(row=2, column=0, padx=15, pady=5, sticky="ew")
        self.github_link.bind("<Button-1>", lambda e: self._open_link("https://github.com/Mirrowel"))

        # Discord Link
        self.discord_link = ctk.CTkLabel(main_frame, text=self.translator.get('discord_link_label'), text_color="#7289DA", cursor="hand2")
        self.discord_link.grid(row=3, column=0, padx=15, pady=5, sticky="ew")
        self.discord_link.bind("<Button-1>", lambda e: self._open_link("https://discord.gg/8MY5gn3gRC"))

    def _open_link(self, url):
        import webbrowser
        webbrowser.open_new(url)

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
            if current_text != self.translator.get("catbox_anonymous_upload_text"):
                self.catbox_user_hash_value = current_text
            
            hash_widget.configure(show="")  # Make text visible
            hash_widget.delete(0, 'end')
            hash_widget.insert(0, self.translator.get("catbox_anonymous_upload_text"))
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
            
            settings_to_save['ui_language'] = self.language_option_menu.get()
    
            settings.save_settings(**settings_to_save)
            # Re-configure providers with new settings
            self._configure_providers()
            self._log_status(self.translator.get("settings_saved_successfully"))
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
        self._log_status(self.translator.get("settings_loaded_from_file"))


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
            self.file_list_textbox.insert("1.0", self.translator.get("file_list_placeholder"))
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
        upload_tab = self.tabview.tab("upload")

        # Recursively search for buttons in the upload tab
        def toggle_buttons_in_frame(frame, new_state):
            for child in frame.winfo_children():
                if isinstance(child, ctk.CTkButton) and ("Browse" in child.cget("text") or "Clear" in child.cget("text")):
                    child.configure(state=new_state)
                elif isinstance(child, ctk.CTkFrame):
                    toggle_buttons_in_frame(child, new_state)

        toggle_buttons_in_frame(upload_tab, state)

    def _open_console_window(self):
        if self.console_window is None or not self.console_window.winfo_exists():
            self.console_window = ConsoleWindow(self)
        else:
            self.console_window.focus()
    
    def _open_upload_notes_popup(self):
        """Opens a popup to edit the release notes."""
        current_notes = self.notes_textbox.get("1.0", "end-1c")
        if current_notes.strip() == self.NOTES_PLACEHOLDER:
            current_notes = ""

        def save_callback(new_notes):
            self.notes_textbox.delete("1.0", "end")
            self.notes_textbox.insert("1.0", new_notes)
            if not new_notes.strip():
                self._on_notes_focus_out() # Restore placeholder if empty
            else:
                self.notes_textbox.configure(text_color=FLY_AGARIC_BLACK)

        NotesEditPopup(self, current_notes, save_callback)

    def _log_status(self, message: str):
        """Thread-safe method to log a message to the feedback queue."""
        logging.info(message)
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

        self._log_status(self.translator.get("launching_release_process"))

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
            profiler=self.profiler_checkbox.get(),
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
            self._log_status(self.translator.get("error_unexpected", error=str(e)))
        finally:
            # Schedule the UI update to run in the main thread
            self.after(0, self._toggle_ui_elements, True)

    def _start_fetch_releases(self):
        """Fetches release data in a background thread."""
        if self.is_fetching_releases:
            self._log_status(self.translator.get("status_refresh_in_progress"))
            return

        self._log_status(self.translator.get("status_fetching_releases"))
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
            self._log_status(self.translator.get("error_failed_to_fetch", error=str(e)))
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
                self._no_releases_label = ctk.CTkLabel(self.releases_scroll_frame, text=self.translator.get("no_releases_found"))
                self._no_releases_label.pack(pady=10)
            return
        elif hasattr(self, '_no_releases_label') and self._no_releases_label.winfo_exists():
            self._no_releases_label.destroy()

        # Configure grid columns for the table
        self.releases_scroll_frame.grid_columnconfigure(0, weight=0, minsize=50)   # Checkbox
        self.releases_scroll_frame.grid_columnconfigure(1, weight=0, minsize=50)   # Profiler
        self.releases_scroll_frame.grid_columnconfigure(2, weight=1, minsize=100)  # Version
        self.releases_scroll_frame.grid_columnconfigure(3, weight=2, minsize=150)  # Upload Date
        self.releases_scroll_frame.grid_columnconfigure(4, weight=1, minsize=150)  # SHA
        self.releases_scroll_frame.grid_columnconfigure(5, weight=3, minsize=200)  # Release Notes


        # Create Header
        self.header_labels = []
        header_font = ctk.CTkFont(weight="bold")
        headers = [
            self.translator.get("header_latest"),
            self.translator.get("header_profiler"),
            self.translator.get("header_version"),
            self.translator.get("header_upload_date"),
            self.translator.get("header_sha256"),
            self.translator.get("header_release_notes")
        ]
        for col, header_text in enumerate(headers):
            header = ctk.CTkLabel(self.releases_scroll_frame, text=header_text, font=header_font)
            header.grid(row=0, column=col, padx=10, pady=5, sticky="w")
            self.header_labels.append(header)

        # Create Table Rows
        for i, release_entry in enumerate(release_data):
            row_index = i + 1  # Start after header row
            
            version_data = release_entry.get("version_data", {})
            manifest_data = release_entry.get("manifest_data", {})

            version = version_data.get("version", "N/A")
            upload_date = manifest_data.get("upload_date", "N/A")
            sha = manifest_data.get("archive_sha256", "N/A")
            is_latest = version_data.get("latest", False)
            is_profiler = manifest_data.get("profiler", False)
            release_notes = manifest_data.get("release_notes", "")


            # Latest Checkbox
            latest_var = ctk.BooleanVar(value=is_latest)
            latest_checkbox = ctk.CTkCheckBox(
                self.releases_scroll_frame,
                text="",
                variable=latest_var,
                command=lambda var=latest_var: self._on_latest_checkbox_change(var),
                fg_color=FLY_AGARIC_RED
            )
            latest_checkbox.grid(row=row_index, column=0, padx=10, pady=5)
            
            # Profiler Checkbox
            profiler_var = ctk.BooleanVar(value=is_profiler)
            profiler_checkbox = ctk.CTkCheckBox(
                self.releases_scroll_frame,
                text="",
                variable=profiler_var,
                command=self._on_widget_change,
                fg_color=FLY_AGARIC_RED
            )
            profiler_checkbox.grid(row=row_index, column=1, padx=10, pady=5)

            # Version Label (not editable)
            version_label = ctk.CTkLabel(self.releases_scroll_frame, text=version)
            version_label.grid(row=row_index, column=2, padx=10, pady=5, sticky="ew")

            # Upload Date Entry
            date_entry = ctk.CTkEntry(self.releases_scroll_frame)
            date_entry.insert(0, upload_date)
            date_entry.grid(row=row_index, column=3, padx=10, pady=5, sticky="ew")
            date_entry.bind("<KeyRelease>", self._on_widget_change)
            
            # SHA Label (not editable)
            sha_label = ctk.CTkLabel(self.releases_scroll_frame, text=sha[:12] + "...")
            sha_label.grid(row=row_index, column=4, padx=10, pady=5, sticky="ew")

            # Release Notes Button
            notes_button = ctk.CTkButton(
                self.releases_scroll_frame,
                text=self.translator.get("edit_notes_button"),
                command=lambda i=i: self._open_notes_popup(i)
            )
            notes_button.grid(row=row_index, column=5, padx=10, pady=5, sticky="ew")

            # Hidden notes entry to store the value
            notes_var = ctk.StringVar(value=release_notes)


            self.release_widgets.append({
                "latest_checkbox": latest_checkbox,
                "profiler_checkbox": profiler_checkbox,
                "version_label": version_label,
                "date_entry": date_entry,
                "sha_label": sha_label,
                "notes_button": notes_button,
                "notes_var": notes_var,
                "version_data": version_data,
                "manifest_data": manifest_data,
                "latest_var": latest_var,
                "profiler_var": profiler_var,
            })
        self._log_status(self.translator.get("status_release_info_updated"))
    
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
                "archive_sha256": original_manifest_data.get("archive_sha256"), # Not editable
                "files": original_manifest_data.get("files", []), # Preserve the files list
                "profiler": widget_info['profiler_var'].get(),
            }

            # Only add manifest to the update list if it has actually changed
            if new_manifest_data != original_manifest_data:
                manifests_to_update[version] = new_manifest_data

            # --- Reconstruct versions.json entry ---
            version_entry = original_version_data.copy() # Start with original data
            is_latest = widget_info['latest_var'].get()
            is_profiler = widget_info['profiler_var'].get()

            if is_latest and not is_profiler:
                version_entry["latest"] = True
            else:
                # Ensure the 'latest' key is removed if the box is unchecked or it's a profiler build
                version_entry.pop("latest", None)
            
            # Update profiler status in versions.json as well
            version_entry["profiler"] = is_profiler

            updated_versions_content.append(version_entry)

        try:
            self.index_provider.save_all_changes(updated_versions_content, manifests_to_update)
            self._log_status("Successfully saved all changes!")
            self.save_changes_button.configure(state="disabled")
            # Refresh the data to show the latest state
            self._start_fetch_releases()
        except Exception as e:
            logging.error(f"Failed to save changes: {e}", exc_info=True)
            self._log_status(self.translator.get("error_failed_to_save", error=str(e)))


    def _on_language_select(self, language: str):
        """Sets the language and updates the UI."""
        self.translator.set_language(language)
        settings.UI_LANGUAGE = language
        settings.save_settings(ui_language=language)
        self._update_ui_text()

    def _update_ui_text(self):
        """Updates all text in the UI to the current language."""
        self.title(self.translator.get("app_title"))

        # Update tab names by accessing the internal segmented button
        try:
            segmented_button = self.tabview._segmented_button
            buttons = segmented_button._buttons_dict
            if "upload" in buttons:
                buttons["upload"].configure(text=self.translator.get("upload_tab"))
            if "manage_releases" in buttons:
                buttons["manage_releases"].configure(text=self.translator.get("manage_releases_tab"))
            if "settings" in buttons:
                buttons["settings"].configure(text=self.translator.get("settings_tab"))
            if "info" in buttons:
                buttons["info"].configure(text=self.translator.get("info_tab"))
        except (AttributeError, KeyError) as e:
            logging.warning(f"Could not update tab names: {e}")

        self._update_upload_tab_text()
        self._update_manage_releases_tab_text()
        self._update_settings_tab_text()
        self._update_info_tab_text()

    def _update_upload_tab_text(self):
        self.provider_frame_label.configure(text=self.translator.get("asset_providers_label"))
        self.files_to_upload_label.configure(text=self.translator.get("files_to_upload_label"))
        self.browse_files_button.configure(text=self.translator.get("browse_files_button"))
        self.clear_button.configure(text=self.translator.get("clear_button"))
        self.release_version_label.configure(text=self.translator.get("release_version_label"))
        self.version_entry.configure(placeholder_text=self.translator.get("release_version_placeholder"))
        self.profiler_checkbox.configure(text=self.translator.get("profiler_build_checkbox"))
        self.release_notes_label.configure(text=self.translator.get("release_notes_label"))
        self.edit_in_new_window_button.configure(text=self.translator.get("edit_in_new_window_button"))
        self.create_release_button.configure(text=self.translator.get("create_release_button"))
        self.log_label.configure(text=self.translator.get("log_label"))
        self.open_in_new_window_button.configure(text=self.translator.get("open_in_new_window_button"))

        self.file_list_textbox.configure(state="normal")
        self.file_list_textbox.delete("1.0", "end")
        if not self.file_paths:
            self.file_list_textbox.insert("1.0", self.translator.get("file_list_placeholder"))
        self.file_list_textbox.configure(state="disabled")
        
        if self.notes_textbox.get("1.0", "end-1c").strip() == self.NOTES_PLACEHOLDER:
            self.notes_textbox.delete("1.0", "end")
            self.notes_textbox.insert("1.0", self.translator.get("notes_placeholder"))

    def _update_manage_releases_tab_text(self):
        if hasattr(self, 'refresh_releases_button'):
            self.refresh_releases_button.configure(text=self.translator.get("refresh_releases_button"))
        if hasattr(self, 'save_changes_button'):
            self.save_changes_button.configure(text=self.translator.get("save_changes_button"))
        if hasattr(self, 'releases_scroll_frame'):
            self.releases_scroll_frame.configure(label_text=self.translator.get("available_releases_label"))
        
        headers = [
            self.translator.get("header_latest"),
            self.translator.get("header_profiler"),
            self.translator.get("header_version"),
            self.translator.get("header_upload_date"),
            self.translator.get("header_sha256"),
            self.translator.get("header_release_notes")
        ]
        for col, header_text in enumerate(headers):
            if col < len(self.header_labels):
                self.header_labels[col].configure(text=header_text)
            
        for widget_info in self.release_widgets:
            widget_info['notes_button'].configure(text=self.translator.get("edit_notes_button"))

    def _update_settings_tab_text(self):
        if hasattr(self, 'index_repo_config_label'):
            self.index_repo_config_label.configure(text=self.translator.get("index_repo_config_label"))
        if hasattr(self, 'git_clone_url_label'):
            self.git_clone_url_label.configure(text=self.translator.get("git_clone_url_label"))
        if hasattr(self, 'branch_label'):
            self.branch_label.configure(text=self.translator.get("branch_label"))
        if hasattr(self, 'local_folder_label'):
            self.local_folder_label.configure(text=self.translator.get("local_folder_label"))
        if hasattr(self, 'auth_tokens_label'):
            self.auth_tokens_label.configure(text=self.translator.get("auth_tokens_label"))
        if hasattr(self, 'use_single_token_checkbox'):
            self.use_single_token_checkbox.configure(text=self.translator.get("use_single_token_checkbox"))
        if hasattr(self, 'github_token_label'):
            self.github_token_label.configure(text=self.translator.get("github_token_label"))
        if hasattr(self, 'index_token_label'):
            self.index_token_label.configure(text=self.translator.get("index_repo_token_label"))
        if hasattr(self, 'assets_token_label'):
            self.assets_token_label.configure(text=self.translator.get("assets_repo_token_label"))
        if hasattr(self, 'asset_provider_settings_label'):
            self.asset_provider_settings_label.configure(text=self.translator.get("asset_provider_settings_label"))
        if hasattr(self, 'github_assets_repo_label'):
            self.github_assets_repo_label.configure(text=self.translator.get("github_assets_repo_label"))
        if hasattr(self, 'catbox_config_label'):
            self.catbox_config_label.configure(text=self.translator.get("catbox_config_label"))
        if hasattr(self, 'catbox_anonymous_checkbox'):
            self.catbox_anonymous_checkbox.configure(text=self.translator.get("catbox_anonymous_checkbox"))
        if hasattr(self, 'catbox_hash_label'):
            self.catbox_hash_label.configure(text=self.translator.get("catbox_user_hash_label"))
        if hasattr(self, 'save_settings_button'):
            self.save_settings_button.configure(text=self.translator.get("save_settings_button"))
        if hasattr(self, 'load_settings_button'):
            self.load_settings_button.configure(text=self.translator.get("reload_settings_button"))
        if hasattr(self, 'language_label'):
            self.language_label.configure(text=self.translator.get("language_switcher_label"))
        if hasattr(self, 'settings_widgets') and 'catbox_user_hash' in self.settings_widgets: self.settings_widgets['catbox_user_hash'].configure(placeholder_text=self.translator.get("catbox_user_hash_placeholder"))

    def _update_info_tab_text(self):
        """Updates all text in the info tab to the current language."""
        if hasattr(self, 'uploader_description_label'):
            self.uploader_description_label.configure(text=self.translator.get("uploader_description"))
        if hasattr(self, 'creator_label'):
            self.creator_label.configure(text=f"{self.translator.get('creator_label')}: Mirrowel")
        if hasattr(self, 'github_link'):
            self.github_link.configure(text=self.translator.get('github_link_label'))
        if hasattr(self, 'discord_link'):
            self.discord_link.configure(text=self.translator.get('discord_link_label'))


class ConsoleWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title(get_translator().get("console_window_title"))
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

        self._load_history()

    def _load_history(self):
        """Loads the existing log history into the textbox."""
        self.log_textbox.configure(state="normal")
        for message in log_history:
            self.log_textbox.insert("end", message + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def log(self, message: str):
        """Appends a message to the log display."""
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", message + "\n")
        self.log_textbox.see("end") # Scroll to the end
        self.log_textbox.configure(state="disabled")
