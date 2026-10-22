import os
import shutil
import subprocess

import pytest


def _node_ok() -> bool:
    """Node.js >= 22 on PATH - HyperFrames requires Node 22+ (plan B3 #3)."""
    exe = shutil.which("node")
    if not exe:
        return False
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, check=True)
    except subprocess.SubprocessError:
        return False
    version = (out.stdout or "").strip().lstrip("v")
    try:
        return int(version.split(".")[0]) >= 22
    except ValueError:
        return False


def _chromium_ok() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as p:
            return os.path.exists(p.chromium.executable_path)
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    conditions = {
        "requires_ffmpeg": lambda: bool(shutil.which("ffmpeg")) and bool(shutil.which("ffprobe")),
        "requires_node": _node_ok,
        "requires_browser": _chromium_ok,
    }
    for marker, check in conditions.items():
        if check():
            continue
        skip = pytest.mark.skip(reason=f"{marker}: required tool not available in this environment")
        for item in items:
            if marker in item.keywords:
                item.add_marker(skip)