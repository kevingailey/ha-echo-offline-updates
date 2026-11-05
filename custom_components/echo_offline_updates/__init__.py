"""The Echo Kiosk Offline Updates integration.

Mirrors LineageOS Echo image releases and Kiosk Satellite APKs from GitHub
into Home Assistant's own web server, so Echo devices on a network without
internet access can update from Home Assistant instead.

Implements the flow described in:
https://github.com/jxlarrea/lineageos-echo-kiosk-satellite/blob/main/docs/offline-updates.md
"""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse

from .const import (
    CONF_BASE_URL,
    CONF_DEVICES,
    CONF_KIOSK_REPO,
    CONF_MIRROR_KIOSK,
    CONF_RELEASE_REPO,
    DEVICE_LABELS,
    DOMAIN,
    ECHO_RELEASES_FILE,
    KIOSK_RELEASES_FILE,
    NAME,
    SERVICE_ADB_COMMANDS,
    SERVICE_SYNC,
)
from .coordinator import EchoOfflineCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

_EMPTY_SCHEMA = vol.Schema({})


def _coordinators(hass: HomeAssistant) -> list[EchoOfflineCoordinator]:
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if isinstance(getattr(entry, "runtime_data", None), EchoOfflineCoordinator)
    ]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the mirror from a config entry."""
    coordinator = EchoOfflineCoordinator(hass, entry)
    entry.runtime_data = coordinator
    # Tolerate a failed first refresh (e.g. GitHub rate limits at boot):
    # whatever was mirrored before keeps being served either way.
    await coordinator.async_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    if not hass.data.get(f"{DOMAIN}_services_registered"):
        _async_register_services(hass)
        hass.data[f"{DOMAIN}_services_registered"] = True
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _adb_commands_for_entry(entry: ConfigEntry) -> dict:
    """Build the commands that point each device at the mirrored folder."""
    base = entry.data[CONF_BASE_URL].rstrip("/")
    releases_json = f"{base}/{ECHO_RELEASES_FILE}"
    out: dict = {
        "entry": entry.title or NAME,
        "releases_json": releases_json,
        "devices": [],
    }
    for device in entry.data.get(CONF_DEVICES, []):
        is_dot = device == "biscuit"
        prop = "biscuit" if is_dot else "echo"
        service = "biscuit_service" if is_dot else "echo_service"
        out["devices"].append(
            {
                "device": device,
                "label": DEVICE_LABELS.get(device, device),
                "commands": [
                    f"adb shell setprop persist.{prop}.ota.releases {releases_json}",
                    f"adb shell {service} update check",
                    f"adb shell {service} update status",
                ],
            }
        )
    if entry.data.get(CONF_MIRROR_KIOSK):
        out["kiosk_releases_json"] = f"{base}/{KIOSK_RELEASES_FILE}"
        out["devices"].append(
            {
                "device": "kiosk_satellite",
                "label": "Kiosk Satellite (any Android device)",
                "commands": [
                    "Settings > Device > Updates > Update source: Custom Repository",
                    f"Repository URL: {out['kiosk_releases_json']}",
                ],
            }
        )
    return out


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the domain-wide services."""

    async def handle_sync(call: ServiceCall) -> None:
        """Check GitHub now and refresh the mirrored folder."""
        for coordinator in _coordinators(hass):
            await coordinator.async_request_refresh()

    async def handle_adb_commands(call: ServiceCall) -> ServiceResponse:
        """Return the per-device setup commands for the current configuration."""
        return {
            "entries": [
                _adb_commands_for_entry(entry)
                for entry in hass.config_entries.async_entries(DOMAIN)
            ]
        }

    hass.services.async_register(DOMAIN, SERVICE_SYNC, handle_sync, schema=_EMPTY_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADB_COMMANDS,
        handle_adb_commands,
        schema=_EMPTY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
