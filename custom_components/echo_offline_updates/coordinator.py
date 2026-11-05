"""Data update coordinator for the Echo Kiosk Offline Updates integration."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import urllib.request
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BASE_URL,
    CONF_DEVICES,
    CONF_INTERVAL_HOURS,
    CONF_KIOSK_REPO,
    CONF_KIOSK_UNIVERSAL_ONLY,
    CONF_MIRROR_KIOSK,
    CONF_RELEASE_REPO,
    CONF_WWW_SUBDIR,
    DOMAIN,
    ECHO_IMAGE_PREFIX,
    ECHO_RELEASES_FILE,
    GITHUB_API,
    KIOSK_DEFAULT_REPO,
    KIOSK_IMAGE_PREFIX,
    KIOSK_RELEASES_FILE,
    USER_AGENT,
)
from .mirror import (
    AssetMirror,
    apk_assets,
    newest_release_for_device,
    rewrite_release_urls,
    sorted_releases,
    echo_sig_asset,
    echo_zip_asset,
    strip_device_prefix,
)

_LOGGER = logging.getLogger(__name__)

_COPY_CHUNK = 1 << 20
_API_TIMEOUT = aiohttp.ClientTimeout(total=30)
_DOWNLOAD_TIMEOUT = 120  # seconds; connects/reads only, a slow body stream is fine


def _github_headers() -> dict[str, str]:
    return {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}


async def async_probe_repo(session: aiohttp.ClientSession, repo: str) -> int:
    """Return the GitHub API HTTP status for a repository (0 on connection failure)."""
    url = f"{GITHUB_API}/repos/{repo}/releases?per_page=1"
    try:
        async with session.get(url, headers=_github_headers(), timeout=_API_TIMEOUT) as resp:
            return resp.status
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return 0


def _ensure_dir(path: Path) -> None:
    """Create the mirror folder inside the config www directory."""
    path.mkdir(parents=True, exist_ok=True)

def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")

def _download(url: str, dest: Path) -> int:
    """Stream one asset to disk in the executor, via a .part file for atomicity."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT) as resp, tmp.open("wb") as out:
            shutil.copyfileobj(resp, out, _COPY_CHUNK)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, dest)
    return dest.stat().st_size

def _prune(www: Path, keep: set[str], prefixes: tuple[str, ...]) -> None:
    """Delete older mirrored zips/APKs; devices only ever fetch the newest release."""
    for child in www.iterdir():
        name = child.name
        if name in keep or not child.is_file():
            continue
        if name.endswith(".part") or (
            name.startswith(prefixes) and name.endswith((".zip", ".sig", ".apk"))
        ):
            child.unlink()
            _LOGGER.info("Pruned stale mirror file %s", name)


@dataclass
class DeviceMirror:
    """The newest mirrored image for one device."""

    device: str
    tag: str
    version: str
    zip: AssetMirror
    sig: AssetMirror | None

@dataclass
class KioskMirror:
    """The newest mirrored Kiosk Satellite release."""

    tag: str
    files: list[AssetMirror]
    json_name: str

@dataclass
class MirrorData:
    """What the coordinator mirrored on its last successful pass."""

    last_sync: Any
    base_url: str
    www_path: str
    echo_repo: str
    kiosk_repo: str | None
    devices: dict[str, DeviceMirror]
    kiosk: KioskMirror | None
    errors: list[str]


