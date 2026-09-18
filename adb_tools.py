"""ADB Developer & Build CLI Utility (Package-Independent).

Dynamically resolves application ID, debug suffix, and launcher activity
from Gradle configuration (build.gradle.kts / build.gradle / AndroidManifest.xml).
Adapts automatically whenever package names change without requiring script edits.
"""

import glob
import os
import re
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_DIR: str = os.path.abspath(os.path.dirname(__file__))
BOOMING_DIR: str = (
    os.path.join(PROJECT_DIR, "BoomingMusic")
    if os.path.isdir(os.path.join(PROJECT_DIR, "BoomingMusic"))
    else PROJECT_DIR
)
GRADLE_CMD: str = os.path.join(BOOMING_DIR, "gradlew.bat" if os.name == "nt" else "gradlew")
APK_OUTPUTS_DIR: str = os.path.join(BOOMING_DIR, "app", "build", "outputs", "apk")

FLAVORS: List[str] = ["github", "fdroid", "playstore"]
DEFAULT_FLAVOR: str = "github"

AUDIO_PERMISSIONS: List[str] = [
    "android.permission.READ_MEDIA_AUDIO",
    "android.permission.READ_MEDIA_IMAGES",
    "android.permission.POST_NOTIFICATIONS",
    "android.permission.READ_EXTERNAL_STORAGE",
    "android.permission.WRITE_EXTERNAL_STORAGE",
]

# ANSI Styling
GREEN, YELLOW, RED = "\033[92m", "\033[93m", "\033[91m"
CYAN, MAGENTA, BOLD = "\033[96m", "\033[95m", "\033[1m"
DIM, RESET = "\033[2m", "\033[0m"


def clear_screen() -> None:
    """Clears the console screen."""
    os.system("cls" if os.name == "nt" else "clear")


def detect_package_config(app_dir: str) -> Dict[str, str]:
    """Dynamically parses build.gradle(.kts) and AndroidManifest.xml for package configuration.

    Args:
        app_dir: Root directory of the Android project.

    Returns:
        Dict[str, str]: Map containing 'release_package', 'debug_package',
                        'namespace', and 'main_activity'.
    """
    namespace = ""
    app_id = ""
    suffix = ".debug"
    main_activity = ""

    # 1. Parse Gradle files for namespace, applicationId, and debug suffix
    gradle_files = [
        os.path.join(app_dir, "app", "build.gradle.kts"),
        os.path.join(app_dir, "app", "build.gradle"),
        os.path.join(app_dir, "build.gradle.kts"),
        os.path.join(app_dir, "build.gradle"),
    ]

    for gf in gradle_files:
        if os.path.isfile(gf):
            try:
                with open(gf, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                ns_match = re.search(r'namespace\s*=?\s*["\']([^"\']+)["\']', content)
                if ns_match:
                    namespace = ns_match.group(1).strip()

                app_match = re.search(r'applicationId\s*=?\s*["\']([^"\']+)["\']', content)
                if app_match:
                    app_id = app_match.group(1).strip()
                elif re.search(r'applicationId\s*=?\s*namespace', content):
                    app_id = namespace

                suf_match = re.search(
                    r'debug\s*\{[^}]*applicationIdSuffix\s*=?\s*["\']([^"\']+)["\']',
                    content,
                    re.DOTALL,
                )
                if suf_match:
                    suffix = suf_match.group(1).strip()
            except Exception:
                pass
            if app_id or namespace:
                break

    # 2. Parse AndroidManifest.xml for launcher activity & manifest package
    manifest_path = os.path.join(app_dir, "app", "src", "main", "AndroidManifest.xml")
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8", errors="ignore") as f:
                m_content = f.read()

            pkg_match = re.search(r'<manifest[^>]+package=["\']([^"\']+)["\']', m_content)
            if pkg_match and not namespace:
                namespace = pkg_match.group(1).strip()

            activities = re.findall(
                r'<activity\b([^>]+>(?:(?!</activity>).)*?android\.intent\.category\.LAUNCHER.*?</activity>)',
                m_content,
                re.DOTALL,
            )
            if activities:
                act_block = activities[0]
                name_match = re.search(r'android:name=["\']([^"\']+)["\']', act_block)
                if name_match:
                    raw_act = name_match.group(1).strip()
                    if raw_act.startswith("."):
                        main_activity = f"{namespace}{raw_act}"
                    elif "." in raw_act:
                        main_activity = raw_act
                    else:
                        main_activity = f"{namespace}.{raw_act}"
        except Exception:
            pass

    release_pkg = app_id or namespace or "com.mardous.booming"
    debug_pkg = (
        f"{release_pkg}{suffix}"
        if suffix and not release_pkg.endswith(suffix)
        else release_pkg
    )
    main_activity = main_activity or (
        f"{namespace}.MainActivity" if namespace else f"{release_pkg}.MainActivity"
    )

    return {
        "release_package": release_pkg,
        "debug_package": debug_pkg,
        "namespace": namespace or release_pkg,
        "main_activity": main_activity,
    }


def check_adb_device() -> bool:
    """Returns True if at least one authorized ADB device is connected."""
    try:
        res = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=True)
        lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
        return any("\tdevice" in line for line in lines[1:])
    except Exception:
        return False


