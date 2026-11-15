"""Schalter: Automatik ein/aus."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .controller import Controller
from .sensor import device_info


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([AutomationSwitch(entry.runtime_data, entry)])


class AutomationSwitch(SwitchEntity):
    """Aus bedeutet: Die Regelung greift nicht mehr ein und stellt einmal auf Normalbetrieb."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "automation"

    def __init__(self, controller: Controller, entry: ConfigEntry) -> None:
        self._controller = controller
        self._attr_unique_id = f"{entry.entry_id}_automation"
        self._attr_device_info = device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._controller.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self._controller.automation

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._controller.async_set_automation(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._controller.async_set_automation(False)
