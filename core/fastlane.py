#!/usr/bin/env python3
"""
Fastlane configuration discovery, Fastfile parser, and execution command builder.
Zero external dependencies.
"""

import os
import re
import shutil
from pathlib import Path
from typing import List, Optional, Tuple
from .config import ConfigManager

class FastlaneLane:
    def __init__(
        self,
        name: str,
        platform: Optional[str] = None,
        description: str = "",
        is_private: bool = False,
        line_number: int = 0
    ):
        self.name = name
        self.platform = platform
        self.description = description
        self.is_private = is_private
        self.line_number = line_number

    @property
    def qualified_name(self) -> str:
        if self.platform:
            return f"{self.platform} {self.name}"
        return self.name

    def get_exec_command(self, use_bundler: bool = True, default_platform: Optional[str] = None) -> List[str]:
        """
        Build executable CLI command tokens.
        If Bundler is enabled: ['bundle', 'exec', 'fastlane', ...]
        Otherwise: ['fastlane', ...]
        """
        cmd = ["bundle", "exec", "fastlane"] if use_bundler else ["fastlane"]
        
        # Include platform if lane is explicitly scoped to a non-default platform
        if self.platform and (default_platform is None or self.platform != default_platform):
            cmd.extend([self.platform, self.name])
        else:
            cmd.append(self.name)
        return cmd

    def __repr__(self) -> str:
        return f"FastlaneLane(name={self.name!r}, platform={self.platform!r}, private={self.is_private})"


class FastlaneConfig:
    def __init__(
        self,
        fastfile_path: Path,
        gemfile_path: Optional[Path],
        working_dir: Path,
        project_root: Path,
        default_platform: Optional[str],
        lanes: List[FastlaneLane],
        has_bundler: bool
    ):
        self.fastfile_path = fastfile_path
        self.gemfile_path = gemfile_path
        self.working_dir = working_dir
        self.project_root = project_root
        self.default_platform = default_platform
        self.lanes = lanes
        self.has_bundler = has_bundler

    @property
    def runnable_lanes(self) -> List[FastlaneLane]:
        """Return public lanes that can be executed directly via bundle exec / CLI."""
        return [l for l in self.lanes if not l.is_private]


def parse_fastfile(fastfile_path: Path) -> Tuple[Optional[str], List[FastlaneLane]]:
    """
    Parse a Fastfile to extract default_platform and defined lanes with their descriptions.
    """
    try:
        content = fastfile_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = fastfile_path.read_text(encoding="latin-1", errors="replace")

    default_platform = None

    # Detect default_platform(:android) or default_platform :android or default_platform "android"
    dp_m = re.search(r"default_platform\s*(?:\(\s*)?[:'\"]([a-zA-Z0-9_]+)['\"]?\s*\)?", content)
    if dp_m:
        default_platform = dp_m.group(1)

    lines = content.splitlines()
    lanes: List[FastlaneLane] = []
    current_platform: Optional[str] = None
    platform_depth = 0
    pending_desc: List[str] = []

    platform_start_re = re.compile(r"^\s*platform\s+[:'\"]([a-zA-Z0-9_]+)['\"]?\s+do\b")
    lane_re = re.compile(
        r"^\s*(private_lane|lane)\s*(?:\(\s*)?[:'\"]([a-zA-Z0-9_]+)['\"]?(?:\s*,\s*(?:\"([^\"]*)\"|'([^']*)'))?(?:\s*\))?(?:\s+do\b|\s*\{)?"
    )
    desc_re = re.compile(r"^\s*desc\s*(?:\(\s*)?(?:\"([^\"]*)\"|'([^']*)'|%[qQ]?\{([^}]*)\})(?:\s*\))?")

    # Ruby keywords that open control/block scopes
    stmt_block_re = re.compile(r"^\s*(if|unless|while|until|for)\b")

    for line_idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Check for platform start
        plat_m = platform_start_re.match(line)
        if plat_m:
            current_platform = plat_m.group(1)
            platform_depth = 1
            pending_desc = []
            continue

        # If inside a platform block, track nested scope depth
        if current_platform:
            open_count = len(re.findall(r"\b(do|begin|case|class|module|def)\b", line))
            open_count += len(stmt_block_re.findall(line))
            end_count = len(re.findall(r"\bend\b", line))

            platform_depth += open_count - end_count
            if platform_depth <= 0:
                current_platform = None
                platform_depth = 0
                pending_desc = []
                continue

        # Check desc annotation
        desc_m = desc_re.match(line)
        if desc_m:
            d_text = desc_m.group(1) or desc_m.group(2) or desc_m.group(3) or ""
            pending_desc.append(d_text.strip())
            continue

        # Check lane / private_lane definition
        lane_m = lane_re.match(line)
        if lane_m:
            lane_type = lane_m.group(1)
            lane_name = lane_m.group(2)
            inline_desc = lane_m.group(3) or lane_m.group(4) or ""
            is_private = (lane_type == "private_lane")

            desc = " ".join(pending_desc)
            if inline_desc and not desc:
                desc = inline_desc

            lanes.append(FastlaneLane(
                name=lane_name,
                platform=current_platform,
                description=desc,
                is_private=is_private,
                line_number=line_idx
            ))
            pending_desc = []
            continue

        # If other statement and not a comment or empty line, clear stale desc if we crossed unrelated statements
        if pending_desc and not desc_m:
            # Check if line looks like another variable assignment or method call that breaks desc affinity
            if any(stripped.startswith(k) for k in ("def ", "class ", "module ", "platform ")):
                pending_desc = []

    return default_platform, lanes


