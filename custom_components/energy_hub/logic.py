"""Entscheidungslogik für Energy Hub.

Dieses Modul ist bewusst frei von Home-Assistant-Importen: Es bekommt
Messwerte, Einstellungen und den bisherigen Zustand und liefert zurück,
was die Heizung tun soll und warum. Dadurch lässt es sich ohne laufendes
Home Assistant testen (siehe tests/test_logic.py).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta

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
    boost_off_w: float = -300
    boost_off_min: float = 15
    min_hold_min: float = 20
    # Nur für die Begründungen: über wie viele Minuten der Regler die Messwerte mittelt
    smoothing_min: float = 0
    setback_enabled: bool = True
    setback_start: time = time(5, 0)
    setback_end: time = time(10, 0)
    setback_min_forecast_kwh: float = 10
    setback_min_outdoor_c: float | None = 3
    setback_min_dhw_c: float | None = 42
    # Speicher (Kamin): bereit ab Rücklaufsoll + Differenz. storage_ready_c ist die feste
    # Ersatz-Schwelle ohne Rücklaufsoll; None = kein Speicher hinterlegt
    storage_ready_delta_k: float = 5
    storage_ready_c: float | None = None
    storage_blocks_boost: bool = True


@dataclass(frozen=True)
class Inputs:
    """Messwerte zum Zeitpunkt der Entscheidung. None = nicht verfügbar.

    balance_w ist der Überschuss ohne Akku: PV-Überschuss plus Ladeleistung des Akkus
    (Entladen zählt negativ). Er entscheidet über das Ende des Anhebens; None heißt,
    es zählt wie bisher der PV-Überschuss.
    """

    now: datetime
    surplus_w: float | None = None
    balance_w: float | None = None
    forecast_kwh: float | None = None
    forecast_tomorrow_kwh: float | None = None
    outdoor_c: float | None = None
    dhw_c: float | None = None
    storage_c: float | None = None
    return_target_c: float | None = None


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


def window_mean(
    samples: Sequence[tuple[datetime, float]], now: datetime, minutes: float, max_age_min: float
) -> float | None:
    """Zeitgewichteter Mittelwert der Messwerte aus den letzten `minutes` Minuten.

    Jeder Messwert gilt bis zum nächsten, der neueste bis jetzt. So überbrückt der Regler
    kurze Aussetzer eines Sensors. Ist der neueste Wert älter als max_age_min, gilt der
    Sensor als nicht verfügbar (None). Ohne Glättung (minutes <= 0) zählt der neueste Wert.
    """
    if not samples:
        return None
    last_at, last_value = samples[-1]
    if (now - last_at).total_seconds() > max_age_min * 60:
        return None
    if minutes <= 0:
        return last_value
    start = now - timedelta(minutes=minutes)
    total = 0.0
    weight = 0.0
    for i, (at, value) in enumerate(samples):
        end = samples[i + 1][0] if i + 1 < len(samples) else now
        seconds = (end - max(at, start)).total_seconds()
        if seconds > 0:
            total += value * seconds
            weight += seconds
    return total / weight if weight else last_value


def trim_samples(
    samples: list[tuple[datetime, float]], now: datetime, minutes: float
) -> list[tuple[datetime, float]]:
    """Behält, was window_mean noch braucht: die Werte im Zeitraum und den letzten davor."""
    start = now - timedelta(minutes=max(0.0, minutes))
    first = next((i for i, (at, _value) in enumerate(samples) if at > start), len(samples))
    return samples[max(0, first - 1):]


def update_timers(timers: Timers, inputs: Inputs, settings: Settings) -> Timers:
    """Führt die Zeitmarken für 'über Einschaltschwelle' / 'unter Ausschaltschwelle'.

    Eingeschaltet wird nach dem PV-Überschuss, ausgeschaltet nach dem Überschuss ohne Akku,
    sofern er bekannt ist.
    """
    surplus = inputs.surplus_w
    if surplus is None:
        return Timers()
    above = timers.above_since if surplus >= settings.boost_on_w else None
    if surplus >= settings.boost_on_w and above is None:
        above = inputs.now
    off = inputs.balance_w if inputs.balance_w is not None else surplus
    below = timers.below_since if off < settings.boost_off_w else None
    if off < settings.boost_off_w and below is None:
        below = inputs.now
    return Timers(above_since=above, below_since=below)


def _measured(value: float, s: Settings) -> str:
    """'aktuell 2.140 W' oder mit Glättung 'im 5-Minuten-Mittel 2.140 W'."""
    if s.smoothing_min > 0:
        return f"im {s.smoothing_min:.0f}-Minuten-Mittel {fmt_w(value)}"
    return f"aktuell {fmt_w(value)}"


def _off_measure(inputs: Inputs) -> tuple[float, str]:
    """Wert und Name der Größe, nach der das Anheben endet."""
    if inputs.balance_w is not None:
        return inputs.balance_w, "Der Überschuss ohne Akku"
    assert inputs.surplus_w is not None
    return inputs.surplus_w, "Der PV-Überschuss"


def ready_threshold(return_target_c: float | None, delta_k: float, fallback_c: float) -> float:
    """Ab welcher Temperatur der Speicher die Heizung versorgen kann.

    Gerechnet wird wie im Regler der Wärmepumpe: Rücklauf-Solltemperatur plus
    Differenz. Liegt keine Solltemperatur vor, gilt die feste Ersatz-Schwelle.
    """
    if return_target_c is None:
        return fallback_c
    return return_target_c + delta_k


def storage_threshold(inputs: Inputs, s: Settings) -> float | None:
    """Aktuelle Bereit-Schwelle; None, wenn kein Speicher hinterlegt ist."""
    if s.storage_ready_c is None:
        return None
    return ready_threshold(inputs.return_target_c, s.storage_ready_delta_k, s.storage_ready_c)


def storage_ready(inputs: Inputs, s: Settings) -> bool:
    """Hat der Speicher genug Temperatur, um die Heizung zu versorgen?"""
    threshold = storage_threshold(inputs, s)
    return threshold is not None and inputs.storage_c is not None and inputs.storage_c >= threshold


def _storage_block(inputs: Inputs, s: Settings) -> str | None:
    """Begründung, warum wegen des Speichers nicht angehoben wird, sonst None."""
    if not (s.storage_blocks_boost and storage_ready(inputs, s)):
        return None
    threshold = storage_threshold(inputs, s)
    basis = f"bereit ab {fmt_num(threshold, '°C')}"
    if inputs.return_target_c is not None:
        basis += (
            f": Rücklaufsoll {fmt_num(inputs.return_target_c, '°C')} plus "
            f"{fmt_num(s.storage_ready_delta_k, 'K')}"
        )
    return (
        f"Der Speicher hat {fmt_num(inputs.storage_c, '°C')} und kann die Heizung versorgen "
        f"({basis}). Deshalb wird nicht angehoben."
    )


def uses_tomorrow(now: time, start: time, end: time) -> bool:
    """Zählt gerade die Prognose für morgen?

    Ja im Abendteil eines Absenkfensters über Mitternacht (etwa 21:00 bis Mitternacht bei
    21:00–10:00): Die Prognose für den Rest des Tages liegt dann bei null, gewartet wird
    auf die Sonne des nächsten Tages. Nach Mitternacht zählt wieder „Rest heute“.
    """
    return start > end and now >= start


def _setback_check(inputs: Inputs, s: Settings) -> tuple[bool, str]:
    """Prüft die Absenkbedingungen. Liefert (erfüllt, Begründung)."""
    window = f"{s.setback_start:%H:%M}–{s.setback_end:%H:%M} Uhr"
    if not s.setback_enabled:
        return False, "Absenken ist abgeschaltet."
    if not in_window(inputs.now.time(), s.setback_start, s.setback_end):
        return False, f"Abgesenkt wird nur {window}."
    tomorrow = uses_tomorrow(inputs.now.time(), s.setback_start, s.setback_end)
    forecast = inputs.forecast_tomorrow_kwh if tomorrow else inputs.forecast_kwh
    which = "für morgen " if tomorrow else ""
    if forecast is None:
        return False, f"Die PV-Prognose {which}ist nicht verfügbar."
    if forecast < s.setback_min_forecast_kwh:
        return False, (
            f"Die Prognose {which}von {fmt_num(forecast, 'kWh')} reicht nicht zum "
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
    when = "Für morgen" if tomorrow else "Für den Rest des Tages"
    return True, (
        f"{when} sind {fmt_num(forecast, 'kWh')} PV-Ertrag "
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
        off_value, off_name = _off_measure(inputs)
        if below_for is None or below_for < s.boost_off_min:
            if below_for is None:
                reason = (
                    f"{off_name} reicht weiter aus ({_measured(off_value, s)}). "
                    f"Beendet wird unter {fmt_w(s.boost_off_w)} für {fmt_min(s.boost_off_min)}."
                )
            else:
                reason = (
                    f"{off_name} liegt seit {fmt_min(below_for)} unter "
                    f"{fmt_w(s.boost_off_w)} ({_measured(off_value, s)}). Nach "
                    f"{fmt_min(s.boost_off_min)} endet das Anheben."
                )
            return Decision(MODE_BOOST, reason, "boost_keep")
        ended = (
            f"{off_name} liegt seit {fmt_min(below_for)} unter "
            f"{fmt_w(s.boost_off_w)} ({_measured(off_value, s)})."
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
            f"{fmt_w(s.boost_on_w)} ({_measured(surplus, s)}).",
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
            f"{fmt_w(s.boost_on_w)} ({_measured(surplus, s)}); angehoben wird nach "
            f"{fmt_min(s.boost_on_min)}."
        )
    else:
        mean = f" im {s.smoothing_min:.0f}-Minuten-Mittel" if s.smoothing_min > 0 else ""
        # Angezeigt wird nie weniger als 0 W; ein negativer Wert ist Netzbezug
        boost_text = (
            f"Der PV-Überschuss von {fmt_w(max(0.0, surplus))}{mean} liegt unter der Einschaltschwelle "
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
