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
from .alerts import (
    DHW_COLD_C,
    DHW_WARM_AGAIN_K,
    FAULT_DELAY_MIN,
    LEVEL_ISSUES,
    PROBLEM_DELAY_MIN,
    REAPPLY_WINDOW_MIN,
    START_GRACE_MIN,
    Issue,
    Message,
    Runs,
    automation_off_text,
    cold_since,
    cold_text,
    cycling_text,
    entry_title,
    fault_text,
    fmt_c,
    heater_texts,
    locked,
    log_message,
    no_effect_text,
    override_text,
    reapply_text,
    step_issues,
    tag,
    track_runs,
    wanted,
)
from .logic import (
    MODE_BOOST,
    MODE_LABEL,
    MODE_NORMAL,
    MODE_SETBACK,
    MODE_STRONG,
    RUN_MIN_W,
    Decision,
    Inputs,
    Override,
    ReloadCheck,
    Segment,
    Settings,
    Timers,
    battery_fills,
    battery_missing_kwh,
    capacity_step,
    decide,
    dhw_reload_check,
    dhw_reload_end,
    learn_capacity,
    learn_run_power,
    learned_run_w,
    on_rule,
    ready_threshold,
    trim_samples,
    update_timers,
    window_mean,
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
    c.CONF_ENT_DHW_HYST,
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
    c.CONF_BOOST_ON_LEARNED,
    c.CONF_BOOST_ON_MIN,
    c.CONF_BOOST_OFF_W,
    c.CONF_BOOST_OFF_MIN,
    c.CONF_SMOOTHING_MIN,
    c.CONF_OFF_WITHOUT_BATTERY,
    c.CONF_STRONG_ENABLED,
    c.CONF_STRONG_ON_W,
    c.CONF_DHW_RELOAD,
    c.CONF_DHW_RELOAD_HYST_K,
    c.CONF_MIN_HOLD_MIN,
    c.CONF_SETBACK_ENABLED,
    c.CONF_SETBACK_START,
    c.CONF_SETBACK_END,
    c.CONF_SETBACK_MIN_FORECAST,
    c.CONF_SETBACK_MIN_OUTDOOR,
    c.CONF_SETBACK_MIN_DHW,
    c.CONF_ACTUATOR,
    c.CONF_SHIFT_BOOST_K,
    c.CONF_SHIFT_STRONG_K,
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


# Sensoren der Wärmepumpe: Liefert keiner einen Wert, meldet der Problem-Sensor das
HEATPUMP_KEYS = (
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
)


def _parse(value: str | None) -> datetime | None:
    return dt_util.parse_datetime(value) if value else None


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
        # Messwerte der letzten Minuten für Mittelwert und Lücken (nur im Arbeitsspeicher):
        # Überschuss, ohne Akku, für die Wärmepumpe übrig (Akku zuerst bzw. mit seiner Ladeleistung)
        self._samples: dict[str, list[tuple[datetime, float]]] = {
            "surplus": [], "balance": [], "available": [], "available_free": [],
        }
        # Lernen: Zeitpunkt der letzten Messung, letztes Speichern, laufender Abschnitt für die Kapazität
        self._learn_at: datetime | None = None
        self._learn_saved_at: datetime | None = None
        self._segment: Segment | None = None
        self._problems: list[str] = []
        # Warmwasser nachladen: letzte Prüfung, Fehler beim Schreiben der Hysterese, nächster Versuch
        self._reload_check: ReloadCheck | None = None
        self._reload_error: str | None = None
        self._reload_retry_at: datetime | None = None
        self._aux: dict[str, Any] = {}
        self._retry_at: datetime | None = None
        self._last_apply: datetime | None = None
        self._last_error: str | None = None
        # Auffälligkeiten (nur im Arbeitsspeicher): Läufe des Verdichters, erneut gesetzte
        # Vorgaben, seit wann etwas ansteht, Warmwasser kalt seit; Meldungen zum Versenden
        self._runs = Runs()
        self._reapplied: list[datetime] = []
        self._since: dict[str, datetime] = {}
        self._cold_since: datetime | None = None
        self._outbox: list[Message] = []
        self._started_at: datetime | None = None
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
            boost_on_learned=bool(o[c.CONF_BOOST_ON_LEARNED]),
            boost_on_min=float(o[c.CONF_BOOST_ON_MIN]),
            boost_off_w=float(o[c.CONF_BOOST_OFF_W]),
            boost_off_min=float(o[c.CONF_BOOST_OFF_MIN]),
            strong_enabled=bool(o[c.CONF_STRONG_ENABLED]),
            strong_on_w=float(o[c.CONF_STRONG_ON_W]),
            dhw_reload=self.reload_possible,
            dhw_reload_hyst_k=float(o[c.CONF_DHW_RELOAD_HYST_K]),
            min_hold_min=float(o[c.CONF_MIN_HOLD_MIN]),
            smoothing_min=float(o[c.CONF_SMOOTHING_MIN]),
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
            "pv_grid": {},
            # Gelerntes: Leistung der Wärmepumpe im Lauf (W, Minuten Laufzeit), Kapazität des Akkus
            "run_w": None,
            "run_min": 0.0,
            "battery_kwh": None,
            "battery_n": 0,
            # Warmwasser nachladen: läuft seit, Hysterese vorher, Tag und Zeitpunkt des letzten Starts
            "dhw_reload_since": None,
            "dhw_hyst_base": None,
            "dhw_reload_day": None,
            "dhw_reload_last": None,
            # Benachrichtigung: gemeldete Auffälligkeiten (gegen Wiederholung), zuletzt
            # eingerichteter Dienst und Umfang (für die Testnachricht); Automatik aus seit
            "notify_memory": {},
            "notify_setup": None,
            "automation_since": None,
            **stored,
        }
        if self._data["mode"] not in c.MODES:
            self._data["mode"] = MODE_NORMAL
        self._started_at = dt_util.now()
        if not self._data["automation"] and not self._data.get("automation_since"):
            self._data["automation_since"] = self._started_at.isoformat()
        self._queue_setup_message()

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
        self._outbox.clear()
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

    @property
    def off_without_battery(self) -> bool:
        """Endet das Anheben nach dem Überschuss ohne Akku? Nur mit hinterlegtem Akku."""
        o = self.options
        return bool(o[c.CONF_OFF_WITHOUT_BATTERY]) and bool(o.get(c.CONF_ENT_BATTERY))

    def _charge_w(self) -> float | None:
        """Ladeleistung des Akkus in W, Entladen negativ."""
        value = self._power_w(c.CONF_ENT_BATTERY)
        if value is None:
            return None
        return value if self.options[c.CONF_BATTERY_SIGN] == c.BATTERY_CHARGE_POSITIVE else -value

    @property
    def uses_available(self) -> bool:
        """Wird „für die Wärmepumpe übrig“ gerechnet? Mit Leistung der Wärmepumpe oder Akku."""
        return bool(self.options.get(c.CONF_ENT_POWER_EL)) or self.off_without_battery

    def _read_surplus(self, now: datetime) -> dict[str, float | None]:
        """Überschuss, ohne Akku und für die Wärmepumpe übrig, gemittelt; kurze Aussetzer überbrückt.

        Für die Wärmepumpe übrig ist der Überschuss plus ihre eigene Leistung; Entladen des
        Akkus zählt dabei nicht als übrig, Laden nur in der Reihe „available_free“. Was nicht
        gebraucht wird, ist None. Fehlt nur der Wert des Akkus oder der Wärmepumpe, zählt er
        für diesen Zeitpunkt als 0.
        """
        o = self.options
        smoothing = float(o[c.CONF_SMOOTHING_MIN])
        surplus = self._power_w(c.CONF_ENT_SURPLUS)
        if surplus is not None:
            if o[c.CONF_SURPLUS_SIGN] == c.SIGN_EXPORT_NEGATIVE:
                surplus = -surplus
            charge = (self._charge_w() if self.off_without_battery else None) or 0.0
            heat_pump = self._power_w(c.CONF_ENT_POWER_EL) or 0.0
            values = {
                "surplus": surplus,
                "balance": surplus + charge,
                "available": surplus + heat_pump + min(0.0, charge),
                "available_free": surplus + heat_pump + charge,
            }
            for key, value in values.items():
                self._samples[key].append((now, value))
        keep = max(smoothing, c.SURPLUS_GAP_MINUTES)
        gap = c.SURPLUS_GAP_MINUTES
        used = {
            "surplus": True,
            "balance": self.off_without_battery,
            "available": self.uses_available,
            "available_free": self.uses_available,
        }
        out: dict[str, float | None] = {}
        for key, samples in self._samples.items():
            self._samples[key] = trim_samples(samples, now, keep)
            out[key] = window_mean(self._samples[key], now, smoothing, gap) if used[key] else None
        return out

    def _learn(self, now: datetime) -> None:
        """Lernt die Leistung der Wärmepumpe im Lauf und die Kapazität des Akkus."""
        last, self._learn_at = self._learn_at, now
        dt_min = 0.0 if last is None else min(1.0, max(0.0, (now - last).total_seconds() / 60))
        data = self._data
        data["run_w"], data["run_min"] = learn_run_power(
            data.get("run_w"), float(data.get("run_min") or 0.0), self._power_w(c.CONF_ENT_POWER_EL), dt_min
        )
        soc = self._number(c.CONF_ENT_BATTERY_SOC)[0]
        self._segment, estimate = capacity_step(self._segment, now, soc, self._charge_w())
        if estimate is not None:
            data["battery_kwh"], data["battery_n"] = learn_capacity(
                data.get("battery_kwh"), int(data.get("battery_n") or 0), estimate
            )
            _LOGGER.debug("Kapazität des Akkus geschätzt: %.1f kWh", estimate)
        if self._learn_saved_at is None or now - self._learn_saved_at >= timedelta(minutes=c.LEARN_SAVE_MINUTES):
            self._learn_saved_at = now
            self._save()

    @property
    def run_w(self) -> float | None:
        """Gelernte Leistung der Wärmepumpe im Lauf, sobald genug Laufzeit beisammen ist."""
        return learned_run_w(self._data.get("run_w"), float(self._data.get("run_min") or 0.0))

    @property
    def battery_kwh(self) -> float | None:
        """Gelernte Kapazität des Akkus, auf 0,1 kWh gerundet."""
        value = self._data.get("battery_kwh")
        return None if value is None else round(float(value), 1)

    def _read_inputs(self) -> Inputs:
        now = dt_util.now()
        power = self._read_surplus(now)
        self._learn(now)
        self._aux = self._read_aux()
        return Inputs(
            now=now,
            surplus_w=power["surplus"],
            balance_w=power["balance"],
            available_w=power["available"],
            available_free_w=power["available_free"],
            run_w=self.run_w,
            battery_soc=self._number(c.CONF_ENT_BATTERY_SOC)[0],
            battery_kwh=self.battery_kwh,
            forecast_kwh=self._energy_kwh(c.CONF_ENT_FORECAST_TODAY),
            forecast_tomorrow_kwh=self._energy_kwh(c.CONF_ENT_FORECAST_TOMORROW),
            outdoor_c=self._number(c.CONF_ENT_OUTDOOR)[0],
            dhw_c=self._number(c.CONF_ENT_DHW)[0],
            storage_c=self._aux["storage"]["temp"],
            return_target_c=self._aux["return_target"],
            dhw_target_c=self._number(c.CONF_ENT_DHW_TARGET)[0],
            afternoon=self._afternoon(now),
            dhw_heating=self._dhw_heating(),
        )

    def _afternoon(self, now: datetime) -> bool:
        """Nach dem Sonnenhöchststand? Aus sun.sun, ohne die Sonne-Integration ab 13 Uhr."""
        sun = self.hass.states.get("sun.sun")
        rising = sun.attributes.get("rising") if sun is not None else None
        if rising is None:
            return now.hour >= 13
        return not bool(rising)

    def _dhw_heating(self) -> bool | None:
        """Macht die Wärmepumpe gerade Warmwasser? Aus dem Status; None ohne Status."""
        status = self._text(c.CONF_ENT_STATUS)
        return None if status is None else "warmwasser" in status.casefold()

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
        title: str | None = None,
        notify: bool = True,
    ) -> None:
        """Schreibt ins Logbuch (Panel und Home Assistant).

        notify: beim Umfang „alles“ auch als Benachrichtigung. Auffälligkeiten gehen ihren
        eigenen Weg (_check_alerts) und stehen mit title im Logbuch.
        """
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
                "balance_w": inputs.balance_w if inputs else None,
                "available_w": self._on_value(inputs),
                "forecast_kwh": inputs.forecast_kwh if inputs else None,
                "forecast_tomorrow_kwh": inputs.forecast_tomorrow_kwh if inputs else None,
                "outdoor_c": inputs.outdoor_c if inputs else None,
                "dhw_c": inputs.dhw_c if inputs else None,
                "storage_c": inputs.storage_c if inputs else None,
            },
        }
        if title:
            entry["title"] = title
        log: list[dict[str, Any]] = self._data["log"]
        log.append(entry)
        del log[: max(0, len(log) - c.LOG_LIMIT)]
        self.log_rev += 1
        self._save()

        heading = title or entry_title(kind, mode_from, mode_to)
        event = {"name": c.TITLE, "message": f"{heading}: {text}", "domain": c.DOMAIN}
        if entity_id := self.state_entity_id:
            event["entity_id"] = entity_id
        self.hass.bus.async_fire("logbook_entry", event)
        if notify:
            self._outbox.append(log_message(kind, text, mode_from, mode_to, result, detail))

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

    @property
    def pv_grid(self) -> dict[str, list[int]]:
        """Plätze der Optimierer im Panel: {Label: [Zeile, Spalte]}; leer, solange nichts angeordnet ist."""
        grid = self._data.get("pv_grid")
        return {label: list(cell) for label, cell in grid.items()} if isinstance(grid, dict) else {}

    async def async_set_pv_grid(self, grid: dict[str, list[int]]) -> None:
        """Nur Anzeige: kein Logbuch, keine neue Auswertung."""
        self._data["pv_grid"] = {str(label): [int(cell[0]), int(cell[1])] for label, cell in grid.items()}
        self._save()

    # -------------------------------------------------------------- Bedienung
    async def async_set_automation(self, enabled: bool) -> None:
        if enabled == self.automation:
            return
        self._data["automation"] = enabled
        self._data["automation_since"] = None if enabled else dt_util.now().isoformat()
        self._log(
            "automation",
            "Automatik eingeschaltet." if enabled else "Automatik ausgeschaltet.",
        )
        await self.async_evaluate()

    async def async_set_override(self, mode: str, minutes: float | None) -> None:
        now = dt_util.now()
        until = now + timedelta(minutes=minutes) if minutes else None
        self._data["override"] = {"mode": mode, "until": _iso(until), "since": now.isoformat()}
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
            await self._send_outbox()
            self._notify()

    def _on_value(self, inputs: Inputs | None) -> float | None:
        """Was für die Wärmepumpe übrig ist, so wie die Regel es gerade zählt; None ohne diese Rechnung."""
        if inputs is None or inputs.available_w is None:
            return None
        rule = on_rule(inputs, self._settings())
        return rule.value if rule else None

    async def _evaluate(self) -> None:
        inputs = self._inputs = self._read_inputs()
        now = inputs.now
        settings = self._settings()
        self._timers = update_timers(self._timers, inputs, settings, self.mode)
        try:
            await self._decide_and_apply(inputs, settings)
            await self._reload_step(inputs, settings)
        finally:
            self._problems = self._find_problems()
            self._check_alerts(inputs)

    async def _decide_and_apply(self, inputs: Inputs, settings: Settings) -> None:
        now = inputs.now

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
        if result == "failed":
            self._last_error = detail
        else:
            self._last_error = None
            self._reapplied.append(now)
        self._log(
            "reapply" if result != "failed" else "error",
            f"Die Vorgabe „{MODE_LABEL[self.mode]}“ stand nicht mehr an der Wärmepumpe "
            f"(gefunden: {found}) und wurde erneut gesetzt."
            if result != "failed"
            else f"Die Vorgabe „{MODE_LABEL[self.mode]}“ ging verloren und ließ sich nicht erneut setzen.",
            result=result,
            detail=detail,
        )

    # ------------------------------------------------------ Warmwasser nachladen
    @property
    def reload_possible(self) -> bool:
        """Nachladen ist an und alles dafür hinterlegt: Hysterese, Warmwasser und sein Soll."""
        o = self.options
        return bool(
            o.get(c.CONF_DHW_RELOAD)
            and o.get(c.CONF_ENT_DHW_HYST)
            and o.get(c.CONF_ENT_DHW)
            and o.get(c.CONF_ENT_DHW_TARGET)
        )

    async def _reload_step(self, inputs: Inputs, settings: Settings) -> None:
        """Startet, beendet oder prüft das Nachladen des Warmwassers."""
        now = inputs.now
        since = _parse(self._data.get("dhw_reload_since"))
        if since is not None:
            if not self.reload_possible:
                reason = "Nachladen ist abgeschaltet."
            elif self.override is not None:
                reason = "Handbetrieb."
            elif not self.automation:
                reason = "Die Automatik ist aus."
            else:
                reason = dhw_reload_end(inputs, settings, since, self._timers)
            if reason:
                await self._reload_stop(reason, now)
            return
        if self._data.get("dhw_hyst_base") is not None:
            # Die Hysterese steht noch vom letzten Nachladen (Fehler beim Zurückstellen, Neustart)
            await self._reload_restore(now)
            return
        if not self.reload_possible or not self.automation or self.override is not None:
            self._reload_check = None
            return
        done_today = self._data.get("dhw_reload_day") == now.date().isoformat()
        check = dhw_reload_check(inputs, settings, self._timers, done_today)
        self._reload_check = check
        if check.start:
            await self._reload_start(check.reason, now)

    async def _reload_start(self, reason: str, now: datetime) -> None:
        o = self.options
        entity_id = o[c.CONF_ENT_DHW_HYST]
        self._data["dhw_reload_day"] = now.date().isoformat()  # höchstens ein Versuch am Tag
        target = float(o[c.CONF_DHW_RELOAD_HYST_K])
        if self.dry_run:
            result, detail = "simulated", None
        else:
            base = self._number(c.CONF_ENT_DHW_HYST)[0]
            if base is None:
                result, detail = "failed", f"{entity_id} ist nicht verfügbar."
            else:
                result, detail = await self._write_number(entity_id, target)
                if result != "failed":
                    self._data["dhw_hyst_base"] = base
                    detail = f"{entity_id} → {target:g} K (vorher {base:g} K)"
        if result == "failed":
            self._reload_error = detail
            self._log("error", "Das Warmwasser ließ sich nicht nachladen: Die Hysterese ließ sich nicht setzen.",
                      result=result, detail=detail)
            return
        self._reload_error = None
        self._data["dhw_reload_since"] = now.isoformat()
        self._data["dhw_reload_last"] = now.isoformat()
        self._log("dhw_start", reason, result=result, detail=detail)

    async def _reload_stop(self, reason: str, now: datetime) -> None:
        self._data["dhw_reload_since"] = None
        detail = None
        result = "simulated" if self.dry_run else "sent"
        if self._data.get("dhw_hyst_base") is not None:
            result, detail = await self._reload_restore(now, log=False)
        self._log("dhw_end", reason, result=result, detail=detail)

    async def _reload_restore(self, now: datetime, *, log: bool = True) -> tuple[str, str | None]:
        """Stellt die Hysterese von vor dem Nachladen wieder her; bei Fehler alle 5 min neu."""
        if self._reload_retry_at and now < self._reload_retry_at:
            return "failed", self._reload_error
        entity_id = self.options.get(c.CONF_ENT_DHW_HYST)
        base = float(self._data["dhw_hyst_base"])
        if not entity_id:
            self._data["dhw_hyst_base"] = None
            return "failed", "Es ist keine Entität für die Hysterese mehr eingestellt."
        result, detail = await self._write_number(entity_id, base)
        if result == "failed":
            self._reload_error = detail
            self._reload_retry_at = now + timedelta(minutes=c.REAPPLY_MINUTES)
            self._log("error", f"Die Warmwasser-Hysterese ließ sich nicht auf {base:g} K zurückstellen. "
                      f"Nächster Versuch um {self._reload_retry_at:%H:%M} Uhr.", result=result, detail=detail)
            return result, detail
        self._data["dhw_hyst_base"] = None
        self._reload_error = None
        self._reload_retry_at = None
        detail = f"{entity_id} → {base:g} K"
        if log:
            self._log("reapply", "Die Warmwasser-Hysterese vom letzten Nachladen wurde zurückgestellt.",
                      result=result, detail=detail)
        else:
            self._save()
        return result, detail

    async def _write_number(self, entity_id: str, value: float) -> tuple[str, str | None]:
        """Schreibt eine Zahl-Entität, begrenzt auf ihr Minimum und Maximum."""
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, ""):
            return "failed", f"{entity_id} ist nicht verfügbar."
        low, high = state.attributes.get("min"), state.attributes.get("max")
        if low is not None:
            value = max(float(low), value)
        if high is not None:
            value = min(float(high), value)
        try:
            await self.hass.services.async_call(
                "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
            )
        except HomeAssistantError as err:
            return "failed", str(err)
        return "sent", f"{entity_id} → {value:g}"

    def _reload_snapshot(self) -> dict[str, Any] | None:
        if not self.reload_possible:
            return None
        check = self._reload_check
        today = dt_util.now().date().isoformat()
        return {
            "active_since": self._data.get("dhw_reload_since"),
            "last": self._data.get("dhw_reload_last"),
            "done_today": self._data.get("dhw_reload_day") == today,
            "wait": check.short if check and not check.start else None,
            "hyst_base": self._data.get("dhw_hyst_base"),
        }

    # ----------------------------------------------------------------- Probleme
    @property
    def problems(self) -> list[str]:
        """Was gerade nicht stimmt, in Klartext; leer, wenn alles läuft."""
        return list(self._problems)

    def _missing(self, key: str) -> bool:
        entity_id = self.options.get(key)
        state = self.hass.states.get(entity_id) if entity_id else None
        return state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, "")

    def _find_problems(self) -> list[str]:
        """Probleme, die die Regelung behindern. Grundlage des Problem-Sensors."""
        o = self.options
        out: list[str] = []
        if self._last_error:
            out.append(f"Die Wärmepumpe hat die letzte Vorgabe nicht angenommen: {self._last_error}")
        if o.get(c.CONF_ENT_SURPLUS) and self._decision.rule == "no_data":
            out.append(f"Der PV-Überschuss ({o[c.CONF_ENT_SURPLUS]}) liefert keinen Wert.")
        actuator = o[c.CONF_ACTUATOR]
        key = {c.ACT_SMART_GRID: c.CONF_ENT_SMART_GRID, c.ACT_SHIFT: c.CONF_ENT_SHIFT}.get(actuator)
        if key and self._missing(key):
            out.append(f"Die Stellgröße ({o.get(key) or 'nicht eingestellt'}) ist nicht verfügbar.")
        heat_pump = [k for k in HEATPUMP_KEYS if o.get(k)]
        if heat_pump and all(self._missing(k) for k in heat_pump):
            out.append("Die Wärmepumpe meldet keine Werte.")
        if o[c.CONF_SETBACK_ENABLED] and o.get(c.CONF_ENT_FORECAST_TODAY) and self._missing(c.CONF_ENT_FORECAST_TODAY):
            out.append(f"Die PV-Prognose ({o[c.CONF_ENT_FORECAST_TODAY]}) liefert keinen Wert.")
        if self.reload_possible and not self.dry_run and self._missing(c.CONF_ENT_DHW_HYST):
            out.append(f"Die Warmwasser-Hysterese ({o[c.CONF_ENT_DHW_HYST]}) ist nicht verfügbar.")
        elif self._reload_error:
            out.append(f"Die Warmwasser-Hysterese ließ sich nicht setzen: {self._reload_error}")
        service = self.notify_service
        if service and not self.hass.services.has_service("notify", service):
            out.append(f"Der Benachrichtigungsdienst (notify.{service}) ist nicht vorhanden.")
        return out

    # ------------------------------------------------------ Auffälligkeiten
    def _on_off(self, key: str) -> bool | None:
        """Ein/Aus einer Entität (binary_sensor, Schalter); None ohne Wert."""
        text = self._text(key)
        if text is None:
            return None
        low = text.strip().casefold()
        if low in ("on", "true", "an", "ein", "1"):
            return True
        if low in ("off", "false", "aus", "0"):
            return False
        return None

    def _running(self) -> bool | None:
        """Läuft der Verdichter? Aus dem Verdichter-Sensor, sonst aus der elektrischen Leistung."""
        o = self.options
        if o.get(c.CONF_ENT_COMPRESSOR):
            return self._on_off(c.CONF_ENT_COMPRESSOR)
        if o.get(c.CONF_ENT_POWER_EL):
            power = self._power_w(c.CONF_ENT_POWER_EL)
            return None if power is None else power >= RUN_MIN_W
        return None

    def _check_alerts(self, inputs: Inputs) -> None:
        """Sammelt, was gerade auffällig ist, und schreibt neue Meldungen ins Logbuch."""
        now = inputs.now
        o = self.options
        issues: list[Issue] = []
        unknown: set[str] = set()

        self._runs = track_runs(self._runs, now, self._running())
        if text := cycling_text(self._runs, now):
            issues.append(Issue("cycling", "Takten", text, daily=True))

        names: list[str] = []
        for key, name in ((c.CONF_ENT_HEATER, "Heizstab"), (c.CONF_ENT_SECOND_HEAT, "2. Wärmeerzeuger")):
            if o.get(key):
                on = self._on_off(key)
                if on is None:
                    unknown.add("heater")
                elif on:
                    names.append(name)
        if names:
            text, ok = heater_texts(names, self.mode, self.dry_run)
            title = " und ".join(names) + (" laufen" if len(names) > 1 else " läuft")
            issues.append(Issue("heater", title, text, ok, self._since.setdefault("heater", now)))
        else:
            self._since.pop("heater", None)

        if text := no_effect_text(
            mode=self.mode,
            mode_since=self.mode_since,
            now=now,
            dry_run=self.dry_run,
            runs=self._runs,
            dhw_c=inputs.dhw_c,
            dhw_target_c=inputs.dhw_target_c,
            hyst_k=self._number(c.CONF_ENT_DHW_HYST)[0],
            locked=locked(self._text(c.CONF_ENT_LOCK)),
        ):
            issues.append(Issue(
                "no_effect", "Anheben ohne Wirkung", text, "Der Verdichter läuft, oder es wird nicht mehr angehoben"
            ))

        window = timedelta(minutes=REAPPLY_WINDOW_MIN)
        self._reapplied = [t for t in self._reapplied if now - t < window]
        if text := reapply_text(self._reapplied, now):
            issues.append(Issue(
                "overwritten", "Vorgabe wird überschrieben", text, "Die Vorgabe bleibt wieder an der Wärmepumpe stehen"
            ))

        if o.get(c.CONF_ENT_FAULT):
            state = self._text(c.CONF_ENT_FAULT)
            if state is None:
                unknown.add("fault")
            elif text := fault_text(state):
                issues.append(Issue(
                    "fault", "Störung", text, "Die Wärmepumpe meldet keine Störung mehr",
                    self._since.setdefault("fault", now), FAULT_DELAY_MIN,
                ))
            else:
                self._since.pop("fault", None)

        self._cold_since = cold_since(self._cold_since, inputs.dhw_c, now)
        if text := cold_text(self._cold_since, inputs.dhw_c, now):
            issues.append(Issue(
                "dhw_cold", "Warmwasser kalt", text,
                f"Das Warmwasser ist wieder über {fmt_c(DHW_COLD_C + DHW_WARM_AGAIN_K)}", self._cold_since,
            ))

        if override := self._data.get("override"):
            if not override.get("since"):
                override["since"] = now.isoformat()  # Handbetrieb von vor 0.8
            since = _parse(override["since"])
            if text := override_text(override["mode"], since, _parse(override.get("until")), now):
                issues.append(Issue("override_long", "Handbetrieb läuft lange", text, "Der Handbetrieb ist beendet", since))
        if not self.automation:
            since = _parse(self._data.get("automation_since"))
            if text := automation_off_text(since, now):
                issues.append(Issue("automation_off", "Automatik aus", text, "Die Automatik ist wieder an", since))

        for problem in self._problems:
            issues.append(Issue(
                f"problem:{problem}", "Problem", problem, f"Behoben: {problem.rstrip('.')}",
                self._since.setdefault(f"problem:{problem}", now), PROBLEM_DELAY_MIN,
            ))
        for key in [k for k in self._since if k.startswith("problem:") and k[8:] not in self._problems]:
            del self._since[key]

        quiet = self._started_at is not None and now - self._started_at < timedelta(minutes=START_GRACE_MIN)
        memory = self._data.get("notify_memory") or {}
        messages, memory = step_issues(issues, memory, now, unknown=unknown, quiet_end=quiet)
        if memory != self._data.get("notify_memory"):
            self._data["notify_memory"] = memory
            self._save()
        for message in messages:
            self._log("alert_end" if message.end else "alert", message.text, title=message.title, notify=False)
            self._outbox.append(message)

    # ---------------------------------------------------------- Benachrichtigung
    @property
    def notify_service(self) -> str | None:
        """Dienst ohne „notify.“, etwa „mobile_app_handy“; None = keine Benachrichtigung."""
        value = str(self.options.get(c.CONF_NOTIFY_SERVICE) or "").strip()
        return value.removeprefix("notify.") or None

    @property
    def notify_level(self) -> str:
        return str(self.options.get(c.CONF_NOTIFY_LEVEL) or LEVEL_ISSUES)

    def _queue_setup_message(self) -> None:
        """Testnachricht, sobald Dienst oder Umfang neu eingestellt sind."""
        service = self.notify_service
        setup = [service, self.notify_level] if service else None
        if setup == self._data.get("notify_setup"):
            return
        self._data["notify_setup"] = setup
        self._save()
        if setup:
            what = "jeden Eingriff, Auffälligkeiten und Fehler" if self.notify_level != LEVEL_ISSUES \
                else "Auffälligkeiten und Fehler"
            self._outbox.append(Message(
                "Benachrichtigung eingerichtet", f"Energy Hub meldet hier ab jetzt {what}.", issue=True
            ))

    async def _send_outbox(self) -> None:
        """Verschickt, was beim Umfang gewünscht ist. Fehler stehen im Protokoll von HA."""
        messages, self._outbox = self._outbox, []
        service = self.notify_service
        if not service:
            return
        level = self.notify_level
        for message in messages:
            if not wanted(message, level):
                continue
            data: dict[str, Any] = {"title": f"{c.TITLE} · {message.title}", "message": message.text}
            if service.startswith("mobile_app_"):
                # Companion-App: alles in einer Gruppe; „wieder in Ordnung“ ersetzt die Warnung
                extra = {"group": c.DOMAIN}
                if message.key:
                    extra["tag"] = tag(message.key)
                data["data"] = extra
            try:
                await self.hass.services.async_call("notify", service, data, blocking=False)
            except Exception as err:  # noqa: BLE001 - eine Benachrichtigung darf die Regelung nicht stören
                _LOGGER.warning("Benachrichtigung über notify.%s fehlgeschlagen: %s", service, err)

    # --------------------------------------------------------------- Stellgröße
    def _smart_grid_option(self, mode: str, offered: list[str] | None = None) -> str:
        """Option der Smart-Grid-Auswahl für einen Zustand.

        Gibt es die Option für „Stark anheben“ in der Auswahl nicht (offered), gilt die für
        „Anheben“: Nicht jede Wärmepumpe kennt eine zweite Stufe.
        """
        o = self.options
        option = str(
            {
                MODE_NORMAL: o[c.CONF_OPT_NORMAL],
                MODE_BOOST: o[c.CONF_OPT_BOOST],
                MODE_STRONG: o[c.CONF_OPT_STRONG],
                MODE_SETBACK: o[c.CONF_OPT_SETBACK],
            }[mode]
        )
        if mode == MODE_STRONG and offered is not None and option not in offered:
            return str(o[c.CONF_OPT_BOOST])
        return option

    def _shift_target(self, mode: str, base: float) -> float:
        o = self.options
        if mode == MODE_BOOST:
            return base + float(o[c.CONF_SHIFT_BOOST_K])
        if mode == MODE_STRONG:
            return base + float(o[c.CONF_SHIFT_STRONG_K])
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
            offered = list(state.attributes.get("options") or [])
            return state.state == self._smart_grid_option(mode, offered), state.state
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
                offered = list(state.attributes.get("options") or [])
                option = self._smart_grid_option(mode, offered)
                if option not in offered:
                    return "failed", f"Die Option „{option}“ gibt es bei {entity_id} nicht."
                await self.hass.services.async_call(
                    "select",
                    "select_option",
                    {"entity_id": entity_id, "option": option},
                    blocking=True,
                )
                detail = f"{entity_id} → {option}"
                if option != self._smart_grid_option(mode):
                    detail += f" (die Option „{self._smart_grid_option(mode)}“ gibt es nicht)"
                return "sent", detail

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
                "strong_since": _iso(self._timers.strong_since),
                "on": self._on_snapshot(inputs),
                "learned": {
                    "run_w": self.run_w,
                    "run_min": round(float(self._data.get("run_min") or 0.0), 1),
                    "battery_kwh": self.battery_kwh,
                    "battery_n": int(self._data.get("battery_n") or 0),
                },
                "problems": self.problems,
                "dhw_reload": self._reload_snapshot(),
                "inputs": {
                    "surplus_w": inputs.surplus_w if inputs else None,
                    "balance_w": inputs.balance_w if inputs else None,
                    "available_w": inputs.available_w if inputs else None,
                    "available_free_w": inputs.available_free_w if inputs else None,
                    "battery_soc": inputs.battery_soc if inputs else None,
                    "forecast_kwh": inputs.forecast_kwh if inputs else None,
                    "forecast_tomorrow_kwh": inputs.forecast_tomorrow_kwh if inputs else None,
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

    def _on_snapshot(self, inputs: Inputs | None) -> dict[str, Any] | None:
        """Die Einschaltregel fürs Panel: Wert, Schwelle und woher beides kommt."""
        if inputs is None:
            return None
        rule = on_rule(inputs, self._settings())
        if rule is None:
            return None
        return {
            "value_w": rule.value,
            "threshold_w": rule.threshold,
            "available": rule.available,
            "learned": rule.learned,
            "battery_fills": battery_fills(inputs),
            "battery_missing_kwh": battery_missing_kwh(inputs),
        }
