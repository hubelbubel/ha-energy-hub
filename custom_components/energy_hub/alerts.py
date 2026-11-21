"""Auffälligkeiten und Benachrichtigungen für Energy Hub.

Wie logic.py bewusst frei von Home-Assistant-Importen: Der Regler übergibt Messwerte
und den bisherigen Zustand, dieses Modul sagt, was auffällig ist und welche Meldung
rausgeht. Getestet in tests/test_alerts.py.
"""
from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import hashlib
from typing import Any

from .logic import MODE_LABEL, RAISED, fmt_num

# Umfang der Benachrichtigung
LEVEL_ISSUES = "issues"  # nur Auffälligkeiten und Fehler
LEVEL_ALL = "all"  # dazu jeder Eintrag im Logbuch (Debug)
LEVELS = (LEVEL_ISSUES, LEVEL_ALL)

# Takten: mehr Starts als so viele in einer Stunde, oder ein Lauf kürzer als so lange
CYCLE_MAX_STARTS = 3
CYCLE_WINDOW_MIN = 60
CYCLE_SHORT_MIN = 10
# Anheben ohne Wirkung: so lange angehoben, ohne dass der Verdichter läuft
NO_EFFECT_MIN = 45
# Ohne Hysterese-Entität muss das Warmwasser so weit unter dem Soll liegen
NO_EFFECT_HYST_K = 2.0
# Vorgabe wird überschrieben: öfter als so oft in einer Stunde neu gesetzt
REAPPLY_MAX = 2
REAPPLY_WINDOW_MIN = 60
# Warmwasser bleibt kalt: so lange unter dieser Temperatur; wieder in Ordnung 2 K darüber
DHW_COLD_C = 40.0
DHW_COLD_MIN = 60
DHW_WARM_AGAIN_K = 2.0
# Vergessen: Handbetrieb ohne Ende oder Automatik aus seit so vielen Stunden
FORGOTTEN_H = 12
# So lange muss ein Problem bzw. eine Störung anstehen, bevor sie gemeldet wird
PROBLEM_DELAY_MIN = 5
FAULT_DELAY_MIN = 1
# Dieselbe Meldung höchstens alle so viele Stunden; Takten höchstens einmal am Tag
REPEAT_H = 6
# Nach dem Start keine „wieder in Ordnung“, solange die Sensoren noch hochkommen
START_GRACE_MIN = 5
# Erledigte Meldungen werden so lange gemerkt (für die Wiederholsperre)
FORGET_H = 26

# Zustände, die „keine Störung“ bzw. „keine Sperre“ bedeuten (zusätzlich jede Zahl 0)
FAULT_OK = frozenset(
    {"kein fehler", "keine störung", "keine", "kein", "ok", "none", "no error", "off", "normal", "false"}
)
LOCK_FREE = frozenset({"keine", "kein", "none", "off", "false"})


def _minutes(since: datetime | None, now: datetime) -> float:
    return 0.0 if since is None else max(0.0, (now - since).total_seconds() / 60)


def fmt_duration(minutes: float) -> str:
    """42 -> '42 min', 130 -> '2 h 10 min', 720 -> '12 h'."""
    total = max(1, round(minutes))
    if total < 60:
        return f"{total} min"
    hours, rest = divmod(total, 60)
    return f"{hours} h {rest} min" if rest else f"{hours} h"


def fmt_c(value: float) -> str:
    return fmt_num(value, "°C")


def _is_zero(text: str) -> bool:
    try:
        return float(text) == 0
    except ValueError:
        return False


# --------------------------------------------------------------------- Verdichter
@dataclass(frozen=True)
class Runs:
    """Läufe des Verdichters aus den Messungen alle 30 s.

    running: läuft gerade (None = noch nichts gemessen); since: Beginn des laufenden
    Laufs, None, wenn er schon vor der ersten Messung lief; starts: Starts der letzten
    Stunde; last_on: zuletzt laufend gesehen; last_run_min und last_end: Dauer und Ende
    des letzten ganz gesehenen Laufs; watched_since: erste Messung seit dem Start.
    """

    running: bool | None = None
    since: datetime | None = None
    starts: tuple[datetime, ...] = ()
    last_on: datetime | None = None
    last_run_min: float | None = None
    last_end: datetime | None = None
    watched_since: datetime | None = None


