"""WebSocket-Schnittstelle für das Panel in der Seitenleiste."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from . import const as c
from .tigo import RegistryEntity, build_layout


def _controller(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]):
    from . import get_controller  # noqa: PLC0415 - vermeidet Importzyklus

    controller = get_controller(hass)
    if controller is None:
        connection.send_error(msg["id"], "not_loaded", "Energy Hub ist nicht geladen.")
    return controller


@websocket_api.websocket_command({vol.Required("type"): f"{c.DOMAIN}/subscribe"})
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Sendet den Zustand sofort und bei jeder Änderung. Das Logbuch nur, wenn es sich geändert hat."""
    controller = _controller(hass, connection, msg)
    if controller is None:
        return
    sent_rev = -1

    @callback
    def _forward() -> None:
        nonlocal sent_rev
        with_log = controller.log_rev != sent_rev
        sent_rev = controller.log_rev
        connection.send_message(
            websocket_api.event_message(msg["id"], controller.snapshot(with_log=with_log))
        )

    connection.subscriptions[msg["id"]] = controller.async_add_listener(_forward)
    connection.send_result(msg["id"])
    _forward()


@websocket_api.websocket_command(
    {vol.Required("type"): f"{c.DOMAIN}/set_automation", vol.Required("enabled"): bool}
)
@websocket_api.async_response
async def ws_set_automation(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    controller = _controller(hass, connection, msg)
    if controller is None:
        return
    await controller.async_set_automation(msg["enabled"])
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{c.DOMAIN}/set_override",
        vol.Required("mode"): vol.In(c.MODES),
        vol.Optional("minutes"): vol.Any(None, vol.All(vol.Coerce(float), vol.Range(min=1))),
    }
)
@websocket_api.async_response
async def ws_set_override(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    controller = _controller(hass, connection, msg)
    if controller is None:
        return
    await controller.async_set_override(msg["mode"], msg.get("minutes"))
    connection.send_result(msg["id"])


@websocket_api.websocket_command({vol.Required("type"): f"{c.DOMAIN}/clear_override"})
@websocket_api.async_response
async def ws_clear_override(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    controller = _controller(hass, connection, msg)
    if controller is None:
        return
    await controller.async_clear_override()
    connection.send_result(msg["id"])


@websocket_api.websocket_command({vol.Required("type"): f"{c.DOMAIN}/clear_log"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_clear_log(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    controller = _controller(hass, connection, msg)
    if controller is None:
        return
    await controller.async_clear_log()
    connection.send_result(msg["id"])


@websocket_api.websocket_command({vol.Required("type"): f"{c.DOMAIN}/pv_layout"})
@callback
def ws_pv_layout(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Tigo-Optimierer mit String und Entitäten, gelesen aus dem Entitätsregister."""
    entries = [(entry.entry_id, dict(entry.options)) for entry in hass.config_entries.async_entries(c.TIGO_DOMAIN)]
    registry = er.async_get(hass)
    entities = [
        RegistryEntity(
            entity_id=ent.entity_id,
            unique_id=str(ent.unique_id),
            config_entry_id=ent.config_entry_id or "",
            disabled=ent.disabled_by is not None,
        )
        for ent in registry.entities.values()
        if ent.platform == c.TIGO_DOMAIN and ent.entity_id.startswith("sensor.")
    ]
    connection.send_result(msg["id"], {"found": bool(entries), **build_layout(entries, entities)})


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    for command in (
        ws_subscribe,
        ws_set_automation,
        ws_set_override,
        ws_clear_override,
        ws_clear_log,
        ws_pv_layout,
    ):
        websocket_api.async_register_command(hass, command)
