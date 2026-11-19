"""Erkennung der Tigo-Optimierer aus dem Entitätsregister (tigo.py, ohne Home Assistant)."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

_PATH = Path(__file__).parents[1] / "custom_components" / "energy_hub" / "tigo.py"
_SPEC = importlib.util.spec_from_file_location("energy_hub_tigo", _PATH)
tigo = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = tigo  # dataclasses schlägt das Modul dort nach
_SPEC.loader.exec_module(tigo)

ENTRY = "01JTIGOENTRY0000000000000A"
Ent = tigo.RegistryEntity


def panel(label: str, key: str, entry: str = ENTRY, **kw) -> tigo.RegistryEntity:
    slug = label.lower().replace(" ", "_").replace("-", "_")
    return Ent(f"sensor.panel_{slug}_{key}", f"{entry}_{label}_{key}", entry, **kw)


def test_unique_id_wird_vom_ende_her_gelesen():
    assert tigo.parse_unique_id(f"{ENTRY}_A1_power", ENTRY) == ("panel", "A1", "power")
    assert tigo.parse_unique_id(f"{ENTRY}_A1_energy_today", ENTRY) == ("panel", "A1", "energy_today")
    assert tigo.parse_unique_id(f"{ENTRY}_Dach links 3_voltage_in", ENTRY) == ("panel", "Dach links 3", "voltage_in")
    assert tigo.parse_unique_id(f"{ENTRY}_group_string:A_energy_total", ENTRY) == ("group", "string:A", "energy_total")
    assert tigo.parse_unique_id(f"{ENTRY}_group_installation_power", ENTRY) == ("group", "installation", "power")
    assert tigo.parse_unique_id(f"ANDERER_A1_power", ENTRY) is None
    assert tigo.parse_unique_id(f"{ENTRY}_power", ENTRY) is None
    assert tigo.parse_unique_id(f"{ENTRY}_A1_unbekannt", ENTRY) is None


def test_string_aus_dem_label_wie_tigo_rs485():
    assert tigo.guess_string("A1") == "A"
    assert tigo.guess_string("Süd-12") == "Süd"
    assert tigo.guess_string("Dach links 3") == "Dach links"
    assert tigo.guess_string("17") is None
    assert tigo.guess_string("Ost") is None


def test_layout_mit_strings_aus_den_optionen_und_natuerlicher_reihenfolge():
    ents = [
        *(panel(label, key) for label in ("A10", "A2", "A1", "B1") for key in ("power", "voltage_in", "energy_today")),
        panel("A1", "rssi", disabled=True),
        Ent("sensor.tigo_string_a_power", f"{ENTRY}_group_string:A_power", ENTRY),
        Ent("sensor.tigo_installation_energy_today", f"{ENTRY}_group_installation_energy_today", ENTRY),
        Ent("sensor.fremd", "irgendwas", "andere_integration"),
    ]
    layout = tigo.build_layout([(ENTRY, {"strings": {"A1": "A", "A2": "A", "A10": "A", "B1": "Ost"}})], ents)
    assert [p["label"] for p in layout["panels"]] == ["A1", "A2", "A10", "B1"]
    assert [p["string"] for p in layout["panels"]] == ["A", "A", "A", "Ost"]
    assert layout["panels"][0]["entities"] == {
        "power": "sensor.panel_a1_power",
        "voltage_in": "sensor.panel_a1_voltage_in",
        "energy_today": "sensor.panel_a1_energy_today",
    }
    assert [s["name"] for s in layout["strings"]] == ["A", "Ost"]
    assert layout["strings"][0]["entities"] == {"power": "sensor.tigo_string_a_power"}
    assert layout["strings"][1]["entities"] == {}
    assert layout["installation"] == {"energy_today": "sensor.tigo_installation_energy_today"}


def test_ohne_option_strings_wird_der_string_geraten_und_leere_zuordnung_bleibt_leer():
    ents = [panel("A1", "power"), panel("X", "power")]
    assert [p["string"] for p in tigo.build_layout([(ENTRY, {})], ents)["panels"]] == ["A", None]
    # Mit gespeicherter Option, aber ohne Eintrag für das Label: kein String
    layout = tigo.build_layout([(ENTRY, {"strings": {"X": "B"}})], ents)
    assert {p["label"]: p["string"] for p in layout["panels"]} == {"A1": None, "X": "B"}
    # Optimierer ohne String stehen am Ende
    assert [p["label"] for p in layout["panels"]] == ["X", "A1"]


def test_ohne_tigo_integration_bleibt_alles_leer():
    layout = tigo.build_layout([], [panel("A1", "power")])
    assert layout == {"panels": [], "strings": [], "installation": {}}
