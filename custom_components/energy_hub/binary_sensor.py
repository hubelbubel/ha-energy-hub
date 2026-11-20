"""Problem-Sensor: an, wenn etwas die Regelung behindert. Grundlage für eigene Benachrichtigungen."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .controller import Controller
from .sensor import device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([ProblemSensor(entry.runtime_data, entry)])


class ProblemSensor(BinarySensorEntity):
    """An, solange ein Problem vorliegt; die Probleme in Klartext stehen im Attribut problems."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, controller: Controller, entry: ConfigEntry) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_problem"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._controller.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return bool(self._controller.problems)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"problems": self._controller.problems}