def get_connected_devices() -> List[str]:
    """Returns a list of connected ADB device serials."""
    try:
        res = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=True)
        lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
        return [l.split("\t")[0] for l in lines[1:] if "\tdevice" in l]
    except Exception:
        return []


def get_device_abi() -> Optional[str]:
    """Queries connected ADB device for primary CPU ABI (e.g., 'arm64-v8a')."""
    try:
        res = subprocess.run(["adb", "shell", "getprop", "ro.product.cpu.abi"], capture_output=True, text=True)
        return res.stdout.strip() or None
    except Exception:
        return None


def detect_target_package(pkg_config: Dict[str, str]) -> str:
    """Detects which package variant (debug or release) is currently installed on device."""
    debug_pkg = pkg_config["debug_package"]
    release_pkg = pkg_config["release_package"]
    try:
        proc = subprocess.run(
            ["adb", "shell", "pm", "list", "packages"],
            capture_output=True, text=True, check=False
        )
        out = proc.stdout.lower()
        if f"package:{debug_pkg.lower()}" in out or debug_pkg.lower() in out:
            return debug_pkg
        if f"package:{release_pkg.lower()}" in out or release_pkg.lower() in out:
            return release_pkg
    except Exception:
        pass
    return debug_pkg


def find_latest_apk(flavor: str, is_debug: bool) -> Optional[str]:
    """Finds the most suitable APK matching flavor, build type, and device ABI."""
    build_type = "debug" if is_debug else "release"
    target_dir = os.path.join(APK_OUTPUTS_DIR, flavor, build_type)
    candidates: List[str] = []

    if os.path.isdir(target_dir):
        candidates.extend(glob.glob(os.path.join(target_dir, "*.apk")))

    if not candidates and os.path.isdir(APK_OUTPUTS_DIR):
        for root, _, files in os.walk(APK_OUTPUTS_DIR):
            if build_type in root.lower() and (flavor in root.lower() or not candidates):
                candidates.extend(os.path.join(root, f) for f in files if f.endswith(".apk"))

    if not candidates:
        for d in [BOOMING_DIR, PROJECT_DIR]:
            for f in glob.glob(os.path.join(d, "*.apk")):
                low = os.path.basename(f).lower()
                if (build_type in low) or (not is_debug and "debug" not in low):
                    candidates.append(f)

    if not candidates:
        return None

    device_abi = get_device_abi()

    def score(path: str) -> Tuple[int, float]:
        name = os.path.basename(path).lower()
        abi_score = 3 if (device_abi and device_abi.lower() in name) else (2 if "universal" in name else 1)
        return (abi_score, os.path.getmtime(path))

    candidates.sort(key=score, reverse=True)
    return candidates[0]


def run_gradle_task(task_name: str) -> bool:
    """Executes a Gradle task in the project directory."""
    print(f"\n{CYAN}⚡ Running Gradle: {BOLD}{task_name}{RESET}...")
    start_time = time.time()
    try:
        res = subprocess.run([GRADLE_CMD, task_name], cwd=BOOMING_DIR, shell=(os.name == "nt"))
        elapsed = time.time() - start_time
        if res.returncode != 0:
            print(f"\n{RED}✗ Gradle {task_name} failed (elapsed: {elapsed:.1f}s)!{RESET}")
            return False
        print(f"{GREEN}✓ Gradle {task_name} completed in {elapsed:.1f}s!{RESET}")
        return True
    except Exception as e:
        print(f"\n{RED}✗ Failed to execute Gradle: {e}{RESET}")
        return False


