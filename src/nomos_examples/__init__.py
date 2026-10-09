"""Installed author assets for the two release demonstrations."""

from pathlib import Path


def everflame_bundle_path() -> Path:
    """Locate the installed, explicitly assembled M1 author bundle."""
    return Path(__file__).resolve().parent / "everflame" / "world.bundle.yaml"
