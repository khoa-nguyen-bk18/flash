#!/usr/bin/env python3
"""
Gradle build execution and multi-module discovery.
"""

import os
import sys
import subprocess
import re
from itertools import product
from pathlib import Path
from typing import List, Optional, Tuple
from .config import ConfigManager
from . import ui

def get_gradlew_path() -> Path:
    cfg = ConfigManager.get_instance()
    root = cfg.project_root
    if not root:
        raise FileNotFoundError("Không tìm thấy thư mục gốc của project Android.")

    wrapper_name = "gradlew.bat" if sys.platform == "win32" else "gradlew"
    wrapper_path = root / wrapper_name
    if wrapper_path.exists():
        # Ensure executable bit on Unix
        if sys.platform != "win32" and not os.access(wrapper_path, os.X_OK):
            try:
                os.chmod(wrapper_path, 0o755)  # NOSONAR: Ensure gradlew executable bit on Unix
            except Exception:
                pass
        return wrapper_path

    raise FileNotFoundError(f"Không tìm thấy '{wrapper_name}' tại {root}.")


def cap_first(name: str) -> str:
    """Capitalize only the first character, preserving inner camelCase."""
    return name[:1].upper() + name[1:] if name else ""


def lower_first(name: str) -> str:
    """Lowercase only the first character, preserving inner camelCase."""
    return name[:1].lower() + name[1:] if name else ""


class FlavorInfo:
    def __init__(self, name: str, dimension: Optional[str] = None,
                 application_id_suffix: str = "", version_name_suffix: str = "",
                 flavors: Optional[List["FlavorInfo"]] = None):
        self.name = name
        self.dimension = dimension
        self.application_id_suffix = application_id_suffix
        self.version_name_suffix = version_name_suffix
        self.flavors = flavors

    def __repr__(self) -> str:
        return f"FlavorInfo(name={self.name!r}, dimension={self.dimension!r}, suffix={self.application_id_suffix!r})"


class BuildTypeInfo:
    def __init__(self, name: str, application_id_suffix: str = "", version_name_suffix: str = ""):
        self.name = name
        self.application_id_suffix = application_id_suffix
        self.version_name_suffix = version_name_suffix

    def __repr__(self) -> str:
        return f"BuildTypeInfo(name={self.name!r}, suffix={self.application_id_suffix!r})"


class BuildVariantInfo:
    def __init__(self, name: str, build_type: str, flavor_name: Optional[str] = None,
                 flavors: Optional[List[FlavorInfo]] = None,
                 application_id_suffix: str = "", version_name_suffix: str = ""):
        self.name = name
        self.build_type = build_type
        self.flavor_name = flavor_name
        self.flavors = flavors or []
        self.application_id_suffix = application_id_suffix
        self.version_name_suffix = version_name_suffix

    @property
    def gradle_task(self) -> str:
        if self.flavor_name:
            return f"assemble{cap_first(self.flavor_name)}{cap_first(self.build_type)}"
        return f"assemble{cap_first(self.build_type)}"

    def format_label(self) -> str:
        desc_parts = []
        for f in self.flavors:
            if f.dimension:
                desc_parts.append(f"{f.dimension}: {f.name}")
            else:
                desc_parts.append(f"flavor: {f.name}")
        bt_color = ui.Colors.CYAN if self.build_type.lower() == "debug" else ui.Colors.YELLOW
        desc_parts.append(f"type: {bt_color}{self.build_type}{ui.Colors.RESET}")
        if self.application_id_suffix:
            desc_parts.append(f"suffix: {self.application_id_suffix}")
        return f"{ui.Colors.BOLD}{self.name}{ui.Colors.RESET} ({', '.join(desc_parts)})"

    def __repr__(self) -> str:
        return f"BuildVariantInfo(name={self.name!r}, build_type={self.build_type!r}, flavor_name={self.flavor_name!r})"


_NON_ENTRY_KEYWORDS = frozenset({
    "dimension", "dimensionList", "flavorDimensions", "signingConfig", "signingConfigs",
    "manifestPlaceholders", "initWith", "matchingFallbacks", "proguardFiles",
    "consumerProguardFiles", "ndk", "packaging", "packagingOptions", "externalNativeBuild",
    "buildFeatures", "splits", "bundle", "lint", "testOptions", "sourceSets",
    "all", "forEach", "configureEach", "matching", "defaultConfig", "androidResources",
    "aaptOptions", "compileOptions", "kotlinOptions", "composeOptions", "dependenciesInfo",
})