def launch_app(package_name: str, main_activity: str) -> bool:
    """Launches the application via explicit component or implicit launcher intent."""
    print(f"{CYAN}Launching {BOLD}{package_name}{RESET}...")
    activity = f"{package_name}/{main_activity}"
    res = subprocess.run(
        ["adb", "shell", "am", "start", "-n", activity],
        capture_output=True, text=True
    )
    if res.returncode != 0 or "Error" in res.stdout or "Error" in res.stderr:
        subprocess.run(
            ["adb", "shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"],
            capture_output=True
        )
    print(f"{GREEN}✓ App launched!{RESET}")
    return True


def install_apk(apk_path: str, package_name: str, main_activity: str) -> bool:
    """Installs an APK via ADB and launches its main activity."""
    if not os.path.exists(apk_path):
        print(f"{RED}✗ APK file not found: {apk_path}{RESET}")
        return False
    if not check_adb_device():
        print(f"{RED}✗ No ADB device detected. Please connect your device.{RESET}")
        return False

    print(f"\n{CYAN}Installing APK: {BOLD}{os.path.basename(apk_path)}{RESET}...")
    start_time = time.time()
    res = subprocess.run(["adb", "install", "-r", "-d", apk_path])
    elapsed = time.time() - start_time

    if res.returncode != 0:
        print(f"{RED}✗ Installation failed ({elapsed:.1f}s)!{RESET}")
        return False
    print(f"{GREEN}✓ APK installed in {elapsed:.1f}s!{RESET}")
    return launch_app(package_name, main_activity)


def handle_debug_flow(pkg_config: Dict[str, str], build_first: bool, clean_install: bool, flavor: str) -> None:
    """Handles Debug build, installation, and launch flow."""
    task = f"assemble{flavor.capitalize()}Debug"
    debug_pkg = pkg_config["debug_package"]
    main_act = pkg_config["main_activity"]

    apk = find_latest_apk(flavor, is_debug=True)
    if build_first or not apk:
        if not run_gradle_task(task):
            return
        apk = find_latest_apk(flavor, is_debug=True)
    if not apk:
        print(f"{RED}✗ Debug APK not found in outputs.{RESET}")
        return
    if clean_install:
        if not check_adb_device():
            print(f"{RED}✗ No ADB device detected.{RESET}")
            return
        print(f"\n{YELLOW}Uninstalling {debug_pkg} for clean install...{RESET}")
        subprocess.run(["adb", "uninstall", debug_pkg])
    install_apk(apk, debug_pkg, main_act)


def handle_release_flow(pkg_config: Dict[str, str], build_first: bool, flavor: str) -> None:
    """Handles Release build, installation, and launch flow."""
    task = f"assemble{flavor.capitalize()}Release"
    release_pkg = pkg_config["release_package"]
    main_act = pkg_config["main_activity"]

    if build_first and not run_gradle_task(task):
        return
    apk = find_latest_apk(flavor, is_debug=False)
    if not apk:
        print(f"{RED}✗ No release APK found. Build one first using option [4].{RESET}")
        return
    install_apk(apk, release_pkg, main_act)


def grant_audio_permissions(pkg_config: Dict[str, str]) -> None:
    """Grants audio and media permissions directly via ADB shell."""
    if not check_adb_device():
        print(f"{RED}✗ No ADB device detected.{RESET}")
        return
    target = detect_target_package(pkg_config)
    print(f"\n{CYAN}Granting permissions for {BOLD}{target}{RESET}...")
    count = 0
    for perm in AUDIO_PERMISSIONS:
        res = subprocess.run(["adb", "shell", "pm", "grant", target, perm], capture_output=True, text=True)
        if res.returncode == 0:
            print(f"  {GREEN}✓{RESET} Granted {perm.split('.')[-1]}")
            count += 1
        else:
            print(f"  {DIM}○ Skipped: {perm.split('.')[-1]}{RESET}")
    print(f"{GREEN}✓ Granted {count} permissions successfully.{RESET}")


def push_test_audio() -> None:
    """Pushes audio files to /sdcard/Music and triggers MediaScanner."""
    if not check_adb_device():
        print(f"{RED}✗ No ADB device detected.{RESET}")
        return
    print(f"\n{BOLD}{CYAN}=== Push Test Music to Device ==={RESET}")
    try:
        path = input(f"{BOLD}Enter local audio file or folder path: {RESET}").strip().strip('"').strip("'")
    except (KeyboardInterrupt, EOFError):
        return
    if not path or not os.path.exists(path):
        print(f"{RED}✗ Path does not exist: {path}{RESET}")
        return

    dest = "/sdcard/Music/"
    print(f"\n{CYAN}Pushing to {dest}...{RESET}")
    res = subprocess.run(["adb", "push", path, dest])
    if res.returncode != 0:
        print(f"{RED}✗ Push failed.{RESET}")
        return
    subprocess.run(
        ["adb", "shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d", f"file://{dest}"],
        capture_output=True
    )
    print(f"{GREEN}✓ Files transferred and MediaScanner triggered!{RESET}")