def track_runs(runs: Runs, now: datetime, running: bool | None) -> Runs:
    """Nächster Stand nach einer Messung. None (kein Wert) ändert nichts."""
    window = timedelta(minutes=CYCLE_WINDOW_MIN)
    starts = tuple(t for t in runs.starts if now - t < window)
    if running is None:
        return replace(runs, starts=starts)
    if runs.running is None:
        return replace(
            runs, running=running, since=None, starts=starts,
            last_on=now if running else runs.last_on, watched_since=runs.watched_since or now,
        )
    if running and not runs.running:
        return replace(runs, running=True, since=now, starts=(*starts, now), last_on=now)
    if not running and runs.running:
        if runs.since is None:
            return replace(runs, running=False, starts=starts, last_run_min=None)
        return replace(
            runs, running=False, since=None, starts=starts,
            last_run_min=_minutes(runs.since, now), last_end=now,
        )
    return replace(runs, starts=starts, last_on=now if running else runs.last_on)


def cycling_text(runs: Runs, now: datetime) -> str | None:
    """Taktet die Wärmepumpe? Zu viele Starts in einer Stunde oder ein kurzer Lauf."""
    window = timedelta(minutes=CYCLE_WINDOW_MIN)
    starts = sum(1 for t in runs.starts if now - t < window)
    many = starts > CYCLE_MAX_STARTS
    short = (
        runs.last_run_min is not None
        and runs.last_end is not None
        and runs.last_run_min < CYCLE_SHORT_MIN
        and now - runs.last_end < window
    )
    if not (many or short):
        return None
    parts = []
    if many:
        parts.append(f"{starts} Verdichterstarts in der letzten Stunde")
    if short:
        parts.append(f"der letzte Lauf dauerte nur {fmt_duration(runs.last_run_min or 0)}")
    return "Die Wärmepumpe taktet: " + ", ".join(parts) + "."


def no_effect_text(
    *,
    mode: str,
    mode_since: datetime | None,
    now: datetime,
    dry_run: bool,
    runs: Runs,
    dhw_c: float | None,
    dhw_target_c: float | None,
    hyst_k: float | None,
    locked: bool,
) -> str | None:
    """Angehoben, aber der Verdichter läuft nicht an, obwohl das Warmwasser Wärme braucht.

    Gezählt wird ab dem Anheben bzw. ab der ersten Messung nach einem Neustart. Keine
    Meldung im Probebetrieb (es wird ja nichts gesendet) und nicht, solange eine Sperre
    der Wärmepumpe ansteht.
    """
    if mode not in RAISED or dry_run or mode_since is None or locked:
        return None
    if runs.running is not False or runs.watched_since is None:
        return None
    if runs.last_on is not None and runs.last_on >= mode_since:
        return None
    minutes = _minutes(max(mode_since, runs.watched_since), now)
    if minutes < NO_EFFECT_MIN or dhw_c is None or dhw_target_c is None:
        return None
    gap = NO_EFFECT_HYST_K if hyst_k is None else hyst_k
    if dhw_c > dhw_target_c - gap:
        return None
    return (
        f"Seit {fmt_duration(minutes)} steht „{MODE_LABEL[mode]}“, der Verdichter ist aber nicht "
        f"angelaufen, obwohl das Warmwasser mit {fmt_c(dhw_c)} unter dem Soll von {fmt_c(dhw_target_c)} "
        "liegt. Die Wärmepumpe setzt die Vorgabe wohl nicht um."
    )


# ------------------------------------------------------------------ weitere Prüfungen
def heater_texts(names: Sequence[str], mode: str, dry_run: bool) -> tuple[str, str]:
    """Meldung und Satz für „wieder aus“, wenn Heizstab oder 2. Wärmeerzeuger laufen."""
    both = len(names) > 1
    who = " und ".join(names)
    where = f"Energy Hub steht auf „{MODE_LABEL[mode]}“"
    if dry_run:
        where += ", im Probebetrieb nur protokolliert"
    if both:
        return f"{who} laufen. {where}.", f"{who} sind wieder aus"
    return f"Der {who} läuft. {where}.", f"Der {who} ist wieder aus"