def _get_module_build_files(module: Optional[str] = None) -> List[Path]:
    cfg = ConfigManager.get_instance()
    root = cfg.project_root
    if not root:
        return []

    if module and module != "(Project Root)":
        clean_mod = module.lstrip(":")
        mod_dir = clean_mod.replace(":", os.sep)
        return [
            root / mod_dir / "build.gradle.kts",
            root / mod_dir / "build.gradle",
        ]
    return [
        root / "app" / "build.gradle.kts",
        root / "app" / "build.gradle",
        root / "build.gradle.kts",
        root / "build.gradle",
    ]


def _strip_gradle_comments(content: str) -> str:
    """Remove // and /* */ comments while preserving string literals."""
    out = []
    i = 0
    n = len(content)
    while i < n:
        ch = content[i]
        if ch in ('"', "'"):
            quote = ch
            # Handle triple-quoted strings in Kotlin/Groovy
            if content[i:i + 3] == quote * 3:
                end = content.find(quote * 3, i + 3)
                if end == -1:
                    out.append(content[i:])
                    break
                out.append(content[i:end + 3])
                i = end + 3
                continue
            out.append(ch)
            i += 1
            while i < n:
                c = content[i]
                out.append(c)
                if c == "\\" and i + 1 < n:
                    i += 1
                    out.append(content[i])
                    i += 1
                    continue
                if c == quote:
                    i += 1
                    break
                i += 1
            continue

        if ch == "/" and i + 1 < n:
            nxt = content[i + 1]
            if nxt == "/":
                nl = content.find("\n", i + 2)
                if nl == -1:
                    break
                out.append("\n")
                i = nl + 1
                continue
            if nxt == "*":
                end = content.find("*/", i + 2)
                if end == -1:
                    break
                # Keep line structure
                out.append("\n" * content[i:end + 2].count("\n"))
                i = end + 2
                continue

        out.append(ch)
        i += 1
    return "".join(out)


def _extract_balanced_block(content: str, open_brace_idx: int) -> Tuple[str, int]:
    """Extract content inside {...} starting at open_brace_idx, respecting strings."""
    depth = 1
    pos = open_brace_idx + 1
    n = len(content)
    while pos < n and depth > 0:
        ch = content[pos]
        if ch in ('"', "'"):
            quote = ch
            pos += 1
            while pos < n:
                if content[pos] == "\\" and pos + 1 < n:
                    pos += 2
                    continue
                if content[pos] == quote:
                    pos += 1
                    break
                pos += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        pos += 1
    if depth != 0:
        return content[open_brace_idx + 1:], n
    return content[open_brace_idx + 1:pos - 1], pos


def _find_named_block(content: str, block_name: str) -> Optional[str]:
    """Find first top-level/nested `block_name { ... }` and return its inner text."""
    m = re.search(rf'\b{re.escape(block_name)}\s*\{{', content)
    if not m:
        return None
    open_brace = content.find("{", m.start())
    if open_brace == -1:
        return None
    inner, _ = _extract_balanced_block(content, open_brace)
    return inner


def _parse_entry_name(header: str) -> Optional[str]:
    """Extract flavor or buildType name from a block header or standalone statement."""
    h = header.strip()
    if not h:
        return None

    m_dsl = re.search(
        r'(?:create|register|maybeCreate|getByName|named)\s*\(\s*["\']([a-zA-Z0-9_]+)["\']\s*\)\s*$',
        h
    )
    if m_dsl:
        name = m_dsl.group(1)
        return None if name in _NON_ENTRY_KEYWORDS else name

    m_quoted = re.search(r'["\']([a-zA-Z0-9_]+)["\']\s*$', h)
    if m_quoted:
        name = m_quoted.group(1)
        return None if name in _NON_ENTRY_KEYWORDS else name

    m_ident = re.match(r'^([a-zA-Z0-9_]+)$', h)
    if m_ident:
        name = m_ident.group(1)
        return None if name in _NON_ENTRY_KEYWORDS else name

    return None


