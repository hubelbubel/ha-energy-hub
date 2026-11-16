"""Konstanten für WP Leitstand."""
from __future__ import annotations

from .logic import MODE_BOOST, MODE_NORMAL, MODE_SETBACK

DOMAIN = "wp_leitstand"
VERSION = "0.2.0"
TITLE = "WP Leitstand"

PANEL_URL_PATH = "wp-leitstand"
PANEL_COMPONENT = "wp-leitstand-panel"
PANEL_TITLE = "Wärmepumpe"
PANEL_ICON = "mdi:heat-pump-outline"
STATIC_URL = "/wp_leitstand_static"

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.state"
LOG_LIMIT = 500
EVALUATE_SECONDS = 30
REAPPLY_MINUTES = 5

# Regelzustände (definiert in logic.py, damit die Logik ohne HA testbar bleibt)
MODES = (MODE_NORMAL, MODE_BOOST, MODE_SETBACK)

# Stellgröße
ACT_DRY_RUN = "dry_run"
ACT_SMART_GRID = "smart_grid"
ACT_SHIFT = "parallel_shift"
ACTUATORS = (ACT_DRY_RUN, ACT_SMART_GRID, ACT_SHIFT)

# Vorzeichen des Überschuss-Sensors
SIGN_SURPLUS_POSITIVE = "surplus_positive"
SIGN_EXPORT_NEGATIVE = "export_negative"

# --- Wärmepumpe: angezeigte Entitäten -------------------------------------
CONF_ENT_FLOW = "ent_flow"
CONF_ENT_RETURN = "ent_return"
CONF_ENT_RETURN_TARGET = "ent_return_target"
CONF_ENT_DHW = "ent_dhw"
CONF_ENT_DHW_TARGET = "ent_dhw_target"
CONF_ENT_OUTDOOR = "ent_outdoor"
CONF_ENT_STATUS = "ent_status"
CONF_ENT_COMPRESSOR = "ent_compressor"
CONF_ENT_POWER_EL = "ent_power_el"
CONF_ENT_POWER_HEAT = "ent_power_heat"

# --- Effizienz und Export --------------------------------------------------
CONF_ENT_ENERGY_EL = "ent_energy_el"
CONF_ENT_ENERGY_HEAT = "ent_energy_heat"
CONF_ENT_ENERGY_DHW = "ent_energy_dhw"
CONF_ENT_ENERGY_ENV = "ent_energy_env"
CONF_ENT_HEATER = "ent_heater"
CONF_ENT_SECOND_HEAT = "ent_second_heat"
CONF_EXPORT_EXTRA = "export_extra"

# --- Photovoltaik ----------------------------------------------------------
CONF_ENT_SURPLUS = "ent_pv_surplus"
CONF_SURPLUS_SIGN = "surplus_sign"
CONF_ENT_FORECAST_TODAY = "ent_forecast_today"
CONF_ENT_FORECAST_TOMORROW = "ent_forecast_tomorrow"

# --- Regeln ----------------------------------------------------------------
CONF_BOOST_ON_W = "boost_on_w"
CONF_BOOST_ON_MIN = "boost_on_min"
CONF_BOOST_OFF_W = "boost_off_w"
CONF_BOOST_OFF_MIN = "boost_off_min"
CONF_MIN_HOLD_MIN = "min_hold_min"
CONF_SETBACK_ENABLED = "setback_enabled"
CONF_SETBACK_START = "setback_start"
CONF_SETBACK_END = "setback_end"
CONF_SETBACK_MIN_FORECAST = "setback_min_forecast_kwh"
CONF_SETBACK_MIN_OUTDOOR = "setback_min_outdoor_c"
CONF_SETBACK_MIN_DHW = "setback_min_dhw_c"

