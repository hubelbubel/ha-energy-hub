"""Abläufe im Regler gegen einen nachgebildeten Home Assistant (siehe fake_ha.py)."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fake_ha  # noqa: E402

controller_mod, c = fake_ha.install()
CLOCK = fake_ha.CLOCK

SURPLUS = "sensor.pv_ueberschuss"
FORECAST = "sensor.pv_prognose"
OUTDOOR = "sensor.wp_aussentemperatur"
DHW = "sensor.wp_warmwassertemperatur"
SG = "select.wp_smart_grid_setzen"
SHIFT = "number.wp_parallelverschiebung_setzen"
SG_OPTIONS = ["Hardware-Eingang", "Normalbetrieb (gelb)", "Verstärkter Betrieb (grün)", "Abgesenkter Betrieb (rot)"]


def make(actuator, **extra):
    """Frischer Regler um 12:00 Uhr mit 500 W Netzbezug.

    Ohne Glättung, damit die Abläufe in groben Zeitschritten lesbar bleiben; die Glättung
    prüfen eigene Tests mit einem Messwert alle 30 s.
    """
    fake_ha.Store.saved = None
    CLOCK.now = CLOCK.now.replace(year=2026, month=11, day=16, hour=12, minute=0, second=0)
    hass = fake_ha.HomeAssistant()
    hass.states.set(SURPLUS, -500, unit_of_measurement="W")
    hass.states.set(FORECAST, 14, unit_of_measurement="kWh")
    hass.states.set(OUTDOOR, 6)
    hass.states.set(DHW, 47)
    hass.states.set(SG, "Hardware-Eingang", options=SG_OPTIONS)
    hass.states.set(SHIFT, 1, min=-19, max=19)
    options = {
        **c.DEFAULTS,
        c.CONF_ENT_SURPLUS: SURPLUS,
        c.CONF_ENT_FORECAST_TODAY: FORECAST,
        c.CONF_ENT_OUTDOOR: OUTDOOR,
        c.CONF_ENT_DHW: DHW,
        c.CONF_ENT_SMART_GRID: SG,
        c.CONF_ENT_SHIFT: SHIFT,
        c.CONF_ACTUATOR: actuator,
        c.CONF_SMOOTHING_MIN: 0,
        **extra,
    }
    ctrl = controller_mod.Controller(hass, fake_ha.ConfigEntry(options))
    return hass, ctrl


async def tick(ctrl, minutes=0):
    CLOCK.advance(minutes=minutes)
    await ctrl.async_evaluate()


async def sunny_until_boost(hass, ctrl):
    """Überschuss anlegen und warten, bis Einschaltverzögerung und Haltezeit erfüllt sind."""
    await tick(ctrl, 25)  # Mindesthaltezeit des Startzustands abwarten
    hass.states.set(SURPLUS, 2400, unit_of_measurement="W")
    await tick(ctrl)
    await tick(ctrl, 10)


def log_kinds(ctrl):
    return [(e["kind"], e["to"], e["result"]) for e in ctrl.snapshot()["log"]]


def test_dry_run_logs_but_writes_nothing():
    async def run():
        hass, ctrl = make(c.ACT_DRY_RUN)
        await ctrl.async_start()
        await sunny_until_boost(hass, ctrl)
        assert ctrl.mode == "boost"
        assert hass.services.calls == []
        assert log_kinds(ctrl)[0] == ("switch", "boost", "simulated")
        assert hass.bus.events[-1][0] == "logbook_entry"
        assert "2.400 W" in hass.bus.events[-1][1]["message"]

    asyncio.run(run())


def test_smart_grid_boost_and_back():
    async def run():
        hass, ctrl = make(c.ACT_SMART_GRID)
        await ctrl.async_start()
        await sunny_until_boost(hass, ctrl)
        assert ctrl.mode == "boost"
        assert hass.states.get(SG).state == "Verstärkter Betrieb (grün)"

        hass.states.set(SURPLUS, -500)
        await tick(ctrl, 1)
        assert ctrl.mode == "boost"  # Ausschaltverzögerung läuft
        await tick(ctrl, 15)
        assert ctrl.mode == "boost"  # Mindesthaltezeit (20 min) noch nicht um
        assert ctrl.snapshot()["state"]["rule"] == "hold"
        await tick(ctrl, 5)
        assert ctrl.mode == "normal"
        assert hass.states.get(SG).state == "Normalbetrieb (gelb)"
        assert [k[:2] for k in log_kinds(ctrl)[:2]] == [("switch", "normal"), ("switch", "boost")]

    asyncio.run(run())


def test_lost_setting_is_reapplied():
    async def run():
        hass, ctrl = make(c.ACT_SMART_GRID)
        await ctrl.async_start()
        await sunny_until_boost(hass, ctrl)
        hass.states.set(SG, "Hardware-Eingang")  # z. B. Spannungsreset am WPM
        await tick(ctrl, 1)
        assert hass.states.get(SG).state == "Hardware-Eingang"  # noch innerhalb der Wartezeit
        await tick(ctrl, 5)
        assert hass.states.get(SG).state == "Verstärkter Betrieb (grün)"
        assert log_kinds(ctrl)[0][0] == "reapply"

    asyncio.run(run())


def test_failed_write_is_logged_and_retried():
    async def run():
        hass, ctrl = make(c.ACT_SMART_GRID)
        await ctrl.async_start()
        hass.services.fail = True
        await sunny_until_boost(hass, ctrl)
        assert ctrl.mode == "normal"
        snap = ctrl.snapshot()
        assert snap["log"][0]["kind"] == "error" and snap["log"][0]["result"] == "failed"
        assert "Modbus antwortet nicht" in snap["state"]["last_error"]
        errors = len(snap["log"])

        await tick(ctrl, 2)
        assert len(ctrl.snapshot()["log"]) == errors  # kein Dauerfeuer im Logbuch

        hass.services.fail = False
        await tick(ctrl, 4)
        assert ctrl.mode == "boost"
        assert ctrl.snapshot()["state"]["last_error"] is None

    asyncio.run(run())


def test_unknown_option_fails_cleanly():
    async def run():
        hass, ctrl = make(c.ACT_SMART_GRID, **{c.CONF_OPT_BOOST: "Gibt es nicht"})
        await ctrl.async_start()
        await sunny_until_boost(hass, ctrl)
        assert ctrl.mode == "normal"
        assert "Gibt es nicht" in ctrl.snapshot()["log"][0]["detail"]
        assert all(call[2]["option"] != "Gibt es nicht" for call in hass.services.calls)

    asyncio.run(run())


def test_parallel_shift_remembers_and_restores_base():
    async def run():
        hass, ctrl = make(c.ACT_SHIFT)
        await ctrl.async_start()
        await sunny_until_boost(hass, ctrl)
        assert float(hass.states.get(SHIFT).state) == 3  # Grundwert 1 + 2 K

        hass.states.set(SHIFT, 0)  # jemand verstellt den Wert am Display
        await tick(ctrl, 6)
        assert float(hass.states.get(SHIFT).state) == 3  # wird nachgeführt

        hass.states.set(SURPLUS, -500)
        await tick(ctrl, 1)
        await tick(ctrl, 20)
        assert ctrl.mode == "normal"
        assert float(hass.states.get(SHIFT).state) == 1  # Grundwert wiederhergestellt

        hass.states.set(SHIFT, -4)  # im Normalbetrieb darf der Nutzer frei verstellen
        await tick(ctrl, 10)
        assert float(hass.states.get(SHIFT).state) == -4

    asyncio.run(run())


def test_setback_in_morning_then_boost():
    async def run():
        hass, ctrl = make(c.ACT_SMART_GRID)
        CLOCK.now = CLOCK.now.replace(hour=6, minute=0)
        await ctrl.async_start()
        await tick(ctrl, 21)
        assert ctrl.mode == "setback"
        assert hass.states.get(SG).state == "Abgesenkter Betrieb (rot)"
        hass.states.set(SURPLUS, 3000)
        await tick(ctrl, 10)
        await tick(ctrl, 11)
        assert ctrl.mode == "boost"

    asyncio.run(run())


def test_override_and_automation():
    async def run():
        hass, ctrl = make(c.ACT_SMART_GRID)
        await ctrl.async_start()
        await ctrl.async_set_override("boost", 60)
        assert ctrl.mode == "boost"  # sofort, ohne Haltezeit
        await tick(ctrl, 59)
        assert ctrl.mode == "boost"
        await tick(ctrl, 2)
        assert ctrl.override is None
        await tick(ctrl, 20)
        assert ctrl.mode == "normal"

        await ctrl.async_set_override("setback", None)
        assert ctrl.mode == "setback"
        await ctrl.async_clear_override()
        await tick(ctrl, 21)
        assert ctrl.mode == "normal"

        await sunny_until_boost(hass, ctrl)
        assert ctrl.mode == "boost"
        calls = len(hass.services.calls)
        await ctrl.async_set_automation(False)
        assert ctrl.mode == "normal" and len(hass.services.calls) == calls + 1
        hass.states.set(SG, "Hardware-Eingang")
        await tick(ctrl, 30)
        assert hass.states.get(SG).state == "Hardware-Eingang"  # Automatik aus: Finger weg

    asyncio.run(run())


def test_sign_units_and_missing_sensor():
    async def run():
        hass, ctrl = make(c.ACT_DRY_RUN, **{c.CONF_SURPLUS_SIGN: c.SIGN_EXPORT_NEGATIVE})
        await ctrl.async_start()
        hass.states.set(SURPLUS, -2.4, unit_of_measurement="kW")  # Einspeisung als negativer Netzbezug
        hass.states.set(FORECAST, 14000, unit_of_measurement="Wh")
        await tick(ctrl)
        inputs = ctrl.snapshot()["state"]["inputs"]
        assert inputs["surplus_w"] == 2400 and inputs["forecast_kwh"] == 14

        await tick(ctrl, 25)
        await tick(ctrl, 10)
        assert ctrl.mode == "boost"
        hass.states.set(SURPLUS, "unavailable")
        await tick(ctrl, 1)
        assert ctrl.mode == "boost"  # kurzer Aussetzer: der letzte Wert gilt noch 3 min
        await tick(ctrl, 2.5)
        assert ctrl.mode == "normal"  # danach wirkt der Sicherheitsfall sofort
        assert ctrl.snapshot()["state"]["rule"] == "no_data"

    asyncio.run(run())


def test_state_survives_restart_and_snapshot_is_json():
    async def run():
        hass, ctrl = make(c.ACT_DRY_RUN)
        await ctrl.async_start()
        await sunny_until_boost(hass, ctrl)
        await ctrl.async_stop()
        json.dumps(ctrl.snapshot())

        again = controller_mod.Controller(hass, ctrl.entry)
        await again.async_start()
        assert again.mode == "boost" and len(again.snapshot()["log"]) == 1

    asyncio.run(run())


def test_pv_grid_is_stored_and_old_data_stays_valid():
    async def run():
        hass, ctrl = make(c.ACT_DRY_RUN)
        # Gespeichert von einer Version ohne Raster
        fake_ha.Store.saved = {"automation": True, "mode": "normal", "log": []}
        await ctrl.async_start()
        assert ctrl.pv_grid == {}

        await ctrl.async_set_pv_grid({"A1": [0, 1], "A2": [1, 0]})
        assert ctrl.snapshot()["log"] == [], "Anordnen schreibt nichts ins Logbuch"
        ctrl.pv_grid["A1"][0] = 9  # eine Kopie, der Speicher bleibt unverändert
        await ctrl.async_stop()

        again = controller_mod.Controller(hass, ctrl.entry)
        await again.async_start()
        assert again.pv_grid == {"A1": [0, 1], "A2": [1, 0]}
        json.dumps(fake_ha.Store.saved)

        await again.async_set_pv_grid({})
        assert again.pv_grid == {}

    asyncio.run(run())


def test_cleared_optional_guards_stay_off():
    hass, ctrl = make(c.ACT_DRY_RUN)
    opts = dict(ctrl.entry.options)
    del opts[c.CONF_SETBACK_MIN_OUTDOOR], opts[c.CONF_SETBACK_MIN_DHW]
    ctrl.entry.options = opts
    settings = ctrl._settings()
    assert settings.setback_min_outdoor_c is None and settings.setback_min_dhw_c is None
    assert settings.setback_start.hour == 5 and settings.boost_on_w == 1500


def test_snapshot_lists_export_entities_and_full_log():
    extra = ["sensor.wp_statuscode", "binary_sensor.wp_heizungspumpe_m13"]
    hass, ctrl = make(
        c.ACT_DRY_RUN,
        **{c.CONF_EXPORT_EXTRA: extra, c.CONF_ENT_ENERGY_HEAT: "sensor.wp_warmemenge_heizen", c.CONF_ENT_HEATER: "binary_sensor.wp_flanschheizung_e9"},
    )

    async def run():
        await ctrl.async_start()
        for i in range(c.LOG_LIMIT + 20):
            ctrl._log("info", f"Eintrag {i}")
        snap = ctrl.snapshot()
        assert snap["export_extra"] == extra
        assert snap["entities"]["ent_energy_heat"] == "sensor.wp_warmemenge_heizen"
        assert snap["entities"]["ent_heater"] == "binary_sensor.wp_flanschheizung_e9"
        assert snap["entities"]["ent_energy_el"] is None
        assert len(snap["log"]) == c.LOG_LIMIT  # das ganze Logbuch, neueste zuerst
        assert snap["log"][0]["text"] == f"Eintrag {c.LOG_LIMIT + 19}"
        assert snap["version"] == c.VERSION
        json.dumps(snap)

    asyncio.run(run())


STORAGE = "sensor.wp_regenerativspeicher_temperatur"
LOCK = "sensor.wp_sperre"
FIRE = "sensor.kamin_exhaust_temperature"


def test_ready_storage_blocks_and_ends_boost():
    async def run():
        hass, ctrl = make(
            c.ACT_SMART_GRID,
            **{c.CONF_ENT_STORAGE: STORAGE, c.CONF_ENT_LOCK: LOCK, c.CONF_ENT_FIREPLACE: FIRE},
        )
        hass.states.set(STORAGE, 55)
        hass.states.set(LOCK, "Regenerativ")
        hass.states.set(FIRE, 240)
        await ctrl.async_start()
        await sunny_until_boost(hass, ctrl)
        state = ctrl.snapshot()["state"]
        assert ctrl.mode == "normal" and state["rule"] == "storage"
        assert "55,0 °C" in state["reason"] and "40,0 °C" in state["reason"]
        assert state["storage"] == {
            "temp": 55.0, "ready": True, "ready_c": 40.0, "basis": "fixed", "drawing": True,
        }  # ohne Rücklaufsoll gilt die feste Ersatz-Schwelle
        assert state["fireplace"] == {"temp": 240.0, "on": True, "on_c": 80.0, "status": None}

        hass.states.set(STORAGE, 32)  # Speicher leer: jetzt darf angehoben werden
        hass.states.set(LOCK, "Keine")
        hass.states.set(FIRE, 31)
        await tick(ctrl, 1)
        assert ctrl.mode == "boost"
        state = ctrl.snapshot()["state"]
        assert state["storage"]["ready"] is False and state["storage"]["drawing"] is False
        assert state["fireplace"]["on"] is False

        hass.states.set(STORAGE, 48)  # Kamin hat nachgeladen: Anheben endet nach der Haltezeit
        await tick(ctrl, 5)
        assert ctrl.mode == "boost" and ctrl.snapshot()["state"]["rule"] == "hold"
        await tick(ctrl, 16)
        assert ctrl.mode == "normal"
        assert ctrl.snapshot()["log"][0]["values"]["storage_c"] == 48.0

    asyncio.run(run())


def test_storage_rule_can_be_switched_off_and_code_matches():
    async def run():
        hass, ctrl = make(
            c.ACT_DRY_RUN,
            **{
                c.CONF_ENT_STORAGE: STORAGE,
                c.CONF_STORAGE_BLOCKS_BOOST: False,
                c.CONF_ENT_LOCK: "sensor.wp_sperrcode",
                c.CONF_LOCK_REGEN_VALUE: "Regenerativ, 14",
            },
        )
        hass.states.set(STORAGE, 60)
        hass.states.set("sensor.wp_sperrcode", 14)
        await ctrl.async_start()
        await sunny_until_boost(hass, ctrl)
        assert ctrl.mode == "boost"
        assert ctrl.snapshot()["state"]["storage"]["drawing"] is True

    asyncio.run(run())


def test_without_storage_nothing_changes():
    async def run():
        hass, ctrl = make(c.ACT_DRY_RUN)
        await ctrl.async_start()
        await sunny_until_boost(hass, ctrl)
        state = ctrl.snapshot()["state"]
        assert ctrl.mode == "boost"
        assert state["storage"]["temp"] is None and state["storage"]["ready"] is None
        assert state["storage"]["drawing"] is None and state["fireplace"]["on"] is None

    asyncio.run(run())


def test_ready_follows_return_target_like_the_heat_pump_controller():
    target = "sensor.wp_rucklaufsolltemperatur"

    async def run():
        hass, ctrl = make(
            c.ACT_DRY_RUN,
            **{c.CONF_ENT_STORAGE: STORAGE, c.CONF_ENT_RETURN_TARGET: target, c.CONF_STORAGE_READY_DELTA_K: 6},
        )
        hass.states.set(target, 31.5)
        hass.states.set(STORAGE, 37)  # über der festen Ersatz-Schwelle wäre das noch nicht, hier zählt 31,5 + 6
        await ctrl.async_start()
        await tick(ctrl)
        storage = ctrl.snapshot()["state"]["storage"]
        assert storage["ready_c"] == 37.5 and storage["basis"] == "return_target" and storage["ready"] is False

        hass.states.set(STORAGE, 38)
        await sunny_until_boost(hass, ctrl)
        state = ctrl.snapshot()["state"]
        assert ctrl.mode == "normal" and state["rule"] == "storage"
        assert "37,5 °C" in state["reason"] and "Rücklaufsoll 31,5 °C plus 6,0 K" in state["reason"]

        hass.states.set(target, 45)  # kalter Tag: höherer Sollwert, derselbe Speicher reicht nicht mehr
        await tick(ctrl, 1)
        assert ctrl.snapshot()["state"]["storage"]["ready"] is False
        assert ctrl.mode == "boost"

        hass.states.set(target, "unavailable")  # Sollwert fällt aus: zurück zur Ersatz-Schwelle 40 °C
        await tick(ctrl, 1)
        storage = ctrl.snapshot()["state"]["storage"]
        assert storage["ready_c"] == 40.0 and storage["basis"] == "fixed" and storage["ready"] is False

    asyncio.run(run())


def test_snapshot_carries_power_settings():
    consumers = ["sensor.badheizung_leistung", "sensor.spuelmaschine_leistung"]
    hass, ctrl = make(
        c.ACT_DRY_RUN,
        **{
            c.CONF_ENT_GRID: "sensor.netz_leistung",
            c.CONF_ENT_PV: "sensor.pv_leistung",
            c.CONF_ENT_BATTERY: "sensor.venus_leistung",
            c.CONF_BATTERY_SIGN: c.BATTERY_CHARGE_POSITIVE,
            c.CONF_CONSUMERS: consumers,
        },
    )

    async def run():
        await ctrl.async_start()
        snap = ctrl.snapshot()
        assert snap["consumers"] == consumers
        assert snap["entities"]["ent_grid_power"] == "sensor.netz_leistung"
        assert snap["entities"]["ent_wallbox_power"] is None
        assert snap["settings"]["grid_sign"] == c.GRID_IMPORT_POSITIVE  # Standardwert
        assert snap["settings"]["battery_sign"] == c.BATTERY_CHARGE_POSITIVE
        json.dumps(snap)

    asyncio.run(run())



BATTERY = "sensor.akku_leistung"
TOMORROW = "sensor.pv_prognose_morgen"


async def every_30s(ctrl, minutes, surplus_at=None, hass=None):
    """Tickt im Takt des echten Reglers; surplus_at(i) liefert den Messwert je Takt."""
    for i in range(int(minutes * 2)):
        if surplus_at:
            hass.states.set(SURPLUS, surplus_at(i))
        await tick(ctrl, 0.5)


def test_smoothing_rides_through_clouds():
    async def run():
        # Alle 3 min zieht für 30 s eine Wolke durch: 800 W statt 2.400 W
        cloudy = lambda i: 800 if i % 6 == 5 else 2400  # noqa: E731
        hass, ctrl = make(c.ACT_DRY_RUN, **{c.CONF_SMOOTHING_MIN: 5})
        await ctrl.async_start()
        await every_30s(ctrl, 25)
        await every_30s(ctrl, 20, cloudy, hass)
        assert ctrl.mode == "boost"
        assert "-Minuten-Mittel" in ctrl.snapshot()["log"][0]["text"]

        # dieselben Wolken ohne Glättung: der Zähler beginnt bei jeder Wolke neu
        hass, ctrl = make(c.ACT_DRY_RUN)
        await ctrl.async_start()
        await every_30s(ctrl, 25)
        await every_30s(ctrl, 20, cloudy, hass)
        assert ctrl.mode == "normal"

    asyncio.run(run())


def test_boost_ends_by_surplus_without_battery():
    async def run():
        hass, ctrl = make(
            c.ACT_SMART_GRID, **{c.CONF_ENT_BATTERY: BATTERY, c.CONF_BATTERY_SIGN: c.BATTERY_DISCHARGE_POSITIVE}
        )
        hass.states.set(BATTERY, -1.0, unit_of_measurement="kW")  # lädt mit 1 kW
        await ctrl.async_start()
        await sunny_until_boost(hass, ctrl)
        assert ctrl.mode == "boost"
        assert ctrl.snapshot()["state"]["inputs"]["balance_w"] == 3400

        # Die Wärmepumpe nimmt den Überschuss, der Akku lädt noch mit 200 W: weiter anheben
        hass.states.set(SURPLUS, 0)
        hass.states.set(BATTERY, -0.2)
        await tick(ctrl, 1)
        await tick(ctrl, 30)
        assert ctrl.mode == "boost"

        # Wolke: der Akku muss mit 900 W stützen, eingespeist und bezogen wird nichts
        hass.states.set(BATTERY, 0.9)
        await tick(ctrl, 1)
        assert ctrl.snapshot()["state"]["inputs"]["balance_w"] == -900
        await tick(ctrl, 15)
        assert ctrl.mode == "normal"
        entry = ctrl.snapshot()["log"][0]
        assert "Der Überschuss ohne Akku liegt seit 15 min unter -300 W" in entry["text"]
        assert entry["values"]["balance_w"] == -900

    asyncio.run(run())


def test_battery_rule_off_or_without_battery():
    async def run():
        hass, ctrl = make(c.ACT_DRY_RUN, **{c.CONF_ENT_BATTERY: BATTERY, c.CONF_OFF_WITHOUT_BATTERY: False})
        hass.states.set(BATTERY, 900, unit_of_measurement="W")
        await ctrl.async_start()
        await tick(ctrl)
        assert ctrl.snapshot()["state"]["inputs"]["balance_w"] is None

        hass, ctrl = make(c.ACT_DRY_RUN)  # kein Akku hinterlegt
        await ctrl.async_start()
        await tick(ctrl)
        assert ctrl.snapshot()["state"]["inputs"]["balance_w"] is None
        assert ctrl.snapshot()["settings"][c.CONF_OFF_WITHOUT_BATTERY] is True

        # Akku hinterlegt, aber gerade ohne Wert: es zählt der Überschuss
        hass, ctrl = make(c.ACT_DRY_RUN, **{c.CONF_ENT_BATTERY: BATTERY})
        hass.states.set(BATTERY, "unavailable")
        await ctrl.async_start()
        await tick(ctrl)
        assert ctrl.snapshot()["state"]["inputs"]["balance_w"] == -500

    asyncio.run(run())


def test_night_setback_with_tomorrows_forecast():
    async def run():
        hass, ctrl = make(
            c.ACT_SMART_GRID,
            **{c.CONF_ENT_FORECAST_TOMORROW: TOMORROW, c.CONF_SETBACK_START: "21:00:00", c.CONF_SETBACK_END: "10:00:00"},
        )
        hass.states.set(FORECAST, 0.2, unit_of_measurement="kWh")
        hass.states.set(TOMORROW, 15000, unit_of_measurement="Wh")
        CLOCK.now = CLOCK.now.replace(hour=20, minute=30)
        await ctrl.async_start()
        await tick(ctrl, 25)  # 20:55: noch vor dem Fenster
        assert ctrl.mode == "normal"
        await tick(ctrl, 10)  # 21:05
        assert ctrl.mode == "setback"
        assert hass.states.get(SG).state == "Abgesenkter Betrieb (rot)"
        entry = ctrl.snapshot()["log"][0]
        assert entry["text"].startswith("Für morgen sind 15,0 kWh PV-Ertrag vorhergesagt.")
        assert entry["values"]["forecast_tomorrow_kwh"] == 15
        assert ctrl.snapshot()["state"]["inputs"]["forecast_tomorrow_kwh"] == 15

        # nach Mitternacht zählt die Prognose für den Tag, der jetzt begonnen hat
        hass.states.set(FORECAST, 15, unit_of_measurement="kWh")
        hass.states.set(TOMORROW, 3, unit_of_measurement="kWh")
        await tick(ctrl, 240)  # 01:05
        assert ctrl.mode == "setback"
        assert ctrl.snapshot()["state"]["reason"].startswith("Für den Rest des Tages sind 15,0 kWh")

    asyncio.run(run())
