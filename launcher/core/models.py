from typing import Dict, Optional, List
from pydantic import BaseModel

class Config(BaseModel):
    game_path: Optional[str] = None
    language: Optional[str] = "en"

class Version(BaseModel):
    version: str
    manifest_urls: Dict[str, str]
    download_urls: Dict[str, str]
    latest: Optional[bool] = False
    profiler: Optional[bool] = False

class Manifest(BaseModel):
    version: str
    release_notes: str
    archive_sha256: str
    upload_date: str
    files: List[str]
    profiler: Optional[bool] = False


class ReleaseInfo(Version, Manifest):
    """Combined model for a release, containing both version and manifest info."""
    pass