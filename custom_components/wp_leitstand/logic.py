"""Entscheidungslogik für WP Leitstand.

Dieses Modul ist bewusst frei von Home-Assistant-Importen: Es bekommt
Messwerte, Einstellungen und den bisherigen Zustand und liefert zurück,
was die Heizung tun soll und warum. Dadurch lässt es sich ohne laufendes
Home Assistant testen (siehe tests/test_logic.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

MODE_NORMAL = "normal"
MODE_BOOST = "boost"
MODE_SETBACK = "setback"

MODE_LABEL = {
    MODE_NORMAL: "Normalbetrieb",
    MODE_BOOST: "Anheben",
    MODE_SETBACK: "Absenken",
}

# Regeln, die sofort gelten und die Mindesthaltezeit übergehen
_IMMEDIATE_RULES = {"override", "automation_off", "no_data"}


@dataclass(frozen=True)
class Settings:
    """Parameter der Regelung."""

    boost_on_w: float = 1500
    boost_on_min: float = 10
    boost_off_w: float = 300
    boost_off_min: float = 15
    min_hold_min: float = 20
    setback_enabled: bool = True
    setback_start: time = time(5, 0)
    setback_end: time = time(10, 0)
    setback_min_forecast_kwh: float = 10
    setback_min_outdoor_c: float | None = 3
    setback_min_dhw_c: float | None = 42
    # Speicher (Kamin): ab dieser Temperatur gilt er als bereit; None = kein Speicher hinterlegt
    storage_ready_c: float | None = None
    storage_blocks_boost: bool = True


@dataclass(frozen=True)
class Inputs:
    """Messwerte zum Zeitpunkt der Entscheidung. None = nicht verfügbar."""

    now: datetime
    surplus_w: float | None = None
    forecast_kwh: float | None = None
    outdoor_c: float | None = None
    dhw_c: float | None = None
    storage_c: float | None = None


@dataclass(frozen=True)
class Timers:
    """Seit wann der Überschuss über bzw. unter den Schwellen liegt."""

    above_since: datetime | None = None
    below_since: datetime | None = None


@dataclass(frozen=True)
class Override:
    """Handbetrieb. until = None bedeutet: bis er beendet wird."""

    mode: str
    until: datetime | None = None


@dataclass(frozen=True)
class Decision:
    """Ergebnis: Zielzustand, Begründung in Klartext und Kürzel der Regel."""

    mode: str
    reason: str
    rule: str


def fmt_w(value: float) -> str:
    """1500 -> '1.500 W'."""
    return f"{value:,.0f}".replace(",", ".") + " W"


def fmt_num(value: float, unit: str, digits: int = 1) -> str:
    """12.5 -> '12,5 kWh'."""
    text = f"{value:.{digits}f}".replace(".", ",")
    return f"{text} {unit}"


def fmt_min(value: float) -> str:
    """Minuten ohne Nachkommastellen."""
    return f"{value:.0f} min"


def _minutes(since: datetime | None, now: datetime) -> float | None:
    if since is None:
        return None
    return max(0.0, (now - since).total_seconds() / 60)


def in_window(now: time, start: time, end: time) -> bool:
    """Liegt now im Fenster start..end? Fenster über Mitternacht sind erlaubt."""
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


def update_timers(timers: Timers, inputs: Inputs, settings: Settings) -> Timers:
    """Führt die Zeitmarken für 'über Einschaltschwelle' / 'unter Ausschaltschwelle'."""
    surplus = inputs.surplus_w
    if surplus is None:
        return Timers()
    above = timers.above_since if surplus >= settings.boost_on_w else None
    if surplus >= settings.boost_on_w and above is None:
        above = inputs.now
    below = timers.below_since if surplus < settings.boost_off_w else None
    if surplus < settings.boost_off_w and below is None:
        below = inputs.now
    return Timers(above_since=above, below_since=below)


def storage_ready(inputs: Inputs, s: Settings) -> bool:
    """Hat der Speicher genug Temperatur, um die Heizung zu versorgen?"""
    return (
        s.storage_ready_c is not None
        and inputs.storage_c is not None
        and inputs.storage_c >= s.storage_ready_c
    )


def _storage_block(inputs: Inputs, s: Settings) -> str | None:
    """Begründung, warum wegen des Speichers nicht angehoben wird, sonst None."""
    if not (s.storage_blocks_boost and storage_ready(inputs, s)):
        return None
    return (
        f"Der Speicher hat {fmt_num(inputs.storage_c, '°C')} und kann die Heizung versorgen "
        f"(bereit ab {fmt_num(s.storage_ready_c, '°C')}). Deshalb wird nicht angehoben."
    )


def _setback_check(inputs: Inputs, s: Settings) -> tuple[bool, str]:
    """Prüft die Absenkbedingungen. Liefert (erfüllt, Begründung)."""
    window = f"{s.setback_start:%H:%M}–{s.setback_end:%H:%M} Uhr"
    if not s.setback_enabled:
        return False, "Absenken ist abgeschaltet."
    if not in_window(inputs.now.time(), s.setback_start, s.setback_end):
        return False, f"Abgesenkt wird nur {window}."
    if inputs.forecast_kwh is None:
        return False, "Die PV-Prognose ist nicht verfügbar."
    if inputs.forecast_kwh < s.setback_min_forecast_kwh:
        return False, (
            f"Die Prognose von {fmt_num(inputs.forecast_kwh, 'kWh')} reicht nicht zum "
            f"Absenken (mindestens {fmt_num(s.setback_min_forecast_kwh, 'kWh')})."
        )
    if s.setback_min_outdoor_c is not None:
        if inputs.outdoor_c is None:
            return False, "Die Außentemperatur ist nicht verfügbar, deshalb wird nicht abgesenkt."
        if inputs.outdoor_c < s.setback_min_outdoor_c:
            return False, (
                f"Bei {fmt_num(inputs.outdoor_c, '°C')} außen wird nicht abgesenkt "
                f"(Grenze {fmt_num(s.setback_min_outdoor_c, '°C')})."
            )
    if s.setback_min_dhw_c is not None:
        if inputs.dhw_c is None:
            return False, "Die Warmwassertemperatur ist nicht verfügbar, deshalb wird nicht abgesenkt."
        if inputs.dhw_c < s.setback_min_dhw_c:
            return False, (
                f"Das Warmwasser hat nur {fmt_num(inputs.dhw_c, '°C')}, deshalb wird nicht "
                f"abgesenkt (Grenze {fmt_num(s.setback_min_dhw_c, '°C')})."
            )
    return True, (
        f"Für den Rest des Tages sind {fmt_num(inputs.forecast_kwh, 'kWh')} PV-Ertrag "
        f"vorhergesagt. Die Heizung wartet im Absenkfenster ({window}) auf eigenen Strom."
    )


def _wanted(
    inputs: Inputs,
    s: Settings,
    timers: Timers,
    current_mode: str,
) -> Decision:
    """Was die Regeln ohne Mindesthaltezeit verlangen."""
    surplus = inputs.surplus_w
    assert surplus is not None
    above_for = _minutes(timers.above_since, inputs.now)
    below_for = _minutes(timers.below_since, inputs.now)
    block = _storage_block(inputs, s)

    if current_mode == MODE_BOOST:
        if block:
            ok, text = _setback_check(inputs, s)
            if ok:
                return Decision(MODE_SETBACK, f"{block} {text}", "setback")
            return Decision(MODE_NORMAL, block, "storage")
        if below_for is None or below_for < s.boost_off_min:
            if below_for is None:
                reason = (
                    f"Der PV-Überschuss reicht weiter aus (aktuell {fmt_w(surplus)}). "
                    f"Beendet wird unter {fmt_w(s.boost_off_w)} für {fmt_min(s.boost_off_min)}."
                )
            else:
                reason = (
                    f"Der PV-Überschuss liegt seit {fmt_min(below_for)} unter "
                    f"{fmt_w(s.boost_off_w)} (aktuell {fmt_w(surplus)}). Nach "
                    f"{fmt_min(s.boost_off_min)} endet das Anheben."
                )
            return Decision(MODE_BOOST, reason, "boost_keep")
        ended = (
            f"Der PV-Überschuss liegt seit {fmt_min(below_for)} unter "
            f"{fmt_w(s.boost_off_w)} (aktuell {fmt_w(surplus)})."
        )
        ok, text = _setback_check(inputs, s)
        if ok:
            return Decision(MODE_SETBACK, f"{ended} {text}", "setback")
        return Decision(MODE_NORMAL, ended, "boost_end")

    enough = above_for is not None and above_for >= s.boost_on_min
    if enough and not block:
        return Decision(
            MODE_BOOST,
            f"Der PV-Überschuss liegt seit {fmt_min(above_for)} über "
            f"{fmt_w(s.boost_on_w)} (aktuell {fmt_w(surplus)}).",
            "boost",
        )

    ok, text = _setback_check(inputs, s)
    if ok:
        return Decision(MODE_SETBACK, text, "setback")
    if enough and block:
        return Decision(MODE_NORMAL, block, "storage")

    if above_for is not None:
        boost_text = (
            f"Der PV-Überschuss liegt erst seit {fmt_min(above_for)} über "
            f"{fmt_w(s.boost_on_w)} (aktuell {fmt_w(surplus)}); angehoben wird nach "
            f"{fmt_min(s.boost_on_min)}."
        )
    else:
        boost_text = (
            f"Der PV-Überschuss von {fmt_w(surplus)} liegt unter der Einschaltschwelle "
            f"von {fmt_w(s.boost_on_w)}."
        )
    return Decision(MODE_NORMAL, f"{boost_text} {text}", "idle")


def decide(
    inputs: Inputs,
    settings: Settings,
    timers: Timers,
    current_mode: str,
    mode_since: datetime | None,
    automation: bool = True,
    override: Override | None = None,
) -> Decision:
    """Bestimmt den Zielzustand der Heizung.

    Reihenfolge: Handbetrieb, Automatik aus, fehlende Messwerte, dann die
    PV-Regeln. Wechsel durch die PV-Regeln warten die Mindesthaltezeit ab.
    """
    now = inputs.now
    if override is not None and (override.until is None or now < override.until):
        until = (
            f"bis {override.until:%H:%M} Uhr" if override.until else "bis er beendet wird"
        )
        return Decision(
            override.mode,
            f"Handbetrieb: {MODE_LABEL[override.mode]}, {until}.",
            "override",
        )
    if not automation:
        return Decision(
            MODE_NORMAL, "Die Automatik ist ausgeschaltet, es wird nicht eingegriffen.", "automation_off"
        )
    if inputs.surplus_w is None:
        return Decision(
            MODE_NORMAL,
            "Der PV-Überschuss ist nicht verfügbar. Zur Sicherheit läuft die Heizung normal.",
            "no_data",
        )

    wanted = _wanted(inputs, settings, timers, current_mode)
    if wanted.mode == current_mode or wanted.rule in _IMMEDIATE_RULES:
        return wanted

    held = _minutes(mode_since, now)
    if held is not None and held < settings.min_hold_min:
        remaining = settings.min_hold_min - held
        return Decision(
            current_mode,
            f"Wechsel zu „{MODE_LABEL[wanted.mode]}“ steht an: {wanted.reason} "
            f"Die Mindesthaltezeit läuft noch {fmt_min(max(1.0, remaining))}.",
            "hold",
        )
    return wanted
