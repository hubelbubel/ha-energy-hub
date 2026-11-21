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
    d = run(Inputs(NOON, surplus_w=-500), dip, mode=BOOST)
    assert (d.mode, d.rule) == (BOOST, "boost_keep")


def test_boost_ends_after_off_delay():
    low = Timers(below_since=NOON - timedelta(minutes=15))
    d = run(Inputs(NOON, surplus_w=-500), low, mode=BOOST)
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

    t4 = logic.update_timers(t3, Inputs(later, surplus_w=-500), S)
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



# --- Mittelwert und Lücken -------------------------------------------------


def at(minutes):
    return NOON + timedelta(minutes=minutes)


def test_window_mean_weights_by_time():
    samples = [(at(-10), 0.0), (at(-4), 2000.0), (at(-1), 500.0)]
    # die letzten 5 min: 1 min 0 W, 3 min 2000 W, 1 min 500 W
    assert logic.window_mean(samples, NOON, 5, 3) == (0 * 60 + 2000 * 180 + 500 * 60) / 300
    # ohne Glättung zählt der neueste Wert
    assert logic.window_mean(samples, NOON, 0, 3) == 500
    # nach dem Start: Mittel über das, was da ist
    assert logic.window_mean([(at(-2), 1000.0), (at(-1), 3000.0)], NOON, 5, 3) == 2000


def test_window_mean_bridges_short_gaps_only():
    samples = [(at(-6), 2400.0)]
    assert logic.window_mean(samples, at(-4), 5, 3) == 2400  # 2 min ohne neuen Wert: gilt weiter
    assert logic.window_mean(samples, at(-2.5), 5, 3) is None  # 3,5 min: nicht verfügbar
    assert logic.window_mean([], NOON, 5, 3) is None


def test_trim_keeps_value_before_window():
    samples = [(at(-20), 1.0), (at(-8), 2.0), (at(-3), 3.0), (at(-1), 4.0)]
    assert logic.trim_samples(samples, NOON, 5) == samples[1:]
    assert logic.trim_samples(samples[:1], NOON, 5) == samples[:1]  # der letzte Wert bleibt immer
    assert logic.trim_samples([], NOON, 5) == []


def test_reason_names_the_mean():
    smooth = Settings(smoothing_min=5)
    d = run(Inputs(NOON, surplus_w=2140), Timers(above_since=NOON - timedelta(minutes=10)), settings=smooth)
    assert d.mode == BOOST and "im 5-Minuten-Mittel 2.140 W" in d.reason
    d = run(Inputs(NOON, surplus_w=200), settings=smooth)
    assert "200 W im 5-Minuten-Mittel liegt unter" in d.reason


# --- Ende des Anhebens nach dem Überschuss ohne Akku -----------------------


def test_timers_end_by_balance_when_known():
    # Einspeisung 0, weil der Akku die Wärmepumpe mit 800 W stützt
    t = logic.update_timers(Timers(), Inputs(NOON, surplus_w=0, balance_w=-800), S)
    assert t.below_since == NOON
    # Akku lädt noch mit 200 W: PV trägt die Wärmepumpe
    t = logic.update_timers(t, Inputs(NOON, surplus_w=0, balance_w=200), S)
    assert t.below_since is None
    # ohne Akku-Wert zählt der Überschuss
    assert logic.update_timers(Timers(), Inputs(NOON, surplus_w=-500), S).below_since == NOON


def test_boost_keeps_while_pv_carries_the_heat_pump():
    d = run(Inputs(NOON, surplus_w=0, balance_w=-150), Timers(), mode=BOOST)
    assert (d.mode, d.rule) == (BOOST, "boost_keep")
    assert d.reason.startswith("Der Überschuss ohne Akku reicht weiter aus (aktuell -150 W)")


