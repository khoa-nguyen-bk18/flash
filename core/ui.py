#!/usr/bin/env python3
"""
Terminal UI utilities with ANSI colors, formatting, and interactive helpers.
Zero external dependencies.
"""

import sys
import os
import re
import shutil
from typing import Optional

class Colors:
    ENABLED = sys.stdout.isatty() and not os.getenv("NO_COLOR")
    
    RESET = "\033[0m" if ENABLED else ""
    BOLD = "\033[1m" if ENABLED else ""
    DIM = "\033[2m" if ENABLED else ""
    ITALIC = "\033[3m" if ENABLED else ""
    UNDERLINE = "\033[4m" if ENABLED else ""

    BLACK = "\033[30m" if ENABLED else ""
    RED = "\033[31m" if ENABLED else ""
    GREEN = "\033[32m" if ENABLED else ""
    YELLOW = "\033[33m" if ENABLED else ""
    BLUE = "\033[34m" if ENABLED else ""
    MAGENTA = "\033[35m" if ENABLED else ""
    CYAN = "\033[36m" if ENABLED else ""
    WHITE = "\033[37m" if ENABLED else ""

    BG_RED = "\033[41m" if ENABLED else ""
    BG_GREEN = "\033[42m" if ENABLED else ""
    BG_YELLOW = "\033[43m" if ENABLED else ""
    BG_BLUE = "\033[44m" if ENABLED else ""
    BG_MAGENTA = "\033[45m" if ENABLED else ""
    BG_CYAN = "\033[46m" if ENABLED else ""


def header(title: str):
    line = "━" * 60
    print(f"\n{Colors.CYAN}{Colors.BOLD}⚡ {title}{Colors.RESET}")
    print(f"{Colors.DIM}{line}{Colors.RESET}")


def info(msg: str):
    print(f"{Colors.BLUE}ℹ{Colors.RESET}  {msg}")


def success(msg: str):
    print(f"{Colors.GREEN}✅ {msg}{Colors.RESET}")


def warning(msg: str):
    print(f"{Colors.YELLOW}⚠️  {msg}{Colors.RESET}")


def error(msg: str):
    print(f"{Colors.RED}{Colors.BOLD}❌ {msg}{Colors.RESET}", file=sys.stderr)


def detail(label: str, value: str):
    print(f"  {Colors.DIM}{label}:{Colors.RESET} {Colors.BOLD}{value}{Colors.RESET}")


def ask_choice(title: str, options: list[tuple[str, str]], default_idx: int = 0) -> str:
    """
    options: list of (value, label)
    Returns selected value.
    """
    print(f"\n{Colors.BOLD}{title}{Colors.RESET}")
    for idx, (val, desc) in enumerate(options):
        marker = f"{Colors.GREEN}>{Colors.RESET}" if idx == default_idx else " "
        print(f"  {marker} [{idx + 1}] {desc} ({Colors.DIM}{val}{Colors.RESET})")
    
    while True:
        try:
            choice = input(f"Chọn (1-{len(options)}) [mặc định: {default_idx + 1}]: ").strip()
            if not choice:
                return options[default_idx][0]
            num = int(choice)
            if 1 <= num <= len(options):
                return options[num - 1][0]
        except (ValueError, KeyboardInterrupt, EOFError):
            pass
        print(f"{Colors.RED}Lựa chọn không hợp lệ. Vui lòng nhập số từ 1 đến {len(options)}.{Colors.RESET}")


def ask_input(prompt: str, default: str = "") -> str:
    default_str = f" [{default}]" if default else ""
    try:
        val = input(f"{Colors.BOLD}{prompt}{default_str}:{Colors.RESET} ").strip()
        return val if val else default
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(130)


def ask_confirm(prompt: str, default: bool = True) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    try:
        val = input(f"{Colors.BOLD}{prompt} {hint}:{Colors.RESET} ").strip().lower()
        if not val:
            return default
        return val in ("y", "yes", "true", "1")
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(130)


