#!/usr/bin/env python3
"""
Xcode Project & Workspace discovery, scheme/configuration parsing,
build settings inspection, Info.plist reading, and variant resolution.
Zero external dependencies (Python stdlib + Apple native CLI tools).
"""

import json
import re
import subprocess
import sys
import plistlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import ConfigManager
from . import ui


@dataclass
class XcodeListInfo:
    name: str
    schemes: List[str] = field(default_factory=list)
    configurations: List[str] = field(default_factory=list)
    targets: List[str] = field(default_factory=list)
    path: Path = field(default_factory=Path)
    is_workspace: bool = False
    uses_targets_as_schemes: bool = False
    all_schemes: List[str] = field(default_factory=list)
    scheme_launch_configs: Dict[str, str] = field(default_factory=dict)


@dataclass
class XcodeVariantInfo:
    scheme: str
    configuration: str
    use_target: bool = False
    project_path: Optional[Path] = field(default=None, compare=False)

    @property
    def name(self) -> str:
        return f"{self.scheme} ({self.configuration})"

    def format_label(self) -> str:
        cfg_color = ui.Colors.CYAN if self.configuration.lower() == "debug" else ui.Colors.YELLOW
        kind = "target" if self.use_target else "config"
        if self.use_target:
            return (
                f"{ui.Colors.BOLD}{self.scheme}{ui.Colors.RESET} "
                f"(target, config: {cfg_color}{self.configuration}{ui.Colors.RESET})"
            )
        return (
            f"{ui.Colors.BOLD}{self.scheme}{ui.Colors.RESET} "
            f"({kind}: {cfg_color}{self.configuration}{ui.Colors.RESET})"
        )


_BUILD_SETTINGS_CACHE: Dict[Tuple[str, str, str, str], Dict[str, str]] = {}


def clear_build_settings_cache() -> None:
    """Clear the in-memory xcodebuild -showBuildSettings cache."""
    _BUILD_SETTINGS_CACHE.clear()


def get_active_xcode_path() -> Optional[Path]:
    """Return the active .xcworkspace or .xcodeproj path from ConfigManager."""
    return ConfigManager.get_instance().project_context.active_xcode_path


def xcode_project_flag(xcode_path: Path) -> List[str]:
    """Return ['-workspace', path] for .xcworkspace else ['-project', path]."""
    if xcode_path.suffix == ".xcworkspace":
        return ["-workspace", str(xcode_path)]
    return ["-project", str(xcode_path)]