def test_boost_ends_when_battery_has_to_help():
    low = Timers(below_since=NOON - timedelta(minutes=15))
    d = run(Inputs(NOON, surplus_w=0, balance_w=-900), low, mode=BOOST)
    assert (d.mode, d.rule) == (NORMAL, "boost_end")
    assert "Der Überschuss ohne Akku liegt seit 15 min unter -300 W (aktuell -900 W)" in d.reason


# --- Absenken mit der Prognose für morgen ----------------------------------

NIGHT = Settings(setback_start=time(21, 0), setback_end=time(10, 0))
EVENING = datetime(2026, 11, 16, 22, 0)
AFTER_MIDNIGHT = datetime(2026, 11, 17, 2, 0)


def test_uses_tomorrow_only_before_midnight_of_a_night_window():
    assert logic.uses_tomorrow(time(21, 0), time(21, 0), time(10, 0))
    assert logic.uses_tomorrow(time(23, 59), time(21, 0), time(10, 0))
    assert not logic.uses_tomorrow(time(2, 0), time(21, 0), time(10, 0))
    assert not logic.uses_tomorrow(time(7, 0), time(5, 0), time(10, 0))


def test_night_setback_waits_for_tomorrows_sun():
    d = run(Inputs(EVENING, surplus_w=-400, forecast_kwh=0.2, forecast_tomorrow_kwh=14, outdoor_c=5, dhw_c=48),
            settings=NIGHT)
    assert (d.mode, d.rule) == (SETBACK, "setback")
    assert d.reason.startswith("Für morgen sind 14,0 kWh PV-Ertrag vorhergesagt.")
    assert "(21:00–10:00 Uhr)" in d.reason

    d = run(Inputs(AFTER_MIDNIGHT, surplus_w=-400, forecast_kwh=14, forecast_tomorrow_kwh=2, outdoor_c=5, dhw_c=48),
            settings=NIGHT)
    assert d.mode == SETBACK and d.reason.startswith("Für den Rest des Tages sind 14,0 kWh")


def test_night_setback_not_before_a_dull_day():
    d = run(Inputs(EVENING, surplus_w=-400, forecast_kwh=0.2, forecast_tomorrow_kwh=4, outdoor_c=5, dhw_c=48),
            settings=NIGHT)
    assert d.mode == NORMAL and "Die Prognose für morgen von 4,0 kWh reicht nicht" in d.reason

    d = run(Inputs(EVENING, surplus_w=-400, forecast_kwh=12, outdoor_c=5, dhw_c=48), settings=NIGHT)
    assert d.mode == NORMAL and "Die PV-Prognose für morgen ist nicht verfügbar." in d.reason


def test_reason_shows_no_negative_surplus():
    d = run(Inputs(NOON, surplus_w=-480, forecast_kwh=5))
    assert "Der PV-Überschuss von 0 W liegt unter" in d.reason and "-480" not in d.reason


# --- Stark anheben ----------------------------------------------------------

STRONG = logic.MODE_STRONG


def test_strong_timer_runs_only_while_raised():
    sunny = Inputs(NOON, surplus_w=2600)
    assert logic.update_timers(Timers(), sunny, S, NORMAL).strong_since is None
    t = logic.update_timers(Timers(), sunny, S, BOOST)
    assert t.strong_since == NOON
    later = NOON + timedelta(minutes=4)
    assert logic.update_timers(t, Inputs(later, surplus_w=2100), S, BOOST).strong_since == NOON
    assert logic.update_timers(t, Inputs(later, surplus_w=1900), S, BOOST).strong_since is None
    off = Settings(strong_enabled=False)
    assert logic.update_timers(Timers(), sunny, off, BOOST).strong_since is None


