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
MODE_STRONG = "strong"
MODE_SETBACK = "setback"

MODE_LABEL = {
    MODE_NORMAL: "Normalbetrieb",
    MODE_BOOST: "Anheben",
    MODE_STRONG: "Stark anheben",
    MODE_SETBACK: "Absenken",
}

# Zustände, in denen die Heizung angehoben ist
RAISED = (MODE_BOOST, MODE_STRONG)

# Regeln, die sofort gelten und die Mindesthaltezeit übergehen
_IMMEDIATE_RULES = {"override", "automation_off", "no_data"}

# Ab dieser elektrischen Leistung gilt die Wärmepumpe als laufend
RUN_MIN_W = 300
# Die Leistung im Lauf wird anfangs einfach gemittelt, ab so vielen Minuten Laufzeit gleitend
LEARN_TAU_MIN = 360
# So viel Laufzeit braucht es, bevor die gelernte Leistung als Einschaltschwelle gilt
LEARN_MIN_MIN = 30
# Der Akku wird „ohnehin voll“, wenn die Prognose für den Rest des Tages so oft reicht,
# wie ihm zum Vollladen fehlt (der Rest geht an Haus, Wärmepumpe und Prognosefehler)
BATTERY_FORECAST_FACTOR = 2.0
# Kapazität des Akkus: geschätzt, sobald sich der Ladestand um so viele Prozentpunkte geändert hat
CAPACITY_SOC_SPAN = 20
CAPACITY_RANGE_KWH = (0.5, 200.0)
# Ein Abschnitt der Schätzung beginnt neu nach einer Lücke oder wenn er zu lange dauert
CAPACITY_GAP = timedelta(minutes=5)
CAPACITY_MAX_SPAN = timedelta(hours=24)
# Die Kapazität mittelt die letzten Schätzungen, gleitend über so viele
CAPACITY_KEEP = 5

# Warmwasser nachladen: einmal am Tag, wenn die Sonne nachlässt und die PV gerade noch eine Ladung trägt
DHW_RELOAD_GAP_K = 4.0  # so weit muss das Warmwasser unter dem Soll liegen
DHW_RELOAD_BAND = 1.5  # übrig für die Wärmepumpe: zwischen ihrer Leistung und dem 1,5-Fachen
DHW_RELOAD_WAIT_MIN = 10  # so lange muss das anliegen
DHW_RELOAD_MAX_MIN = 90  # längstens so lange nachladen
DHW_RELOAD_DONE_K = 0.5  # fertig, wenn das Warmwasser so nah am Soll ist
BATTERY_FULL_SOC = 95.0  # ab diesem Ladestand gilt der Akku als voll


