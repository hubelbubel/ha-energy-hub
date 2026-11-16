"""Minimaler Ersatz für Home Assistant, damit der Regler ohne HA testbar ist.

Nachgebildet ist nur, was controller.py benutzt: Zustände, Dienstaufrufe,
Ereignisbus, Speicher und die Uhr. Das ersetzt keinen Test in einem echten
Home Assistant, prüft aber die Abläufe im Regler.
"""
from __future__ import annotations

import importlib
import sys
import types
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

COMPONENT = Path(__file__).parents[1] / "custom_components" / "energy_hub"
TZ = timezone(timedelta(hours=1))


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 16, 12, 0, tzinfo=TZ)

    def advance(self, **kw) -> None:
        self.now += timedelta(**kw)


CLOCK = Clock()


class State:
    def __init__(self, state, attributes=None) -> None:
        self.state = str(state)
        self.attributes = attributes or {}


class States:
    def __init__(self) -> None:
        self._states: dict[str, State] = {}

    def get(self, entity_id):
        return self._states.get(entity_id)

    def set(self, entity_id, state, **attributes) -> None:
        old = self._states.get(entity_id)
        self._states[entity_id] = State(state, {**(old.attributes if old else {}), **attributes})


class HomeAssistantError(Exception):
    pass


class Services:
    """select.select_option und number.set_value wirken wie echte Entitäten auf den Zustand."""

    def __init__(self, hass) -> None:
        self.hass = hass
        self.calls: list[tuple[str, str, dict]] = []
        self.fail = False

    async def async_call(self, domain, service, data, blocking=False):
        if self.fail:
            raise HomeAssistantError("Modbus antwortet nicht")
        self.calls.append((domain, service, dict(data)))
        if (domain, service) == ("select", "select_option"):
            self.hass.states.set(data["entity_id"], data["option"])
        if (domain, service) == ("number", "set_value"):
            self.hass.states.set(data["entity_id"], data["value"])


class Bus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def async_fire(self, event_type, data=None) -> None:
        self.events.append((event_type, data or {}))


class HomeAssistant:
    def __init__(self) -> None:
        self.states = States()
        self.services = Services(self)
        self.bus = Bus()
        self.data: dict = {}


class ConfigEntry:
    def __init__(self, options) -> None:
        self.entry_id = "test-entry"
        self.options = options


class Store:
    saved: dict | None = None

    def __init__(self, hass, version, key) -> None:
        pass

    async def async_load(self):
        return Store.saved

    async def async_save(self, data) -> None:
        Store.saved = data

    def async_delay_save(self, func, delay) -> None:
        Store.saved = func()


def _module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    return mod


def install():
    """Legt die Ersatzmodule an und lädt controller.py, ohne __init__.py auszuführen."""
    _module("homeassistant")
    _module("homeassistant.config_entries", ConfigEntry=ConfigEntry)
    _module(
        "homeassistant.const",
        ATTR_UNIT_OF_MEASUREMENT="unit_of_measurement",
        STATE_UNAVAILABLE="unavailable",
        STATE_UNKNOWN="unknown",
    )
    _module("homeassistant.core", CALLBACK_TYPE=object, HomeAssistant=HomeAssistant, callback=lambda f: f)
    _module("homeassistant.exceptions", HomeAssistantError=HomeAssistantError)
    registry = types.SimpleNamespace(
        async_get_entity_id=lambda domain, platform, unique_id: "sensor.energy_hub_regelzustand"
    )
    er = _module("homeassistant.helpers.entity_registry", async_get=lambda hass: registry)
    _module("homeassistant.helpers", entity_registry=er)
    _module(
        "homeassistant.helpers.event",
        async_call_later=lambda hass, delay, action: (lambda: None),
        async_track_time_interval=lambda hass, action, interval: (lambda: None),
    )
    _module("homeassistant.helpers.start", async_at_started=lambda hass, cb: (lambda: None))
    _module("homeassistant.helpers.storage", Store=Store)

    def parse_time(text):
        try:
            return time.fromisoformat(text)
        except ValueError:
            return None

    dt = _module(
        "homeassistant.util.dt",
        now=lambda: CLOCK.now,
        utcnow=lambda: CLOCK.now.astimezone(timezone.utc),
        parse_datetime=datetime.fromisoformat,
        parse_time=parse_time,
    )
    _module("homeassistant.util", dt=dt)

    pkg = types.ModuleType("energy_hub_under_test")
    pkg.__path__ = [str(COMPONENT)]
    sys.modules["energy_hub_under_test"] = pkg
    return (
        importlib.import_module("energy_hub_under_test.controller"),
        importlib.import_module("energy_hub_under_test.const"),
    )