def test_strong_after_delay_and_back_to_boost():
    t = Timers(strong_since=NOON - timedelta(minutes=4))
    d = run(Inputs(NOON, surplus_w=2600, balance_w=2600), t, mode=BOOST)
    assert (d.mode, d.rule) == (BOOST, "boost_keep")
    assert "stark angehoben wird nach 10 min" in d.reason

    t = Timers(strong_since=NOON - timedelta(minutes=10))
    d = run(Inputs(NOON, surplus_w=2600, balance_w=2600), t, mode=BOOST)
    assert (d.mode, d.rule) == (STRONG, "strong")
    assert d.reason == "Trotz Anheben sind seit 10 min mehr als 2.000 W übrig (aktuell 2.600 W)."

    # Stark angehoben trägt die PV die Wärmepumpe nicht mehr, für einfaches Anheben reicht es: eine Stufe zurück
    low = Timers(below_since=NOON - timedelta(minutes=15))
    d = run(Inputs(NOON, surplus_w=0, balance_w=-700, available_w=2800, available_free_w=2800), low, mode=STRONG)
    assert (d.mode, d.rule) == (BOOST, "strong_end")
    assert d.reason.endswith("Für einfaches Anheben reicht es noch (aktuell 2.800 W für die Wärmepumpe übrig, nötig 1.500 W).")
    # reicht es auch dafür nicht, endet das Anheben ganz
    d = run(Inputs(NOON, surplus_w=0, balance_w=-700, available_w=900, available_free_w=900), low, mode=STRONG)
    assert (d.mode, d.rule) == (NORMAL, "boost_end")

    d = run(Inputs(NOON, surplus_w=900, balance_w=900), Timers(), mode=STRONG)
    assert (d.mode, d.rule) == (STRONG, "boost_keep")


def test_storage_ends_strong_like_boost():
    s = Settings(storage_ready_c=40)
    d = run(Inputs(NOON, surplus_w=3000, storage_c=55), Timers(), mode=STRONG, settings=s)
    assert (d.mode, d.rule) == (NORMAL, "storage")


# --- Einschalten nach dem, was für die Wärmepumpe übrig ist -----------------


def test_heat_pump_draw_counts_as_available():
    # Die Wärmepumpe läuft normal mit 1.600 W, eingespeist werden nur 400 W: die PV trägt sie trotzdem
    inputs = Inputs(NOON, surplus_w=400, available_w=2000, available_free_w=2000)
    t = logic.update_timers(Timers(), inputs, S)
    assert t.above_since == NOON
    d = run(inputs, Timers(above_since=NOON - timedelta(minutes=10)))
    assert (d.mode, d.rule) == (BOOST, "boost")
    assert d.reason == "Für die Wärmepumpe sind seit 10 min mehr als 1.500 W übrig (aktuell 2.000 W)."

    d = run(Inputs(NOON, surplus_w=-200, available_w=900, available_free_w=900, forecast_kwh=3))
    assert d.reason.startswith("Für die Wärmepumpe sind 900 W übrig, angehoben wird ab 1.500 W.")


def test_learned_threshold_replaces_the_fixed_one():
    inputs = Inputs(NOON, surplus_w=200, available_w=1300, available_free_w=1300, run_w=1250)
    rule = logic.on_rule(inputs, S)
    assert (rule.threshold, rule.learned) == (1250, True)
    d = run(inputs, Timers(above_since=NOON - timedelta(minutes=10)))
    assert d.mode == BOOST
    assert d.reason == ("Für die Wärmepumpe sind seit 10 min mehr als 1.250 W übrig (aktuell 1.300 W). "
                        "So viel zieht die Wärmepumpe im Lauf.")

    fixed = Settings(boost_on_learned=False)
    assert logic.on_rule(inputs, fixed).threshold == 1500
    assert logic.update_timers(Timers(), inputs, fixed).above_since is None


