"""Config flow for the Echo Kiosk Offline Updates integration."""
from __future__ import annotations

import re

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_BASE_URL,
    CONF_DEVICES,
    CONF_INTERVAL_HOURS,
    CONF_KIOSK_REPO,
    CONF_KIOSK_UNIVERSAL_ONLY,
    CONF_MIRROR_KIOSK,
    CONF_RELEASE_REPO,
    CONF_WWW_SUBDIR,
    DEFAULT_BASE_URL,
    DEFAULT_INTERVAL_HOURS,
    DEFAULT_RELEASE_REPO,
    DEFAULT_WWW_SUBDIR,
    DOMAIN,
    KIOSK_DEFAULT_REPO,
    NAME,
)
from .coordinator import async_probe_repo

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_DEVICE_RE = re.compile(r"^[a-z0-9_-]+$")
_SUBDIR_RE = re.compile(r"^[A-Za-z0-9_-]+$")

_BASE_URL_RE = re.compile(r"^https?://\S+$")


class EchoOfflineUpdatesConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for the update mirror."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            repo = str(user_input[CONF_RELEASE_REPO]).strip().strip("/")
            kiosk_repo = str(
                user_input.get(CONF_KIOSK_REPO, KIOSK_DEFAULT_REPO)
            ).strip().strip("/")
            devices = [
                token
                for token in re.split(r"[,\s]+", str(user_input[CONF_DEVICES]).strip().lower())
                if token
            ]
            subdir = str(user_input[CONF_WWW_SUBDIR]).strip().strip("/")
            base = str(user_input[CONF_BASE_URL]).strip().rstrip("/")

            if not _REPO_RE.fullmatch(repo):
                errors[CONF_RELEASE_REPO] = "invalid_repo"
            if any(not _DEVICE_RE.fullmatch(device) for device in devices):
                errors[CONF_DEVICES] = "invalid_devices"
            if not _SUBDIR_RE.fullmatch(subdir):
                errors[CONF_WWW_SUBDIR] = "invalid_subdir"
            if not _BASE_URL_RE.fullmatch(base):
                errors[CONF_BASE_URL] = "invalid_base_url"
            if user_input[CONF_MIRROR_KIOSK] and not _REPO_RE.fullmatch(kiosk_repo):
                errors[CONF_KIOSK_REPO] = "invalid_repo"

            if not errors:
                await self.async_set_unique_id(repo)
                self._abort_if_unique_id_configured()
                session = async_get_clientsession(self.hass)
                targets = [repo, kiosk_repo] if user_input[CONF_MIRROR_KIOSK] else [repo]
                for target in targets:
                    status = await async_probe_repo(session, target)
                    if status == 404:
                        errors["base"] = "invalid_repo"
                    elif status == 403:
                        errors["base"] = "rate_limited"
                    elif status != 200:
                        errors["base"] = "cannot_connect"
                    if errors.get("base"):
                        break
                else:
                    return self.async_create_entry(
                        title=NAME,
                        data={
                            CONF_RELEASE_REPO: repo,
                            CONF_DEVICES: devices,
                            CONF_BASE_URL: base,
                            CONF_WWW_SUBDIR: subdir,
                            CONF_INTERVAL_HOURS: int(user_input[CONF_INTERVAL_HOURS]),
                            CONF_MIRROR_KIOSK: bool(user_input[CONF_MIRROR_KIOSK]),
                            CONF_KIOSK_REPO: kiosk_repo,
                            CONF_KIOSK_UNIVERSAL_ONLY: bool(
                                user_input.get(CONF_KIOSK_UNIVERSAL_ONLY, False)
                            ),
                        },
                    )

        schema = vol.Schema(
            {
                vol.Required(CONF_RELEASE_REPO, default=DEFAULT_RELEASE_REPO): str,
                vol.Required(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
                vol.Required(CONF_DEVICES, default="biscuit cronos crown"): str,
                vol.Required(CONF_WWW_SUBDIR, default=DEFAULT_WWW_SUBDIR): str,
                vol.Required(
                    CONF_INTERVAL_HOURS, default=DEFAULT_INTERVAL_HOURS
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=168)),
                vol.Optional(CONF_MIRROR_KIOSK, default=True): bool,
                vol.Optional(CONF_KIOSK_REPO, default=KIOSK_DEFAULT_REPO): str,
                vol.Optional(CONF_KIOSK_UNIVERSAL_ONLY, default=False): bool,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
