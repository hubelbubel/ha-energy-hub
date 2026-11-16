"""Tests der Entscheidungslogik. Läuft ohne Home Assistant: `pytest tests`."""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

_PATH = Path(__file__).parents[1] / "custom_components" / "energy_hub" / "logic.py"
_SPEC = importlib.util.spec_from_file_location("energy_hub_logic", _PATH)
logic = importlib.util.module_from_spec(_SPEC)
sys.modules["energy_hub_logic"] = logic
_SPEC.loader.exec_module(logic)

Inputs, Settings, Timers, Override = logic.Inputs, logic.Settings, logic.Timers, logic.Override
NORMAL, BOOST, SETBACK = logic.MODE_NORMAL, logic.MODE_BOOST, logic.MODE_SETBACK

S = Settings()
NOON = datetime(2026, 11, 16, 12, 0)
MORNING = datetime(2026, 11, 16, 7, 0)
LONG_AGO = NOON - timedelta(hours=5)


def run(inputs, timers=Timers(), mode=NORMAL, since=None, settings=S, **kw):
    return logic.decide(inputs, settings, timers, mode, since or inputs.now - timedelta(hours=5), **kw)


def test_no_surplus_stays_normal():
    d = run(Inputs(NOON, surplus_w=200, forecast_kwh=5))
    assert (d.mode, d.rule) == (NORMAL, "idle")
    assert "200 W" in d.reason and "1.500 W" in d.reason


def test_boost_needs_sustained_surplus():
    short = Timers(above_since=NOON - timedelta(minutes=4))
    d = run(Inputs(NOON, surplus_w=2140), short)
    assert d.mode == NORMAL and "erst seit 4 min" in d.reason

    long = Timers(above_since=NOON - timedelta(minutes=10))
    d = run(Inputs(NOON, surplus_w=2140), long)
    assert (d.mode, d.rule) == (BOOST, "boost")
    assert "2.140 W" in d.reason


def test_boost_survives_short_dip():
    dip = Timers(below_since=NOON - timedelta(minutes=5))
    d = run(Inputs(NOON, surplus_w=100), dip, mode=BOOST)
    assert (d.mode, d.rule) == (BOOST, "boost_keep")


def test_boost_ends_after_off_delay():
    low = Timers(below_since=NOON - timedelta(minutes=15))
    d = run(Inputs(NOON, surplus_w=100), low, mode=BOOST)
    assert (d.mode, d.rule) == (NORMAL, "boost_end")


def test_between_thresholds_keeps_boost():
    # 300 W <= Überschuss < 1500 W: weder Ein- noch Ausschaltbedingung
    d = run(Inputs(NOON, surplus_w=800), Timers(), mode=BOOST)
    assert d.mode == BOOST


def test_min_hold_delays_switch():
    low = Timers(below_since=NOON - timedelta(minutes=30))
    d = run(Inputs(NOON, surplus_w=0), low, mode=BOOST, since=NOON - timedelta(minutes=8))
    assert (d.mode, d.rule) == (BOOST, "hold")
    assert "noch 12 min" in d.reason


def test_setback_in_morning_with_good_forecast():
    d = run(Inputs(MORNING, surplus_w=0, forecast_kwh=18, outdoor_c=6, dhw_c=47))
    assert (d.mode, d.rule) == (SETBACK, "setback")
    assert "18,0 kWh" in d.reason


def test_setback_blocked_by_each_guard():
    base = dict(surplus_w=0, forecast_kwh=18, outdoor_c=6, dhw_c=47)
    cases = {
        "forecast_kwh": (4, "reicht nicht"),
        "outdoor_c": (-2, "außen"),
        "dhw_c": (38, "Warmwasser"),
    }
    for key, (value, text) in cases.items():
        d = run(Inputs(MORNING, **{**base, key: value}))
        assert d.mode == NORMAL, key
        assert text in d.reason, key
    for key in ("forecast_kwh", "outdoor_c", "dhw_c"):
        d = run(Inputs(MORNING, **{**base, key: None}))
        assert d.mode == NORMAL and "nicht verfügbar" in d.reason, key


def test_setback_guards_can_be_disabled():
    s = Settings(setback_min_outdoor_c=None, setback_min_dhw_c=None)
    d = run(Inputs(MORNING, surplus_w=0, forecast_kwh=18), settings=s)
    assert d.mode == SETBACK


def test_setback_only_inside_window_and_when_enabled():
    d = run(Inputs(NOON, surplus_w=0, forecast_kwh=18, outdoor_c=6, dhw_c=47))
    assert d.mode == NORMAL and "05:00–10:00" in d.reason
    d = run(
        Inputs(MORNING, surplus_w=0, forecast_kwh=18, outdoor_c=6, dhw_c=47),
        settings=Settings(setback_enabled=False),
    )
    assert d.mode == NORMAL


def test_surplus_beats_setback():
    sunny = Timers(above_since=MORNING - timedelta(minutes=12))
    d = run(Inputs(MORNING, surplus_w=2500, forecast_kwh=18, outdoor_c=6, dhw_c=47), sunny, mode=SETBACK)
    assert d.mode == BOOST


def test_missing_surplus_is_failsafe_and_immediate():
    d = run(Inputs(NOON, surplus_w=None), mode=BOOST, since=NOON - timedelta(minutes=1))
    assert (d.mode, d.rule) == (NORMAL, "no_data")


