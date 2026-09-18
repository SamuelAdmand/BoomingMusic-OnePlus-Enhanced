"""Android package modifier and configuration patcher.

Updates Gradle build files to change the applicationId to the target package
(e.g., 'com.tencent.qqmusic' for OnePlus/Oppo audio enhancement whitelist)
while maintaining project compilation compatibility.
"""

import re
import shutil
from pathlib import Path
from typing import Optional, Tuple

from scripts.config import (
    BUILD_GRADLE_KTS,
    DEFAULT_PACKAGE_NAME,
)


class GradlePatcher:
    """Handles parsing and updating Gradle configuration for package changes."""

    def __init__(self, build_gradle_path: Optional[Path] = None) -> None:
        """Initialize the patcher with target Gradle file.

        Args:
            build_gradle_path: Path to app/build.gradle.kts. Defaults to config path.
        """
        self.gradle_file = build_gradle_path or BUILD_GRADLE_KTS

    def verify_target_exists(self) -> None:
        """Verify the Gradle build file exists.

        Raises:
            FileNotFoundError: If the target build.gradle.kts is missing.
        """
        if not self.gradle_file.is_file():
            raise FileNotFoundError(
                f"Gradle build file not found at: {self.gradle_file.resolve()}"
            )

    def read_content(self) -> str:
        """Read existing Gradle file content.

        Returns:
            str: File contents.
        """
        self.verify_target_exists()
        return self.gradle_file.read_text(encoding="utf-8")

    def get_current_application_id(self) -> Optional[str]:
        """Extract the current applicationId from build.gradle.kts.

        Returns:
            Optional[str]: Current applicationId or reference expression.
        """
        content = self.read_content()
        match = re.search(r'applicationId\s*=\s*("([^"]+)"|([^\r\n]+))', content)
        if match:
            return match.group(2) or match.group(1).strip()
        return None

    def patch_package_name(
        self,
        new_package: str = DEFAULT_PACKAGE_NAME,
        dry_run: bool = False,
    ) -> Tuple[bool, str]:
        """Replace applicationId with the specified package name.

        Args:
            new_package: Target package name (e.g. 'com.tencent.qqmusic').
            dry_run: If True, performs regex replacement without writing to disk.

        Returns:
            Tuple[bool, str]: (success, message)
        """
        content = self.read_content()

        # Regex matching: applicationId = namespace OR applicationId = "com.something"
        pattern = r'(applicationId\s*=\s*)(namespace|"[^"\r\n]+")'
        replacement = rf'\1"{new_package}"'

        if not re.search(pattern, content):
            return (
                False,
                f"Could not locate 'applicationId = ...' pattern in {self.gradle_file}",
            )

        new_content, count = re.subn(pattern, replacement, content, count=1)

        if count == 0:
            return False, "No replacements performed in Gradle file."

        if dry_run:
            return (
                True,
                f"[DRY-RUN] Successfully patched applicationId -> '{new_package}' (1 occurrence)",
            )

        # Create backup before modification
        backup_path = self.gradle_file.with_suffix(".kts.bak")
        shutil.copyfile(self.gradle_file, backup_path)

        self.gradle_file.write_text(new_content, encoding="utf-8")
        return (
            True,
            f"Successfully updated {self.gradle_file} applicationId to '{new_package}'. Backup saved to {backup_path.name}.",
        )

    def restore_backup(self) -> bool:
        """Restore build.gradle.kts from its backup file if present.

        Returns:
            bool: True if restored, False if backup did not exist.
        """
        backup_path = self.gradle_file.with_suffix(".kts.bak")
        if backup_path.is_file():
            shutil.copyfile(backup_path, self.gradle_file)
            backup_path.unlink()
            return True
        return False


def apply_package_patch(
    new_package: str = DEFAULT_PACKAGE_NAME,
    build_gradle_path: Optional[Path] = None,
    dry_run: bool = False,
) -> bool:
    """Convenience functional interface for applying package patch.

    Args:
        new_package: New Android package name.
        build_gradle_path: Custom path to build.gradle.kts.
        dry_run: Whether to simulate changes.

    Returns:
        bool: True if patching succeeded.
    """
    patcher = GradlePatcher(build_gradle_path)
    success, msg = patcher.patch_package_name(new_package, dry_run=dry_run)
    print(msg)
    return success


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Patch Android applicationId in Gradle file")
    parser.add_argument(
        "--package",
        type=str,
        default=DEFAULT_PACKAGE_NAME,
        help=f"Target package name (default: {DEFAULT_PACKAGE_NAME})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate package replacement without modifying file",
    )
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Path to app/build.gradle.kts",
    )

    args = parser.parse_args()
    target_path = Path(args.file) if args.file else None

    result = apply_package_patch(
        new_package=args.package,
        build_gradle_path=target_path,
        dry_run=args.dry_run,
    )
    sys.exit(0 if result else 1)