def ask_multiselect(
    title: str,
    options: list[tuple[str, str]],
    all_label: str = "⚡ Run all",
    default: str = "a",
    extra_presets: Optional[dict[str, tuple[str, list[str]]]] = None
) -> list[str]:
    """
    Select multiple items by entering index numbers separated by ',', preset keys, or 'a' for all.
    options: list of (value, label)
    extra_presets: optional mapping {shortcut_key: (label, list_of_values)}
    Returns list of selected values.
    """
    if not options:
        return []

    presets = {k.lower(): v for k, v in extra_presets.items()} if extra_presets else {}
    option_idx_by_val = {opt[0]: idx for idx, opt in enumerate(options)}

    print(f"\n{Colors.BOLD}{title}{Colors.RESET}")
    for key, (label, _) in presets.items():
        print(f"  {Colors.YELLOW}[{key}]{Colors.RESET} {label}")
    print(f"  {Colors.CYAN}[a]{Colors.RESET} {all_label}")
    for idx, (val, desc) in enumerate(options):
        print(f"  {Colors.GREEN}[{idx + 1}]{Colors.RESET} {desc}")

    if presets:
        preset_keys = ", ".join(f"'{k}'" for k in presets)
        prompt_msg = f"\n{Colors.BOLD}Chọn (1-{len(options)}, {preset_keys}, hoặc 'a' cho tất cả, cách nhau bởi dấu phẩy ',') [mặc định: {default}]:{Colors.RESET} "
    else:
        prompt_msg = f"\n{Colors.BOLD}Chọn (1-{len(options)}, hoặc 'a' cho tất cả, cách nhau bởi dấu phẩy ',') [mặc định: {default}]:{Colors.RESET} "

    while True:
        try:
            choice = input(prompt_msg).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(130)

        if not choice:
            choice = default

        choice_lower = choice.lower()
        if choice_lower in ("a", "all"):
            success(f"Đã chọn: Run all ({len(options)} mục)")
            return [opt[0] for opt in options]

        if choice_lower in presets:
            label, preset_vals = presets[choice_lower]
            success(f"Đã chọn: {label}")
            return list(preset_vals)

        # Split by comma or semicolon
        parts = [p.strip() for p in choice.replace(";", ",").split(",") if p.strip()]

        if any(p.lower() in ("a", "all") for p in parts):
            success(f"Đã chọn: Run all ({len(options)} mục)")
            return [opt[0] for opt in options]

        selected_indices = []
        invalid_parts = []
        for part in parts:
            part_lower = part.lower()
            if part_lower in presets:
                for val in presets[part_lower][1]:
                    if val in option_idx_by_val and option_idx_by_val[val] not in selected_indices:
                        selected_indices.append(option_idx_by_val[val])
            elif part.isdigit():
                num = int(part)
                if 1 <= num <= len(options):
                    idx = num - 1
                    if idx not in selected_indices:
                        selected_indices.append(idx)
                else:
                    invalid_parts.append(part)
            else:
                invalid_parts.append(part)

        if invalid_parts:
            valid_hint = f"1 đến {len(options)}"
            if presets:
                valid_hint += ", " + ", ".join(f"'{k}'" for k in presets)
            print(f"{Colors.RED}Lựa chọn không hợp lệ: {', '.join(invalid_parts)}. Vui lòng nhập số từ {valid_hint} hoặc 'a'.{Colors.RESET}")
            continue

        if not selected_indices:
            print(f"{Colors.RED}Vui lòng chọn ít nhất một mục hoặc 'a' cho tất cả.{Colors.RESET}")
            continue

        selected_values = [options[i][0] for i in selected_indices]
        if len(selected_values) == len(options) and len(options) > 1:
            success(f"Đã chọn: Run all ({len(options)} mục)")
        else:
            chosen_names = [options[i][0] for i in selected_indices]
            success(f"Đã chọn ({len(selected_values)}): {', '.join(chosen_names)}")

        return selected_values
