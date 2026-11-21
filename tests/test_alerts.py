"""Auffälligkeiten und Meldungen (alerts.py), ohne Home Assistant."""
from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import types

_PKG = types.ModuleType("energy_hub_pure")
_PKG.__path__ = [str(Path(__file__).parents[1] / "custom_components" / "energy_hub")]
sys.modules["energy_hub_pure"] = _PKG
alerts = importlib.import_module("energy_hub_pure.alerts")

TZ = timezone(timedelta(hours=1))
T0 = datetime(2026, 11, 21, 12, 0, tzinfo=TZ)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def runs_from(samples):
    """samples: [(Minute, läuft)] -> Runs nach allen Messungen."""
    runs = alerts.Runs()
    for minute, running in samples:
        runs = alerts.track_runs(runs, at(minute), running)
    return runs


# ------------------------------------------------------------------ Takten
def test_runs_count_starts_and_last_run():
    runs = runs_from([(0, False), (5, True), (11, False), (20, True)])
    assert runs.running is True
    assert runs.starts == (at(5), at(20))
    assert (runs.last_run_min, runs.last_end) == (6, at(11))
    assert runs.last_on == at(20)


def test_runs_ignore_missing_values_and_unknown_start():
    runs = runs_from([(0, True), (3, None), (30, False)])
    # Der Lauf begann vor der ersten Messung: Dauer unbekannt, kein Start gezählt
    assert runs.starts == ()
    assert runs.last_run_min is None
    assert runs.watched_since == at(0)


def test_cycling_many_starts():
    samples = []
    for i in range(4):
        samples += [(i * 15, True), (i * 15 + 12, False)]
    runs = runs_from([(-1, False), *samples])
    text = alerts.cycling_text(runs, at(50))
    assert text == "Die Wärmepumpe taktet: 4 Verdichterstarts in der letzten Stunde."


def test_cycling_short_run_and_window():
    runs = runs_from([(0, False), (5, True), (11, False)])
    assert alerts.cycling_text(runs, at(12)) == (
        "Die Wärmepumpe taktet: der letzte Lauf dauerte nur 6 min."
    )
    assert alerts.cycling_text(runs, at(75)) is None  # länger als eine Stunde her
    long = runs_from([(0, False), (5, True), (25, False)])
    assert alerts.cycling_text(long, at(26)) is None


# ------------------------------------------------------- Anheben ohne Wirkung
def no_effect(**kw):
    base = dict(
        mode="boost", mode_since=at(0), now=at(50), dry_run=False,
        runs=runs_from([(0, False), (49, False)]), dhw_c=45.0, dhw_target_c=55.0, hyst_k=5.0, locked=False,
    )
    base.update(kw)
    return alerts.no_effect_text(**base)


def test_no_effect_after_45_minutes():
    text = no_effect()
    assert text.startswith("Seit 50 min steht „Anheben“, der Verdichter ist aber nicht angelaufen")
    assert "45,0 °C unter dem Soll von 55,0 °C" in text


def test_no_effect_not_when_ok():
    assert no_effect(now=at(40)) is None  # noch keine 45 min
    assert no_effect(dry_run=True) is None
    assert no_effect(locked=True) is None
    assert no_effect(mode="normal") is None
    assert no_effect(dhw_c=51.0) is None  # innerhalb der Hysterese: nichts zu tun
    assert no_effect(dhw_target_c=None) is None
    ran = runs_from([(0, False), (10, True), (20, False)])
    assert no_effect(runs=ran) is None  # lief seit dem Anheben


def test_no_effect_counts_from_first_measurement_after_restart():
    runs = runs_from([(30, False), (49, False)])  # Neustart: erst ab Minute 30 gemessen
    assert no_effect(runs=runs, now=at(60)) is None
    assert no_effect(runs=runs, now=at(76)) is not None


def test_no_effect_without_hysteresis_uses_2_k():
    assert no_effect(hyst_k=None, dhw_c=52.5) is not None
    assert no_effect(hyst_k=None, dhw_c=53.5) is None


# -------------------------------------------------------- weitere Prüfungen
def test_heater_texts():
    assert alerts.heater_texts(["Heizstab"], "strong", False) == (
        "Der Heizstab läuft. Energy Hub steht auf „Stark anheben“.",
        "Der Heizstab ist wieder aus",
    )
    text, ok = alerts.heater_texts(["Heizstab", "2. Wärmeerzeuger"], "normal", True)
    assert text == ("Heizstab und 2. Wärmeerzeuger laufen. Energy Hub steht auf „Normalbetrieb“, "
                    "im Probebetrieb nur protokolliert.")
    assert ok == "Heizstab und 2. Wärmeerzeuger sind wieder aus"


def test_reapply_more_than_twice_an_hour():
    times = [at(0), at(5), at(10)]
    assert "3× an der Wärmepumpe verloren" in alerts.reapply_text(times, at(12))
    assert alerts.reapply_text(times[:2], at(12)) is None
    assert alerts.reapply_text(times, at(65)) is None


def test_fault_from_code_text_or_binary():
    assert alerts.fault_text("0") is None
    assert alerts.fault_text("Kein Fehler") is None
    assert alerts.fault_text("off") is None
    assert alerts.fault_text(None) is None
    assert alerts.fault_text("28") == "Die Wärmepumpe meldet eine Störung, Fehlercode 28."
    assert alerts.fault_text("!Hochdruck") == "Die Wärmepumpe meldet eine Störung: !Hochdruck."
    assert alerts.fault_text("on") == "Die Wärmepumpe meldet eine Störung."


