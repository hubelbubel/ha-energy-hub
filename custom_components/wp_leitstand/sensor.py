"""Sensor: aktueller Regelzustand mit Begründung."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import const as c
from .controller import Controller


def device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(c.DOMAIN, entry.entry_id)},
        name=c.TITLE,
        manufacturer="WP Leitstand",
        model="PV-geführte Heizungsregelung",
        sw_version=c.VERSION,
        entry_type=DeviceEntryType.SERVICE,
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([ModeSensor(entry.runtime_data, entry)])


class ModeSensor(SensorEntity):
    """normal / boost / setback, dazu Begründung und Zeitpunkt als Attribute."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "mode"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(c.MODES)

    def __init__(self, controller: Controller, entry: ConfigEntry) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_mode"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._controller.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        return self._controller.mode

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ctrl = self._controller
        override = ctrl.override
        return {
            "reason": ctrl.reason,
            "since": ctrl.mode_since.isoformat() if ctrl.mode_since else None,
            "automation": ctrl.automation,
            "override": override.mode if override else None,
            "override_until": override.until.isoformat() if override and override.until else None,
            "dry_run": ctrl.dry_run,
        }