def find_fastlane_config(start_dir: Optional[Path] = None) -> Optional[FastlaneConfig]:
    """
    Search for Fastfile and Gemfile in current directory and project root.
    Returns FastlaneConfig if found, or None.
    """
    cfg = ConfigManager.get_instance()
    project_root = cfg.project_root or Path.cwd().resolve()
    current_dir = Path(start_dir or Path.cwd()).resolve()

    # Search candidates for Fastfile in order of priority
    candidate_roots = [
        current_dir,
        project_root,
        project_root.parent if project_root.parent != project_root else None,
    ]
    candidate_roots = [r for r in candidate_roots if r is not None]

    fastfile_subpaths = [
        Path("fastlane/Fastfile"),
        Path(".fastlane/Fastfile"),
        Path("Fastfile"),
        Path("android/fastlane/Fastfile"),
        Path("app/fastlane/Fastfile"),
        Path("fastlane/fastfile"),
        Path("fastfile"),
    ]

    fastfile_path: Optional[Path] = None
    for root in candidate_roots:
        for sub in fastfile_subpaths:
            p = (root / sub).resolve()
            if p.is_file():
                fastfile_path = p
                break
        if fastfile_path:
            break

    if not fastfile_path:
        return None

    # Search for Gemfile
    gemfile_candidates = [
        fastfile_path.parent.parent / "Gemfile",
        fastfile_path.parent / "Gemfile",
        project_root / "Gemfile",
        project_root / "android" / "Gemfile",
        project_root.parent / "Gemfile",
        current_dir / "Gemfile",
    ]

    gemfile_path: Optional[Path] = None
    for gp in gemfile_candidates:
        if gp.is_file():
            gemfile_path = gp.resolve()
            break

    # Determine execution working directory
    if gemfile_path:
        working_dir = gemfile_path.parent
    elif fastfile_path.parent.name in ("fastlane", ".fastlane"):
        working_dir = fastfile_path.parent.parent
    else:
        working_dir = fastfile_path.parent

    # Check bundler availability
    bundle_bin = shutil.which("bundle")
    has_bundler = bool(bundle_bin and gemfile_path and gemfile_path.is_file())

    default_platform, lanes = parse_fastfile(fastfile_path)

    return FastlaneConfig(
        fastfile_path=fastfile_path,
        gemfile_path=gemfile_path,
        working_dir=working_dir,
        project_root=project_root,
        default_platform=default_platform,
        lanes=lanes,
        has_bundler=has_bundler
    )
