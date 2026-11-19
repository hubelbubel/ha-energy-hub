"""Konstanten für Energy Hub."""
from __future__ import annotations

from .logic import MODE_BOOST, MODE_NORMAL, MODE_SETBACK

DOMAIN = "energy_hub"
VERSION = "0.5.0"
TITLE = "Energy Hub"

PANEL_URL_PATH = "energy-hub"
PANEL_COMPONENT = "energy-hub-panel"
PANEL_TITLE = "Energie"
PANEL_ICON = "mdi:home-lightning-bolt-outline"
STATIC_URL = "/energy_hub_static"

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

# --- Strom (nur Anzeige) ---------------------------------------------------
CONF_ENT_GRID = "ent_grid_power"
CONF_GRID_SIGN = "grid_sign"
CONF_ENT_PV = "ent_pv_power"
CONF_ENT_BATTERY = "ent_battery_power"
CONF_BATTERY_SIGN = "battery_sign"
CONF_ENT_BATTERY_SOC = "ent_battery_soc"
CONF_ENT_HOUSE = "ent_house_power"
CONF_ENT_WALLBOX = "ent_wallbox_power"
CONF_CONSUMERS = "consumers"

GRID_IMPORT_POSITIVE = "import_positive"
GRID_EXPORT_POSITIVE = "export_positive"
BATTERY_DISCHARGE_POSITIVE = "discharge_positive"
BATTERY_CHARGE_POSITIVE = "charge_positive"

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

# --- Wechselrichter und Optimierer (nur Anzeige) ----------------------------
CONF_ENT_INV_STATUS = "ent_inv_status"
CONF_ENT_MPPT1_POWER = "ent_mppt1_power"
CONF_ENT_MPPT1_VOLTAGE = "ent_mppt1_voltage"
CONF_ENT_MPPT1_CURRENT = "ent_mppt1_current"
CONF_ENT_MPPT2_POWER = "ent_mppt2_power"
CONF_ENT_MPPT2_VOLTAGE = "ent_mppt2_voltage"
CONF_ENT_MPPT2_CURRENT = "ent_mppt2_current"
CONF_ENT_GRID_FREQUENCY = "ent_grid_frequency"
CONF_ENT_PV_ENERGY_TODAY = "ent_pv_energy_today"
CONF_ENT_PV_ENERGY_TOTAL = "ent_pv_energy_total"
CONF_ENT_LOAD_ENERGY_TODAY = "ent_load_energy_today"
CONF_ENT_LOAD_ENERGY_TOTAL = "ent_load_energy_total"
CONF_ENT_IMPORT_ENERGY_TODAY = "ent_import_energy_today"
CONF_ENT_IMPORT_ENERGY_TOTAL = "ent_import_energy_total"
CONF_ENT_EXPORT_ENERGY_TODAY = "ent_export_energy_today"
CONF_ENT_EXPORT_ENERGY_TOTAL = "ent_export_energy_total"
# Welcher Tigo-String an welchem MPPT hängt; leer = automatisch
CONF_TIGO_MPPT1 = "tigo_string_mppt1"
CONF_TIGO_MPPT2 = "tigo_string_mppt2"

# Integration, aus der die Optimierer gelesen werden
TIGO_DOMAIN = "tigo_rs485"

# --- Kamin und Speicher ----------------------------------------------------
CONF_ENT_STORAGE = "ent_storage"
CONF_STORAGE_READY_DELTA_K = "storage_ready_delta_k"
CONF_STORAGE_READY_C = "storage_ready_c"
CONF_STORAGE_BLOCKS_BOOST = "storage_blocks_boost"
CONF_ENT_LOCK = "ent_lock"
CONF_LOCK_REGEN_VALUE = "lock_regen_value"
CONF_ENT_FIREPLACE = "ent_fireplace"
CONF_FIREPLACE_ON_C = "fireplace_on_c"
CONF_ENT_FIREPLACE_STATUS = "ent_fireplace_status"

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
    CONF_ENT_STORAGE: "sensor.wp_regenerativspeicher_temperatur",
    CONF_ENT_LOCK: "sensor.wp_sperre",
    CONF_ENT_ENERGY_HEAT: "sensor.wp_warmemenge_heizen",
    CONF_ENT_ENERGY_DHW: "sensor.wp_warmemenge_warmwasser",
    CONF_ENT_ENERGY_ENV: "sensor.wp_umweltenergie",
    CONF_ENT_HEATER: "binary_sensor.wp_flanschheizung_e9",
    CONF_ENT_SECOND_HEAT: "binary_sensor.wp_2_warmeerzeuger",
    # Namen aus einer Modbus-Konfiguration für ZCS Azzurro HYD (siehe README)
    CONF_ENT_INV_STATUS: "sensor.azzurro_status",
    CONF_ENT_MPPT1_POWER: "sensor.pv_power",
    CONF_ENT_MPPT1_VOLTAGE: "sensor.azzurro_pv1_spannung",
    CONF_ENT_MPPT1_CURRENT: "sensor.azzurro_pv1_strom",
    CONF_ENT_MPPT2_POWER: "sensor.azzurro_pv2_leistung",
    CONF_ENT_MPPT2_VOLTAGE: "sensor.azzurro_pv2_spannung",
    CONF_ENT_MPPT2_CURRENT: "sensor.azzurro_pv2_strom",
    CONF_ENT_GRID_FREQUENCY: "sensor.azzurro_netz_frequenz",
    CONF_ENT_PV_ENERGY_TODAY: "sensor.pv_generation_today",
    CONF_ENT_PV_ENERGY_TOTAL: "sensor.pv_generation_total",
    CONF_ENT_LOAD_ENERGY_TODAY: "sensor.azzurro_hausverbrauch_heute",
    CONF_ENT_LOAD_ENERGY_TOTAL: "sensor.azzurro_hausverbrauch_gesamt",
    CONF_ENT_IMPORT_ENERGY_TODAY: "sensor.azzurro_netzbezug_heute",
    CONF_ENT_IMPORT_ENERGY_TOTAL: "sensor.azzurro_netzbezug_gesamt",
    CONF_ENT_EXPORT_ENERGY_TODAY: "sensor.azzurro_netzeinspeisung_heute",
    CONF_ENT_EXPORT_ENERGY_TOTAL: "sensor.azzurro_netzeinspeisung_gesamt",
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
    CONF_GRID_SIGN: GRID_IMPORT_POSITIVE,
    CONF_BATTERY_SIGN: BATTERY_DISCHARGE_POSITIVE,
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
    CONF_STORAGE_READY_DELTA_K: 5,
    CONF_STORAGE_READY_C: 40,
    CONF_STORAGE_BLOCKS_BOOST: True,
    CONF_LOCK_REGEN_VALUE: "Regenerativ",
    CONF_FIREPLACE_ON_C: 80,
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
