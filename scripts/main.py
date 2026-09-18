"""Unified CLI entry point for package name change automation.

Coordinates checking upstream releases, applying package modifications,
building release artifacts, and formatting output for CI/CD pipelines.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from scripts.builder import AndroidBuilder
from scripts.config import (
    BOOMING_DIR,
    DEFAULT_FLAVOR,
    DEFAULT_PACKAGE_NAME,
    DEFAULT_UPSTREAM_REPO,
)
from scripts.patcher import GradlePatcher
from scripts.upstream import (
    check_for_new_release,
    clone_upstream_tag,
)


def write_github_output(outputs: Dict[str, Any]) -> None:
    """Write key-value pairs to the GITHUB_OUTPUT environment file.

    Handles single-line and multiline values using GitHub Actions delimiter syntax.

    Args:
        outputs: Dictionary of outputs to publish to subsequent workflow steps.
    """
    gh_output_path = os.environ.get("GITHUB_OUTPUT")
    if not gh_output_path:
        return

    with open(gh_output_path, "a", encoding="utf-8") as out_file:
        for key, value in outputs.items():
            str_val = str(value) if value is not None else ""
            if "\n" in str_val:
                delimiter = "EOF_GH_ACTION_OUTPUT"
                out_file.write(f"{key}<<{delimiter}\n{str_val}\n{delimiter}\n")
            else:
                out_file.write(f"{key}={str_val}\n")


def command_check(args: argparse.Namespace) -> int:
    """Check for new releases in the upstream repository."""
    target_repo = args.target_repo or os.environ.get("GITHUB_REPOSITORY")
    needs_build, release = check_for_new_release(
        target_repo=target_repo,
        upstream_repo=args.upstream,
        requested_tag=args.tag,
        force_rebuild=args.force,
    )

    tag_name = release.get("tag_name", "")
    title = release.get("name") or tag_name
    body = release.get("body", "")
    is_prerelease = release.get("prerelease", False)

    outputs = {
        "needs_build": str(needs_build).lower(),
        "tag_name": tag_name,
        "release_title": title,
        "release_body": body,
        "is_prerelease": str(is_prerelease).lower(),
    }
    write_github_output(outputs)

    print(f"\nResult: needs_build={needs_build}, tag={tag_name}")
    return 0


def command_patch(args: argparse.Namespace) -> int:
    """Patch the Gradle file with the target package name."""
    file_path = Path(args.file) if args.file else None
    patcher = GradlePatcher(file_path)

    current_id = patcher.get_current_application_id()
    print(f"Current applicationId: {current_id}")

    success, message = patcher.patch_package_name(
        new_package=args.package,
        dry_run=args.dry_run,
    )
    print(message)
    return 0 if success else 1


def command_build(args: argparse.Namespace) -> int:
    """Build the release APK with Gradle."""
    project_dir = Path(args.dir) if args.dir else BOOMING_DIR
    builder = AndroidBuilder(project_dir)

    print(f"Building release APK for flavor '{args.flavor}'...")
    apks = builder.build_release_apk(args.flavor)

    if not apks:
        print("Warning: No APK files found after build completion.")
        return 1

    print(f"Successfully generated {len(apks)} APK file(s):")
    for apk in apks:
        print(f" - {apk.name} ({apk.stat().st_size / (1024 * 1024):.2f} MB)")

    write_github_output({"apk_count": len(apks)})
    return 0


def command_sync(args: argparse.Namespace) -> int:
    """Clone upstream tag and apply the package modification."""
    target_dir = Path(args.dir) if args.dir else BOOMING_DIR
    tag = args.tag

    if not tag:
        print("Error: --tag is required for sync command.")
        return 1

    clone_upstream_tag(
        tag=tag,
        destination_dir=target_dir,
        upstream_repo=args.upstream,
    )

    patcher = GradlePatcher(target_dir / "app" / "build.gradle.kts")
    success, message = patcher.patch_package_name(args.package)
    print(message)
    return 0 if success else 1


def build_cli_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        description="Package-Name-Change automation suite for BoomingMusic.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # Subcommand: check
    check_p = subparsers.add_parser("check", help="Check upstream for new releases")
    check_p.add_argument("--upstream", default=DEFAULT_UPSTREAM_REPO, help="Upstream repo (owner/repo)")
    check_p.add_argument("--target-repo", default=None, help="Current repo (owner/repo)")
    check_p.add_argument("--tag", default=None, help="Target specific tag (or 'latest')")
    check_p.add_argument("--force", action="store_true", help="Force build even if tag already exists")
    check_p.set_defaults(func=command_check)

    # Subcommand: patch
    patch_p = subparsers.add_parser("patch", help="Modify applicationId in build.gradle.kts")
    patch_p.add_argument("--package", default=DEFAULT_PACKAGE_NAME, help="New package name")
    patch_p.add_argument("--file", default=None, help="Path to build.gradle.kts")
    patch_p.add_argument("--dry-run", action="store_true", help="Simulate without modifying")
    patch_p.set_defaults(func=command_patch)

    # Subcommand: build
    build_p = subparsers.add_parser("build", help="Build release APK using Gradle")
    build_p.add_argument("--flavor", default=DEFAULT_FLAVOR, help="Product flavor to assemble")
    build_p.add_argument("--dir", default=None, help="Path to project directory")
    build_p.set_defaults(func=command_build)

    # Subcommand: sync
    sync_p = subparsers.add_parser("sync", help="Checkout upstream tag and apply patch")
    sync_p.add_argument("--tag", required=True, help="Tag to checkout and patch")
    sync_p.add_argument("--upstream", default=DEFAULT_UPSTREAM_REPO, help="Upstream repo (owner/repo)")
    sync_p.add_argument("--package", default=DEFAULT_PACKAGE_NAME, help="Target package name")
    sync_p.add_argument("--dir", default=None, help="Destination directory for source clone")
    sync_p.set_defaults(func=command_sync)

    return parser


def main() -> None:
    """Program entry point."""
    parser = build_cli_parser()
    args = parser.parse_args()
    exit_code = args.func(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
