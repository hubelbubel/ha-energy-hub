"""Regler: liest Messwerte, entscheidet, stellt die Wärmepumpe und führt das Logbuch."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, time, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import const as c
from .logic import (
    MODE_BOOST,
    MODE_LABEL,
    MODE_NORMAL,
    MODE_SETBACK,
    Decision,
    Inputs,
    Override,
    Settings,
    Timers,
    decide,
    ready_threshold,
    update_timers,
)

_LOGGER = logging.getLogger(__name__)

_POWER_FACTORS = {"w": 1.0, "kw": 1000.0, "mw": 1_000_000.0}
_ENERGY_FACTORS = {"wh": 0.001, "kwh": 1.0, "mwh": 1000.0}

ENTITY_KEYS = (
    c.CONF_ENT_FLOW,
    c.CONF_ENT_RETURN,
    c.CONF_ENT_RETURN_TARGET,
    c.CONF_ENT_DHW,
    c.CONF_ENT_DHW_TARGET,
    c.CONF_ENT_OUTDOOR,
    c.CONF_ENT_STATUS,
    c.CONF_ENT_COMPRESSOR,
    c.CONF_ENT_POWER_EL,
    c.CONF_ENT_POWER_HEAT,
    c.CONF_ENT_SURPLUS,
    c.CONF_ENT_FORECAST_TODAY,
    c.CONF_ENT_FORECAST_TOMORROW,
    c.CONF_ENT_SMART_GRID,
    c.CONF_ENT_SHIFT,
    c.CONF_ENT_ENERGY_EL,
    c.CONF_ENT_ENERGY_HEAT,
    c.CONF_ENT_ENERGY_DHW,
    c.CONF_ENT_ENERGY_ENV,
    c.CONF_ENT_HEATER,
    c.CONF_ENT_SECOND_HEAT,
    c.CONF_ENT_STORAGE,
    c.CONF_ENT_LOCK,
    c.CONF_ENT_FIREPLACE,
    c.CONF_ENT_FIREPLACE_STATUS,
    c.CONF_ENT_GRID,
    c.CONF_ENT_PV,
    c.CONF_ENT_BATTERY,
    c.CONF_ENT_BATTERY_SOC,
    c.CONF_ENT_HOUSE,
    c.CONF_ENT_WALLBOX,
    c.CONF_ENT_GRID_IMPORT_ENERGY,
    c.CONF_ENT_GRID_EXPORT_ENERGY,
    c.CONF_ENT_PV_ENERGY,
    c.CONF_ENT_BATTERY_CHARGE_ENERGY,
    c.CONF_ENT_BATTERY_DISCHARGE_ENERGY,
    c.CONF_ENT_INV_STATUS,
    c.CONF_ENT_MPPT1_POWER,
    c.CONF_ENT_MPPT1_VOLTAGE,
    c.CONF_ENT_MPPT1_CURRENT,
    c.CONF_ENT_MPPT2_POWER,
    c.CONF_ENT_MPPT2_VOLTAGE,
    c.CONF_ENT_MPPT2_CURRENT,
    c.CONF_ENT_GRID_FREQUENCY,
    c.CONF_ENT_PV_ENERGY_TODAY,
    c.CONF_ENT_PV_ENERGY_TOTAL,
    c.CONF_ENT_LOAD_ENERGY_TODAY,
    c.CONF_ENT_LOAD_ENERGY_TOTAL,
    c.CONF_ENT_IMPORT_ENERGY_TODAY,
    c.CONF_ENT_IMPORT_ENERGY_TOTAL,
    c.CONF_ENT_EXPORT_ENERGY_TODAY,
    c.CONF_ENT_EXPORT_ENERGY_TOTAL,
)

SETTING_KEYS = (
    c.CONF_BOOST_ON_W,
    c.CONF_BOOST_ON_MIN,
    c.CONF_BOOST_OFF_W,
    c.CONF_BOOST_OFF_MIN,
    c.CONF_MIN_HOLD_MIN,
    c.CONF_SETBACK_ENABLED,
    c.CONF_SETBACK_START,
    c.CONF_SETBACK_END,
    c.CONF_SETBACK_MIN_FORECAST,
    c.CONF_SETBACK_MIN_OUTDOOR,
    c.CONF_SETBACK_MIN_DHW,
    c.CONF_ACTUATOR,
    c.CONF_SHIFT_BOOST_K,
    c.CONF_SHIFT_SETBACK_K,
    c.CONF_SURPLUS_SIGN,
    c.CONF_STORAGE_READY_DELTA_K,
    c.CONF_STORAGE_READY_C,
    c.CONF_STORAGE_BLOCKS_BOOST,
    c.CONF_LOCK_REGEN_VALUE,
    c.CONF_FIREPLACE_ON_C,
    c.CONF_GRID_SIGN,
    c.CONF_BATTERY_SIGN,
    c.CONF_TIGO_MPPT1,
    c.CONF_TIGO_MPPT2,
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class Controller:
    """Hält den Regelzustand einer Installation."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store: Store[dict[str, Any]] = Store(hass, c.STORAGE_VERSION, c.STORAGE_KEY)
        self._data: dict[str, Any] = {}
        self._listeners: set[Callable[[], None]] = set()
        self._unsubs: list[CALLBACK_TYPE] = []
        self._lock = asyncio.Lock()
        self._timers = Timers()
        self._decision = Decision(MODE_NORMAL, "Die Regelung startet.", "startup")
        self._inputs: Inputs | None = None
        self._forecast_tomorrow: float | None = None
        self._aux: dict[str, Any] = {}
        self._retry_at: datetime | None = None
        self._last_apply: datetime | None = None
        self._last_error: str | None = None
        self.log_rev = 0

    # ------------------------------------------------------------------ Zugriff
    @property
    def options(self) -> dict[str, Any]:
        """Einstellungen mit Standardwerten. Geleerte optionale Zahlen bleiben None."""
        merged: dict[str, Any] = {**c.DEFAULTS, **self.entry.options}
        for key in c.OPTIONAL_NUMBERS:
            if key not in self.entry.options:
                merged[key] = None
        return merged

    @property
    def mode(self) -> str:
        return self._data["mode"]

    @property
    def mode_since(self) -> datetime | None:
        return dt_util.parse_datetime(self._data["mode_since"]) if self._data.get("mode_since") else None

    @property
    def automation(self) -> bool:
        return bool(self._data["automation"])

    @property
    def reason(self) -> str:
        return self._decision.reason

    @property
    def dry_run(self) -> bool:
        return self.options[c.CONF_ACTUATOR] == c.ACT_DRY_RUN

    @property
    def override(self) -> Override | None:
        raw = self._data.get("override")
        if not raw:
            return None
        until = dt_util.parse_datetime(raw["until"]) if raw.get("until") else None
        return Override(raw["mode"], until)

    def _settings(self) -> Settings:
        o = self.options

        def opt_float(key: str) -> float | None:
            return None if o[key] is None else float(o[key])

        return Settings(
            boost_on_w=float(o[c.CONF_BOOST_ON_W]),
            boost_on_min=float(o[c.CONF_BOOST_ON_MIN]),
            boost_off_w=float(o[c.CONF_BOOST_OFF_W]),
            boost_off_min=float(o[c.CONF_BOOST_OFF_MIN]),
            min_hold_min=float(o[c.CONF_MIN_HOLD_MIN]),
            setback_enabled=bool(o[c.CONF_SETBACK_ENABLED]),
            setback_start=dt_util.parse_time(str(o[c.CONF_SETBACK_START])) or time(5, 0),
            setback_end=dt_util.parse_time(str(o[c.CONF_SETBACK_END])) or time(10, 0),
            setback_min_forecast_kwh=float(o[c.CONF_SETBACK_MIN_FORECAST]),
            setback_min_outdoor_c=opt_float(c.CONF_SETBACK_MIN_OUTDOOR),
            setback_min_dhw_c=opt_float(c.CONF_SETBACK_MIN_DHW),
            storage_ready_delta_k=float(o[c.CONF_STORAGE_READY_DELTA_K]),
            storage_ready_c=float(o[c.CONF_STORAGE_READY_C]) if o.get(c.CONF_ENT_STORAGE) else None,
            storage_blocks_boost=bool(o[c.CONF_STORAGE_BLOCKS_BOOST]),
        )

    # ------------------------------------------------------------- Lebenszyklus
    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self._data = {
            "automation": True,
            "override": None,
            "mode": MODE_NORMAL,
            "mode_since": dt_util.now().isoformat(),
            "shift_base": None,
            "log": [],
            **stored,
        }
        if self._data["mode"] not in c.MODES:
            self._data["mode"] = MODE_NORMAL

        @callback
        def _begin(_hass: HomeAssistant) -> None:
            # Erst nach dem Start auswerten, damit die Sensoren Werte haben.
            self._unsubs.append(async_call_later(self.hass, 45, self._async_tick))
            self._unsubs.append(
                async_track_time_interval(
                    self.hass, self._async_tick, timedelta(seconds=c.EVALUATE_SECONDS)
                )
            )

        self._unsubs.append(async_at_started(self.hass, _begin))

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self._data)

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.add(listener)

        @callback
        def _remove() -> None:
            self._listeners.discard(listener)

        return _remove

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    def _save(self) -> None:
        self._store.async_delay_save(lambda: self._data, 5)

    # ---------------------------------------------------------------- Messwerte
    def _number(self, key: str) -> tuple[float | None, str]:
        entity_id = self.options.get(key)
        if not entity_id:
            return None, ""
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, ""):
            return None, ""
        try:
            value = float(state.state)
        except ValueError:
            return None, ""
        return value, str(state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) or "").strip().lower()

    def _power_w(self, key: str) -> float | None:
        value, unit = self._number(key)
        return None if value is None else value * _POWER_FACTORS.get(unit, 1.0)

    def _energy_kwh(self, key: str) -> float | None:
        value, unit = self._number(key)
        return None if value is None else value * _ENERGY_FACTORS.get(unit, 1.0)

    def _read_inputs(self) -> Inputs:
        surplus = self._power_w(c.CONF_ENT_SURPLUS)
        if surplus is not None and self.options[c.CONF_SURPLUS_SIGN] == c.SIGN_EXPORT_NEGATIVE:
            surplus = -surplus
        self._forecast_tomorrow = self._energy_kwh(c.CONF_ENT_FORECAST_TOMORROW)
        self._aux = self._read_aux()
        return Inputs(
            now=dt_util.now(),
            surplus_w=surplus,
            forecast_kwh=self._energy_kwh(c.CONF_ENT_FORECAST_TODAY),
            outdoor_c=self._number(c.CONF_ENT_OUTDOOR)[0],
            dhw_c=self._number(c.CONF_ENT_DHW)[0],
            storage_c=self._aux["storage"]["temp"],
            return_target_c=self._aux["return_target"],
        )

    def _text(self, key: str) -> str | None:
        entity_id = self.options.get(key)
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, ""):
            return None
        return state.state

    def _read_aux(self) -> dict[str, Any]:
        """Kamin und Speicher: Temperaturen und die daraus abgeleiteten Zustände."""
        o = self.options
        storage = self._number(c.CONF_ENT_STORAGE)[0]
        return_target = self._number(c.CONF_ENT_RETURN_TARGET)[0]
        ready_c = ready_threshold(
            return_target, float(o[c.CONF_STORAGE_READY_DELTA_K]), float(o[c.CONF_STORAGE_READY_C])
        )
        fireplace = self._number(c.CONF_ENT_FIREPLACE)[0]
        on_c = float(o[c.CONF_FIREPLACE_ON_C])
        lock = self._text(c.CONF_ENT_LOCK)
        wanted = {v.strip().casefold() for v in str(o[c.CONF_LOCK_REGEN_VALUE]).split(",") if v.strip()}
        return {
            "return_target": return_target,
            "storage": {
                "temp": storage,
                "ready": None if storage is None else storage >= ready_c,
                "ready_c": ready_c,
                "basis": "fixed" if return_target is None else "return_target",
                "drawing": None if lock is None else lock.strip().casefold() in wanted,
            },
            "fireplace": {
                "temp": fireplace,
                "on": None if fireplace is None else fireplace >= on_c,
                "on_c": on_c,
                "status": self._text(c.CONF_ENT_FIREPLACE_STATUS),
            },
        }

    # ----------------------------------------------------------------- Logbuch
    def _log(
        self,
        kind: str,
        text: str,
        *,
        mode_from: str | None = None,
        mode_to: str | None = None,
        result: str | None = None,
        detail: str | None = None,
    ) -> None:
        inputs = self._inputs
        entry = {
            "ts": dt_util.utcnow().isoformat(),
            "kind": kind,
            "text": text,
            "from": mode_from,
            "to": mode_to,
            "result": result,
            "detail": detail,
            "values": {
                "surplus_w": inputs.surplus_w if inputs else None,
                "forecast_kwh": inputs.forecast_kwh if inputs else None,
                "outdoor_c": inputs.outdoor_c if inputs else None,
                "dhw_c": inputs.dhw_c if inputs else None,
                "storage_c": inputs.storage_c if inputs else None,
            },
        }
        log: list[dict[str, Any]] = self._data["log"]
        log.append(entry)
        del log[: max(0, len(log) - c.LOG_LIMIT)]
        self.log_rev += 1
        self._save()

        title = MODE_LABEL[mode_to] if mode_to else {"error": "Fehler"}.get(kind, "Hinweis")
        event = {"name": c.TITLE, "message": f"{title}: {text}", "domain": c.DOMAIN}
        if entity_id := self.state_entity_id:
            event["entity_id"] = entity_id
        self.hass.bus.async_fire("logbook_entry", event)

    @property
    def state_entity_id(self) -> str | None:
        return er.async_get(self.hass).async_get_entity_id(
            "sensor", c.DOMAIN, f"{self.entry.entry_id}_mode"
        )

    async def async_clear_log(self) -> None:
        self._data["log"] = []
        self.log_rev += 1
        self._save()
        self._notify()

    # -------------------------------------------------------------- Bedienung
    async def async_set_automation(self, enabled: bool) -> None:
        if enabled == self.automation:
            return
        self._data["automation"] = enabled
        self._log(
            "automation",
            "Automatik eingeschaltet." if enabled else "Automatik ausgeschaltet.",
        )
        await self.async_evaluate()

    async def async_set_override(self, mode: str, minutes: float | None) -> None:
        until = dt_util.now() + timedelta(minutes=minutes) if minutes else None
        self._data["override"] = {"mode": mode, "until": _iso(until)}
        when = f"bis {until:%H:%M} Uhr" if until else "bis er beendet wird"
        self._log("override", f"Handbetrieb gestartet: {MODE_LABEL[mode]}, {when}.")
        self._retry_at = None
        await self.async_evaluate()

    async def async_clear_override(self, *, expired: bool = False) -> None:
        if not self._data.get("override"):
            return
        self._data["override"] = None
        self._log("override", "Handbetrieb abgelaufen." if expired else "Handbetrieb beendet.")
        if not expired:
            await self.async_evaluate()

    # ------------------------------------------------------------------ Regeln
    async def _async_tick(self, _now: datetime) -> None:
        await self.async_evaluate()

    async def async_evaluate(self) -> None:
        async with self._lock:
            try:
                await self._evaluate()
            except Exception:  # noqa: BLE001 - die Regelung darf HA nie mitreißen
                _LOGGER.exception("Auswertung fehlgeschlagen")
            self._notify()

    async def _evaluate(self) -> None:
        inputs = self._inputs = self._read_inputs()
        now = inputs.now
        settings = self._settings()
        self._timers = update_timers(self._timers, inputs, settings)

        override = self.override
        if override and override.until and now >= override.until:
            await self.async_clear_override(expired=True)
            override = None

        decision = decide(
            inputs, settings, self._timers, self.mode, self.mode_since, self.automation, override
        )
        self._decision = decision

        if decision.mode != self.mode:
            if self._retry_at and now < self._retry_at:
                return
            previous = self.mode
            result, detail = await self._apply(decision.mode)
            if result == "failed":
                self._retry_at = now + timedelta(minutes=c.REAPPLY_MINUTES)
                self._last_error = detail
                self._log(
                    "error",
                    f"Die Vorgabe „{MODE_LABEL[decision.mode]}“ konnte nicht gesetzt werden. "
                    f"Nächster Versuch um {self._retry_at:%H:%M} Uhr.",
                    mode_from=previous,
                    result=result,
                    detail=detail,
                )
                return
            self._retry_at = None
            self._last_error = None
            self._last_apply = now
            self._data["mode"] = decision.mode
            self._data["mode_since"] = now.isoformat()
            self._log(
                "switch",
                decision.reason,
                mode_from=previous,
                mode_to=decision.mode,
                result=result,
                detail=detail,
            )
            return

        await self._reconcile(now, override is not None)

    async def _reconcile(self, now: datetime, override_active: bool) -> None:
        """Setzt die Vorgabe erneut, wenn sie an der Wärmepumpe verloren ging."""
        if self.dry_run or not (self.automation or override_active):
            return
        if self._last_apply and now - self._last_apply < timedelta(minutes=c.REAPPLY_MINUTES):
            return
        matches, found = self._actuator_matches(self.mode)
        if matches is not False:
            return
        self._last_apply = now
        result, detail = await self._apply(self.mode, reapply=True)
        self._log(
            "reapply" if result != "failed" else "error",
            f"Die Vorgabe „{MODE_LABEL[self.mode]}“ stand nicht mehr an der Wärmepumpe "
            f"(gefunden: {found}) und wurde erneut gesetzt."
            if result != "failed"
            else f"Die Vorgabe „{MODE_LABEL[self.mode]}“ ging verloren und ließ sich nicht erneut setzen.",
            result=result,
            detail=detail,
        )

    # --------------------------------------------------------------- Stellgröße
    def _smart_grid_option(self, mode: str) -> str:
        o = self.options
        return str(
            {
                MODE_NORMAL: o[c.CONF_OPT_NORMAL],
                MODE_BOOST: o[c.CONF_OPT_BOOST],
                MODE_SETBACK: o[c.CONF_OPT_SETBACK],
            }[mode]
        )

    def _shift_target(self, mode: str, base: float) -> float:
        o = self.options
        if mode == MODE_BOOST:
            return base + float(o[c.CONF_SHIFT_BOOST_K])
        if mode == MODE_SETBACK:
            return base - float(o[c.CONF_SHIFT_SETBACK_K])
        return base

    def _actuator_matches(self, mode: str) -> tuple[bool | None, str]:
        """True/False, ob die Vorgabe ansteht; None, wenn das nicht prüfbar ist."""
        o = self.options
        if o[c.CONF_ACTUATOR] == c.ACT_SMART_GRID:
            state = self.hass.states.get(o.get(c.CONF_ENT_SMART_GRID) or "")
            if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                return None, ""
            return state.state == self._smart_grid_option(mode), state.state
        if o[c.CONF_ACTUATOR] == c.ACT_SHIFT:
            base = self._data.get("shift_base")
            if mode == MODE_NORMAL or base is None:
                return None, ""
            value, _unit = self._number(c.CONF_ENT_SHIFT)
            if value is None:
                return None, ""
            return abs(value - self._shift_target(mode, base)) < 0.05, f"{value:g}"
        return None, ""

    async def _apply(self, mode: str, *, reapply: bool = False) -> tuple[str, str | None]:
        """Schreibt die Vorgabe. Liefert ('sent'|'simulated'|'failed', Detail)."""
        o = self.options
        actuator = o[c.CONF_ACTUATOR]
        if actuator == c.ACT_DRY_RUN:
            return "simulated", None
        try:
            if actuator == c.ACT_SMART_GRID:
                entity_id = o.get(c.CONF_ENT_SMART_GRID)
                if not entity_id:
                    return "failed", "Es ist keine Smart-Grid-Entität eingestellt."
                state = self.hass.states.get(entity_id)
                if state is None or state.state == STATE_UNAVAILABLE:
                    return "failed", f"{entity_id} ist nicht verfügbar."
                option = self._smart_grid_option(mode)
                if option not in (state.attributes.get("options") or []):
                    return "failed", f"Die Option „{option}“ gibt es bei {entity_id} nicht."
                await self.hass.services.async_call(
                    "select",
                    "select_option",
                    {"entity_id": entity_id, "option": option},
                    blocking=True,
                )
                return "sent", f"{entity_id} → {option}"

            entity_id = o.get(c.CONF_ENT_SHIFT)
            if not entity_id:
                return "failed", "Es ist keine Entität für die Parallelverschiebung eingestellt."
            state = self.hass.states.get(entity_id)
            value, _unit = self._number(c.CONF_ENT_SHIFT)
            if state is None or value is None:
                return "failed", f"{entity_id} ist nicht verfügbar."
            base = self._data.get("shift_base")
            if base is None or (self.mode == MODE_NORMAL and not reapply):
                base = value
            target = self._shift_target(mode, base)
            low, high = state.attributes.get("min"), state.attributes.get("max")
            if low is not None:
                target = max(float(low), target)
            if high is not None:
                target = min(float(high), target)
            await self.hass.services.async_call(
                "number", "set_value", {"entity_id": entity_id, "value": target}, blocking=True
            )
            self._data["shift_base"] = None if mode == MODE_NORMAL else base
            return "sent", f"{entity_id} → {target:g} (Grundwert {base:g})"
        except HomeAssistantError as err:
            return "failed", str(err)

    # ------------------------------------------------------------- Momentbild
    def snapshot(self, *, with_log: bool = True) -> dict[str, Any]:
        o = self.options
        inputs = self._inputs
        override = self._data.get("override")
        data: dict[str, Any] = {
            "version": c.VERSION,
            "entities": {key: o.get(key) or None for key in ENTITY_KEYS},
            "export_extra": list(o.get(c.CONF_EXPORT_EXTRA) or []),
            "consumers": list(o.get(c.CONF_CONSUMERS) or []),
            "settings": {key: o.get(key) for key in SETTING_KEYS},
            "state": {
                "mode": self.mode,
                "since": self._data.get("mode_since"),
                "reason": self._decision.reason,
                "rule": self._decision.rule,
                "automation": self.automation,
                "override": override,
                "dry_run": self.dry_run,
                "state_entity_id": self.state_entity_id,
                "last_error": self._last_error,
                "retry_at": _iso(self._retry_at),
                "above_since": _iso(self._timers.above_since),
                "below_since": _iso(self._timers.below_since),
                "inputs": {
                    "surplus_w": inputs.surplus_w if inputs else None,
                    "forecast_kwh": inputs.forecast_kwh if inputs else None,
                    "forecast_tomorrow_kwh": self._forecast_tomorrow,
                    "outdoor_c": inputs.outdoor_c if inputs else None,
                    "dhw_c": inputs.dhw_c if inputs else None,
                    "storage_c": inputs.storage_c if inputs else None,
                },
                "storage": self._aux.get("storage"),
                "fireplace": self._aux.get("fireplace"),
            },
            "log_rev": self.log_rev,
        }
        if with_log:
            data["log"] = list(reversed(self._data["log"]))
        return data