def force_stop_app(pkg_config: Dict[str, str]) -> None:
    """Force stops both Debug and Release app processes."""
    if not check_adb_device():
        print(f"{RED}✗ No ADB device detected.{RESET}")
        return
    debug_pkg = pkg_config["debug_package"]
    release_pkg = pkg_config["release_package"]
    print(f"\n{CYAN}Stopping {debug_pkg} and {release_pkg}...{RESET}")
    subprocess.run(["adb", "shell", "am", "force-stop", debug_pkg], capture_output=True)
    subprocess.run(["adb", "shell", "am", "force-stop", release_pkg], capture_output=True)
    print(f"{GREEN}✓ App processes stopped.{RESET}")


def clear_app_data(pkg_config: Dict[str, str]) -> None:
    """Clears application storage data (pm clear) for active build."""
    if not check_adb_device():
        print(f"{RED}✗ No ADB device detected.{RESET}")
        return
    target = detect_target_package(pkg_config)
    print(f"\n{YELLOW}⚠️  This will reset database and settings for: {BOLD}{target}{RESET}")
    try:
        if input(f"{BOLD}Clear app data for {target}? (y/N): {RESET}").strip().lower() != "y":
            print(f"{YELLOW}Cancelled.{RESET}")
            return
    except (KeyboardInterrupt, EOFError):
        return
    subprocess.run(["adb", "shell", "pm", "clear", target])
    print(f"{GREEN}✓ App data cleared for {target}.{RESET}")


def stream_logcat(pkg_config: Dict[str, str]) -> None:
    """Streams live logcat output filtered for the active package."""
    if not check_adb_device():
        print(f"{RED}✗ No ADB device detected.{RESET}")
        return
    target = detect_target_package(pkg_config)
    print(f"\n{CYAN}Streaming logcat for {BOLD}{target}{RESET} (Ctrl+C to stop)...\n")
    try:
        subprocess.run(
            ["adb", "logcat", "-v", "time", "*:S", "Booming:V", "BoomingMusic:V", "ExoPlayer:I", f"{target}:V", "*:E"]
        )
    except KeyboardInterrupt:
        print(f"\n{YELLOW}Logcat stream stopped.{RESET}")


def show_menu(pkg_config: Dict[str, str], current_flavor: str, overridden: bool) -> None:
    """Displays the interactive CLI menu."""
    devices = get_connected_devices()
    abi = get_device_abi() if devices else None
    dev_str = f"{GREEN}● Connected: {', '.join(devices)}" + (f" [{abi}]{RESET}" if abi else f"{RESET}")
    status_str = dev_str if devices else f"{RED}○ No Device Detected{RESET}"

    rel_pkg = pkg_config["release_package"]
    dbg_pkg = pkg_config["debug_package"]
    src_label = f"{YELLOW}(Manual Override){RESET}" if overridden else f"{DIM}(Auto-detected from Gradle){RESET}"

    print(f"{BOLD}{CYAN}===================================================={RESET}")
    print(f"{BOLD}{CYAN}   🚀 Universal Android ADB Developer & Build Tool   {RESET}")
    print(f"{BOLD}{CYAN}===================================================={RESET}")
    print(f"Device:   {status_str}")
    print(f"Package:  {BOLD}{rel_pkg}{RESET} {src_label}")
    print(f"Debug ID: {DIM}{dbg_pkg}{RESET}")
    print(f"Flavor:   {MAGENTA}{current_flavor}{RESET} {DIM}(Available: {', '.join(FLAVORS)}){RESET}\n")
    print(f"  {BOLD}{GREEN}[1]{RESET}  🔨 Build Debug APK, Install & Run {DIM}({current_flavor}Debug){RESET}")
    print(f"  {BOLD}{GREEN}[2]{RESET}  ⚡ Install Existing Debug APK {DIM}(Fast, No Build){RESET}")
    print(f"  {BOLD}{GREEN}[3]{RESET}  🧹 Clean Install Debug APK {DIM}(Uninstall first & Run){RESET}")
    print(f"  {BOLD}{MAGENTA}[4]{RESET}  📦 Build Release APK, Install & Run {DIM}({current_flavor}Release){RESET}")
    print(f"  {BOLD}{MAGENTA}[5]{RESET}  🚀 Install Existing Release APK {DIM}(Fast, No Build){RESET}")
    print(f"  {BOLD}{CYAN}[6]{RESET}  🔑 Grant Audio & Media Permissions")
    print(f"  {BOLD}{CYAN}[7]{RESET}  🎧 Push Test Audio/Music to /sdcard/Music")
    print(f"  {BOLD}{YELLOW}[8]{RESET}  🛑 Force Stop App")
    print(f"  {BOLD}{YELLOW}[9]{RESET}  🗑️ Clear App Data {DIM}(pm clear){RESET}")
    print(f"  {BOLD}{CYAN}[10]{RESET} 📜 Stream Live Logcat {DIM}(Filtered){RESET}")
    print(f"  {BOLD}[p]{RESET}  ✏️ Override / Set Package Name")
    print(f"  {BOLD}[f]{RESET}  🔀 Switch Flavor {DIM}(current: {current_flavor}){RESET}")
    print(f"  {BOLD}[r]{RESET}  🔄 Refresh & Re-detect Config")
    print(f"  {BOLD}[q]{RESET}  🚪 Exit")
    print(f"{CYAN}----------------------------------------------------{RESET}")