def _extract_json_payload(raw_text: str) -> Optional[dict]:
    """Parse JSON from xcodebuild output, tolerating leading/trailing log noise."""
    if not raw_text:
        return None
    text = raw_text.strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _read_sibling_xcodeproj_configurations(workspace_path: Path) -> List[str]:
    """
    Best-effort fallback: if a workspace JSON omits `configurations`, inspect a
    sibling `.xcodeproj` in the same directory using `xcodebuild -list -json`.
    """
    parent = workspace_path.parent
    if not parent.is_dir():
        return []

    sibling_projects: List[Path] = []
    try:
        for entry in sorted(parent.iterdir()):
            if entry.is_dir() and entry.name.endswith(".xcodeproj") and entry.name != "Pods.xcodeproj":
                sibling_projects.append(entry)
    except OSError:
        return []

    if not sibling_projects:
        return []

    # Prefer project matching workspace stem
    preferred = [p for p in sibling_projects if p.stem == workspace_path.stem]
    target_proj = preferred[0] if preferred else sibling_projects[0]

    try:
        xcodebuild = ConfigManager.get_instance().get_xcodebuild_path()
    except FileNotFoundError:
        return []

    try:
        res = subprocess.run(
            [xcodebuild, "-list", "-json", "-project", str(target_proj)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if res.returncode != 0:
            return []
        data = _extract_json_payload(res.stdout)
        if not data:
            return []
        proj_data = data.get("project")
        if isinstance(proj_data, dict):
            configs = proj_data.get("configurations") or []
            return [str(c) for c in configs if c]
    except (OSError, subprocess.SubprocessError):
        return []
    return []


def parse_xcodebuild_list_json(raw_json: str, xcode_path: Path) -> XcodeListInfo:
    """
    Parse JSON output from `xcodebuild -list -json`.
    Handles both `{"workspace": ...}` and `{"project": ...}`.
    Defaults configurations to `["Debug", "Release"]` if omitted.
    """
    data = _extract_json_payload(raw_json)
    if not data:
        raise ValueError(f"Không thể phân tích dữ liệu JSON từ xcodebuild -list cho {xcode_path.name}.")

    is_workspace = xcode_path.suffix == ".xcworkspace" or "workspace" in data
    section = data.get("workspace") if "workspace" in data else data.get("project")
    if not isinstance(section, dict):
        section = {}

    name = str(section.get("name") or xcode_path.stem)
    schemes = [str(s) for s in (section.get("schemes") or []) if s]
    configurations = [str(c) for c in (section.get("configurations") or []) if c]
    targets = [str(t) for t in (section.get("targets") or []) if t]

    if not configurations and is_workspace:
        configurations = _read_sibling_xcodeproj_configurations(xcode_path)

    if not configurations:
        configurations = ["Debug", "Release"]

    return XcodeListInfo(
        name=name,
        schemes=schemes,
        configurations=configurations,
        targets=targets,
        path=xcode_path,
        is_workspace=is_workspace,
    )


def _find_sibling_xcodeproj(workspace_path: Path) -> Optional[Path]:
    """Find a sibling .xcodeproj next to a .xcworkspace (preferring matching stem)."""
    parent = workspace_path.parent
    if not parent.is_dir():
        return None
    sibling_projects: List[Path] = []
    try:
        for entry in sorted(parent.iterdir()):
            if entry.is_dir() and entry.name.endswith(".xcodeproj") and entry.name != "Pods.xcodeproj":
                sibling_projects.append(entry)
    except OSError:
        return None
    if not sibling_projects:
        return None
    preferred = [p for p in sibling_projects if p.stem == workspace_path.stem]
    return preferred[0] if preferred else sibling_projects[0]


def _find_scheme_files_map(xcode_path: Path) -> Dict[str, Path]:
    """Map scheme name -> `.xcscheme` Path across xcshareddata and xcuserdata."""
    search_bundles = [xcode_path]
    if xcode_path.suffix == ".xcworkspace":
        sib = _find_sibling_xcodeproj(xcode_path)
        if sib:
            search_bundles.append(sib)

    found: Dict[str, Path] = {}
    for bundle in search_bundles:
        dirs = [bundle / "xcshareddata" / "xcschemes"]
        xcuserdata = bundle / "xcuserdata"
        if xcuserdata.is_dir():
            try:
                for user_dir in sorted(xcuserdata.iterdir()):
                    if user_dir.is_dir():
                        dirs.append(user_dir / "xcschemes")
            except OSError:
                pass

        for d in dirs:
            if not d.is_dir():
                continue
            try:
                for f in sorted(d.glob("*.xcscheme")):
                    if f.stem and f.stem not in found:
                        found[f.stem] = f
            except OSError:
                pass
    return found


def _scan_schemes_on_disk(xcode_path: Path) -> List[str]:
    """
    Fast disk scan for `.xcscheme` files in `xcshareddata/xcschemes` and
    `xcuserdata/*/xcschemes` (including sibling `.xcodeproj` for workspaces).
    """
    return list(_find_scheme_files_map(xcode_path).keys())


def _inspect_xcscheme_xml(xcscheme_path: Path) -> Tuple[bool, Optional[str]]:
    """
    Inspect an `.xcscheme` XML file using stdlib ElementTree.
    Returns `(is_main_app, launch_build_configuration)`:
      - `is_main_app` is False for App Extensions (`wasCreatedForAppExtension="YES"` or `.appex`),
        frameworks/libraries (`.framework`, `.a`, `.dylib`), and test bundles (`.xctest`).
      - `launch_build_configuration` is the `buildConfiguration` attribute on `<LaunchAction>`.
    """
    try:
        tree = ET.parse(xcscheme_path)
        root = tree.getroot()
    except Exception:
        return True, None

    if str(root.attrib.get("wasCreatedForAppExtension", "")).upper() == "YES":
        return False, None

    launch_action = root.find("LaunchAction")
    launch_cfg = launch_action.attrib.get("buildConfiguration") if launch_action is not None else None

    # Check if primary buildable in BuildAction is an extension / framework / test
    build_entries = root.findall(".//BuildActionEntries/BuildActionEntry/BuildableReference")
    if build_entries:
        first_buildable = str(build_entries[0].attrib.get("BuildableName") or "").lower()
        if first_buildable.endswith((".appex", ".xctest", ".framework", ".a", ".dylib")):
            return False, launch_cfg

    # Check LaunchAction's BuildableProductRunnable
    if launch_action is not None:
        runnable_ref = launch_action.find(".//BuildableProductRunnable/BuildableReference")
        if runnable_ref is not None:
            bname = str(runnable_ref.attrib.get("BuildableName") or "").lower()
            if bname.endswith(".app") and not bname.endswith(("tests.app", "uitests.app", "-runner.app")):
                return True, launch_cfg
            if bname.endswith((".appex", ".xctest", ".framework")):
                return False, launch_cfg
        # If LaunchAction has RemoteRunnable without BuildableProductRunnable, it's typically an extension
        if launch_action.find("RemoteRunnable") is not None and launch_action.find("BuildableProductRunnable") is None:
            return False, launch_cfg

    return True, launch_cfg


def _parse_pbxproj_app_targets(xcodeproj_path: Path) -> List[str]:
    """Return target names whose `productType` is `com.apple.product-type.application`."""
    pbx = xcodeproj_path / "project.pbxproj"
    if not pbx.is_file():
        return []
    try:
        content = pbx.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    target_section = re.search(
        r"/\*\s*Begin PBXNativeTarget section\s*\*/(.*?)/\*\s*End PBXNativeTarget section\s*\*/",
        content,
        re.DOTALL,
    )
    if not target_section:
        return []

    app_targets: List[str] = []
    # Match each target block inside PBXNativeTarget section
    for m in re.finditer(r"isa\s*=\s*PBXNativeTarget;(.*?)\n\s*\};", target_section.group(1), re.DOTALL):
        block = m.group(1)
        if "com.apple.product-type.application" not in block:
            continue
        name_m = re.search(r'name\s*=\s*"?([^";\n]+)"?;', block)
        if name_m:
            t_name = name_m.group(1).strip()
            if t_name and t_name not in app_targets:
                app_targets.append(t_name)
    return app_targets


def _filter_main_app_schemes(
    schemes: List[str],
    xcode_path: Path,
) -> Tuple[List[str], Dict[str, str]]:
    """
    Filter schemes down to main runnable App schemes (excluding Widgets, Share Extensions,
    Frameworks, and Tests), and collect each scheme's `<LaunchAction buildConfiguration>`.
    Falls back to the full list if no scheme is identified as a main app.
    """
    scheme_files = _find_scheme_files_map(xcode_path)
    pbx_proj = _find_sibling_xcodeproj(xcode_path) if xcode_path.suffix == ".xcworkspace" else xcode_path
    app_targets = set(_parse_pbxproj_app_targets(pbx_proj)) if (pbx_proj and pbx_proj.suffix == ".xcodeproj") else set()

    main_schemes: List[str] = []
    launch_configs: Dict[str, str] = {}

    for s in schemes:
        sf = scheme_files.get(s)
        if sf is not None:
            is_app, lcfg = _inspect_xcscheme_xml(sf)
            if lcfg:
                launch_configs[s] = lcfg
            if is_app:
                main_schemes.append(s)
        else:
            # No .xcscheme file on disk: use pbxproj app targets if known, else skip obvious extensions/tests
            s_lower = s.lower()
            if app_targets:
                if s in app_targets:
                    main_schemes.append(s)
            elif not s_lower.endswith(("extension", "widgets", "widget", "tests", "uitests", "test")):
                main_schemes.append(s)

    return (main_schemes if main_schemes else list(schemes)), launch_configs


def _parse_pbxproj_targets_and_configs(xcodeproj_path: Path) -> Tuple[List[str], List[str]]:
    """
    Parse target names and build configuration names directly from `project.pbxproj`.
    Used as a zero-latency fallback when `xcodebuild -list -json` fails or returns no schemes
    (very common in freshly cloned KMP projects without committed `.xcscheme` files).
    """
    pbx = xcodeproj_path / "project.pbxproj"
    if not pbx.is_file():
        return [], []

    try:
        content = pbx.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return [], []

    targets: List[str] = []
    seen_targets = set()
    target_section = re.search(
        r"/\*\s*Begin PBXNativeTarget section\s*\*/(.*?)/\*\s*End PBXNativeTarget section\s*\*/",
        content,
        re.DOTALL,
    )
    if target_section:
        for m in re.finditer(r'isa\s*=\s*PBXNativeTarget;.*?name\s*=\s*"?([^";\n]+)"?;', target_section.group(1), re.DOTALL):
            t_name = m.group(1).strip()
            if t_name and t_name not in seen_targets:
                seen_targets.add(t_name)
                targets.append(t_name)

    configs: List[str] = []
    seen_configs = set()
    cfg_section = re.search(
        r"/\*\s*Begin XCBuildConfiguration section\s*\*/(.*?)/\*\s*End XCBuildConfiguration section\s*\*/",
        content,
        re.DOTALL,
    )
    if cfg_section:
        for m in re.finditer(r'isa\s*=\s*XCBuildConfiguration;.*?name\s*=\s*"?([^";\n]+)"?;', cfg_section.group(1), re.DOTALL):
            c_name = m.group(1).strip()
            if c_name and c_name not in seen_configs:
                seen_configs.add(c_name)
                configs.append(c_name)

    return targets, configs


def _filter_runnable_targets(targets: List[str]) -> List[str]:
    """Prefer non-test targets when falling back to targets as schemes."""
    if not targets:
        return []
    non_test = [
        t for t in targets
        if not t.lower().endswith(("tests", "uitests", "test"))
    ]
    return non_test if non_test else targets


def _run_xcodebuild_list(xcode_path: Path, xcodebuild: str) -> Optional[XcodeListInfo]:
    cmd = [xcodebuild, "-list", "-json", *xcode_project_flag(xcode_path)]
    try:
        res = subprocess.run(
            cmd,
            cwd=str(xcode_path.parent) if xcode_path.parent.is_dir() else None,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        ui.warning(f"xcodebuild -list gặp lỗi với {xcode_path.name}: {exc}")
        return None

    if res.returncode != 0:
        err_msg = (res.stderr or res.stdout or "").strip()
        if err_msg:
            ui.warning(f"xcodebuild -list ({xcode_path.name}): {err_msg.splitlines()[0]}")
        return None

    try:
        return parse_xcodebuild_list_json(res.stdout, xcode_path)
    except ValueError:
        return None


def get_xcode_list_info(xcode_path: Optional[Path] = None) -> Optional[XcodeListInfo]:
    """
    Discover schemes, configurations, and targets for the active Xcode project/workspace.
    Multi-stage resilience for Native Xcode and KMP projects:
      1. `xcodebuild -list -json` on active workspace/project.
      2. If workspace has no schemes or fails, try sibling `.xcodeproj`.
      3. Scan `.xcscheme` files directly on disk.
      4. Fallback to Xcode targets (`xcodebuild -list` targets or `project.pbxproj`) for
         fresh KMP projects that have never been opened in Xcode IDE (no `.xcscheme` yet).
    """
    target_path = xcode_path or get_active_xcode_path()
    if target_path is None:
        return None

    xcodebuild: Optional[str] = None
    try:
        xcodebuild = ConfigManager.get_instance().get_xcodebuild_path()
    except FileNotFoundError as exc:
        ui.error(str(exc))

    info: Optional[XcodeListInfo] = None
    if xcodebuild:
        info = _run_xcodebuild_list(target_path, xcodebuild)

    # If workspace failed or yielded 0 schemes, switch to sibling .xcodeproj
    sibling_proj = _find_sibling_xcodeproj(target_path) if target_path.suffix == ".xcworkspace" else None
    if (info is None or not info.schemes) and sibling_proj and xcodebuild:
        sib_info = _run_xcodebuild_list(sibling_proj, xcodebuild)
        if sib_info:
            if info is None or not info.schemes:
                info = sib_info
            else:
                if not info.targets and sib_info.targets:
                    info.targets = sib_info.targets
                if (not info.configurations or info.configurations == ["Debug", "Release"]) and sib_info.configurations:
                    info.configurations = sib_info.configurations

    # Ensure we have an XcodeListInfo object even if xcodebuild -list failed
    if info is None:
        info = XcodeListInfo(
            name=target_path.stem,
            schemes=[],
            configurations=["Debug", "Release"],
            targets=[],
            path=target_path,
            is_workspace=(target_path.suffix == ".xcworkspace"),
        )

    # Fallback 1: Scan .xcscheme files directly on disk
    if not info.schemes:
        disk_schemes = _scan_schemes_on_disk(target_path)
        if disk_schemes:
            info.schemes = disk_schemes
            if target_path.suffix == ".xcworkspace" and sibling_proj:
                info.path = sibling_proj
                info.is_workspace = False

    # Fallback 2: Parse project.pbxproj for targets & configs if still empty
    pbx_project = sibling_proj if target_path.suffix == ".xcworkspace" else target_path
    if (not info.schemes and not info.targets) and pbx_project and pbx_project.suffix == ".xcodeproj":
        pbx_targets, pbx_configs = _parse_pbxproj_targets_and_configs(pbx_project)
        if pbx_targets:
            info.targets = pbx_targets
        if pbx_configs:
            info.configurations = pbx_configs

    # Fallback 3: Use app targets when no .xcscheme exists (common in freshly cloned KMP projects)
    if not info.schemes and info.targets:
        app_targets = _parse_pbxproj_app_targets(pbx_project) if (pbx_project and pbx_project.suffix == ".xcodeproj") else []
        runnable = app_targets if app_targets else _filter_runnable_targets(info.targets)
        info.schemes = runnable
        info.uses_targets_as_schemes = True
        if pbx_project and pbx_project.suffix == ".xcodeproj":
            info.path = pbx_project
            info.is_workspace = False

    # Filter schemes to main runnable App schemes (exclude Widgets, Share Extensions, Tests, Frameworks)
    if info.schemes:
        info.all_schemes = list(info.schemes)
        if not info.uses_targets_as_schemes:
            filtered, launch_cfgs = _filter_main_app_schemes(info.schemes, info.path)
            info.schemes = filtered
            info.scheme_launch_configs = launch_cfgs

    return info


_SETTING_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.*)$")


def parse_build_settings_output(raw_output: str) -> Dict[str, str]:
    """Parse `KEY = VALUE` lines from `xcodebuild -showBuildSettings`."""
    settings: Dict[str, str] = {}
    if not raw_output:
        return settings

    for line in raw_output.splitlines():
        m = _SETTING_LINE_RE.match(line)
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()
            settings[key] = val
    return settings


def get_build_settings(
    scheme: str,
    configuration: str = "Debug",
    sdk: str = "iphonesimulator",
    xcode_path: Optional[Path] = None,
) -> Dict[str, str]:
    """
    Run `xcodebuild -showBuildSettings` for the given scheme/configuration/sdk
    and cache the parsed key/value dict in memory.
    """
    target_path = xcode_path or get_active_xcode_path()
    if target_path is None:
        return {}

    cache_key = (str(target_path), scheme, configuration, sdk)
    if cache_key in _BUILD_SETTINGS_CACHE:
        return dict(_BUILD_SETTINGS_CACHE[cache_key])

    try:
        xcodebuild = ConfigManager.get_instance().get_xcodebuild_path()
    except FileNotFoundError:
        return {}

    cmd = [
        xcodebuild,
        "-showBuildSettings",
        *xcode_project_flag(target_path),
        "-scheme",
        scheme,
        "-configuration",
        configuration,
        "-sdk",
        sdk,
    ]
    try:
        res = subprocess.run(
            cmd,
            cwd=str(target_path.parent) if target_path.parent.is_dir() else None,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    if res.returncode != 0:
        return {}

    parsed = parse_build_settings_output(res.stdout)
    _BUILD_SETTINGS_CACHE[cache_key] = parsed
    return dict(parsed)


def read_app_plist_info(app_path: Path) -> Dict[str, str]:
    """
    Read `<app_path>/Info.plist` using stdlib `plistlib` and extract:
      - bundle_id (CFBundleIdentifier)
      - display_name (CFBundleDisplayName or CFBundleName)
      - executable (CFBundleExecutable)
      - version (CFBundleShortVersionString)
    """
    plist_file = app_path if app_path.is_file() and app_path.name == "Info.plist" else (app_path / "Info.plist")
    if not plist_file.is_file():
        return {}

    try:
        with open(plist_file, "rb") as fp:
            data = plistlib.load(fp)
    except Exception:
        return {}

    if not isinstance(data, dict):
        return {}

    return {
        "bundle_id": str(data.get("CFBundleIdentifier") or ""),
        "display_name": str(data.get("CFBundleDisplayName") or data.get("CFBundleName") or ""),
        "executable": str(data.get("CFBundleExecutable") or ""),
        "version": str(data.get("CFBundleShortVersionString") or ""),
    }


def detect_ios_bundle_id(
    scheme: Optional[str] = None,
    configuration: str = "Debug",
    app_path: Optional[Path] = None,
    xcode_path: Optional[Path] = None,
) -> Optional[str]:
    """
    Detect iOS Bundle Identifier:
      1. From built `<app_path>/Info.plist` if provided.
      2. From `xcodebuild -showBuildSettings` (`PRODUCT_BUNDLE_IDENTIFIER`).
    """
    if app_path is not None:
        plist_info = read_app_plist_info(app_path)
        bid = plist_info.get("bundle_id")
        if bid:
            return bid

    resolved_scheme = scheme
    if not resolved_scheme:
        cfg = ConfigManager.get_instance()
        resolved_scheme = cfg.get_selected_xcode_scheme()
        if not resolved_scheme:
            info = get_xcode_list_info(xcode_path=xcode_path)
            if info and info.schemes:
                resolved_scheme = info.schemes[0]

    if not resolved_scheme:
        return None

    settings = get_build_settings(
        scheme=resolved_scheme,
        configuration=configuration,
        xcode_path=xcode_path,
    )
    bid = settings.get("PRODUCT_BUNDLE_IDENTIFIER")
    return bid if bid else None


def _order_configurations(configurations: List[str]) -> List[str]:
    """Order configurations with Debug first, custom configs next, Release last."""
    debug_cfgs = [c for c in configurations if c.lower() == "debug"]
    release_cfgs = [c for c in configurations if c.lower() == "release"]
    other_cfgs = [c for c in configurations if c.lower() not in ("debug", "release")]
    return debug_cfgs + other_cfgs + release_cfgs


def _pick_default_configuration(configurations: List[str], saved_config: Optional[str]) -> str:
    cfg_map = {c.lower(): c for c in configurations}
    if saved_config and saved_config.lower() in cfg_map:
        return cfg_map[saved_config.lower()]
    if "debug" in cfg_map:
        return cfg_map["debug"]
    return configurations[0]


def _variant_default_index(variants: List[XcodeVariantInfo], saved_scheme: Optional[str]) -> str:
    if saved_scheme:
        saved_lower = saved_scheme.lower()
        for idx, v in enumerate(variants):
            if v.scheme.lower() == saved_lower and v.configuration.lower() == "debug":
                return str(idx + 1)
        for idx, v in enumerate(variants):
            if v.scheme.lower() == saved_lower:
                return str(idx + 1)
    return "1"


def _prompt_xcode_variant_selection(
    variants: List[XcodeVariantInfo],
    title: str,
    action_verb: str = "Run",
) -> List[XcodeVariantInfo]:
    options = [(v.name, v.format_label()) for v in variants]
    unique_configs = list(dict.fromkeys(v.configuration.lower() for v in variants))
    debug_variants = [v.name for v in variants if v.configuration.lower() == "debug"]

    extra_presets = None
    if len(unique_configs) > 1 and debug_variants:
        extra_presets = {
            "d": (f"⚡ {action_verb} all debug ({len(debug_variants)} bản Debug)", debug_variants)
        }

    cfg = ConfigManager.get_instance()
    saved_scheme = cfg.get_selected_xcode_scheme()
    default_choice = _variant_default_index(variants, saved_scheme)

    chosen_names = ui.ask_multiselect(
        title=title,
        options=options,
        all_label=f"⚡ {action_verb} all (Tất cả {len(variants)} variants)",
        default=default_choice,
        extra_presets=extra_presets,
    )

    chosen_set = {name.lower() for name in chosen_names}
    selected = [v for v in variants if v.name.lower() in chosen_set]
    return selected if selected else [variants[0]]


def resolve_target_xcode_variants(
    scheme_arg: Optional[str] = None,
    config_arg: Optional[str] = None,
    interactive: bool = True,
    action_verb: str = "Run",
    xcode_path: Optional[Path] = None,
) -> List[XcodeVariantInfo]:
    """
    Resolve target Xcode Scheme x Configuration variants, mirroring
    `core.gradle.resolve_target_variants`.
    """
    info = get_xcode_list_info(xcode_path=xcode_path)
    if not info or not info.schemes:
        detected = xcode_path or get_active_xcode_path()
        ui.error(f"Không tìm thấy Xcode Scheme hoặc Target nào trong: {detected or '(không xác định)'}")
        ui.info("Gợi ý: chạy 'flash module list --ios' để kiểm tra project, hoặc mở project trong Xcode / chạy 'flash sync --ios'.")
        sys.exit(1)

    use_target = info.uses_targets_as_schemes
    resolved_proj_path = info.path or xcode_path
    if use_target:
        ui.info(f"Chưa có file .xcscheme, tự động dùng Xcode Target từ {info.path.name}: {', '.join(info.schemes)}")

    schemes = info.schemes
    all_schemes = info.all_schemes or schemes
    launch_cfgs = info.scheme_launch_configs or {}
    configs = _order_configurations(info.configurations or ["Debug", "Release"])

    scheme_map = {s.lower(): s for s in schemes}
    all_scheme_map = {s.lower(): s for s in all_schemes}
    config_map = {c.lower(): c for c in configs}

    cfg = ConfigManager.get_instance()
    saved_scheme = cfg.get_selected_xcode_scheme()
    saved_config = cfg.get_selected_xcode_config()
    default_config = _pick_default_configuration(configs, saved_config)

    matched_config: Optional[str] = None
    if config_arg:
        if config_arg.lower() not in config_map:
            ui.error(
                f"Configuration '{config_arg}' không tồn tại. "
                f"Các configurations hiện có: {', '.join(configs)}"
            )
            sys.exit(1)
        matched_config = config_map[config_arg.lower()]

    if scheme_arg:
        if scheme_arg.lower() not in all_scheme_map:
            ui.error(
                f"Scheme '{scheme_arg}' không tồn tại. "
                f"Các schemes hiện có: {', '.join(schemes)}"
            )
            sys.exit(1)
        matched_scheme = all_scheme_map[scheme_arg.lower()]
        scheme_default_cfg = launch_cfgs.get(matched_scheme)
        target_cfg = matched_config or (
            config_map[scheme_default_cfg.lower()]
            if scheme_default_cfg and scheme_default_cfg.lower() in config_map
            else default_config
        )
        return [XcodeVariantInfo(scheme=matched_scheme, configuration=target_cfg, use_target=use_target, project_path=resolved_proj_path)]

    # No explicit scheme_arg provided
    if matched_config:
        if len(schemes) == 1:
            return [XcodeVariantInfo(scheme=schemes[0], configuration=matched_config, use_target=use_target, project_path=resolved_proj_path)]
        if not interactive:
            if saved_scheme and saved_scheme.lower() in scheme_map:
                return [XcodeVariantInfo(scheme=scheme_map[saved_scheme.lower()], configuration=matched_config, use_target=use_target, project_path=resolved_proj_path)]
            return [XcodeVariantInfo(scheme=schemes[0], configuration=matched_config, use_target=use_target, project_path=resolved_proj_path)]

        filtered_variants = [
            XcodeVariantInfo(scheme=s, configuration=matched_config, use_target=use_target, project_path=resolved_proj_path)
            for s in schemes
        ]
        return _prompt_xcode_variant_selection(
            filtered_variants,
            title=f"Chọn Xcode Scheme để {action_verb} ({matched_config}):",
            action_verb=action_verb,
        )

    # Neither scheme_arg nor config_arg provided
    is_standard_configs = {c.lower() for c in configs}.issubset({"debug", "release"})
    if len(schemes) == 1 and is_standard_configs:
        s0 = schemes[0]
        lcfg = launch_cfgs.get(s0)
        t_cfg = config_map[lcfg.lower()] if (lcfg and lcfg.lower() in config_map) else default_config
        return [XcodeVariantInfo(scheme=s0, configuration=t_cfg, use_target=use_target, project_path=resolved_proj_path)]

    if not interactive:
        if saved_scheme and saved_scheme.lower() in scheme_map:
            s_saved = scheme_map[saved_scheme.lower()]
            lcfg = launch_cfgs.get(s_saved)
            t_cfg = config_map[lcfg.lower()] if (lcfg and lcfg.lower() in config_map) else default_config
            return [XcodeVariantInfo(scheme=s_saved, configuration=t_cfg, use_target=use_target, project_path=resolved_proj_path)]
        s0 = schemes[0]
        lcfg = launch_cfgs.get(s0)
        t_cfg = config_map[lcfg.lower()] if (lcfg and lcfg.lower() in config_map) else default_config
        return [XcodeVariantInfo(scheme=s0, configuration=t_cfg, use_target=use_target, project_path=resolved_proj_path)]

    # If multiple main app schemes already specify distinct LaunchAction configurations
    # (e.g., `iosApp (Debug)` -> Debug, `iosApp (prod)` -> Release), show 1 clean entry per scheme!
    scheme_cfgs_present = [launch_cfgs.get(s) for s in schemes if launch_cfgs.get(s)]
    if len(schemes) > 1 and len(scheme_cfgs_present) == len(schemes) and len({c.lower() for c in scheme_cfgs_present}) > 1:
        all_variants = [
            XcodeVariantInfo(
                scheme=s,
                configuration=config_map.get(launch_cfgs[s].lower(), launch_cfgs[s]),
                use_target=use_target,
                project_path=resolved_proj_path,
            )
            for s in schemes
        ]
    else:
        all_variants = []
        for c in configs:
            for s in schemes:
                all_variants.append(XcodeVariantInfo(scheme=s, configuration=c, use_target=use_target, project_path=resolved_proj_path))

    return _prompt_xcode_variant_selection(
        all_variants,
        title=f"Chọn Xcode Scheme & Configuration để {action_verb}:",
        action_verb=action_verb,
    )
