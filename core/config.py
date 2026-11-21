#!/usr/bin/env python3
"""
Android SDK and Project Configuration Manager.
Handles SDK auto-detection, local.properties updates, and CLI configuration persistence.
"""

import os
import sys
import shutil
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from .project import ProjectContext, ProjectType, detect_project

class ConfigManager:
    _instance = None

    def __init__(self, start_dir: Optional[Path] = None):
        self.start_dir = Path(start_dir or os.getcwd()).resolve()
        self.project_context: ProjectContext = detect_project(self.start_dir)
        self.project_root = self.project_context.root
        self.config_dir = (self.project_root / ".flash") if self.project_root else (Path.home() / ".flash")
        self.config_file = self.config_dir / "config.json"
        self._ensure_config_dir()
        # Re-resolve preferred Xcode workspace/project if saved in config
        saved_xcode = self.get_selected_xcode_project()
        if saved_xcode:
            self.project_context = detect_project(self.start_dir, preferred_xcode=saved_xcode)
            self.project_root = self.project_context.root
        self.sdk_path = self._detect_sdk_path()

    @classmethod
    def get_instance(cls, start_dir: Optional[Path] = None):
        if cls._instance is None:
            cls._instance = ConfigManager(start_dir)
        return cls._instance

    def _find_project_root(self, current: Path) -> Path:
        """Find Android project root by looking for settings.gradle(.kts) or gradlew."""
        curr = current
        for _ in range(10):
            if (curr / "settings.gradle.kts").exists() or (curr / "settings.gradle").exists() or (curr / "gradlew").exists():
                return curr
            if curr.parent == curr:
                break
            curr = curr.parent
        return current

    def _detect_sdk_path(self) -> Optional[str]:
        # 1. From local.properties
        local_props = self.project_root / "local.properties"
        if local_props.exists():
            try:
                with open(local_props, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("sdk.dir="):
                            path_str = line.split("=", 1)[1].strip()
                            # Unescape backslashes and colons (e.g., C\:\\Android)
                            path_str = path_str.replace("\\:", ":").replace("\\\\", "\\")
                            if Path(path_str).exists():
                                return path_str
            except Exception:
                pass

        # 2. From environment variables
        env_sdk = os.getenv("ANDROID_HOME") or os.getenv("ANDROID_SDK_ROOT")
        if env_sdk and Path(env_sdk).exists():
            return env_sdk

        # 3. Default OS standard paths
        home = Path.home()
        candidates = []
        if sys.platform == "darwin":
            candidates = [
                home / "Library" / "Android" / "sdk",
                Path("/opt/homebrew/share/android-commandlinetools"),
            ]
        elif sys.platform == "win32":
            local_appdata = os.getenv("LOCALAPPDATA")
            if local_appdata:
                candidates.append(Path(local_appdata) / "Android" / "Sdk")
            candidates.extend([
                Path("C:/Android/sdk"),
                Path("C:/Program Files/Android/Sdk"),
            ])
        else: # Linux
            candidates = [
                home / "Android" / "Sdk",
                Path("/usr/local/android-sdk"),
                Path("/usr/lib/android-sdk"),
            ]

        for cand in candidates:
            if cand.exists():
                return str(cand)

        # 4. Fallback to where adb is located in PATH
        adb_in_path = shutil.which("adb")
        if adb_in_path:
            adb_p = Path(adb_in_path).resolve()
            if adb_p.parent.name == "platform-tools":
                return str(adb_p.parent.parent)

        return None

    def get_sdk_path(self) -> Optional[str]:
        return self.sdk_path

    def get_adb_path(self) -> str:
        if self.sdk_path:
            adb_name = "adb.exe" if sys.platform == "win32" else "adb"
            adb_file = Path(self.sdk_path) / "platform-tools" / adb_name
            if adb_file.exists():
                return str(adb_file)

        which_adb = shutil.which("adb")
        if which_adb:
            return which_adb
        raise FileNotFoundError("ADB executable not found. Please install Android Platform-Tools or set ANDROID_HOME.")

    def get_aapt_path(self) -> Optional[str]:
        """Find aapt or aapt2 executable in build-tools or PATH."""
        if self.sdk_path:
            bt_dir = Path(self.sdk_path) / "build-tools"
            if bt_dir.exists():
                versions = sorted(os.listdir(bt_dir), reverse=True)
                for ver in versions:
                    for name in ("aapt2", "aapt"):
                        exe = f"{name}.exe" if sys.platform == "win32" else name
                        cand = bt_dir / ver / exe
                        if cand.exists():
                            return str(cand)
        return shutil.which("aapt2") or shutil.which("aapt")

    def get_keytool_path(self) -> str:
        """Find keytool executable from JAVA_HOME or PATH."""
        java_home = os.getenv("JAVA_HOME")
        exe = "keytool.exe" if sys.platform == "win32" else "keytool"
        if java_home:
            cand = Path(java_home) / "bin" / exe
            if cand.exists():
                return str(cand)
        which_kt = shutil.which("keytool")
        if which_kt:
            return which_kt
        raise FileNotFoundError("keytool not found. Please ensure Java JDK is installed and JAVA_HOME or PATH is set.")

    def ensure_local_properties(self) -> bool:
        """Ensure local.properties exists with valid sdk.dir."""
        if not self.sdk_path or not self.project_root:
            return False
        local_props = self.project_root / "local.properties"
        escaped_sdk = self.sdk_path.replace("\\", "\\\\").replace(":", "\\:")
        sdk_line = f"sdk.dir={escaped_sdk}\n"

        if local_props.exists():
            try:
                content = local_props.read_text(encoding="utf-8")
                if "sdk.dir" not in content:
                    with open(local_props, "a", encoding="utf-8") as f:
                        if not content.endswith("\n"):
                            f.write("\n")
                        f.write(sdk_line)
                    return True
            except Exception:
                return False
        else:
            try:
                local_props.write_text(
                    "## This file is automatically generated by Flash CLI\n"
                    "# Do not check into Version Control Systems.\n"
                    + sdk_line,
                    encoding="utf-8"
                )
                return True
            except Exception:
                return False
        return True

    def _ensure_config_dir(self):
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def load_config(self) -> Dict[str, Any]:
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save_config(self, data: Dict[str, Any]):
        self._ensure_config_dir()
        try:
            current = self.load_config()
            current.update(data)
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(current, f, indent=2)
        except Exception:
            pass

    def get_selected_device(self) -> Optional[str]:
        return self.load_config().get("selected_device")

    def set_selected_device(self, serial: str):
        self.save_config({"selected_device": serial})

    def get_target_module(self) -> Optional[str]:
        return self.load_config().get("target_module")

    def set_target_module(self, module: Optional[str]):
        self.save_config({"target_module": module})

    def get_selected_flavor(self) -> Optional[str]:
        return self.load_config().get("selected_flavor")

    def set_selected_flavor(self, flavor: Optional[str]):
        self.save_config({"selected_flavor": flavor})

    def get_remembered_wireless_devices(self) -> List[str]:
        return self.load_config().get("wireless_devices", [])

    def remember_wireless_device(self, endpoint: str):
        devices = self.get_remembered_wireless_devices()
        if endpoint not in devices:
            devices.append(endpoint)
            self.save_config({"wireless_devices": devices})

    def forget_wireless_device(self, endpoint: str):
        devices = self.get_remembered_wireless_devices()
        if endpoint in devices:
            devices.remove(endpoint)
            self.save_config({"wireless_devices": devices})

    # --- Multi-Platform & Xcode / iOS Configuration ---

    def get_target_platform(self) -> Optional[str]:
        return self.load_config().get("target_platform")

    def set_target_platform(self, platform: Optional[str]):
        self.save_config({"target_platform": platform})

    def get_selected_ios_device(self) -> Optional[str]:
        return self.load_config().get("selected_ios_device")

    def set_selected_ios_device(self, udid: Optional[str]):
        self.save_config({"selected_ios_device": udid})

    def get_selected_xcode_scheme(self) -> Optional[str]:
        return self.load_config().get("selected_xcode_scheme")

    def set_selected_xcode_scheme(self, scheme: Optional[str]):
        self.save_config({"selected_xcode_scheme": scheme})

    def get_selected_xcode_config(self) -> Optional[str]:
        return self.load_config().get("selected_xcode_config")

    def set_selected_xcode_config(self, configuration: Optional[str]):
        self.save_config({"selected_xcode_config": configuration})

    def get_selected_xcode_project(self) -> Optional[str]:
        return self.load_config().get("selected_xcode_project")

    def set_selected_xcode_project(self, project_path: Optional[str]):
        self.save_config({"selected_xcode_project": project_path})
        self.project_context = detect_project(self.start_dir, preferred_xcode=project_path)

    def get_derived_data_path(self) -> Path:
        """Flash-isolated DerivedData path: <project_root>/.flash/DerivedData."""
        custom = self.load_config().get("xcode_derived_data_path")
        if custom:
            return Path(custom).expanduser().resolve()
        return (self.config_dir / "DerivedData").resolve()

    def get_xcodebuild_path(self) -> str:
        path = shutil.which("xcodebuild")
        if path:
            return path
        raise FileNotFoundError("Không tìm thấy 'xcodebuild'. Hãy cài đặt Xcode và chạy 'xcode-select --install'.")

    def get_xcrun_path(self) -> str:
        path = shutil.which("xcrun")
        if path:
            return path
        raise FileNotFoundError("Không tìm thấy 'xcrun'. Hãy cài đặt Xcode Command Line Tools.")

    def get_pod_path(self) -> Optional[str]:
        return shutil.which("pod")