# --- Stellgröße ------------------------------------------------------------
CONF_ACTUATOR = "actuator"
CONF_ENT_SMART_GRID = "ent_smart_grid"
CONF_OPT_NORMAL = "opt_normal"
CONF_OPT_BOOST = "opt_boost"
CONF_OPT_SETBACK = "opt_setback"
CONF_ENT_SHIFT = "ent_shift"
CONF_SHIFT_BOOST_K = "shift_boost_k"
CONF_SHIFT_SETBACK_K = "shift_setback_k"

# Vorschläge passend zu packages/dimplex_wpm.yaml
SUGGESTED_ENTITIES: dict[str, str | list[str]] = {
    CONF_ENT_FLOW: "sensor.wp_vorlauftemperatur",
    CONF_ENT_RETURN: "sensor.wp_rucklauftemperatur",
    CONF_ENT_RETURN_TARGET: "sensor.wp_rucklaufsolltemperatur",
    CONF_ENT_DHW: "sensor.wp_warmwassertemperatur",
    CONF_ENT_DHW_TARGET: "sensor.wp_warmwasser_soll_aktuell",
    CONF_ENT_OUTDOOR: "sensor.wp_aussentemperatur",
    CONF_ENT_STATUS: "sensor.wp_status",
    CONF_ENT_COMPRESSOR: "binary_sensor.wp_verdichter_1",
    CONF_ENT_POWER_EL: "sensor.wp_elektrische_leistung",
    CONF_ENT_POWER_HEAT: "sensor.wp_heizleistung",
    CONF_ENT_SMART_GRID: "select.wp_smart_grid_setzen",
    CONF_ENT_SHIFT: "number.wp_parallelverschiebung_setzen",
    CONF_ENT_ENERGY_HEAT: "sensor.wp_warmemenge_heizen",
    CONF_ENT_ENERGY_DHW: "sensor.wp_warmemenge_warmwasser",
    CONF_ENT_ENERGY_ENV: "sensor.wp_umweltenergie",
    CONF_ENT_HEATER: "binary_sensor.wp_flanschheizung_e9",
    CONF_ENT_SECOND_HEAT: "binary_sensor.wp_2_warmeerzeuger",
    CONF_EXPORT_EXTRA: [
        "sensor.wp_statuscode",
        "sensor.wp_sperrcode",
        "sensor.wp_fehlercode",
        "sensor.wp_betriebsmodus_code",
        "sensor.wp_smart_grid_code",
        "sensor.wp_warmwasser_solltemperatur",
        "sensor.wp_laufzeit_verdichter_1",
        "binary_sensor.wp_heizungspumpe_m13",
        "binary_sensor.wp_warmwasserpumpe_m18",
    ],
}

DEFAULTS: dict[str, object] = {
    CONF_SURPLUS_SIGN: SIGN_SURPLUS_POSITIVE,
    CONF_BOOST_ON_W: 1500,
    CONF_BOOST_ON_MIN: 10,
    CONF_BOOST_OFF_W: 300,
    CONF_BOOST_OFF_MIN: 15,
    CONF_MIN_HOLD_MIN: 20,
    CONF_SETBACK_ENABLED: True,
    CONF_SETBACK_START: "05:00:00",
    CONF_SETBACK_END: "10:00:00",
    CONF_SETBACK_MIN_FORECAST: 10,
    CONF_SETBACK_MIN_OUTDOOR: 3,
    CONF_SETBACK_MIN_DHW: 42,
    CONF_ACTUATOR: ACT_DRY_RUN,
    CONF_OPT_NORMAL: "Normalbetrieb (gelb)",
    CONF_OPT_BOOST: "Verstärkter Betrieb (grün)",
    CONF_OPT_SETBACK: "Abgesenkter Betrieb (rot)",
    CONF_SHIFT_BOOST_K: 2,
    CONF_SHIFT_SETBACK_K: 2,
}

# Felder, die leer bleiben dürfen (leer = Bedingung bzw. Anzeige entfällt)
OPTIONAL_NUMBERS = (CONF_SETBACK_MIN_OUTDOOR, CONF_SETBACK_MIN_DHW)

SERVICE_SET_OVERRIDE = "set_override"
SERVICE_CLEAR_OVERRIDE = "clear_override"
