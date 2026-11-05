"""Constants for the Echo Kiosk Offline Updates integration."""
from __future__ import annotations

DOMAIN = "echo_offline_updates"
NAME = "Echo Kiosk Offline Updates"
DEVICE_NAME = "Echo Kiosk Update Mirror"
MANUFACTURER = "jxlarrea"

CONF_RELEASE_REPO = "release_repo"
CONF_DEVICES = "devices"
CONF_BASE_URL = "base_url"
CONF_WWW_SUBDIR = "www_subdir"
CONF_INTERVAL_HOURS = "interval_hours"
CONF_MIRROR_KIOSK = "mirror_kiosk_satellite"
CONF_KIOSK_REPO = "kiosk_repo"
CONF_KIOSK_UNIVERSAL_ONLY = "kiosk_universal_only"

DEFAULT_RELEASE_REPO = "jxlarrea/lineageos-echo-kiosk-satellite"
KIOSK_DEFAULT_REPO = "jxlarrea/kiosk-satellite"
DEFAULT_BASE_URL = "http://homeassistant.local:8123/local/echo-updates"
DEFAULT_WWW_SUBDIR = "echo-updates"
DEFAULT_INTERVAL_HOURS = 6

GITHUB_API = "https://api.github.com"
USER_AGENT = "ha-echo-offline-updates (https://github.com/kevingailey/ha-echo-offline-updates)"

# Filenames expected by EchoService / BiscuitService / Kiosk Satellite.
# They share one folder on purpose; see offline-updates.md and updates.md.
ECHO_RELEASES_FILE = "echo-releases.json"
KIOSK_RELEASES_FILE = "releases.json"
ECHO_IMAGE_PREFIX = "lineageos-echo-kiosk-satellite-"
KIOSK_IMAGE_PREFIX = "kiosk-satellite-"

SERVICE_SYNC = "sync"
SERVICE_ADB_COMMANDS = "adb_commands"

DEVICE_LABELS = {
    "biscuit": "Echo Dot (2nd gen)",
    "cronos": "Echo Show 5 (2nd gen)",
    "crown": "Echo Show 8 (1st gen)",
}
