# AOEngine Release Uploader

## 1. Overview

The AOEngine Release Uploader is a comprehensive, developer-only Python GUI designed to automate and manage the entire software release lifecycle. It provides a robust interface for packaging files, uploading them to multiple hosting providers in parallel, and maintaining a central, version-controlled index of all releases.

The application extends beyond simple uploading, offering a full suite of tools for managing existing releases and configuring application settings directly within the UI.

### 1.1. Core Architectural Concepts

-   **Separation of Concerns**: The architecture is built on a clear distinction between two provider types:
    -   **Index Provider (`GitHubGitProvider`)**: A single, non-negotiable provider that manages the version index (`versions.json`) and canonical release manifests (`manifest-vX.Y.Z.json`) within a dedicated Git repository. This ensures atomic, version-controlled updates for all critical metadata.
    -   **Asset Providers (`GitHubReleaseProvider`, `CatboxProvider`)**: A selectable list of providers for hosting large binary assets (e.g., `.zip` archives). This allows for redundancy and flexibility in asset storage.
-   **Canonical Manifests**: The manifest file for each release is committed directly to the index repository. This Git-hosted version is considered the **canonical source of truth** for the release's metadata. Copies are also uploaded to asset providers as mirrors, but the index repository's version is primary.
-   **Thread-Safe Operations**: All long-running operations, such as file uploads and release data fetching, are executed in background threads to keep the UI responsive. A queue-based system is used to safely pass status updates from the backend to the GUI.

## 2. The User Interface

The application features a modern, tab-based interface for a clear and organized user experience.

### 2.1. Upload Tab

This is the primary tab for creating new releases.

-   **Asset Provider Selection**: A series of checkboxes allows the user to select which hosting platforms will receive the release assets. The "Create Release" button is disabled until at least one provider is selected.
-   **File Input**: A drag-and-drop area for adding the raw release files (e.g., `.exe`, `.dll`, `.pdb`). A list view displays the added files and a "Clear" button removes them, "Browse" allows for file selection.
-   **Metadata Input**:
    -   **Release Version**: A text field for the version number (e.g., `1.2.3`).
    -   **Release Notes**: A multi-line text area for detailing the changes in the release.
-   **Execution**: A "Create Release" button that initiates the automated workflow.
-   **Feedback**: A read-only progress log provides real-time status updates, from initial file packaging to the final success or failure of each upload and the index update.

### 2.2. Manage Releases Tab

This tab provides a powerful interface for viewing and editing existing releases.

-   **Release Table**: Displays a sortable, filterable list of all releases fetched from the `versions.json` index.
-   **Data Fetching**: Fetches manifest data in parallel to populate the table with detailed information like upload dates, SHAs, and release notes.
-   **Editing Capabilities**:
    -   **Set "Latest"**: A dedicated checkbox column to mark a specific release as the latest version. Only one release can be "latest" at a time.
    -   **Edit Metadata**: Modify the release notes and upload date for any version via a popup editor.
-   **Atomic Saves**: A "Save Changes" button commits all modifications to both the `versions.json` file and the corresponding manifest files in a single, atomic Git commit, ensuring data consistency.

### 2.3. Settings Tab

This tab allows for direct configuration of the application, with changes saved to the `.env` file.

-   **Index Repository Configuration**: Set the Git Clone URL, branch, and local folder for the index repository.
-   **Authentication Tokens**:
    -   Configure GitHub tokens for the index and asset repositories.
    -   Option to use a single token for both.
-   **Asset Provider Settings**:
    -   Set the GitHub repository slug for releases.
    -   Configure the Catbox user hash or enable anonymous uploads.
-   **Save/Reload**: Buttons to save the current settings to the `.env` file or reload the configuration from it.

## 3. The "Create Release" Automated Sequence

Pressing the "Create Release" button triggers a fully automated, multi-step workflow:

1.  **Step 1: Package & Hash**:
    -   The application collects all files from the drag-and-drop area.
    -   It creates a local temporary archive named `AOEngine-v<VERSION>.zip`.
    -   It calculates the SHA256 hash of this `.zip` file for integrity verification.

