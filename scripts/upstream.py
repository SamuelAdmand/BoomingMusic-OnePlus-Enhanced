"""Upstream release detection and synchronization via GitHub REST API.

Fetches the latest release from the upstream repository, compares tags against
the local repository, and handles checkout of the target release source code.
"""

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from scripts.config import (
    DEFAULT_UPSTREAM_REPO,
    get_api_headers,
)


def fetch_json(url: str) -> Any:
    """Perform an authenticated GET request to GitHub API and parse JSON.

    Args:
        url: Full API endpoint URL.

    Returns:
        Any: Parsed JSON response (dict or list).

    Raises:
        RuntimeError: If request fails or returns an error status code.
    """
    headers = get_api_headers()
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API Error {exc.code} for {url}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error accessing {url}: {exc.reason}") from exc


def get_latest_upstream_release(repo: str = DEFAULT_UPSTREAM_REPO) -> Dict[str, Any]:
    """Retrieve details for the latest release in an upstream repository.

    Args:
        repo: GitHub repository in 'owner/repo' format.

    Returns:
        Dict[str, Any]: Upstream release object including 'tag_name', 'name', 'body'.
    """
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    return fetch_json(url)


def get_upstream_release_by_tag(
    tag: str, repo: str = DEFAULT_UPSTREAM_REPO
) -> Dict[str, Any]:
    """Retrieve details for a specific tag release in an upstream repository.

    Args:
        tag: Release tag identifier (e.g. 'v1.4.0').
        repo: GitHub repository in 'owner/repo' format.

    Returns:
        Dict[str, Any]: Release payload for the specified tag.
    """
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    return fetch_json(url)


def get_existing_release_tags(repo: str) -> List[str]:
    """Fetch existing release tags from the target repository.

    Args:
        repo: GitHub repository in 'owner/repo' format.

    Returns:
        List[str]: List of tag names already published in the repository.
    """
    url = f"https://api.github.com/repos/{repo}/releases?per_page=100"
    try:
        releases = fetch_json(url)
        if isinstance(releases, list):
            return [str(rel.get("tag_name", "")) for rel in releases]
        return []
    except RuntimeError as exc:
        # If the repository has 0 releases or is private without token, log and continue
        print(f"Notice: Could not query existing releases for {repo}: {exc}")
        return []


def check_for_new_release(
    target_repo: Optional[str] = None,
    upstream_repo: str = DEFAULT_UPSTREAM_REPO,
    requested_tag: Optional[str] = None,
    force_rebuild: bool = False,
) -> Tuple[bool, Dict[str, Any]]:
    """Determine whether an upstream release needs to be built and released.

    Args:
        target_repo: Current repository ('owner/repo'). If None, checks only upstream.
        upstream_repo: Upstream repository to track.
        requested_tag: Optional tag to target specifically. If empty or 'latest', uses latest release.
        force_rebuild: If True, triggers build even if the release exists in target repo.

    Returns:
        Tuple[bool, Dict[str, Any]]: (needs_build, upstream_release_data)
    """
    if requested_tag and requested_tag.lower() != "latest":
        upstream_release = get_upstream_release_by_tag(requested_tag, upstream_repo)
    else:
        upstream_release = get_latest_upstream_release(upstream_repo)

    upstream_tag = upstream_release.get("tag_name", "")
    print(f"Upstream release found: {upstream_tag} ('{upstream_release.get('name', '')}')")

    if force_rebuild:
        print("Force rebuild requested. Proceeding with build.")
        return True, upstream_release

    if not target_repo:
        print("No target repo specified; returning upstream release status.")
        return True, upstream_release

    existing_tags = get_existing_release_tags(target_repo)
    if upstream_tag in existing_tags:
        print(f"Tag {upstream_tag} already exists in {target_repo}. No build needed.")
        return False, upstream_release

    print(f"New release detected: {upstream_tag} not found in {target_repo}.")
    return True, upstream_release


def clone_upstream_tag(
    tag: str,
    destination_dir: Path,
    upstream_repo: str = DEFAULT_UPSTREAM_REPO,
) -> None:
    """Shallow-clone a specific tag of the upstream repository into the destination directory.

    Args:
        tag: Git tag to checkout.
        destination_dir: Destination path for the clone.
        upstream_repo: GitHub repository in 'owner/repo' format.
    """
    repo_url = f"https://github.com/{upstream_repo}.git"
    destination_dir.mkdir(parents=True, exist_ok=True)

    print(f"Cloning {repo_url} at tag {tag} into {destination_dir}...")
    cmd = [
        "git",
        "clone",
        "--depth",
        "1",
        "--branch",
        tag,
        repo_url,
        str(destination_dir),
    ]
    subprocess.run(cmd, check=True)
    print(f"Successfully checked out {tag}.")


if __name__ == "__main__":
    import sys

    repo_arg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_UPSTREAM_REPO
    try:
        latest = get_latest_upstream_release(repo_arg)
        print(f"Latest tag in {repo_arg}: {latest.get('tag_name')}")
        print(f"Title: {latest.get('name')}")
    except Exception as err:
        print(f"Error checking upstream: {err}")
        sys.exit(1)