def _iter_top_level_entries(block: str) -> List[Tuple[str, str]]:
    """Iterate (entry_name, entry_body) for top-level entries inside productFlavors/buildTypes."""
    entries: List[Tuple[str, str]] = []
    n = len(block)
    pos = 0
    paren_depth = 0
    stmt_start = 0
    prev_non_empty_stmt = ""

    while pos < n:
        ch = block[pos]
        if ch in ('"', "'"):
            quote = ch
            pos += 1
            while pos < n:
                if block[pos] == "\\" and pos + 1 < n:
                    pos += 2
                    continue
                if block[pos] == quote:
                    pos += 1
                    break
                pos += 1
            continue

        if ch == "(":
            paren_depth += 1
            pos += 1
            continue
        if ch == ")" and paren_depth > 0:
            paren_depth -= 1
            pos += 1
            continue

        if paren_depth == 0 and ch in ("\n", ";"):
            stmt = block[stmt_start:pos].strip()
            if stmt:
                # Handle standalone create("staging") without { ... }
                if re.search(r'^(?:create|register|maybeCreate)\s*\(\s*["\'][a-zA-Z0-9_]+["\']\s*\)$', stmt):
                    name = _parse_entry_name(stmt)
                    if name:
                        entries.append((name, ""))
                    prev_non_empty_stmt = ""
                else:
                    prev_non_empty_stmt = stmt
            stmt_start = pos + 1
            pos += 1
            continue

        if ch == "{":
            header = block[stmt_start:pos].strip()
            if not header:
                header = prev_non_empty_stmt
            body, next_pos = _extract_balanced_block(block, pos)
            name = _parse_entry_name(header)
            if name:
                entries.append((name, body))
            prev_non_empty_stmt = ""
            stmt_start = next_pos
            pos = next_pos
            continue

        pos += 1

    tail = block[stmt_start:].strip()
    if tail and re.search(r'^(?:create|register|maybeCreate)\s*\(\s*["\'][a-zA-Z0-9_]+["\']\s*\)$', tail):
        name = _parse_entry_name(tail)
        if name:
            entries.append((name, ""))

    return entries


def _extract_string_prop(body: str, prop: str) -> str:
    setter = f"set{cap_first(prop)}"
    m = re.search(
        rf'(?:\b{re.escape(prop)}\s*(?:=|\s)\s*|\b{re.escape(setter)}\s*\(\s*)["\']([^"\']+)["\']',
        body
    )
    return m.group(1) if m else ""