2.  **Step 2: Create Manifest**:
    - A `manifest-v<VERSION>.json` file is generated locally, containing the release version, notes, the zip's SHA256 hash, and a UTC timestamp.

3.  **Step 3: Parallel Asset Upload**:
    -   The uploader initiates a parallel upload process for each checked Asset Provider.
    -   It uploads two files to each provider: the main `.zip` archive and a generated, version-specific `manifest.json`.
    -   It collects all successful URLs into structured lists (`manifest_urls`, `download_urls`).
    -   **Failure Handling**: If an upload to one provider fails, the error is logged clearly. The overall release process continues as long as **at least one provider succeeds**.

4.  **Step 4: Commit Canonical Manifest**:
    - The local `manifest-v<VERSION>.json` is copied into the local git clone of the index repository under a `manifests/` directory.
    - The new manifest is committed and pushed to the remote index repository. This becomes the canonical source of truth for the release.

5.  **Step 5: Update Version Index**:
    -   The `INDEX_PROVIDER` (`GitHubGitProvider`) pulls the latest changes from the remote index repository to avoid conflicts.
    -   It parses the `versions.json` file, inserts a new entry for the current release at the top of the list, and marks it with `"latest": true"`. All other entries have the `"latest"` flag removed.
    -   The provider then commits the updated `versions.json` and pushes it to the remote repository.

6.  **Step 6: Cleanup**:
    -   All local temporary files (like the `.zip` archive) are deleted.
    -   A final success message is logged, detailing which providers were successful.

## 4. Project Structure

-   `main.py`: The entry point of the application. It initializes the Tkinter root window and the main `App` class.
-   `config.py`: Defines the `Settings` class, which loads all configuration variables from the `.env` file and provides them to the application.
-   `core/`: Contains the core business logic.
    -   `workflow.py`: Orchestrates the entire release sequence, from packaging to uploading and updating the index.
-   `gui/`: Contains all user interface components.
    -   `main_window.py`: Defines the main application window, its layout, and its connection to the core workflow.
-   `providers/`: Contains the implementation for all supported Index and Asset Providers.
    -   `base.py`: Defines the abstract base classes for providers.
    -   `github_git.py`: The `GitHubGitProvider` for managing the `versions.json` index.
    -   `github_release.py`: The `GitHubReleaseProvider` for uploading assets to GitHub Releases.
    -   `catbox.py`: The `CatboxProvider` for uploading assets to Catbox.moe.

## 5. Configuration

Configuration is managed via a `.env` file located in the project root.

### `.env` File Example

```dotenv
# --- Index Provider Configuration (GitHub Git) ---
# This is the single, non-negotiable repository for your versions.json file.
INDEX_GIT_CLONE_URL="https://github.com/YourUser/AOEngine-Manifest.git"
INDEX_GIT_BRANCH="main"
INDEX_GIT_LOCAL_FOLDER="_index_repo_data"
GITHUB_TOKEN_FOR_INDEX="ghp_YourIndexRepoToken" # Needs 'repo' scope for the index repo

# --- Asset Provider Configuration ---
# You only need to fill out the sections for providers you intend to use.

# -- GitHub Releases --
GITHUB_ASSET_REPO="YourUser/AOEngine-Releases"
GITHUB_TOKEN_FOR_ASSETS="ghp_YourAssetRepoToken" # Needs 'repo' scope for the asset repo

# -- Catbox --
CATBOX_USER_HASH="" # Optional: for authenticated uploads

# --- UI State Configuration ---
UI_USE_SINGLE_TOKEN="True"
UI_CATBOX_ANONYMOUS="True"
```

## 6. Technology Stack

-   **Language**: Python 3
-   **GUI Framework**: CustomTkinter
-   **Libraries**:
    -   `requests`: For making HTTP API calls to providers.
    -   `GitPython`: For interacting with the Git index repository.
    -   `python-dotenv`: For managing configuration from the `.env` file.
    -   `tkinterdnd2`: For enabling drag-and-drop functionality.

## 7. Running the Application

To run the uploader, execute the `main.py` script from the project root. This ensures correct module resolution.

```bash
python -m uploader.main