def test_automation_off():
    sunny = Timers(above_since=NOON - timedelta(minutes=30))
    d = run(Inputs(NOON, surplus_w=5000), sunny, mode=BOOST, since=NOON, automation=False)
    assert (d.mode, d.rule) == (NORMAL, "automation_off")


def test_override_wins_and_expires():
    until = NOON + timedelta(hours=2)
    d = run(Inputs(NOON, surplus_w=None), automation=False, override=Override(BOOST, until))
    assert (d.mode, d.rule) == (BOOST, "override") and "14:00" in d.reason

    d = run(Inputs(until, surplus_w=0), override=Override(BOOST, until))
    assert d.rule != "override"

    d = run(Inputs(NOON, surplus_w=0), override=Override(SETBACK, None))
    assert d.mode == SETBACK and "bis er beendet wird" in d.reason


def test_update_timers():
    t = logic.update_timers(Timers(), Inputs(NOON, surplus_w=2000), S)
    assert t.above_since == NOON and t.below_since is None

    later = NOON + timedelta(minutes=3)
    t2 = logic.update_timers(t, Inputs(later, surplus_w=1800), S)
    assert t2.above_since == NOON

    t3 = logic.update_timers(t2, Inputs(later, surplus_w=900), S)
    assert t3.above_since is None and t3.below_since is None

    t4 = logic.update_timers(t3, Inputs(later, surplus_w=100), S)
    assert t4.below_since == later

    assert logic.update_timers(t4, Inputs(later, surplus_w=None), S) == Timers()


def test_window_over_midnight():
    assert logic.in_window(time(23, 30), time(22, 0), time(6, 0))
    assert logic.in_window(time(5, 59), time(22, 0), time(6, 0))
    assert not logic.in_window(time(12, 0), time(22, 0), time(6, 0))
    assert not logic.in_window(time(12, 0), time(8, 0), time(8, 0))


def test_formatting():
    assert logic.fmt_w(1500) == "1.500 W"
    assert logic.fmt_w(-240.4) == "-240 W"
    assert logic.fmt_num(12.5, "kWh") == "12,5 kWh"


def test_storage_ready_blocks_boost():
    s = Settings(storage_ready_c=40)
    sunny = Timers(above_since=NOON - timedelta(minutes=30))
    d = run(Inputs(NOON, surplus_w=3000, storage_c=52.5), sunny, settings=s)
    assert (d.mode, d.rule) == (NORMAL, "storage")
    assert "52,5 °C" in d.reason and "nicht angehoben" in d.reason

    d = run(Inputs(NOON, surplus_w=3000, storage_c=39.9), sunny, settings=s)
    assert d.mode == BOOST

    d = run(Inputs(NOON, surplus_w=3000, storage_c=None), sunny, settings=s)
    assert d.mode == BOOST  # ohne Messwert gilt die Regel nicht


def test_storage_ready_ends_running_boost():
    s = Settings(storage_ready_c=40)
    d = run(Inputs(NOON, surplus_w=3000, storage_c=45), Timers(above_since=LONG_AGO), mode=BOOST, settings=s)
    assert (d.mode, d.rule) == (NORMAL, "storage")
    d = run(
        Inputs(NOON, surplus_w=3000, storage_c=45), Timers(above_since=LONG_AGO), mode=BOOST,
        since=NOON - timedelta(minutes=5), settings=s,
    )
    assert (d.mode, d.rule) == (BOOST, "hold")


def test_storage_rule_off_or_not_configured():
    sunny = Timers(above_since=NOON - timedelta(minutes=30))
    d = run(Inputs(NOON, surplus_w=3000, storage_c=70), sunny, settings=Settings(storage_ready_c=40, storage_blocks_boost=False))
    assert d.mode == BOOST
    d = run(Inputs(NOON, surplus_w=3000, storage_c=70), sunny)  # kein Speicher hinterlegt
    assert d.mode == BOOST


def test_storage_does_not_stop_setback():
    s = Settings(storage_ready_c=40)
    d = run(Inputs(MORNING, surplus_w=0, forecast_kwh=18, outdoor_c=6, dhw_c=47, storage_c=60), settings=s)
    assert d.mode == SETBACK


def test_storage_threshold_follows_return_target():
    s = Settings(storage_ready_c=40, storage_ready_delta_k=5)
    assert logic.ready_threshold(30.5, 5, 40) == 35.5
    assert logic.ready_threshold(None, 5, 40) == 40
    assert logic.storage_threshold(Inputs(NOON, return_target_c=30.5), s) == 35.5
    assert logic.storage_threshold(Inputs(NOON), s) == 40
    assert logic.storage_threshold(Inputs(NOON, return_target_c=30.5), Settings()) is None

    sunny = Timers(above_since=NOON - timedelta(minutes=30))
    # 37 °C reichen bei Rücklaufsoll 30,5 °C (Schwelle 35,5), nicht aber bei 34 °C (Schwelle 39)
    d = run(Inputs(NOON, surplus_w=3000, storage_c=37, return_target_c=30.5), sunny, settings=s)
    assert (d.mode, d.rule) == (NORMAL, "storage")
    assert "bereit ab 35,5 °C: Rücklaufsoll 30,5 °C plus 5,0 K" in d.reason
    d = run(Inputs(NOON, surplus_w=3000, storage_c=37, return_target_c=34), sunny, settings=s)
    assert d.mode == BOOST
    # über der festen Ersatz-Schwelle, aber unter Rücklaufsoll + Differenz: nicht bereit
    d = run(Inputs(NOON, surplus_w=3000, storage_c=42, return_target_c=38), sunny, settings=s)
    assert d.mode == BOOST

