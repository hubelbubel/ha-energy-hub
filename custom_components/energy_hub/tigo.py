"""Tigo-Optimierer aus der Integration tigo_rs485 erkennen.

Ohne Home-Assistant-Importe, damit es sich ohne HA testen lässt. Gelesen wird
das Entitätsregister: Die Integration vergibt die Unique-IDs nach festem Muster.

  Optimierer:          <entry_id>_<label>_<key>          z. B. 01J…_A1_power
  String/Installation: <entry_id>_group_<gruppe>_<key>   z. B. 01J…_group_string:A_power

Welcher String zu einem Label gehört, steht in den Optionen der Integration
("strings": {label: string}). Ältere Einträge ohne diese Option leiten den String
aus dem Label ab, so wie die Integration selbst (A1 -> A, "Süd-3" -> Süd).
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

# Sensoren eines Optimierers, wie tigo_rs485 sie anlegt
PANEL_KEYS = (
    "voltage_in",
    "voltage_out",
    "current",
    "power",
    "temperature",
    "pwm",
    "rssi",
    "energy_today",
    "energy_total",
)
GROUP_KEYS = ("power", "energy_today", "energy_total")
INSTALLATION = "installation"

# Ein Name, gefolgt von einer Zahl, z. B. A1, Süd-1 oder "Dach links 3"
_STRING_LABEL = re.compile(r"(\D*?)[\s._-]*\d+")
_NUMBER = re.compile(r"(\d+)")


def guess_string(label: str) -> str | None:
    """String zu einem Label, wie tigo_rs485 ihn vorschlägt."""
    match = _STRING_LABEL.fullmatch(label)
    if not match or not match.group(1):
        return None
    return match.group(1)


def natural_key(text: str) -> tuple:
    """A2 vor A10."""
    return tuple(int(part) if part.isdigit() else part.casefold() for part in _NUMBER.split(text))


@dataclass(frozen=True)
class RegistryEntity:
    """Das, was aus einem Eintrag des Entitätsregisters gebraucht wird."""

    entity_id: str
    unique_id: str
    config_entry_id: str
    disabled: bool = False


def parse_unique_id(unique_id: str, entry_id: str) -> tuple[str, str, str] | None:
    """('panel', label, key) oder ('group', gruppe, key); None bei fremden IDs."""
    prefix = f"{entry_id}_"
    if not unique_id.startswith(prefix):
        return None
    rest = unique_id[len(prefix):]
    if rest.startswith("group_"):
        group = rest[len("group_"):]
        for key in GROUP_KEYS:
            if group.endswith(f"_{key}"):
                return "group", group[: -len(key) - 1], key
        return None
    # Die Schlüssel enthalten selbst Unterstriche, deshalb vom Ende her lesen
    for key in sorted(PANEL_KEYS, key=len, reverse=True):
        if rest.endswith(f"_{key}") and len(rest) > len(key) + 1:
            return "panel", rest[: -len(key) - 1], key
    return None


def build_layout(
    entries: Iterable[tuple[str, dict[str, Any]]], entities: Iterable[RegistryEntity]
) -> dict[str, Any]:
    """Optimierer, Strings und Installation mit ihren Entitäten.

    entries: (entry_id, options) je Eintrag von tigo_rs485.
    Optimierer ohne Label haben keine Entitäten und tauchen deshalb nicht auf.
    """
    options = dict(entries)
    panels: dict[tuple[str, str], dict[str, Any]] = {}
    groups: dict[tuple[str, str], dict[str, str]] = {}
    for ent in entities:
        if ent.disabled or ent.config_entry_id not in options:
            continue
        parsed = parse_unique_id(ent.unique_id, ent.config_entry_id)
        if parsed is None:
            continue
        kind, name, key = parsed
        if kind == "panel":
            panel = panels.setdefault(
                (ent.config_entry_id, name), {"label": name, "entry_id": ent.config_entry_id, "entities": {}}
            )
            panel["entities"][key] = ent.entity_id
        else:
            groups.setdefault((ent.config_entry_id, name), {})[key] = ent.entity_id

    out_panels = []
    for (entry_id, label), panel in panels.items():
        strings = options[entry_id].get("strings")
        string = strings.get(label) if isinstance(strings, dict) else guess_string(label)
        out_panels.append({**panel, "string": string or None})
    out_panels.sort(key=lambda p: (p["string"] is None, natural_key(p["string"] or ""), natural_key(p["label"])))

    out_strings = []
    installation: dict[str, str] = {}
    for (_entry_id, group), ents in sorted(groups.items(), key=lambda item: natural_key(item[0][1])):
        if group == INSTALLATION:
            # Bei mehreren Busleitungen zählt die erste; die Summe rechnet das Panel selbst
            installation = installation or ents
        elif group.startswith("string:"):
            out_strings.append({"name": group[len("string:"):], "entities": ents})
    known = {s["name"] for s in out_strings}
    for panel in out_panels:
        if panel["string"] and panel["string"] not in known:
            known.add(panel["string"])
            out_strings.append({"name": panel["string"], "entities": {}})
    out_strings.sort(key=lambda s: natural_key(s["name"]))
    return {"panels": out_panels, "strings": out_strings, "installation": installation}