class EchoOfflineCoordinator(DataUpdateCoordinator[MirrorData]):
    """Keep <config>/www/<subdir> in sync with upstream GitHub releases."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry = entry
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(hours=entry.data[CONF_INTERVAL_HOURS]),
        )
        self._session = async_get_clientsession(hass)

    async def _async_update_data(self) -> MirrorData:
        data = self._entry.data
        base = data[CONF_BASE_URL].rstrip("/")
        www = Path(self.hass.config.path("www", data[CONF_WWW_SUBDIR]))
        await self.hass.async_add_executor_job(_ensure_dir, www)
        errors: list[str] = []

        # Reuse the last good mirror when a check fails, so sensors and files
        # keep describing what is actually in the folder.
        previous = self.data
        devices: dict[str, DeviceMirror] = dict(previous.devices) if previous else {}
        kiosk_out = previous.kiosk if previous else None

        echo_repo = data[CONF_RELEASE_REPO]
        echo_releases = await self._async_fetch_releases(echo_repo, errors)
        if echo_releases is not None:
            devices = await self._async_mirror_echo(echo_releases, echo_repo, base, www, errors, devices)

        kiosk_repo: str | None = None
        kiosk: KioskMirror | None = kiosk_out
        if data.get(CONF_MIRROR_KIOSK):
            kiosk_repo = data.get(CONF_KIOSK_REPO) or KIOSK_DEFAULT_REPO
            kiosk_releases = await self._async_fetch_releases(kiosk_repo, errors)
            if kiosk_releases is not None:
                kiosk = await self._async_mirror_kiosk(kiosk_releases, kiosk_repo, base, www, errors)

        if echo_releases is None and not devices and kiosk is None:
            # Nothing mirrored yet and nothing could be fetched: retry later.
            raise UpdateFailed("; ".join(errors) or "GitHub did not return any releases")

        return MirrorData(
            last_sync=dt_util.now(),
            base_url=base,
            www_path=str(www),
            echo_repo=echo_repo,
            kiosk_repo=kiosk_repo,
            devices=devices,
            kiosk=kiosk,
            errors=errors,
        )

    async def _async_fetch_releases(self, repo: str, errors: list[str]) -> list[dict[str, Any]] | None:
        """Fetch a repository's release list; None (plus an error note) on any failure."""
        url = f"{GITHUB_API}/repos/{repo}/releases?per_page=100"
        try:
            async with self._session.get(url, headers=_github_headers(), timeout=_API_TIMEOUT) as resp:
                if resp.status != 200:
                    errors.append(f"{repo}: GitHub API returned HTTP {resp.status}")
                    return None
                releases = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            errors.append(f"{repo}: {err}")
            return None
        if not isinstance(releases, list):
            errors.append(f"{repo}: unexpected GitHub API response")
            return None
        return releases

    async def _async_download_asset(self, asset: dict[str, Any], dest: Path) -> None:
        """Download an asset unless it is already mirrored at the expected size."""
        expected = asset.get("size") or 0
        if expected and dest.is_file() and dest.stat().st_size == expected:
            _LOGGER.debug("Already mirrored: %s", dest.name)
            return
        _LOGGER.info("Mirroring %s (%.1f MiB)", dest.name, expected / (1 << 20))
        await self.hass.async_add_executor_job(_download, asset["browser_download_url"], dest)

    async def _async_mirror_echo(
        self,
        releases: list[dict[str, Any]],
        repo: str,
        base: str,
        www: Path,
        errors: list[str],
        devices: dict[str, DeviceMirror],
    ) -> dict[str, DeviceMirror]:
        """Rewrite and save echo-releases.json, then mirror each device's newest image."""
        rewritten = rewrite_release_urls(json.dumps(releases), repo, base)
        await self.hass.async_add_executor_job(_write_text, www / ECHO_RELEASES_FILE, rewritten)
        # Keep the previously mirrored entry for a device whose check failed this
        # round; its last good file is still on disk and still being served.
        devices_out: dict[str, DeviceMirror] = dict(devices)
        keep = {ECHO_RELEASES_FILE}
        clean = True

        for device in self._entry.data.get(CONF_DEVICES, []):
            release = newest_release_for_device(releases, device)
            if release is None:
                errors.append(f"{device}: no release with tag prefix '{device}-'")
                clean = False
                continue
            zip_asset = echo_zip_asset(release, device)
            if zip_asset is None:
                errors.append(
                    f"{device}: release {release.get('tag_name')} has no '{ECHO_IMAGE_PREFIX}*-{device}.zip' asset"
                )
                clean = False
                continue
            zip_name = zip_asset["name"]
            try:
                await self._async_download_asset(zip_asset, www / zip_name)
            except Exception as err:  # noqa: BLE001 - reported per device
                errors.append(f"{device}: download of {zip_name} failed: {err}")
                clean = False
                continue
            keep.add(zip_name)
            sig_asset = echo_sig_asset(release, zip_name)
            sig_mirror: AssetMirror | None = None
            if sig_asset is not None:
                sig_name = sig_asset["name"]
                try:
                    await self._async_download_asset(sig_asset, www / sig_name)
                except Exception as err:  # noqa: BLE001 - reported per device
                    errors.append(f"{device}: download of {sig_name} failed: {err}")
                    clean = False
                    continue
                keep.add(sig_name)
                sig_mirror = AssetMirror(
                    name=sig_name, size=sig_asset.get("size", 0), url=f"{base}/{sig_name}"
                )
            devices_out[device] = DeviceMirror(
                device=device,
                tag=release.get("tag_name", ""),
                version=strip_device_prefix(release.get("tag_name", ""), device),
                zip=AssetMirror(name=zip_name, size=zip_asset.get("size", 0), url=f"{base}/{zip_name}"),
                sig=sig_mirror,
            )

        if clean:
            await self.hass.async_add_executor_job(_prune, www, keep, (ECHO_IMAGE_PREFIX,))
        return devices_out

    async def _async_mirror_kiosk(
        self,
        releases: list[dict[str, Any]],
        repo: str,
        base: str,
        www: Path,
        errors: list[str],
    ) -> KioskMirror | None:
        """Save releases.json and mirror the newest Kiosk Satellite APKs."""
        ordered = sorted_releases(releases)
        if not ordered:
            errors.append(f"{repo}: no releases returned")
            return None
        release = ordered[0]
        rewritten = rewrite_release_urls(json.dumps(releases), repo, base)
        await self.hass.async_add_executor_job(_write_text, www / KIOSK_RELEASES_FILE, rewritten)

        keep = {KIOSK_RELEASES_FILE}
        files: list[AssetMirror] = []
        assets = apk_assets(release, universal_only=self._entry.data.get(CONF_KIOSK_UNIVERSAL_ONLY, False))
        if not assets:
            errors.append(f"{repo}: release {release.get('tag_name')} has no APK assets")
        for asset in assets:
            name = asset["name"]
            try:
                await self._async_download_asset(asset, www / name)
            except Exception as err:  # noqa: BLE001 - reported per asset
                errors.append(f"kiosk-satellite: download of {name} failed: {err}")
                continue
            keep.add(name)
            files.append(AssetMirror(name=name, size=asset.get("size", 0), url=f"{base}/{name}"))

        if assets and len(files) == len(assets):
            await self.hass.async_add_executor_job(_prune, www, keep, (KIOSK_IMAGE_PREFIX,))
        return KioskMirror(tag=release.get("tag_name", ""), files=files, json_name=KIOSK_RELEASES_FILE)
