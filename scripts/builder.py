"""Gradle build orchestrator and release signing manager.

Prepares keystore credentials (from environment variables or auto-generates
a fallback self-signed release keystore), invokes Gradle wrapper tasks, and
discovers output APK artifacts.
"""

import base64
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from scripts.config import (
    BOOMING_DIR,
    DEFAULT_FLAVOR,
)


class AndroidBuilder:
    """Orchestrates Gradle builds and keystore provisioning."""

    def __init__(self, project_dir: Optional[Path] = None) -> None:
        """Initialize the builder.

        Args:
            project_dir: Root directory of the Android project (containing gradlew).
        """
        self.project_dir = project_dir or BOOMING_DIR
        self.gradlew = self._resolve_gradle_wrapper()

    def _resolve_gradle_wrapper(self) -> Path:
        """Find the platform-appropriate Gradle wrapper executable.

        Returns:
            Path: Path to gradlew or gradlew.bat.

        Raises:
            FileNotFoundError: If gradlew executable is not found.
        """
        name = "gradlew.bat" if os.name == "nt" else "gradlew"
        path = self.project_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"Gradle wrapper not found at: {path.resolve()}")
        return path

    def prepare_signing_keystore(self, target_dir: Optional[Path] = None) -> Dict[str, str]:
        """Ensure a valid release signing keystore is configured.

        Checks environment variables for pre-existing keys. If none are configured,
        generates an ephemeral release keystore using Java's keytool.

        Args:
            target_dir: Directory where keystore file should be placed.

        Returns:
            Dict[str, str]: Environment variables (KEYSTORE_FILE, KEY_ALIAS, etc.)
        """
        work_dir = target_dir or self.project_dir
        keystore_path = work_dir / "release_signing.jks"

        # Check for user-provided base64 key in secrets
        b64_key = os.environ.get("SIGNING_KEY_BASE64") or os.environ.get("SIGNING_KEY")
        if b64_key:
            print("Found user-provided base64 signing key in environment.")
            key_bytes = base64.b64decode(b64_key.strip())
            keystore_path.write_bytes(key_bytes)

            return {
                "KEYSTORE_FILE": str(keystore_path.resolve()),
                "KEY_ALIAS": os.environ.get("KEY_ALIAS", "release"),
                "KEY_PASSWORD": os.environ.get("KEY_PASSWORD", ""),
                "STORE_PASSWORD": os.environ.get("STORE_PASSWORD", ""),
            }

        # Check if already generated or existing keystore file path given
        existing_file = os.environ.get("KEYSTORE_FILE")
        if existing_file and Path(existing_file).is_file():
            return {
                "KEYSTORE_FILE": existing_file,
                "KEY_ALIAS": os.environ.get("KEY_ALIAS", "release"),
                "KEY_PASSWORD": os.environ.get("KEY_PASSWORD", "android"),
                "STORE_PASSWORD": os.environ.get("STORE_PASSWORD", "android"),
            }

        # Auto-generate self-signed release keystore fallback if keytool is available
        keytool_bin = shutil.which("keytool")
        if keytool_bin and not keystore_path.is_file():
            print("No external signing key found. Generating fallback release keystore...")
            cmd = [
                keytool_bin,
                "-genkeypair",
                "-v",
                "-keystore",
                str(keystore_path.resolve()),
                "-alias",
                "release",
                "-keyalg",
                "RSA",
                "-keysize",
                "2048",
                "-validity",
                "10000",
                "-storepass",
                "android",
                "-keypass",
                "android",
                "-dname",
                "CN=BoomingMusicRelease, OU=OpenSource, O=Enhanced, L=Global, ST=None, C=US",
            ]
            subprocess.run(cmd, check=True)
            print(f"Fallback release keystore generated at: {keystore_path}")

        return {
            "KEYSTORE_FILE": str(keystore_path.resolve()) if keystore_path.is_file() else "",
            "KEY_ALIAS": "release",
            "KEY_PASSWORD": "android",
            "STORE_PASSWORD": "android",
        }

    def build_release_apk(self, flavor: str = DEFAULT_FLAVOR) -> List[Path]:
        """Execute Gradle assemble task for the specified flavor.

        Args:
            flavor: Android product flavor (e.g. 'github', 'fdroid').

        Returns:
            List[Path]: Paths to generated APK files.
        """
        signing_env = self.prepare_signing_keystore()
        env = os.environ.copy()
        env.update({k: v for k, v in signing_env.items() if v})

        # Ensure gradlew has execute permissions on Linux/macOS
        if os.name != "nt":
            self.gradlew.chmod(0o755)

        cap_flavor = flavor.capitalize()
        task_name = f"assemble{cap_flavor}Release"

        print(f"Executing Gradle task: {task_name}...")
        cmd = [str(self.gradlew.resolve()), task_name, "--stacktrace"]
        subprocess.run(cmd, cwd=self.project_dir, env=env, check=True)

        return self.find_output_apks(flavor)

    def find_output_apks(self, flavor: str = DEFAULT_FLAVOR) -> List[Path]:
        """Discover built release APK files in the build output directory.

        Args:
            flavor: Flavor directory to search.

        Returns:
            List[Path]: Found APK file paths.
        """
        outputs_dir = self.project_dir / "app" / "build" / "outputs" / "apk" / flavor / "release"
        if not outputs_dir.is_dir():
            # Alternative search across all flavor directories
            outputs_dir = self.project_dir / "app" / "build" / "outputs" / "apk"

        apks = list(outputs_dir.glob("**/*.apk"))
        # Exclude unaligned or intermediate apks if any
        return [apk for apk in apks if "unaligned" not in apk.name.lower()]


if __name__ == "__main__":
    import sys

    flavor_arg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FLAVOR
    builder = AndroidBuilder()
    print(f"Resolving Gradle: {builder.gradlew}")
    found = builder.find_output_apks(flavor_arg)
    print(f"Found {len(found)} APKs: {[a.name for a in found]}")
