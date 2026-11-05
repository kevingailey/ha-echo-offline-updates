"""Sensor platform for the Echo Kiosk Offline Updates integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DEVICES,
    CONF_INTERVAL_HOURS,
    CONF_MIRROR_KIOSK,
    DEVICE_LABELS,
    DEVICE_NAME,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import EchoOfflineCoordinator, KioskMirror, MirrorData


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up the mirror sensors."""
    coordinator: EchoOfflineCoordinator = entry.runtime_data
    entities: list[SensorEntity] = [MirrorStatusSensor(coordinator, entry)]
    for device in entry.data.get(CONF_DEVICES, []):
        entities.append(DeviceReleaseSensor(coordinator, entry, device))
    if entry.data.get(CONF_MIRROR_KIOSK):
        entities.append(KioskReleaseSensor(coordinator, entry))
    async_add_entities(entities)


class _MirrorEntity(CoordinatorEntity[EchoOfflineCoordinator], SensorEntity):
    """Base sensor, bound to the mirror device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: EchoOfflineCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_NAME,
            manufacturer=MANUFACTURER,
            model="Release mirror (LineageOS Echo + Kiosk Satellite)",
        )

    @property
    def available(self) -> bool:
        """Stay available so the status sensor keeps reporting after a failed check."""
        return True


class MirrorStatusSensor(_MirrorEntity):
    """Overall mirror health: last sync, folder and per-check errors."""

    _attr_name = "Mirror status"
    _attr_unique_id = "{entry}-status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:cloud-sync"

    def __init__(self, coordinator: EchoOfflineCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = self._attr_unique_id.format(entry=entry.entry_id)

    @property
    def native_value(self) -> str:
        """ok, warning (some checks failed), or error (no sync at all)."""
        data: MirrorData | None = self.coordinator.data
        if data is None or not self.coordinator.last_update_success:
            return "error"
        if data.errors:
            return "warning"
        return "ok"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        if data is None:
            return None
        return {
            "last_sync": data.last_sync.isoformat() if data.last_sync else None,
            "echo_repo": data.echo_repo,
            "kiosk_repo": data.kiosk_repo,
            "base_url": data.base_url,
            "www_path": data.www_path,
            "interval_hours": self._entry.data[CONF_INTERVAL_HOURS],
            "mirrored_devices": sorted(data.devices),
            "upstream_errors": data.errors,
        }


class DeviceReleaseSensor(_MirrorEntity):
    """The newest image mirrored for one device codename."""

    _attr_name = "{label} release"
    _attr_icon = "mdi:package-up"

    def __init__(
        self, coordinator: EchoOfflineCoordinator, entry: ConfigEntry, device: str
    ) -> None:
        super().__init__(coordinator, entry)
        self._device = device
        self._attr_name = self._attr_name.format(label=DEVICE_LABELS.get(device, device))
        self._attr_unique_id = f"{entry.entry_id}-{device}"

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        mirror = data.devices.get(self._device) if data else None
        return mirror.version if mirror else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        mirror = data.devices.get(self._device) if data else None
        if mirror is None:
            return None
        return {
            "tag": mirror.tag,
            "image_file": mirror.zip.name,
            "image_size_bytes": mirror.zip.size,
            "signature_file": mirror.sig.name if mirror.sig else None,
            "download_url": mirror.zip.url,
        }


class KioskReleaseSensor(_MirrorEntity):
    """The newest Kiosk Satellite release mirrored for the custom repository."""

    _attr_name = "Kiosk Satellite release"
    _attr_unique_id = "{entry}-kiosk"
    _attr_icon = "mdi:android"

    def __init__(self, coordinator: EchoOfflineCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = self._attr_unique_id.format(entry=entry.entry_id)

    @property
    def native_value(self) -> str | None:
        kiosk: KioskMirror | None = self.coordinator.data.kiosk if self.coordinator.data else None
        return kiosk.tag if kiosk else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        kiosk = data.kiosk if data else None
        if kiosk is None:
            return None
        return {
            "apk_files": [
                {"name": asset.name, "size_bytes": asset.size, "url": asset.url}
                for asset in kiosk.files
            ],
            "releases_json": f"{data.base_url}/{kiosk.json_name}",
        }