def main() -> None:
    """Main CLI execution loop."""
    if os.name == "nt":
        os.system("")

    pkg_config: Dict[str, str] = detect_package_config(BOOMING_DIR)
    is_overridden: bool = False
    flavor: str = DEFAULT_FLAVOR

    while True:
        clear_screen()
        show_menu(pkg_config, flavor, is_overridden)
        try:
            choice = input(f"{BOLD}Select an option [default 1]: {RESET}").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print(f"\n{GREEN}Goodbye!{RESET}")
            sys.exit(0)

        if choice in ("", "1", "d", "debug"):
            handle_debug_flow(pkg_config, build_first=True, clean_install=False, flavor=flavor)
        elif choice == "2":
            handle_debug_flow(pkg_config, build_first=False, clean_install=False, flavor=flavor)
        elif choice in ("3", "c", "clean"):
            handle_debug_flow(pkg_config, build_first=True, clean_install=True, flavor=flavor)
        elif choice in ("4", "release"):
            handle_release_flow(pkg_config, build_first=True, flavor=flavor)
        elif choice == "5":
            handle_release_flow(pkg_config, build_first=False, flavor=flavor)
        elif choice in ("6", "perm", "permissions"):
            grant_audio_permissions(pkg_config)
        elif choice in ("7", "music", "audio", "push"):
            push_test_audio()
        elif choice in ("8", "stop"):
            force_stop_app(pkg_config)
        elif choice in ("9", "clear"):
            clear_app_data(pkg_config)
        elif choice in ("10", "log", "logcat"):
            stream_logcat(pkg_config)
        elif choice in ("p", "package", "pkg"):
            print(f"\nCurrent Package: {pkg_config['release_package']}")
            try:
                new_pkg = input("Enter new package name (or blank to re-detect from Gradle): ").strip()
                if new_pkg:
                    pkg_config["release_package"] = new_pkg
                    pkg_config["debug_package"] = f"{new_pkg}.debug"
                    is_overridden = True
                    print(f"{GREEN}✓ Package overridden to: {new_pkg}{RESET}")
                else:
                    pkg_config = detect_package_config(BOOMING_DIR)
                    is_overridden = False
                    print(f"{GREEN}✓ Re-detected from Gradle: {pkg_config['release_package']}{RESET}")
            except (KeyboardInterrupt, EOFError):
                pass
        elif choice in ("f", "flavor"):
            print(f"\nAvailable flavors: {', '.join(FLAVORS)}")
            try:
                new_flv = input(f"Enter flavor ({', '.join(FLAVORS)}): ").strip().lower()
                if new_flv in FLAVORS:
                    flavor = new_flv
                    print(f"{GREEN}✓ Flavor changed to: {flavor}{RESET}")
                else:
                    print(f"{RED}Invalid flavor.{RESET}")
            except (KeyboardInterrupt, EOFError):
                pass
        elif choice in ("r", "refresh"):
            if not is_overridden:
                pkg_config = detect_package_config(BOOMING_DIR)
            continue
        elif choice in ("q", "exit", "quit"):
            print(f"\n{GREEN}Goodbye!{RESET}")
            break
        else:
            print(f"{RED}Invalid option: '{choice}'{RESET}")

        print(f"\n{YELLOW}Press Enter to return to menu...{RESET}", end="")
        try:
            input()
        except (KeyboardInterrupt, EOFError):
            break


if __name__ == "__main__":
    main()