def test_battery_that_fills_anyway_lends_its_charge():
    # Akku 10 kWh bei 60 %: es fehlen 4 kWh, vorhergesagt sind noch 9 kWh
    base = dict(surplus_w=100, balance_w=2100, available_w=1700, available_free_w=3700,
                battery_soc=60, battery_kwh=10)
    assert logic.battery_missing_kwh(Inputs(NOON, **base)) == 4
    sunny = Inputs(NOON, forecast_kwh=9, **base)
    rule = logic.on_rule(sunny, S)
    assert rule.fills and rule.value == 3700
    d = run(sunny, Timers(above_since=NOON - timedelta(minutes=10)))
    assert d.mode == BOOST
    assert d.reason.endswith("Der Akku wird heute ohnehin voll, deshalb zählt auch seine Ladeleistung.")

    dull = Inputs(NOON, forecast_kwh=7, **base)  # 7 kWh < 2 × 4 kWh: der Akku lädt zuerst
    rule = logic.on_rule(dull, S)
    assert not rule.fills and rule.value == 1700
    # ohne gelernte Kapazität oder Ladestand bleibt es beim Vorrang des Akkus
    assert not logic.battery_fills(Inputs(NOON, forecast_kwh=50, **{**base, "battery_kwh": None}))
    assert not logic.battery_fills(Inputs(NOON, forecast_kwh=50, **{**base, "battery_soc": None}))


def test_strong_counts_the_battery_when_it_fills_anyway():
    base = dict(surplus_w=500, balance_w=2500, available_w=2000, available_free_w=4000,
                battery_soc=90, battery_kwh=10)
    assert logic.strong_value(Inputs(NOON, forecast_kwh=5, **base)) == 2500
    assert logic.strong_value(Inputs(NOON, forecast_kwh=1, **base)) == 500


# --- Lernen -----------------------------------------------------------------


def test_learn_run_power_mean_then_sliding():
    value, minutes = None, 0.0
    for power in (1000, 2000):
        value, minutes = logic.learn_run_power(value, minutes, power, 0.5)
    assert value == 1500 and minutes == 1
    assert logic.learned_run_w(value, minutes) is None  # zu wenig Laufzeit
    # Stillstand und Umwälzpumpe zählen nicht
    assert logic.learn_run_power(value, minutes, 120, 0.5) == (value, minutes)
    assert logic.learn_run_power(value, minutes, None, 0.5) == (value, minutes)
    for _ in range(58):
        value, minutes = logic.learn_run_power(value, minutes, 1500, 0.5)
    assert minutes == 30 and logic.learned_run_w(value, minutes) == 1500
    # nach Monaten im Lauf folgt der Wert neuen Messungen nur langsam
    value, minutes = 1500.0, 10000.0
    value, minutes = logic.learn_run_power(value, minutes, 2100, 0.5)
    assert 1500 < value < 1501
    assert logic.learned_run_w(1523, 100) == 1500 and logic.learned_run_w(1530, 100) == 1550


def test_capacity_from_charge_and_soc():
    seg, est = logic.capacity_step(None, NOON, 40, 2000)
    assert est is None and seg.soc == 40
    now = NOON
    estimates = []
    for _ in range(12 * 6):  # 6 h mit 2 kW: 12 kWh
        now += timedelta(minutes=5)
        soc = 40 + (now - NOON).total_seconds() / 3600 * 2 / 10 * 100  # 10-kWh-Akku
        seg, est = logic.capacity_step(seg, now, round(soc), 2000)
        if est is not None:
            estimates.append(est)
    assert estimates and all(abs(e - 10) < 0.6 for e in estimates)

    # Lücke: der Abschnitt beginnt neu
    seg2, est = logic.capacity_step(seg, now + timedelta(minutes=30), 50, 2000)
    assert est is None and seg2.start == now + timedelta(minutes=30) and seg2.kwh == 0
    # ohne Ladestand keine Schätzung
    assert logic.capacity_step(seg, now, None, 2000) == (None, None)

    value, count = None, 0
    for e in (10.0, 12.0, 11.0):
        value, count = logic.learn_capacity(value, count, e)
    assert count == 3 and value == 11


# --- Warmwasser nachladen ---------------------------------------------------

