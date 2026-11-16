#!/usr/bin/env python3
"""Erzeugt translations/de.json und en.json.

Einrichtung (config) und Einstellungen (options) zeigen dieselben Formulare.
Damit die Texte nicht doppelt gepflegt werden, stehen sie hier einmal.
Aufruf:  python3 dev/build_translations.py
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).parents[1] / "custom_components" / "wp_leitstand" / "translations"

DE = {
    "steps": {
        "heatpump": {
            "title": "Wärmepumpe",
            "description": "Welche Entitäten zeigen die Werte der Wärmepumpe? Die Vorschläge passen zu packages/dimplex_wpm.yaml. Leere Felder werden im Panel weggelassen.",
            "data": {
                "ent_flow": "Vorlauftemperatur",
                "ent_return": "Rücklauftemperatur",
                "ent_return_target": "Rücklauf-Solltemperatur",
                "ent_dhw": "Warmwassertemperatur",
                "ent_dhw_target": "Warmwasser-Solltemperatur",
                "ent_outdoor": "Außentemperatur",
                "ent_status": "Betriebsstatus (Text)",
                "ent_compressor": "Verdichter läuft",
                "ent_power_el": "Elektrische Leistung",
                "ent_power_heat": "Heizleistung",
            },
            "data_description": {
                "ent_outdoor": "Wird auch für die Bedingung „nicht absenken, wenn es zu kalt ist“ benutzt.",
                "ent_dhw": "Wird auch für die Bedingung „nicht absenken, wenn das Warmwasser zu kalt ist“ benutzt.",
            },
        },
        "pv": {
            "title": "Photovoltaik",
            "description": "Nach diesen Werten richtet sich die Regelung. Ohne Überschuss-Sensor bleibt die Heizung im Normalbetrieb.",
            "data": {
                "ent_pv_surplus": "PV-Überschuss",
                "surplus_sign": "Vorzeichen des Sensors",
                "ent_forecast_today": "PV-Prognose für den Rest des heutigen Tages",
                "ent_forecast_tomorrow": "PV-Prognose für morgen",
            },
            "data_description": {
                "ent_pv_surplus": "Leistung in W oder kW, die gerade übrig ist, zum Beispiel die Einspeisung am Netzanschluss.",
                "ent_forecast_today": "Energie in kWh oder Wh, zum Beispiel aus Solcast oder Forecast.Solar. Wird für das Absenken am Morgen gebraucht.",
                "ent_forecast_tomorrow": "Wird nur angezeigt.",
            },
        },
        "storage": {
            "title": "Kamin und Speicher",
            "description": "Für Anlagen mit wasserführendem Kamin und einem Speicher, aus dem sich die Heizung bedient. Alles ist freiwillig; ohne Speicher bleibt dieser Schritt leer.",
            "data": {
                "ent_storage": "Temperatur im Speicher",
                "storage_ready_c": "Speicher gilt als bereit ab",
                "storage_blocks_boost": "Nicht anheben, solange der Speicher bereit ist",
                "ent_lock": "Sperre der Wärmepumpe (Text oder Code)",
                "lock_regen_value": "Wert der Sperre, wenn der Speicher Wärme liefert",
                "ent_fireplace": "Temperatur am Kamin",
                "fireplace_on_c": "Kamin gilt als an ab",
                "ent_fireplace_status": "Status des Kamins (Text)",
            },
            "data_description": {
                "ent_storage": "Bei Dimplex der Fühler R13 im regenerativen Speicher.",
                "storage_blocks_boost": "Im Smart-Grid-Zustand Grün entlädt eine Dimplex den Speicher nicht. Ohne diese Regel liefe die Wärmepumpe, obwohl Wärme vom Kamin da ist.",
                "ent_lock": "Daran wird erkannt, wann und wie oft Wärme aus dem Speicher geholt wurde.",
                "lock_regen_value": "Bei Dimplex „Regenerativ“ (Text) oder 14 (Code). Mehrere Werte mit Komma trennen.",
                "ent_fireplace": "Zum Beispiel die Abgastemperatur („Exhaust temperature“) einer Spartherm S-Thermatik NEO.",
                "fireplace_on_c": "Liegt die Temperatur am Kamin darüber, gilt er als brennend.",
            },
        },
        "rules": {
            "title": "Regeln",
            "description": "Angehoben wird, wenn genug eigener Strom übrig ist. Abgesenkt wird morgens, wenn die Prognose später genug Sonne verspricht.",
            "data": {
                "boost_on_w": "Anheben ab Überschuss",
                "boost_on_min": "… wenn er so lange anliegt",
                "boost_off_w": "Anheben beenden unter",
                "boost_off_min": "… wenn er so lange darunter liegt",
                "min_hold_min": "Mindesthaltezeit je Zustand",
                "setback_enabled": "Morgens absenken, wenn Sonne vorhergesagt ist",
                "setback_start": "Absenkfenster von",
                "setback_end": "Absenkfenster bis",
                "setback_min_forecast_kwh": "Absenken ab Prognose (Rest heute)",
                "setback_min_outdoor_c": "Nicht absenken unter Außentemperatur",
                "setback_min_dhw_c": "Nicht absenken unter Warmwassertemperatur",
            },
            "data_description": {
                "min_hold_min": "Schützt den Verdichter vor häufigem Umschalten. Handbetrieb und fehlende Messwerte wirken sofort.",
                "setback_min_outdoor_c": "Feld leeren, um die Bedingung abzuschalten.",
                "setback_min_dhw_c": "Feld leeren, um die Bedingung abzuschalten.",
            },
        },
        "actuator": {
            "title": "Eingriff an der Wärmepumpe",
            "description": "Womit wird angehoben und abgesenkt? Im Probebetrieb wird nur protokolliert, was die Regelung tun würde.",
            "data": {
                "actuator": "Stellgröße",
                "ent_smart_grid": "Smart-Grid-Auswahl",
                "opt_normal": "Option für Normalbetrieb",
                "opt_boost": "Option für Anheben",
                "opt_setback": "Option für Absenken",
                "ent_shift": "Parallelverschiebung",
                "shift_boost_k": "Anheben um",
                "shift_setback_k": "Absenken um",
            },
            "data_description": {
                "ent_smart_grid": "Auswahl-Entität, die den Smart-Grid-Zustand der Wärmepumpe schreibt.",
                "opt_normal": "Muss genau so heißen wie in der Auswahl-Entität.",
                "ent_shift": "Zahl-Entität für die Parallelverschiebung der Heizkurve. Der Wert vor dem Eingriff wird gemerkt und danach wiederhergestellt.",
            },
        },
        "export": {
            "title": "Effizienz und Export",
            "description": "Zähler und Zusatzheizungen für die Effizienz-Auswertung, dazu weitere Sensoren, die in den Verlauf-Export aufgenommen werden. Alles ist freiwillig; was fehlt, bleibt im Export leer.",
            "data": {
                "ent_energy_el": "Stromzähler der Wärmepumpe",
                "ent_energy_heat": "Wärmemenge Heizen",
                "ent_energy_dhw": "Wärmemenge Warmwasser",
                "ent_energy_env": "Umweltenergie",
                "ent_heater": "Heizstab oder Flanschheizung läuft",
                "ent_second_heat": "Zweiter Wärmeerzeuger läuft",
                "export_extra": "Weitere Sensoren für den Verlauf-Export",
            },
            "data_description": {
                "ent_energy_el": "Zählerstand in kWh, zum Beispiel von einem eigenen Stromzähler. Ohne Zähler wird der Strom aus der elektrischen Leistung aufsummiert.",
                "ent_energy_heat": "Zählerstand in kWh aus dem Wärmemengenzähler.",
                "export_extra": "Zum Beispiel Statuscodes, Sollwerte, Laufzeiten oder Pumpen.",
            },
        },
    },
    "menu_title": "WP Leitstand einstellen",
    "errors": {
        "thresholds": "Die Schwelle zum Beenden muss unter der Schwelle zum Anheben liegen.",
        "entity_required": "Für diese Stellgröße wird eine Entität gebraucht.",
    },
    "abort": {"single_instance_allowed": "WP Leitstand ist bereits eingerichtet."},
    "selector": {
        "surplus_sign": {
            "options": {
                "surplus_positive": "Positiv bedeutet Überschuss",
                "export_negative": "Negativ bedeutet Einspeisung (Netzleistungs-Sensor)",
            }
        },
        "actuator": {
            "options": {
                "dry_run": "Probebetrieb: nur protokollieren",
                "smart_grid": "Smart Grid (SG Ready) der Wärmepumpe",
                "parallel_shift": "Parallelverschiebung der Heizkurve",
            }
        },
        "mode": {"options": {"normal": "Normalbetrieb", "boost": "Anheben", "setback": "Absenken"}},
    },
    "entity": {
        "sensor": {
            "mode": {
                "name": "Regelzustand",
                "state": {"normal": "Normalbetrieb", "boost": "Angehoben", "setback": "Abgesenkt"},
            }
        },
        "switch": {"automation": {"name": "Automatik"}},
    },
    "services": {
        "set_override": {
            "name": "Handbetrieb starten",
            "description": "Hält die Heizung unabhängig von den Regeln in einem Zustand.",
            "fields": {
                "mode": {"name": "Zustand", "description": "Normalbetrieb, Anheben oder Absenken."},
                "minutes": {
                    "name": "Dauer",
                    "description": "Leer lassen, damit der Handbetrieb bis zum Beenden gilt.",
                },
            },
        },
        "clear_override": {
            "name": "Handbetrieb beenden",
            "description": "Übergibt die Heizung wieder an die Automatik.",
        },
    },
}

EN = {
    "steps": {
        "heatpump": {
            "title": "Heat pump",
            "description": "Which entities carry the heat pump values? The suggestions match packages/dimplex_wpm.yaml. Empty fields are left out of the panel.",
            "data": {
                "ent_flow": "Flow temperature",
                "ent_return": "Return temperature",
                "ent_return_target": "Return target temperature",
                "ent_dhw": "Hot water temperature",
                "ent_dhw_target": "Hot water target temperature",
                "ent_outdoor": "Outdoor temperature",
                "ent_status": "Operating status (text)",
                "ent_compressor": "Compressor running",
                "ent_power_el": "Electrical power",
                "ent_power_heat": "Heat output",
            },
            "data_description": {
                "ent_outdoor": "Also used for the condition \"do not lower when it is too cold\".",
                "ent_dhw": "Also used for the condition \"do not lower when the hot water is too cold\".",
            },
        },
        "pv": {
            "title": "Photovoltaics",
            "description": "The control follows these values. Without a surplus sensor the heating stays in normal operation.",
            "data": {
                "ent_pv_surplus": "PV surplus",
                "surplus_sign": "Sign of the sensor",
                "ent_forecast_today": "PV forecast for the rest of today",
                "ent_forecast_tomorrow": "PV forecast for tomorrow",
            },
            "data_description": {
                "ent_pv_surplus": "Power in W or kW that is currently left over, for example the grid export.",
                "ent_forecast_today": "Energy in kWh or Wh, for example from Solcast or Forecast.Solar. Needed for lowering in the morning.",
                "ent_forecast_tomorrow": "Display only.",
            },
        },
        "storage": {
            "title": "Fireplace and storage tank",
            "description": "For systems with a water-jacket fireplace and a storage tank the heating draws from. Everything is optional; without a tank leave this step empty.",
            "data": {
                "ent_storage": "Temperature in the storage tank",
                "storage_ready_c": "Tank counts as ready from",
                "storage_blocks_boost": "Do not raise while the tank is ready",
                "ent_lock": "Heat pump lock (text or code)",
                "lock_regen_value": "Lock value while the tank supplies heat",
                "ent_fireplace": "Temperature at the fireplace",
                "fireplace_on_c": "Fireplace counts as on from",
                "ent_fireplace_status": "Fireplace status (text)",
            },
            "data_description": {
                "ent_storage": "With Dimplex the sensor R13 in the renewable storage tank.",
                "storage_blocks_boost": "In smart grid state green a Dimplex does not discharge the tank. Without this rule the heat pump would run although heat from the fireplace is available.",
                "ent_lock": "Used to detect when and how often heat was drawn from the tank.",
                "lock_regen_value": "With Dimplex \"Regenerativ\" (text) or 14 (code). Separate several values with commas.",
                "ent_fireplace": "For example the exhaust temperature of a Spartherm S-Thermatik NEO.",
                "fireplace_on_c": "Above this temperature the fireplace counts as burning.",
            },
        },
        "rules": {
            "title": "Rules",
            "description": "The heating is raised when enough own power is left over. It is lowered in the morning when the forecast promises enough sun later.",
            "data": {
                "boost_on_w": "Raise from surplus",
                "boost_on_min": "… once it has lasted",
                "boost_off_w": "Stop raising below",
                "boost_off_min": "… once it has stayed below for",
                "min_hold_min": "Minimum hold time per state",
                "setback_enabled": "Lower in the morning when sun is forecast",
                "setback_start": "Lowering window from",
                "setback_end": "Lowering window until",
                "setback_min_forecast_kwh": "Lower from forecast (rest of today)",
                "setback_min_outdoor_c": "Do not lower below outdoor temperature",
                "setback_min_dhw_c": "Do not lower below hot water temperature",
            },
            "data_description": {
                "min_hold_min": "Protects the compressor from frequent switching. Manual mode and missing readings apply immediately.",
                "setback_min_outdoor_c": "Clear the field to switch the condition off.",
                "setback_min_dhw_c": "Clear the field to switch the condition off.",
            },
        },
        "actuator": {
            "title": "Action on the heat pump",
            "description": "What is used to raise and lower? In trial mode the control only logs what it would do.",
            "data": {
                "actuator": "Actuator",
                "ent_smart_grid": "Smart grid select",
                "opt_normal": "Option for normal operation",
                "opt_boost": "Option for raising",
                "opt_setback": "Option for lowering",
                "ent_shift": "Parallel shift",
                "shift_boost_k": "Raise by",
                "shift_setback_k": "Lower by",
            },
            "data_description": {
                "ent_smart_grid": "Select entity that writes the smart grid state of the heat pump.",
                "opt_normal": "Must be spelled exactly as in the select entity.",
                "ent_shift": "Number entity for the parallel shift of the heating curve. The value before the action is remembered and restored afterwards.",
            },
        },
        "export": {
            "title": "Efficiency and export",
            "description": "Meters and auxiliary heaters for the efficiency analysis, plus further sensors to include in the history export. Everything is optional; whatever is missing stays empty in the export.",
            "data": {
                "ent_energy_el": "Electricity meter of the heat pump",
                "ent_energy_heat": "Heat quantity heating",
                "ent_energy_dhw": "Heat quantity hot water",
                "ent_energy_env": "Environmental energy",
                "ent_heater": "Immersion or flange heater running",
                "ent_second_heat": "Second heat generator running",
                "export_extra": "Further sensors for the history export",
            },
            "data_description": {
                "ent_energy_el": "Meter reading in kWh, for example from a dedicated electricity meter. Without a meter the electricity is summed from the electrical power.",
                "ent_energy_heat": "Meter reading in kWh from the heat meter.",
                "export_extra": "For example status codes, setpoints, runtimes or pumps.",
            },
        },
    },
    "menu_title": "Configure WP Leitstand",
    "errors": {
        "thresholds": "The threshold to stop must be below the threshold to raise.",
        "entity_required": "This actuator needs an entity.",
    },
    "abort": {"single_instance_allowed": "WP Leitstand is already set up."},
    "selector": {
        "surplus_sign": {
            "options": {
                "surplus_positive": "Positive means surplus",
                "export_negative": "Negative means export (grid power sensor)",
            }
        },
        "actuator": {
            "options": {
                "dry_run": "Trial mode: log only",
                "smart_grid": "Smart grid (SG Ready) of the heat pump",
                "parallel_shift": "Parallel shift of the heating curve",
            }
        },
        "mode": {"options": {"normal": "Normal operation", "boost": "Raise", "setback": "Lower"}},
    },
    "entity": {
        "sensor": {
            "mode": {
                "name": "Control state",
                "state": {"normal": "Normal operation", "boost": "Raised", "setback": "Lowered"},
            }
        },
        "switch": {"automation": {"name": "Automatic control"}},
    },
    "services": {
        "set_override": {
            "name": "Start manual mode",
            "description": "Holds the heating in one state regardless of the rules.",
            "fields": {
                "mode": {"name": "State", "description": "Normal operation, raise or lower."},
                "minutes": {
                    "name": "Duration",
                    "description": "Leave empty to keep manual mode until it is ended.",
                },
            },
        },
        "clear_override": {
            "name": "End manual mode",
            "description": "Hands the heating back to the automatic control.",
        },
    },
}


def build(src: dict) -> dict:
    steps = src["steps"]
    return {
        "config": {
            "step": {
                "user": steps["heatpump"],
                "pv": steps["pv"],
                "storage": steps["storage"],
                "rules": steps["rules"],
                "actuator": steps["actuator"],
                "export": steps["export"],
            },
            "error": src["errors"],
            "abort": src["abort"],
        },
        "options": {
            "step": {
                "init": {
                    "title": src["menu_title"],
                    "menu_options": {key: step["title"] for key, step in steps.items()},
                },
                **steps,
            },
            "error": src["errors"],
        },
        "selector": src["selector"],
        "entity": src["entity"],
        "services": src["services"],
    }


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for lang, src in (("de", DE), ("en", EN)):
        path = OUT / f"{lang}.json"
        path.write_text(json.dumps(build(src), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("geschrieben:", path.relative_to(OUT.parents[2]))
