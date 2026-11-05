"""Pure helpers for mirroring GitHub releases to a local web folder.

No Home Assistant imports here, so the mirror logic can be exercised
standalone against a real GitHub API response.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Upstream asset naming (mirrors jxlarrea's repos):
#   tag:      <codename>-<version>              e.g. crown-2026.11.1
#   image:    lineageos-echo-kiosk-satellite-<version>-<codename>.zip(.sig)
#   kiosk:    kiosk-satellite-<tag>.apk and kiosk-satellite-<tag>.<abi>.apk
ECHO_IMAGE_PREFIX = "lineageos-echo-kiosk-satellite-"
KIOSK_IMAGE_PREFIX = "kiosk-satellite-"


def github_download_pattern(repo: str) -> re.Pattern[str]:
    """Match GitHub release download links for one repository (same as the sed in upstream docs)."""
    return re.compile(r"https://github\.com/" + re.escape(repo) + r"/releases/download/[^/\"]+/")

def rewrite_release_urls(body: str, repo: str, base_url: str) -> str:
    """Point every download link of `repo` at `base_url` so offline devices fetch from there."""
    base = base_url.rstrip("/")
    return github_download_pattern(repo).sub(f"{base}/", body)


def sorted_releases(releases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """GitHub returns releases roughly newest-first; re-sort to be sure."""
    return sorted(
        releases,
        key=lambda release: release.get("published_at") or release.get("created_at") or "",
        reverse=True,
    )


def strip_device_prefix(tag: str, device: str) -> str:
    """crown-2026.11.1 -> 2026.11.1"""
    prefix = device + "-"
    return tag[len(prefix):] if tag.startswith(prefix) else tag

def newest_release_for_device(releases: list[dict[str, Any]], device: str) -> dict[str, Any] | None:
    """Find the newest release whose tag is tagged for this device codename."""
    prefix = device + "-"
    for release in sorted_releases(releases):
        if release.get("tag_name", "").startswith(prefix):
            return release
    return None

def echo_zip_asset(release: dict[str, Any], device: str) -> dict[str, Any] | None:
    """The device image zip for one codename, under the name GitHub gives it."""
    suffix = f"-{device}.zip"
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.startswith(ECHO_IMAGE_PREFIX) and name.endswith(suffix):
            return asset
    return None

def echo_sig_asset(release: dict[str, Any], zip_name: str) -> dict[str, Any] | None:
    """The release signature; without it the device refuses to install."""
    for asset in release.get("assets", []):
        if asset.get("name") == zip_name + ".sig":
            return asset
    return None


@dataclass
class AssetMirror:
    """One mirrored file."""

    name: str
    size: int
    url: str


def apk_assets(release: dict[str, Any], universal_only: bool = False) -> list[dict[str, Any]]:
    """The APK assets of a Kiosk Satellite release, optionally only the universal one."""
    tag = release.get("tag_name", "")
    universal_name = f"kiosk-satellite-{tag}.apk"
    assets = [
        asset
        for asset in release.get("assets", [])
        if asset.get("name", "").endswith(".apk")
    ]
    if universal_only:
        universal = [asset for asset in assets if asset.get("name") == universal_name]
        assets = universal or assets
    return assets