AFTERNOON = NOON.replace(hour=17, minute=30)


def reload_inputs(**kw):
    base = dict(surplus_w=300, balance_w=300, available_w=2300, available_free_w=2300, run_w=1800,
                dhw_c=52, dhw_target_c=58, afternoon=True, dhw_heating=False)
    return Inputs(AFTERNOON, **{**base, **kw})


def test_reload_band_timer():
    t = logic.update_timers(Timers(), reload_inputs(), S, BOOST)
    assert t.reload_since == AFTERNOON
    # mehr als das 1,5-Fache: die Sonne reicht noch für später
    assert logic.update_timers(t, reload_inputs(available_w=2800, available_free_w=2800), S, BOOST).reload_since is None
    # weniger, als die Wärmepumpe zieht: zu spät
    assert logic.update_timers(t, reload_inputs(available_w=1700, available_free_w=1700), S, BOOST).reload_since is None
    assert logic.update_timers(Timers(), reload_inputs(), Settings(dhw_reload=False), BOOST).reload_since is None


def test_reload_starts_when_the_sun_fades():
    waiting = logic.dhw_reload_check(reload_inputs(), S, Timers(reload_since=AFTERNOON - timedelta(minutes=4)), False)
    assert not waiting.start and waiting.short == "übrig zwischen 1.800 W und 2.700 W, seit 4 min"
    due = logic.dhw_reload_check(reload_inputs(), S, Timers(reload_since=AFTERNOON - timedelta(minutes=10)), False)
    assert due.start
    assert due.reason == (
        "Die Sonne lässt nach: Für die Wärmepumpe sind seit 10 min nur noch zwischen 1.800 W und 2.700 W übrig "
        "(aktuell 2.300 W), später reicht es für eine Ladung nicht mehr. Das Warmwasser hat 52,0 °C und liegt "
        "6,0 K unter dem Soll von 58,0 °C."
    )


def test_reload_waits_for_its_conditions():
    held = Timers(reload_since=AFTERNOON - timedelta(minutes=30))
    def short(**kw):
        return logic.dhw_reload_check(reload_inputs(**kw), S, held, False).short
    assert logic.dhw_reload_check(reload_inputs(), S, held, True).short == "heute schon nachgeladen"
    assert short(dhw_c=55) == "erst ab 4 K unter Soll, jetzt 3,0 K"
    assert short(afternoon=False) == "erst nach Mittag"
    assert short(dhw_heating=True) == "die Wärmepumpe macht gerade Warmwasser"
    assert short(dhw_target_c=None) == "Warmwasser-Temperatur oder Soll fehlt"
    assert short(battery_soc=80) == "der Akku lädt noch"
    assert logic.dhw_reload_check(reload_inputs(battery_soc=97), S, held, False).start
    fresh = logic.dhw_reload_check(reload_inputs(available_w=3500, available_free_w=3500), S, Timers(), False)
    assert fresh.short == "wartet, bis die Sonne nachlässt"
    assert logic.dhw_reload_check(reload_inputs(), Settings(dhw_reload=False), held, False).short == "abgeschaltet"


def test_reload_ends():
    since = AFTERNOON - timedelta(minutes=20)
    assert logic.dhw_reload_end(reload_inputs(), S, since, Timers()) is None
    assert logic.dhw_reload_end(reload_inputs(dhw_c=57.6), S, since, Timers()) == "Das Warmwasser hat 57,6 °C erreicht (Soll 58,0 °C)."
    assert logic.dhw_reload_end(reload_inputs(), S, AFTERNOON - timedelta(minutes=90), Timers()) == "Nach 90 min beendet."
    low = Timers(below_since=AFTERNOON - timedelta(minutes=15))
    assert logic.dhw_reload_end(reload_inputs(balance_w=-600), S, since, low).endswith("die PV trägt die Wärmepumpe nicht mehr.")