def reapply_text(times: Sequence[datetime], now: datetime) -> str | None:
    """Ging die Vorgabe zu oft verloren? Dann stellt etwas anderes dagegen."""
    window = timedelta(minutes=REAPPLY_WINDOW_MIN)
    count = sum(1 for t in times if now - t < window)
    if count <= REAPPLY_MAX:
        return None
    return (
        f"Die Vorgabe ging in der letzten Stunde {count}× an der Wärmepumpe verloren und wurde neu "
        "gesetzt. Vermutlich stellt etwas anderes dagegen, etwa das Zeitprogramm der Wärmepumpe "
        "oder eine andere Automation."
    )


def fault_text(state: str | None) -> str | None:
    """Störung aus einem Fehlercode (0 = keine), Text oder binary_sensor; None = keine."""
    if state is None:
        return None
    text = state.strip()
    low = text.casefold()
    if not text or low in FAULT_OK or _is_zero(text):
        return None
    if low == "on":
        return "Die Wärmepumpe meldet eine Störung."
    try:
        return f"Die Wärmepumpe meldet eine Störung, Fehlercode {float(text):g}."
    except ValueError:
        return f"Die Wärmepumpe meldet eine Störung: {text}."


def locked(state: str | None) -> bool:
    """Steht eine Sperre der Wärmepumpe an? Ohne Wert: nein."""
    if state is None:
        return False
    text = state.strip()
    return bool(text) and text.casefold() not in LOCK_FREE and not _is_zero(text)


def cold_since(since: datetime | None, dhw_c: float | None, now: datetime) -> datetime | None:
    """Seit wann das Warmwasser unter 40 °C liegt. Einmal lange kalt, gilt es erst ab 42 °C als warm."""
    if dhw_c is None:
        return since
    long = since is not None and _minutes(since, now) >= DHW_COLD_MIN
    if dhw_c >= DHW_COLD_C + (DHW_WARM_AGAIN_K if long else 0):
        return None
    return since or now


def cold_text(since: datetime | None, dhw_c: float | None, now: datetime) -> str | None:
    minutes = _minutes(since, now)
    if since is None or minutes < DHW_COLD_MIN:
        return None
    now_text = f" (jetzt {fmt_c(dhw_c)})" if dhw_c is not None else ""
    return f"Das Warmwasser liegt seit {fmt_duration(minutes)} unter {fmt_c(DHW_COLD_C)}{now_text}."


def override_text(mode: str, since: datetime | None, until: datetime | None, now: datetime) -> str | None:
    """Handbetrieb ohne Ende, der schon lange läuft."""
    minutes = _minutes(since, now)
    if until is not None or since is None or minutes < FORGOTTEN_H * 60:
        return None
    return f"Der Handbetrieb „{MODE_LABEL[mode]}“ läuft seit {fmt_duration(minutes)} und endet nicht von selbst."


def automation_off_text(since: datetime | None, now: datetime) -> str | None:
    minutes = _minutes(since, now)
    if since is None or minutes < FORGOTTEN_H * 60:
        return None
    return f"Die Automatik ist seit {fmt_duration(minutes)} aus. Energy Hub regelt so lange nicht."


# ----------------------------------------------------------------------- Meldungen
@dataclass(frozen=True)
class Issue:
    """Etwas Auffälliges, das gerade ansteht.

    ok: Satz für „wieder in Ordnung“; leer bei einmaligen Ereignissen wie dem Takten.
    since: seit wann es ansteht (None = jetzt); delay_min: so lange muss es anstehen;
    daily: höchstens einmal am Tag statt alle 6 h.
    """

    key: str
    title: str
    text: str
    ok: str = ""
    since: datetime | None = None
    delay_min: float = 0
    daily: bool = False


@dataclass(frozen=True)
class Message:
    """Eine Benachrichtigung. issue: Auffälligkeit oder Fehler, sonst ein Eintrag im Logbuch."""

    title: str
    text: str
    issue: bool
    key: str | None = None
    end: bool = False