@dataclass(frozen=True)
class Settings:
    """Parameter der Regelung."""

    boost_on_w: float = 1500
    # Einschaltschwelle aus der gelernten Leistung der Wärmepumpe im Lauf, sobald sie bekannt ist
    boost_on_learned: bool = True
    boost_on_min: float = 10
    boost_off_w: float = -300
    boost_off_min: float = 15
    # Stark anheben (zweite Stufe): wenn beim Anheben noch so viel übrig ist
    strong_enabled: bool = True
    strong_on_w: float = 2000
    # Warmwasser nachladen: Hysterese vorübergehend auf diesen Wert
    dhw_reload: bool = True
    dhw_reload_hyst_k: float = 2.0
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

    available_w ist, was für die Wärmepumpe übrig ist: PV-Überschuss plus das, was die
    Wärmepumpe gerade selbst zieht. Der Akku lädt zuerst; was er entlädt, zählt nicht als
    übrig. available_free_w rechnet zusätzlich die Ladeleistung des Akkus als übrig; das
    gilt, wenn der Akku heute ohnehin voll wird. None heißt: Es zählt der PV-Überschuss.

    run_w ist die gelernte Leistung der Wärmepumpe im Lauf, battery_kwh die gelernte
    Kapazität des Akkus, beide None, solange sie nicht bekannt sind.
    """

    now: datetime
    surplus_w: float | None = None
    balance_w: float | None = None
    available_w: float | None = None
    available_free_w: float | None = None
    run_w: float | None = None
    battery_soc: float | None = None
    battery_kwh: float | None = None
    # Warmwasser nachladen: Soll, das gerade gilt; Nachmittag (nach dem Sonnenhöchststand);
    # die Wärmepumpe macht gerade Warmwasser
    dhw_target_c: float | None = None
    afternoon: bool | None = None
    dhw_heating: bool | None = None
    forecast_kwh: float | None = None
    forecast_tomorrow_kwh: float | None = None
    outdoor_c: float | None = None
    dhw_c: float | None = None
    storage_c: float | None = None
    return_target_c: float | None = None


@dataclass(frozen=True)
class Timers:
    """Seit wann die Messwerte über bzw. unter den Schwellen liegen.

    above_since: über der Einschaltschwelle, below_since: unter der Ausschaltschwelle,
    strong_since: beim Anheben über der Schwelle zum starken Anheben,
    reload_since: für die Wärmepumpe übrig zwischen ihrer Leistung und dem 1,5-Fachen.
    """

    above_since: datetime | None = None
    below_since: datetime | None = None
    strong_since: datetime | None = None
    reload_since: datetime | None = None


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


def battery_missing_kwh(inputs: Inputs) -> float | None:
    """Wie viel dem Akku zum Vollladen fehlt; None ohne Ladestand oder gelernte Kapazität."""
    if inputs.battery_kwh is None or inputs.battery_soc is None:
        return None
    return inputs.battery_kwh * max(0.0, 100.0 - inputs.battery_soc) / 100.0


def battery_fills(inputs: Inputs) -> bool:
    """Wird der Akku heute ohnehin voll? Dann darf die Wärmepumpe schon vorher seine Ladeleistung nutzen."""
    missing = battery_missing_kwh(inputs)
    if missing is None or inputs.forecast_kwh is None or inputs.available_free_w is None:
        return False
    return inputs.forecast_kwh >= BATTERY_FORECAST_FACTOR * missing


@dataclass(frozen=True)
class OnRule:
    """Wonach angehoben wird: Wert, Schwelle und woher beides kommt."""

    value: float
    threshold: float
    available: bool  # True: „für die Wärmepumpe übrig“, False: PV-Überschuss
    learned: bool  # Schwelle aus der gelernten Leistung der Wärmepumpe
    fills: bool  # Akku wird ohnehin voll, seine Ladeleistung zählt mit


def on_rule(inputs: Inputs, s: Settings) -> OnRule | None:
    """Einschaltregel zum Zeitpunkt; None ohne PV-Überschuss."""
    if inputs.surplus_w is None:
        return None
    learned = s.boost_on_learned and inputs.run_w is not None
    threshold = inputs.run_w if learned else s.boost_on_w
    if inputs.available_w is None:
        return OnRule(inputs.surplus_w, threshold, False, learned, False)
    fills = battery_fills(inputs)
    value = inputs.available_free_w if fills else inputs.available_w
    return OnRule(value, threshold, True, learned, fills)


def strong_value(inputs: Inputs) -> float | None:
    """Was beim Anheben noch übrig ist: der PV-Überschuss, ohne Akku, wenn er ohnehin voll wird."""
    if battery_fills(inputs) and inputs.balance_w is not None:
        return inputs.balance_w
    return inputs.surplus_w


def update_timers(
    timers: Timers, inputs: Inputs, settings: Settings, mode: str = MODE_NORMAL
) -> Timers:
    """Führt die Zeitmarken für die Schwellen.

    Angehoben wird nach dem, was für die Wärmepumpe übrig ist (ohne Messung der Wärmepumpe
    und ohne Akku nach dem PV-Überschuss), beendet nach dem Überschuss ohne Akku, sofern er
    bekannt ist. Die Zeit zum starken Anheben läuft nur, solange angehoben ist.
    """
    rule = on_rule(inputs, settings)
    if rule is None:
        return Timers()
    now = inputs.now
    above = (timers.above_since or now) if rule.value >= rule.threshold else None
    off = inputs.balance_w if inputs.balance_w is not None else inputs.surplus_w
    below = (timers.below_since or now) if off < settings.boost_off_w else None
    strong = None
    extra = strong_value(inputs)
    if mode == MODE_BOOST and settings.strong_enabled and extra is not None and extra >= settings.strong_on_w:
        strong = timers.strong_since or now
    in_band = settings.dhw_reload and rule.threshold > 0 and (
        rule.threshold <= rule.value < DHW_RELOAD_BAND * rule.threshold
    )
    reload = (timers.reload_since or now) if in_band else None
    return Timers(above_since=above, below_since=below, strong_since=strong, reload_since=reload)


# ------------------------------------------------------- Warmwasser nachladen
@dataclass(frozen=True)
class ReloadCheck:
    """Ob das Warmwasser jetzt nachgeladen wird; reason fürs Logbuch, short fürs Panel."""

    start: bool
    reason: str
    short: str


def dhw_reload_check(inputs: Inputs, s: Settings, timers: Timers, done_today: bool) -> ReloadCheck:
    """Warmwasser nachladen: einmal am Tag, bevor die Sonne für eine Ladung nicht mehr reicht.

    Mittags lädt Grün das Warmwasser auf die Maximaltemperatur. Danach fällt es langsam, bleibt
    aber innerhalb der Hysterese, und die Wärmepumpe lädt erst nachts nach. Deshalb wird am
    Nachmittag einmal nachgeladen, wenn für die Wärmepumpe nur noch knapp so viel übrig ist, wie
    sie zieht: Später reicht die PV nicht mehr.
    """
    def no(short: str) -> ReloadCheck:
        return ReloadCheck(False, "", short)

    if not s.dhw_reload:
        return no("abgeschaltet")
    if done_today:
        return no("heute schon nachgeladen")
    if inputs.dhw_c is None or inputs.dhw_target_c is None:
        return no("Warmwasser-Temperatur oder Soll fehlt")
    gap = inputs.dhw_target_c - inputs.dhw_c
    if gap < DHW_RELOAD_GAP_K:
        return no(f"erst ab {fmt_num(DHW_RELOAD_GAP_K, 'K', 0)} unter Soll, jetzt {fmt_num(max(0.0, gap), 'K')}")
    if inputs.afternoon is False:
        return no("erst nach Mittag")
    if inputs.dhw_heating:
        return no("die Wärmepumpe macht gerade Warmwasser")
    if inputs.battery_soc is not None and inputs.battery_soc < BATTERY_FULL_SOC and not battery_fills(inputs):
        return no("der Akku lädt noch")
    rule = on_rule(inputs, s)
    if rule is None:
        return no("kein PV-Überschuss gemessen")
    band = (
        f"zwischen {fmt_w(rule.threshold)} und {fmt_w(DHW_RELOAD_BAND * rule.threshold)}"
    )
    held = _minutes(timers.reload_since, inputs.now)
    if held is None or held < DHW_RELOAD_WAIT_MIN:
        if rule.value >= DHW_RELOAD_BAND * rule.threshold:
            return no("wartet, bis die Sonne nachlässt")
        if rule.value < rule.threshold:
            return no("zu wenig Sonne")
        return no(f"übrig {band}, seit {fmt_min(held or 0)}")
    what = "Für die Wärmepumpe sind" if rule.available else "Als PV-Überschuss sind"
    return ReloadCheck(
        True,
        f"Die Sonne lässt nach: {what} seit {fmt_min(held)} nur noch {band} übrig "
        f"({_measured(rule.value, s)}), später reicht es für eine Ladung nicht mehr. Das Warmwasser hat "
        f"{fmt_num(inputs.dhw_c, '°C')} und liegt {fmt_num(gap, 'K')} unter dem Soll von "
        f"{fmt_num(inputs.dhw_target_c, '°C')}.",
        "läuft",
    )


def dhw_reload_end(inputs: Inputs, s: Settings, since: datetime, timers: Timers) -> str | None:
    """Warum das Nachladen jetzt endet; None, solange es weiterläuft."""
    if inputs.dhw_c is not None and inputs.dhw_target_c is not None:
        if inputs.dhw_c >= inputs.dhw_target_c - DHW_RELOAD_DONE_K:
            return f"Das Warmwasser hat {fmt_num(inputs.dhw_c, '°C')} erreicht (Soll {fmt_num(inputs.dhw_target_c, '°C')})."
    ran = _minutes(since, inputs.now) or 0.0
    if ran >= DHW_RELOAD_MAX_MIN:
        return f"Nach {fmt_min(DHW_RELOAD_MAX_MIN)} beendet."
    below = _minutes(timers.below_since, inputs.now)
    if below is not None and below >= s.boost_off_min:
        off_value, off_name = _off_measure(inputs)
        return (
            f"{off_name} liegt seit {fmt_min(below)} unter {fmt_w(s.boost_off_w)} "
            f"({_measured(off_value, s)}); die PV trägt die Wärmepumpe nicht mehr."
        )
    return None


# ------------------------------------------------------------------- Lernen
def learn_run_power(
    value: float | None, minutes: float, power_w: float | None, dt_min: float
) -> tuple[float | None, float]:
    """Lernt die Leistung der Wärmepumpe im Lauf.

    Anfangs ist es der zeitgewichtete Mittelwert aller Messungen im Lauf, ab LEARN_TAU_MIN
    Minuten Laufzeit ein gleitender Mittelwert. So folgt er langsam der Jahreszeit: Bei Kälte
    zieht eine Luft-Wärmepumpe mehr. Gezählt wird nur, solange sie läuft.
    """
    if power_w is None or power_w < RUN_MIN_W or dt_min <= 0:
        return value, minutes
    minutes += dt_min
    weight = min(minutes, LEARN_TAU_MIN)
    value = power_w if value is None else value + (power_w - value) * dt_min / weight
    return value, minutes


def learned_run_w(value: float | None, minutes: float) -> float | None:
    """Die gelernte Leistung, sobald genug Laufzeit beisammen ist; auf 50 W gerundet."""
    if value is None or minutes < LEARN_MIN_MIN:
        return None
    return max(float(RUN_MIN_W), round(value / 50) * 50.0)


@dataclass(frozen=True)
class Segment:
    """Laufender Abschnitt der Kapazitäts-Schätzung: Beginn, Ladestand am Beginn, Energie seitdem."""

    start: datetime
    soc: float
    kwh: float
    last: datetime


def capacity_step(
    segment: Segment | None, now: datetime, soc: float | None, charge_w: float | None
) -> tuple[Segment | None, float | None]:
    """Ein Schritt der Kapazitäts-Schätzung aus Ladeleistung und Ladestand.

    Die Energie, die seit Beginn des Abschnitts in den Akku floss (Entladen negativ), geteilt
    durch die Änderung des Ladestands, ergibt die Kapazität. Geschätzt wird, sobald sich der
    Ladestand um CAPACITY_SOC_SPAN Prozentpunkte geändert hat. Liefert den neuen Abschnitt
    und, wenn es so weit ist, die Schätzung in kWh.
    """
    if soc is None or charge_w is None or not 0 <= soc <= 100:
        return None, None
    if segment is None or now - segment.last > CAPACITY_GAP or now - segment.start > CAPACITY_MAX_SPAN:
        return Segment(now, soc, 0.0, now), None
    hours = (now - segment.last).total_seconds() / 3600
    kwh = segment.kwh + charge_w * hours / 1000
    span = soc - segment.soc
    if abs(span) < CAPACITY_SOC_SPAN:
        return Segment(segment.start, segment.soc, kwh, now), None
    estimate = kwh / span * 100
    low, high = CAPACITY_RANGE_KWH
    return Segment(now, soc, 0.0, now), (estimate if low <= estimate <= high else None)


def learn_capacity(value: float | None, count: int, estimate: float) -> tuple[float, int]:
    """Mittelt die Schätzungen der Kapazität, gleitend über die letzten CAPACITY_KEEP."""
    count += 1
    value = estimate if value is None else value + (estimate - value) / min(count, CAPACITY_KEEP)
    return value, count


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


def _on_texts(rule: OnRule, s: Settings) -> tuple[str, str]:
    """Bausteine der Begründung: Schwelle mit Herkunft und Hinweis auf den Akku."""
    note = " So viel zieht die Wärmepumpe im Lauf." if rule.learned else ""
    if rule.fills:
        note += " Der Akku wird heute ohnehin voll, deshalb zählt auch seine Ladeleistung."
    return fmt_w(rule.threshold), note


def _boost_text(rule: OnRule, s: Settings, above_for: float) -> str:
    limit, note = _on_texts(rule, s)
    if rule.available:
        return (
            f"Für die Wärmepumpe sind seit {fmt_min(above_for)} mehr als {limit} übrig "
            f"({_measured(rule.value, s)}).{note}"
        )
    return f"Der PV-Überschuss liegt seit {fmt_min(above_for)} über {limit} ({_measured(rule.value, s)})."


def _waiting_text(rule: OnRule, s: Settings, above_for: float | None) -> str:
    """Begründung im Normalbetrieb, solange (noch) nicht angehoben wird."""
    limit, note = _on_texts(rule, s)
    mean = f" im {s.smoothing_min:.0f}-Minuten-Mittel" if s.smoothing_min > 0 else ""
    # Angezeigt wird nie weniger als 0 W; ein negativer Wert ist Netzbezug oder Akku
    shown = fmt_w(max(0.0, rule.value))
    if rule.available:
        if above_for is not None:
            return (
                f"Für die Wärmepumpe sind erst seit {fmt_min(above_for)} mehr als {limit} übrig "
                f"({_measured(rule.value, s)}); angehoben wird nach {fmt_min(s.boost_on_min)}.{note}"
            )
        return f"Für die Wärmepumpe sind{mean} {shown} übrig, angehoben wird ab {limit}.{note}"
    if above_for is not None:
        return (
            f"Der PV-Überschuss liegt erst seit {fmt_min(above_for)} über {limit} "
            f"({_measured(rule.value, s)}); angehoben wird nach {fmt_min(s.boost_on_min)}."
        )
    return f"Der PV-Überschuss von {shown}{mean} liegt unter der Einschaltschwelle von {limit}."


def _wanted(
    inputs: Inputs,
    s: Settings,
    timers: Timers,
    current_mode: str,
) -> Decision:
    """Was die Regeln ohne Mindesthaltezeit verlangen."""
    rule = on_rule(inputs, s)
    assert rule is not None
    above_for = _minutes(timers.above_since, inputs.now)
    below_for = _minutes(timers.below_since, inputs.now)
    strong_for = _minutes(timers.strong_since, inputs.now)
    block = _storage_block(inputs, s)

    if current_mode in RAISED:
        if block:
            ok, text = _setback_check(inputs, s)
            if ok:
                return Decision(MODE_SETBACK, f"{block} {text}", "setback")
            return Decision(MODE_NORMAL, block, "storage")
        off_value, off_name = _off_measure(inputs)
        if below_for is not None and below_for >= s.boost_off_min:
            ended = (
                f"{off_name} liegt seit {fmt_min(below_for)} unter "
                f"{fmt_w(s.boost_off_w)} ({_measured(off_value, s)})."
            )
            if current_mode == MODE_STRONG and rule.value >= rule.threshold:
                # Für einfaches Anheben reicht es noch: eine Stufe zurück
                return Decision(
                    MODE_BOOST,
                    f"{ended} Für einfaches Anheben reicht es noch ({_measured(rule.value, s)} "
                    f"für die Wärmepumpe übrig, nötig {fmt_w(rule.threshold)}).",
                    "strong_end",
                )
            ok, text = _setback_check(inputs, s)
            if ok:
                return Decision(MODE_SETBACK, f"{ended} {text}", "setback")
            return Decision(MODE_NORMAL, ended, "boost_end")
        extra = strong_value(inputs)
        if current_mode == MODE_BOOST and strong_for is not None and strong_for >= s.boost_on_min:
            assert extra is not None
            return Decision(
                MODE_STRONG,
                f"Trotz Anheben sind seit {fmt_min(strong_for)} mehr als {fmt_w(s.strong_on_w)} "
                f"übrig ({_measured(extra, s)}).",
                "strong",
            )
        if below_for is None:
            reason = (
                f"{off_name} reicht weiter aus ({_measured(off_value, s)}). "
                f"Beendet wird unter {fmt_w(s.boost_off_w)} für {fmt_min(s.boost_off_min)}."
            )
        else:
            reason = (
                f"{off_name} liegt seit {fmt_min(below_for)} unter "
                f"{fmt_w(s.boost_off_w)} ({_measured(off_value, s)}). Nach "
                f"{fmt_min(s.boost_off_min)} endet "
                + ("das starke Anheben." if current_mode == MODE_STRONG else "das Anheben.")
            )
        if current_mode == MODE_BOOST and strong_for is not None and extra is not None:
            reason += (
                f" Trotz Anheben sind seit {fmt_min(strong_for)} mehr als {fmt_w(s.strong_on_w)} übrig; "
                f"stark angehoben wird nach {fmt_min(s.boost_on_min)}."
            )
        return Decision(current_mode, reason, "boost_keep")

    enough = above_for is not None and above_for >= s.boost_on_min
    if enough and not block:
        assert above_for is not None
        return Decision(MODE_BOOST, _boost_text(rule, s, above_for), "boost")

    ok, text = _setback_check(inputs, s)
    if ok:
        return Decision(MODE_SETBACK, text, "setback")
    if enough and block:
        return Decision(MODE_NORMAL, block, "storage")
    return Decision(MODE_NORMAL, f"{_waiting_text(rule, s, above_for)} {text}", "idle")


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
