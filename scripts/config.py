"""Configuration settings and environment helpers for the automation suite.

Defines repository constants, package identifier defaults, filesystem paths,
and standard headers for GitHub REST API interaction.
"""

import os
from pathlib import Path
from typing import Dict, Optional

# Base paths
ROOT_DIR: Path = Path(__file__).resolve().parent.parent
BOOMING_DIR: Path = (
    ROOT_DIR / "BoomingMusic" if (ROOT_DIR / "BoomingMusic").is_dir() else ROOT_DIR
)
APP_DIR: Path = BOOMING_DIR / "app"
BUILD_GRADLE_KTS: Path = APP_DIR / "build.gradle.kts"
MANIFEST_XML: Path = APP_DIR / "src" / "main" / "AndroidManifest.xml"
WHITELIST_FILE: Path = ROOT_DIR / "OnePlus-Whitelist.txt"

# Default identifiers
DEFAULT_UPSTREAM_REPO: str = "mardous/BoomingMusic"
DEFAULT_PACKAGE_NAME: str = "com.tencent.qqmusic"
DEFAULT_FLAVOR: str = "github"

# Build configurations
SUPPORTED_FLAVORS: tuple[str, ...] = ("github", "fdroid")


def get_github_token() -> Optional[str]:
    """Retrieve the GitHub API authentication token from environment.

    Returns:
        Optional[str]: The token string if found, otherwise None.
    """
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def get_api_headers() -> Dict[str, str]:
    """Build HTTP headers for authenticating GitHub REST API requests.

    Returns:
        Dict[str, str]: Headers dict with User-Agent, Accept, and optional Authorization.
    """
    headers: Dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Package-Name-Change-Automation",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = get_github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers
