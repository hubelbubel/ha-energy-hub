"""Energy Hub: Wärmepumpe anzeigen und nach PV-Überschuss führen."""
from __future__ import annotations

from pathlib import Path

import voluptuous as vol

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from . import const as c
from .controller import Controller
from .websocket_api import async_register_websocket

PLATFORMS = [Platform.SENSOR, Platform.SWITCH]

type EnergyHubConfigEntry = ConfigEntry[Controller]

OVERRIDE_SCHEMA = vol.Schema(
    {
        vol.Required("mode"): vol.In(c.MODES),
        vol.Optional("minutes"): vol.All(vol.Coerce(float), vol.Range(min=1, max=7 * 24 * 60)),
    }
)


def get_controller(hass: HomeAssistant) -> Controller | None:
    """Liefert den Regler der (einzigen) geladenen Installation."""
    for entry in hass.config_entries.async_entries(c.DOMAIN):
        controller = getattr(entry, "runtime_data", None)
        if isinstance(controller, Controller):
            return controller
    return None


async def async_setup_entry(hass: HomeAssistant, entry: EnergyHubConfigEntry) -> bool:
    """Richtet Regler, Entitäten, Dienste und das Panel in der Seitenleiste ein."""
    controller = Controller(hass, entry)
    await controller.async_start()
    entry.runtime_data = controller

    shared = hass.data.setdefault(c.DOMAIN, {})
    if not shared.get("static"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(c.STATIC_URL, str(Path(__file__).parent / "frontend"), False)]
        )
        async_register_websocket(hass)
        _register_services(hass)
        shared["static"] = True

    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=c.PANEL_URL_PATH,
        webcomponent_name=c.PANEL_COMPONENT,
        sidebar_title=c.PANEL_TITLE,
        sidebar_icon=c.PANEL_ICON,
        module_url=f"{c.STATIC_URL}/energy-hub-panel.js?v={c.VERSION}",
        require_admin=False,
        config={"version": c.VERSION},
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EnergyHubConfigEntry) -> bool:
    """Entfernt Panel und Entitäten. An der Wärmepumpe wird dabei nichts verstellt."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        frontend.async_remove_panel(hass, c.PANEL_URL_PATH)
        await entry.runtime_data.async_stop()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: EnergyHubConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _register_services(hass: HomeAssistant) -> None:
    def _controller() -> Controller:
        controller = get_controller(hass)
        if controller is None:
            raise ServiceValidationError("Energy Hub ist nicht geladen.")
        return controller

    async def _set_override(call: ServiceCall) -> None:
        await _controller().async_set_override(call.data["mode"], call.data.get("minutes"))

    async def _clear_override(call: ServiceCall) -> None:
        await _controller().async_clear_override()

    hass.services.async_register(c.DOMAIN, c.SERVICE_SET_OVERRIDE, _set_override, OVERRIDE_SCHEMA)
    hass.services.async_register(c.DOMAIN, c.SERVICE_CLEAR_OVERRIDE, _clear_override, vol.Schema({}))