def _recent(memo: dict[str, Any], now: datetime, daily: bool) -> bool:
    at = datetime.fromisoformat(memo["at"])
    if daily:
        return at.astimezone(now.tzinfo).date() == now.date()
    return now - at < timedelta(hours=REPEAT_H)


def step_issues(
    issues: Sequence[Issue],
    memory: dict[str, dict[str, Any]],
    now: datetime,
    *,
    unknown: Collection[str] = (),
    quiet_end: bool = False,
) -> tuple[list[Message], dict[str, dict[str, Any]]]:
    """Welche Meldungen rausgehen, und das neue Gedächtnis dazu.

    Eine Auffälligkeit wird einmal gemeldet, sobald sie lange genug ansteht, und einmal
    mit „wieder in Ordnung“, wenn sie vorbei ist. Dieselbe kommt höchstens alle 6 h
    (daily: einmal am Tag). unknown: Schlüssel, deren Sensor gerade keinen Wert hat;
    die gelten weder als neu noch als vorbei. quiet_end: noch keine „wieder in Ordnung“
    (kurz nach dem Start). Das Gedächtnis ist JSON-tauglich und übersteht Neustarts.
    """
    memory = {key: dict(memo) for key, memo in memory.items()}
    out: list[Message] = []
    active = {issue.key for issue in issues}
    for issue in issues:
        memo = memory.get(issue.key)
        if memo and memo.get("open"):
            continue
        since = issue.since or now
        if _minutes(since, now) < issue.delay_min:
            continue
        if memo and _recent(memo, now, issue.daily):
            continue
        out.append(Message(issue.title, issue.text, True, issue.key))
        memory[issue.key] = {
            "at": now.isoformat(), "open": bool(issue.ok), "ok": issue.ok, "since": since.isoformat(),
        }
    for key, memo in list(memory.items()):
        if key in active or key in unknown:
            continue
        if memo.get("open"):
            if quiet_end:
                continue
            since = datetime.fromisoformat(memo["since"])
            out.append(Message(
                "Wieder in Ordnung", f"{memo['ok']} (nach {fmt_duration(_minutes(since, now))}).",
                True, key, end=True,
            ))
            memo["open"] = False
        elif now - datetime.fromisoformat(memo["at"]) > timedelta(hours=FORGET_H):
            del memory[key]
    return out, memory


def entry_title(kind: str, mode_from: str | None, mode_to: str | None) -> str:
    """Überschrift eines Logbuch-Eintrags, wie im Panel (entryTitle)."""
    if kind == "switch":
        if mode_to == "strong":
            return "Stark angehoben"
        if mode_to == "boost":
            return "Zurück auf Anheben" if mode_from == "strong" else "Angehoben"
        if mode_to == "setback":
            return "Abgesenkt"
        if mode_from in RAISED:
            return "Anheben beendet"
        return "Absenken beendet" if mode_from == "setback" else "Normalbetrieb"
    return {
        "override": "Handbetrieb", "automation": "Automatik", "error": "Fehler", "reapply": "Erneut gesetzt",
        "dhw_start": "Warmwasser nachladen", "dhw_end": "Nachladen beendet",
        "alert": "Auffällig", "alert_end": "Wieder in Ordnung",
    }.get(kind, "Hinweis")


def log_message(kind: str, text: str, mode_from: str | None, mode_to: str | None,
                result: str | None, detail: str | None) -> Message:
    """Benachrichtigung zu einem Logbuch-Eintrag (nur beim Umfang „alles“)."""
    if result == "simulated":
        text += " (Probebetrieb, nicht gesendet)"
    elif result == "failed" and detail:
        text += f" Grund: {detail}"
    return Message(entry_title(kind, mode_from, mode_to), text, issue=False)


def wanted(message: Message, level: str) -> bool:
    """Geht die Meldung bei diesem Umfang raus?"""
    return message.issue or level == LEVEL_ALL


def tag(key: str) -> str:
    """Kennung für die Companion-App: Die Meldung „wieder in Ordnung“ ersetzt die Warnung."""
    simple = key.replace("_", "").isalnum() and key.isascii() and len(key) <= 24
    return f"energy_hub_{key}" if simple else f"energy_hub_{hashlib.sha1(key.encode()).hexdigest()[:10]}"