def test_lock():
    assert alerts.locked("Keine") is False
    assert alerts.locked("0") is False
    assert alerts.locked(None) is False
    assert alerts.locked("EVU-Sperre") is True
    assert alerts.locked("Regenerativ") is True


def test_dhw_cold_with_hysteresis():
    since = None
    for minute, dhw in [(0, 39.5), (30, 40.5)]:
        since = alerts.cold_since(since, dhw, at(minute))
    assert since is None  # kurz kalt, wieder über 40 °C
    for minute, dhw in [(40, 39), (101, 39), (110, 41)]:
        since = alerts.cold_since(since, dhw, at(minute))
    assert since == at(40)  # einmal lange kalt: erst ab 42 °C wieder warm
    assert alerts.cold_text(since, 41, at(110)) == "Das Warmwasser liegt seit 1 h 10 min unter 40,0 °C (jetzt 41,0 °C)."
    assert alerts.cold_since(since, 42, at(115)) is None
    assert alerts.cold_text(at(0), 39, at(59)) is None


def test_forgotten_override_and_automation():
    assert alerts.override_text("boost", at(0), None, at(12 * 60)) == (
        "Der Handbetrieb „Anheben“ läuft seit 12 h und endet nicht von selbst."
    )
    assert alerts.override_text("boost", at(0), at(13 * 60), at(12 * 60)) is None
    assert alerts.override_text("boost", at(0), None, at(11 * 60)) is None
    assert alerts.automation_off_text(at(0), at(13 * 60 + 5)).startswith("Die Automatik ist seit 13 h 5 min aus.")
    assert alerts.automation_off_text(at(0), at(60)) is None


# ----------------------------------------------------------------- Meldungen
def issue(key="heater", **kw):
    return alerts.Issue(key, kw.pop("title", "Heizstab läuft"), kw.pop("text", "Der Heizstab läuft."),
                        kw.pop("ok", "Der Heizstab ist wieder aus"), **kw)


def test_issue_once_then_ok():
    out, mem = alerts.step_issues([issue()], {}, at(0))
    assert [(m.title, m.end) for m in out] == [("Heizstab läuft", False)]
    out, mem = alerts.step_issues([issue()], mem, at(1))
    assert out == []
    out, mem = alerts.step_issues([], mem, at(40))
    assert [(m.title, m.text, m.end) for m in out] == [
        ("Wieder in Ordnung", "Der Heizstab ist wieder aus (nach 40 min).", True)
    ]
    assert mem["heater"]["open"] is False


def test_issue_repeats_at_most_every_6_hours():
    _out, mem = alerts.step_issues([issue()], {}, at(0))
    _out, mem = alerts.step_issues([], mem, at(10))
    out, mem = alerts.step_issues([issue()], mem, at(60))
    assert out == []  # wieder da, aber gerade erst gemeldet
    out, mem = alerts.step_issues([], mem, at(70))
    assert out == []  # nicht gemeldet, also auch kein „wieder in Ordnung“
    out, mem = alerts.step_issues([issue()], mem, at(6 * 60 + 1))
    assert len(out) == 1


def test_issue_delay_unknown_and_quiet_end():
    problem = issue("problem:x", title="Problem", since=at(0), delay_min=5)
    out, mem = alerts.step_issues([problem], {}, at(4))
    assert out == [] and mem == {}
    out, mem = alerts.step_issues([problem], mem, at(5))
    assert len(out) == 1
    out, _ = alerts.step_issues([], mem, at(6), unknown={"problem:x"})
    assert out == []
    out, _ = alerts.step_issues([], mem, at(6), quiet_end=True)
    assert out == []
    out, _ = alerts.step_issues([], mem, at(6))
    assert out[0].end


def test_daily_event_without_ok():
    cyc = alerts.Issue("cycling", "Takten", "Die Wärmepumpe taktet.", daily=True)
    out, mem = alerts.step_issues([cyc], {}, at(0))
    assert len(out) == 1 and mem["cycling"]["open"] is False
    out, mem = alerts.step_issues([], mem, at(5))
    assert out == []  # Ereignis: kein „wieder in Ordnung“
    out, mem = alerts.step_issues([cyc], mem, at(10 * 60))
    assert out == []  # 22 Uhr, derselbe Tag
    out, mem = alerts.step_issues([cyc], mem, at(12 * 60 + 1))
    assert len(out) == 1  # nächster Tag


def test_memory_is_forgotten_after_a_day():
    _out, mem = alerts.step_issues([issue()], {}, at(0))
    _out, mem = alerts.step_issues([], mem, at(10))
    _out, mem = alerts.step_issues([], mem, at(27 * 60))
    assert mem == {}


def test_level_and_tag():
    event = alerts.Message("Angehoben", "…", issue=False)
    assert not alerts.wanted(event, alerts.LEVEL_ISSUES)
    assert alerts.wanted(event, alerts.LEVEL_ALL)
    assert alerts.wanted(alerts.Message("Takten", "…", issue=True), alerts.LEVEL_ISSUES)
    assert alerts.tag("no_effect") == "energy_hub_no_effect"
    long = alerts.tag("problem:Die PV-Prognose (sensor.x) liefert keinen Wert.")
    assert long.startswith("energy_hub_") and len(long) == len("energy_hub_") + 10


def test_fmt_duration():
    assert alerts.fmt_duration(0.4) == "1 min"
    assert alerts.fmt_duration(59.6) == "1 h"
    assert alerts.fmt_duration(130) == "2 h 10 min"
