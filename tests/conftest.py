import shutil

import pytest


def pytest_collection_modifyitems(config, items):
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return
    skip = pytest.mark.skip(reason="ffmpeg/ffprobe not on PATH")
    for item in items:
        if "requires_ffmpeg" in item.keywords:
            item.add_marker(skip)