def _read_first_gradle_content(module: Optional[str] = None) -> Optional[str]:
    for bp in _get_module_build_files(module=module):
        if not bp.exists():
            continue
        try:
            return _strip_gradle_comments(bp.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def get_flavor_dimensions(module: Optional[str] = None) -> List[str]:
    """
    Parse flavorDimensions order from build.gradle.kts or build.gradle.
    """
    content = _read_first_gradle_content(module=module)
    if not content:
        return []

    dims: List[str] = []
    seen = set()

    for m in re.finditer(r'\b(?:flavorDimensions|setFlavorDimensions)\b', content):
        pos = m.end()
        n = len(content)
        while pos < n and content[pos] in " \t":
            pos += 1

        # Extract the statement slice (handles multi-line parens/brackets)
        paren = 0
        bracket = 0
        start = pos
        while pos < n:
            ch = content[pos]
            if ch in ('"', "'"):
                quote = ch
                pos += 1
                while pos < n:
                    if content[pos] == "\\" and pos + 1 < n:
                        pos += 2
                        continue
                    if content[pos] == quote:
                        pos += 1
                        break
                    pos += 1
                continue
            if ch == "(":
                paren += 1
            elif ch == ")" and paren > 0:
                paren -= 1
            elif ch == "[":
                bracket += 1
            elif ch == "]" and bracket > 0:
                bracket -= 1
            elif paren == 0 and bracket == 0 and ch in ("\n", ";", "{", "}"):
                break
            pos += 1

        stmt_slice = content[start:pos]
        for qm in re.finditer(r'["\']([^"\']+)["\']', stmt_slice):
            d = qm.group(1).strip()
            if d and d not in seen:
                seen.add(d)
                dims.append(d)

    return dims


def get_build_types(module: Optional[str] = None) -> List[BuildTypeInfo]:
    """
    Parse buildTypes from build.gradle.kts / build.gradle.
    Always includes 'debug' and 'release' (Gradle defaults), plus any custom buildTypes.
    """
    parsed: dict[str, BuildTypeInfo] = {}
    custom_order: List[str] = []

    content = _read_first_gradle_content(module=module)
    if content:
        block = _find_named_block(content, "buildTypes")
        if block:
            for name, body in _iter_top_level_entries(block):
                bt = BuildTypeInfo(
                    name=name,
                    application_id_suffix=_extract_string_prop(body, "applicationIdSuffix"),
                    version_name_suffix=_extract_string_prop(body, "versionNameSuffix"),
                )
                key = name.lower()
                if key not in parsed:
                    parsed[key] = bt
                    if key not in ("debug", "release"):
                        custom_order.append(key)

    result: List[BuildTypeInfo] = [
        parsed.get("debug", BuildTypeInfo("debug")),
    ]
    for key in custom_order:
        result.append(parsed[key])
    result.append(parsed.get("release", BuildTypeInfo("release")))
    return result


def get_product_flavors(module: Optional[str] = None) -> List[FlavorInfo]:
    """
    Parse build.gradle.kts or build.gradle of the given module to discover productFlavors.
    """
    for bp in _get_module_build_files(module=module):
        if not bp.exists():
            continue
        try:
            content = _strip_gradle_comments(bp.read_text(encoding="utf-8"))
            block = _find_named_block(content, "productFlavors")
            if not block:
                continue

            flavors: List[FlavorInfo] = []
            seen = set()

            for fl_name, f_body in _iter_top_level_entries(block):
                if fl_name in seen:
                    continue
                seen.add(fl_name)

                suffix = _extract_string_prop(f_body, "applicationIdSuffix")
                version_suffix = _extract_string_prop(f_body, "versionNameSuffix")
                dimension = _extract_string_prop(f_body, "dimension") or None

                flavors.append(FlavorInfo(
                    name=fl_name,
                    dimension=dimension,
                    application_id_suffix=suffix,
                    version_name_suffix=version_suffix
                ))

            if flavors:
                return flavors

        except Exception:
            pass

    return []


def get_flavor_combinations(module: Optional[str] = None) -> List[FlavorInfo]:
    """
    Compute the flavor matrix across flavorDimensions.
    For single-dimension or un-dimensioned flavors, returns the flavors directly.
    For multi-dimension flavors (e.g., edition x distribution), returns Cartesian combinations
    like globalGplay, globalDirect, vietnameseGplay, vietnameseDirect.
    """
    flavors = get_product_flavors(module=module)
    if not flavors:
        return []

    has_dimensions = any(f.dimension is not None for f in flavors)
    if not has_dimensions:
        return flavors

    declared_dims = get_flavor_dimensions(module=module)
    grouped: dict[Optional[str], List[FlavorInfo]] = {}
    for f in flavors:
        grouped.setdefault(f.dimension, []).append(f)

    # If a single dimension exists and some flavor omitted dimension, group them together
    non_none_dims = [d for d in grouped if d is not None]
    if None in grouped and len(non_none_dims) == 1:
        sole_dim = non_none_dims[0]
        grouped[sole_dim].extend(grouped.pop(None))

    ordered_dims: List[Optional[str]] = []
    for d in declared_dims:
        if d in grouped and d not in ordered_dims:
            ordered_dims.append(d)
    for d in grouped:
        if d not in ordered_dims:
            ordered_dims.append(d)

    dimension_lists = [grouped[d] for d in ordered_dims if grouped.get(d)]
    if not dimension_lists:
        return flavors

    if len(dimension_lists) == 1:
        return dimension_lists[0]

    combos: List[FlavorInfo] = []
    for combo_tuple in product(*dimension_lists):
        combo_name = lower_first(combo_tuple[0].name) + "".join(cap_first(f.name) for f in combo_tuple[1:])
        combo_dim = ", ".join(f"{f.dimension}: {f.name}" if f.dimension else f.name for f in combo_tuple)
        combo_suffix = "".join(f.application_id_suffix for f in combo_tuple if f.application_id_suffix)
        combo_ver_suffix = "".join(f.version_name_suffix for f in combo_tuple if f.version_name_suffix)
        combos.append(FlavorInfo(
            name=combo_name,
            dimension=combo_dim,
            application_id_suffix=combo_suffix,
            version_name_suffix=combo_ver_suffix,
            flavors=list(combo_tuple),
        ))
    return combos


def get_build_variants(module: Optional[str] = None) -> List[BuildVariantInfo]:
    """
    Return the full Build Variants matrix (flavor combinations x buildTypes).
    Ordered by buildType (debug first, custom types next, release last).
    """
    combos = get_flavor_combinations(module=module)
    build_types = get_build_types(module=module)

    variants: List[BuildVariantInfo] = []
    for bt in build_types:
        if not combos:
            variants.append(BuildVariantInfo(
                name=bt.name,
                build_type=bt.name,
                flavor_name=None,
                flavors=[],
                application_id_suffix=bt.application_id_suffix,
                version_name_suffix=bt.version_name_suffix,
            ))
        else:
            for combo in combos:
                constituents = combo.flavors if combo.flavors else [combo]
                variants.append(BuildVariantInfo(
                    name=f"{lower_first(combo.name)}{cap_first(bt.name)}",
                    build_type=bt.name,
                    flavor_name=combo.name,
                    flavors=constituents,
                    application_id_suffix=f"{combo.application_id_suffix}{bt.application_id_suffix}",
                    version_name_suffix=f"{combo.version_name_suffix}{bt.version_name_suffix}",
                ))
    return variants


def _variant_default_index(variants: List[BuildVariantInfo], saved_flavor: Optional[str]) -> str:
    if saved_flavor:
        saved_lower = saved_flavor.lower()
        for idx, v in enumerate(variants):
            if v.name.lower() == saved_lower or (v.flavor_name and v.flavor_name.lower() == saved_lower):
                return str(idx + 1)
    return "1"


def _prompt_variant_selection(variants: List[BuildVariantInfo], title: str,
                              allow_all_default: bool = False,
                              action_verb: str = "Run") -> List[BuildVariantInfo]:
    options = [(v.name, v.format_label()) for v in variants]
    unique_bts = list(dict.fromkeys(v.build_type.lower() for v in variants))
    debug_variants = [v.name for v in variants if v.build_type.lower() == "debug"]

    extra_presets = None
    if len(unique_bts) > 1 and debug_variants:
        extra_presets = {
            "d": (f"⚡ {action_verb} all debug ({len(debug_variants)} bản debug)", debug_variants)
        }

    cfg = ConfigManager.get_instance()
    saved = cfg.get_selected_flavor()
    if len(unique_bts) > 1:
        default_choice = _variant_default_index(variants, saved)
    else:
        default_choice = "a" if allow_all_default else _variant_default_index(variants, saved)

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


def resolve_target_variants(
    module: Optional[str] = None,
    flavor_arg: Optional[str] = None,
    variant_arg: Optional[str] = None,
    interactive: bool = True,
    action_verb: str = "Run",
) -> List[BuildVariantInfo]:
    """
    Resolve target Build Variants (flavor matrix x build types):
    - If both flavor_arg and variant_arg are provided: matches exact variant/combo or filters.
    - If only variant_arg is provided: filters variants to that buildType; prompts if >1.
    - If only flavor_arg is provided: matches full variant name or flavor combo with default debug buildType.
    - If neither is provided:
        - Simple project (<=1 flavor combo and only standard debug/release): returns debug variant immediately.
        - Complex matrix / custom buildTypes: prompts full Build Variants menu when interactive.
    """
    all_variants = get_build_variants(module=module)
    build_types = get_build_types(module=module)
    combos = get_flavor_combinations(module=module)
    valid_bt_map = {bt.name.lower(): bt.name for bt in build_types}

    if variant_arg:
        if variant_arg.lower() not in valid_bt_map:
            ui.error(f"Build type '{variant_arg}' không tồn tại. Các build types hiện có: {', '.join(valid_bt_map.values())}")
            sys.exit(1)
        candidates = [v for v in all_variants if v.build_type.lower() == variant_arg.lower()]
    else:
        candidates = all_variants

    if flavor_arg:
        fl_lower = flavor_arg.lower()
        # 1. Exact match against full variant name (e.g. globalGplayRelease)
        exact_var = [v for v in candidates if v.name.lower() == fl_lower]
        if exact_var:
            return exact_var

        # 2. Restrict to target buildType (default 'debug') when variant_arg omitted
        if not variant_arg:
            default_bt = "debug" if "debug" in valid_bt_map else build_types[0].name
            candidates = [v for v in all_variants if v.build_type.lower() == default_bt.lower()]

        # 3. Exact match against flavor combination name (e.g. globalGplay)
        exact_flavor = [v for v in candidates if v.flavor_name and v.flavor_name.lower() == fl_lower]
        if exact_flavor:
            return exact_flavor

        # 4. Partial dimension flavor match (e.g. 'global' matching globalGplay, globalDirect)
        partial_matches = [
            v for v in candidates
            if any(f.name.lower() == fl_lower for f in v.flavors)
        ]
        if len(partial_matches) == 1:
            return partial_matches
        if len(partial_matches) > 1:
            if not interactive:
                return partial_matches
            return _prompt_variant_selection(
                partial_matches,
                title=f"Flavor '{flavor_arg}' khớp với nhiều Build Variants. Vui lòng chọn:",
                allow_all_default=False,
                action_verb=action_verb,
            )

        available = ", ".join(c.name for c in combos) if combos else "(không có flavor)"
        ui.error(f"Flavor hoặc Variant '{flavor_arg}' không tồn tại trong module. Hiện có: {available}")
        sys.exit(1)

    if variant_arg:
        if len(candidates) <= 1 or not interactive:
            return candidates
        return _prompt_variant_selection(
            candidates,
            title=f"Phát hiện nhiều Build Variants ({variant_arg}). Vui lòng chọn:",
            allow_all_default=True,
            action_verb=action_verb,
        )

    # Neither flavor_arg nor variant_arg provided:
    # Preserve fast 1-click debug for simple projects (<=1 flavor, only standard debug/release)
    has_custom_bt = any(bt.name.lower() not in ("debug", "release") for bt in build_types)
    if len(combos) <= 1 and not has_custom_bt:
        debug_vars = [v for v in all_variants if v.build_type.lower() == "debug"]
        return [debug_vars[0]] if debug_vars else [all_variants[0]]

    if not interactive:
        debug_vars = [v for v in all_variants if v.build_type.lower() == "debug"]
        return debug_vars if debug_vars else all_variants

    return _prompt_variant_selection(
        all_variants,
        title="Phát hiện nhiều Build Variants. Vui lòng chọn Variant:",
        allow_all_default=False,
        action_verb=action_verb,
    )


def _format_flavor_option(f: FlavorInfo) -> Tuple[str, str]:
    desc_parts = []
    if f.dimension:
        desc_parts.append(f.dimension if f.flavors else f"dimension: {f.dimension}")
    if f.application_id_suffix:
        desc_parts.append(f"suffix: {f.application_id_suffix}")
    desc = f"{ui.Colors.BOLD}{f.name}{ui.Colors.RESET}"
    if desc_parts:
        desc += f" ({', '.join(desc_parts)})"
    return f.name, desc


def resolve_target_flavor(module: Optional[str] = None, flavor_arg: Optional[str] = None,
                          interactive: bool = True, allow_all: bool = False) -> Optional[FlavorInfo]:
    """
    Resolve flavor (or flavor matrix combination):
    - If module has 0 flavors, returns None.
    - If flavor_arg is provided, validates and returns it.
    - If saved in config, returns it (or prompts if interactive).
    - If interactive and >1 flavors, presents choice menu to user.
    """
    flavors = get_flavor_combinations(module=module)
    if not flavors:
        return None

    flavor_map = {f.name.lower(): f for f in flavors}

    if flavor_arg:
        fl_lower = flavor_arg.lower()
        if fl_lower in flavor_map:
            return flavor_map[fl_lower]
        ui.error(f"Flavor '{flavor_arg}' không tồn tại trong module. Các flavor hiện có: {', '.join(flavor_map.keys())}")
        sys.exit(1)

    if len(flavors) == 1:
        return flavors[0]

    cfg = ConfigManager.get_instance()
    saved = cfg.get_selected_flavor()
    if saved and saved.lower() in flavor_map and not interactive:
        return flavor_map[saved.lower()]

    if not interactive:
        return flavor_map[saved.lower()] if (saved and saved.lower() in flavor_map) else flavors[0]

    # Multiple flavors: interactive selection
    options = []
    default_idx = 0
    for idx, f in enumerate(flavors):
        options.append(_format_flavor_option(f))
        if saved and f.name.lower() == saved.lower():
            default_idx = idx

    if allow_all:
        options.append(("all", f"{ui.Colors.CYAN}Build tất cả flavors{ui.Colors.RESET}"))

    chosen = ui.ask_choice("Phát hiện nhiều Product Flavors. Vui lòng chọn Flavor:", options, default_idx=default_idx)
    if chosen == "all":
        return None

    selected = flavor_map[chosen.lower()]
    return selected


def resolve_target_flavors(module: Optional[str] = None, flavor_arg: Optional[str] = None,
                           interactive: bool = True) -> List[Optional[FlavorInfo]]:
    """
    Resolve target product flavors (or flavor matrix combinations):
    - If 0 flavors exist in module, returns [None] (standard single APK build).
    - If flavor_arg is provided via CLI (-f/--flavor), validates and returns [matched_flavor].
    - If 1 flavor exists, returns [flavors[0]].
    - If >1 flavors exist:
        If interactive: prompts user with multiselect.
        If not interactive: returns all flavors.
    Note: Does NOT prompt to save default flavor.
    """
    flavors = get_flavor_combinations(module=module)
    if not flavors:
        return [None]

    flavor_map = {f.name.lower(): f for f in flavors}

    if flavor_arg:
        fl_lower = flavor_arg.lower()
        if fl_lower in flavor_map:
            return [flavor_map[fl_lower]]
        ui.error(f"Flavor '{flavor_arg}' không tồn tại trong module. Các flavor hiện có: {', '.join(flavor_map.keys())}")
        sys.exit(1)

    if len(flavors) == 1:
        return [flavors[0]]

    if not interactive:
        return flavors

    # Multiple flavors: interactive multiselect
    options = [_format_flavor_option(f) for f in flavors]

    chosen_names = ui.ask_multiselect(
        title="Phát hiện nhiều Product Flavors. Vui lòng chọn Flavor:",
        options=options,
        all_label="⚡ Run all (Tất cả flavors)"
    )

    chosen_set = {name.lower() for name in chosen_names}
    selected_flavors = [f for f in flavors if f.name.lower() in chosen_set]
    return selected_flavors if selected_flavors else flavors


def list_modules() -> List[str]:
    """
    Parse settings.gradle.kts and settings.gradle to discover all modules.
    """
    cfg = ConfigManager.get_instance()
    root = cfg.project_root
    modules = [":app"]

    settings_files = [root / "settings.gradle.kts", root / "settings.gradle"]
    found_modules = set()

    for sf in settings_files:
        if sf.exists():
            try:
                content = sf.read_text(encoding="utf-8")
                # Matches: include(":app", ":core", ":feature:login")
                matches = re.findall(r'include\s*\((.*?)\)', content, re.DOTALL)
                for block in matches:
                    items = re.findall(r'["\'](:[^"\']+)["\']', block)
                    found_modules.update(items)
                # Matches: include ":app", ":core"
                line_matches = re.findall(r'include\s+([^\r\n]+)', content)
                for line in line_matches:
                    items = re.findall(r'["\'](:[^"\']+)["\']', line)
                    found_modules.update(items)
            except Exception:
                pass

    if found_modules:
        modules = sorted(list(found_modules))
        # Ensure :app is first if present
        if ":app" in modules:
            modules.remove(":app")
            modules.insert(0, ":app")

    return modules


def execute_gradle(task: str, module: Optional[str] = None, extra_args: Optional[List[str]] = None, capture: bool = False) -> subprocess.CompletedProcess:
    cfg = ConfigManager.get_instance()
    cfg.ensure_local_properties()
    gradlew = get_gradlew_path()

    # Prepend target module if given (e.g. :app:assembleDebug)
    final_task = task
    if module and module != "(Project Root)" and not task.startswith(":"):
        final_task = f"{module}:{task}"

    cmd = [str(gradlew), final_task]
    if extra_args:
        cmd.extend(extra_args)

    env = os.environ.copy()
    if cfg.sdk_path:
        env.setdefault("ANDROID_HOME", cfg.sdk_path)
        env.setdefault("ANDROID_SDK_ROOT", cfg.sdk_path)

    ui.info(f"Thực thi Gradle: {ui.Colors.BOLD}{' '.join(cmd)}{ui.Colors.RESET}")
    ui.detail("Project Root", str(cfg.project_root))

    if capture:
        return subprocess.run(cmd, cwd=str(cfg.project_root), env=env, capture_output=True, text=True)
    else:
        return subprocess.run(cmd, cwd=str(cfg.project_root), env=env)
