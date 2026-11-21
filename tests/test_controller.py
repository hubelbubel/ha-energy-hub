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


# --- Stark anheben, Wärmepumpe herausrechnen, Akku, Probleme ----------------

POWER_EL = "sensor.wp_elektrische_leistung"
SOC = "sensor.akku_ladestand"
SG_STRONG = [*SG_OPTIONS, "Verstärkt Stufe 3 (dunkelgrün)"]


def test_strong_raise_and_step_back():
    async def run():
        hass, ctrl = make(
            c.ACT_SMART_GRID,
            **{c.CONF_ENT_BATTERY: BATTERY, c.CONF_BATTERY_SIGN: c.BATTERY_DISCHARGE_POSITIVE,
               c.CONF_ENT_POWER_EL: POWER_EL, c.CONF_BOOST_ON_LEARNED: False},
        )
        hass.states.set(SG, "Hardware-Eingang", options=SG_STRONG)
        hass.states.set(BATTERY, 0, unit_of_measurement="W")
        hass.states.set(POWER_EL, 40, unit_of_measurement="W")
        await ctrl.async_start()
        hass.states.set(SURPLUS, 4600, unit_of_measurement="W")
        await sunny_until_boost(hass, ctrl)
        assert ctrl.mode == "boost"

        # Die Wärmepumpe zieht 2.000 W, trotzdem bleiben 2.600 W übrig: nach 10 min und der Haltezeit stark anheben
        hass.states.set(POWER_EL, 2000)
        hass.states.set(SURPLUS, 2600)
        await tick(ctrl, 1)
        assert ctrl.snapshot()["state"]["strong_since"] is not None
        await tick(ctrl, 10)
        assert ctrl.mode == "boost" and ctrl.snapshot()["state"]["rule"] == "hold"
        await tick(ctrl, 10)
        assert ctrl.mode == "strong"
        assert hass.states.get(SG).state == "Verstärkt Stufe 3 (dunkelgrün)"
        assert ctrl.snapshot()["log"][0]["text"].startswith("Trotz Anheben sind seit")

        # Stark angehoben zieht sie 3.500 W, der Akku muss mit 900 W stützen: zurück auf Grün
        hass.states.set(POWER_EL, 3500)
        hass.states.set(SURPLUS, 0)
        hass.states.set(BATTERY, 900)
        await tick(ctrl, 1)
        await tick(ctrl, 20)
        assert ctrl.mode == "boost"
        assert hass.states.get(SG).state == "Verstärkter Betrieb (grün)"
        assert ctrl.snapshot()["log"][0]["text"].endswith("nötig 1.500 W).")

        # Auch einfach angehoben stützt der Akku: Normalbetrieb
        hass.states.set(POWER_EL, 2000)
        await tick(ctrl, 20)
        assert ctrl.mode == "normal"
        titles = [(e["from"], e["to"]) for e in ctrl.snapshot()["log"] if e["kind"] == "switch"]
        assert titles[:3] == [("boost", "normal"), ("strong", "boost"), ("boost", "strong")]

    asyncio.run(run())


def test_strong_falls_back_to_boost_option_and_shift_steps():
    async def run():
        hass, ctrl = make(c.ACT_SMART_GRID)  # Auswahl ohne Dunkelgrün
        await ctrl.async_start()
        await ctrl.async_set_override("strong", None)
        assert ctrl.mode == "strong"
        assert hass.states.get(SG).state == "Verstärkter Betrieb (grün)"
        assert "gibt es nicht" in ctrl.snapshot()["log"][0]["detail"]
        await tick(ctrl, 10)
        assert log_kinds(ctrl)[0][0] != "reapply"  # Grün gilt als richtig gesetzt

        hass, ctrl = make(c.ACT_SHIFT)
        await ctrl.async_start()
        await ctrl.async_set_override("boost", None)
        assert float(hass.states.get(SHIFT).state) == 3  # Grundwert 1 + 2 K
        await ctrl.async_set_override("strong", None)
        assert float(hass.states.get(SHIFT).state) == 5  # Grundwert 1 + 4 K
        await ctrl.async_clear_override()
        await tick(ctrl, 21)
        assert ctrl.mode == "normal" and float(hass.states.get(SHIFT).state) == 1

    asyncio.run(run())


def test_running_heat_pump_counts_as_available_and_its_draw_is_learned():
    async def run():
        hass, ctrl = make(c.ACT_DRY_RUN, **{c.CONF_ENT_POWER_EL: POWER_EL})
        hass.states.set(POWER_EL, 1.2, unit_of_measurement="kW")
        await ctrl.async_start()
        # Die Wärmepumpe läuft normal mit 1.200 W, eingespeist werden 100 W: zusammen unter 1.500 W
        hass.states.set(SURPLUS, 100)
        await every_30s(ctrl, 25)
        state = ctrl.snapshot()["state"]
        assert state["inputs"]["available_w"] == 1300
        assert state["learned"]["run_w"] is None  # erst nach 30 min Laufzeit
        assert ctrl.mode == "normal" and state["above_since"] is None
        await every_30s(ctrl, 6)
        state = ctrl.snapshot()["state"]
        assert state["learned"]["run_w"] == 1200  # jetzt reicht es: die PV trägt die Wärmepumpe
        assert state["on"] == {
            "value_w": 1300, "threshold_w": 1200, "available": True, "learned": True,
            "battery_fills": False, "battery_missing_kwh": None,
        }
        await every_30s(ctrl, 10)
        assert ctrl.mode == "boost"
        entry = ctrl.snapshot()["log"][0]
        assert entry["text"].startswith("Für die Wärmepumpe sind seit 10 min mehr als 1.200 W übrig")
        assert entry["text"].endswith("So viel zieht die Wärmepumpe im Lauf.")
        assert entry["values"]["available_w"] == 1300

        # Umwälzpumpe allein zählt nicht zum Lernen; das Gelernte übersteht einen Neustart
        hass.states.set(POWER_EL, 0.08)
        await every_30s(ctrl, 5)
        minutes = ctrl.snapshot()["state"]["learned"]["run_min"]
        await ctrl.async_stop()
        again = controller_mod.Controller(hass, ctrl.entry)
        await again.async_start()
        assert again.run_w == 1200 and again.snapshot()["state"]["learned"]["run_min"] == minutes

    asyncio.run(run())


def test_battery_capacity_is_learned_and_lends_its_charge():
    async def run():
        hass, ctrl = make(
            c.ACT_DRY_RUN,
            **{c.CONF_ENT_BATTERY: BATTERY, c.CONF_BATTERY_SIGN: c.BATTERY_CHARGE_POSITIVE,
               c.CONF_ENT_BATTERY_SOC: SOC, c.CONF_ENT_POWER_EL: POWER_EL},
        )
        hass.states.set(POWER_EL, 40, unit_of_measurement="W")
        hass.states.set(BATTERY, 2000, unit_of_measurement="W")  # lädt mit 2 kW
        hass.states.set(SURPLUS, 0)
        hass.states.set(FORECAST, 2, unit_of_measurement="kWh")
        await ctrl.async_start()
        # 10-kWh-Akku: 2 kW heben den Ladestand um 20 % je Stunde
        start = CLOCK.now
        for _ in range(130):
            hours = (CLOCK.now - start).total_seconds() / 3600
            hass.states.set(SOC, round(30 + hours * 20))
            await tick(ctrl, 0.5)
        learned = ctrl.snapshot()["state"]["learned"]
        assert learned["battery_n"] >= 1 and abs(learned["battery_kwh"] - 10) <= 0.5
        assert ctrl.mode == "normal"  # der Akku lädt zuerst, die Prognose reicht nicht

        # Viel Sonne angesagt: dem Akku fehlen bei 70 % rund 3 kWh, vorhergesagt sind 12 kWh
        hass.states.set(SOC, 70)
        hass.states.set(FORECAST, 12)
        await tick(ctrl, 0.5)
        state = ctrl.snapshot()["state"]
        assert state["on"]["battery_fills"] is True and state["on"]["value_w"] == 2040
        assert state["inputs"]["available_w"] == 40
        await tick(ctrl, 10)
        assert ctrl.mode == "boost"
        assert "Der Akku wird heute ohnehin voll" in ctrl.snapshot()["log"][0]["text"]

    asyncio.run(run())


def test_problems_are_listed():
    async def run():
        hass, ctrl = make(c.ACT_SMART_GRID, **{c.CONF_ENT_POWER_EL: POWER_EL, c.CONF_ENT_OUTDOOR: OUTDOOR})
        hass.states.set(POWER_EL, 500, unit_of_measurement="W")
        await ctrl.async_start()
        await tick(ctrl)
        assert ctrl.problems == []

        hass.services.fail = True
        await sunny_until_boost(hass, ctrl)
        assert any("nicht angenommen: Modbus antwortet nicht" in p for p in ctrl.problems)
        hass.services.fail = False
        await tick(ctrl, 6)
        assert ctrl.mode == "boost" and ctrl.problems == []

        hass.states.set(SURPLUS, "unavailable")
        hass.states.set(SG, "unavailable")
        hass.states.set(POWER_EL, "unavailable")
        hass.states.set(OUTDOOR, "unknown")
        hass.states.set(DHW, "unavailable")
        hass.states.set(FORECAST, "unavailable")
        await tick(ctrl, 4)
        problems = ctrl.snapshot()["state"]["problems"]
        assert problems == [
            "Die Wärmepumpe hat die letzte Vorgabe nicht angenommen: select.wp_smart_grid_setzen ist nicht verfügbar.",
            "Der PV-Überschuss (sensor.pv_ueberschuss) liefert keinen Wert.",
            "Die Stellgröße (select.wp_smart_grid_setzen) ist nicht verfügbar.",
            "Die Wärmepumpe meldet keine Werte.",
            "Die PV-Prognose (sensor.pv_prognose) liefert keinen Wert.",
        ]

    asyncio.run(run())


# --- Warmwasser nachladen ---------------------------------------------------

DHW_TARGET = "sensor.wp_warmwasser_soll_aktuell"
DHW_HYST = "number.wp_warmwasser_hysterese_setzen"
STATUS = "sensor.wp_status"


def make_reload(actuator=c.ACT_SMART_GRID):
    hass, ctrl = make(
        actuator,
        **{c.CONF_ENT_DHW_TARGET: DHW_TARGET, c.CONF_ENT_DHW_HYST: DHW_HYST, c.CONF_ENT_STATUS: STATUS,
           c.CONF_ENT_POWER_EL: POWER_EL, c.CONF_BOOST_ON_LEARNED: False},
    )
    CLOCK.now = CLOCK.now.replace(hour=17, minute=0)
    hass.states.set("sun.sun", "above_horizon", rising=False)
    hass.states.set(DHW, 52)
    hass.states.set(DHW_TARGET, 58)
    hass.states.set(DHW_HYST, 7, min=1, max=15)
    hass.states.set(STATUS, "Aus")
    hass.states.set(POWER_EL, 40, unit_of_measurement="W")
    hass.states.set(SURPLUS, 1900)  # 1.940 W übrig: zwischen 1.500 W und 2.250 W
    return hass, ctrl


def test_reload_lowers_the_hysteresis_and_restores_it():
    async def run():
        hass, ctrl = make_reload()
        await ctrl.async_start()
        await tick(ctrl)
        assert ctrl.snapshot()["state"]["dhw_reload"]["wait"] == "übrig zwischen 1.500 W und 2.250 W, seit 0 min"
        await tick(ctrl, 10)
        assert float(hass.states.get(DHW_HYST).state) == 2
        entry = next(e for e in ctrl.snapshot()["log"] if e["kind"] == "dhw_start")
        assert entry["text"].startswith("Die Sonne lässt nach")
        assert entry["detail"] == f"{DHW_HYST} → 2 K (vorher 7 K)"
        state = ctrl.snapshot()["state"]["dhw_reload"]
        assert state["active_since"] is not None and state["hyst_base"] == 7

        # Die Wärmepumpe lädt, das Warmwasser erreicht den Soll: Hysterese zurück
        hass.states.set(STATUS, "Warmwasser")
        hass.states.set(DHW, 57.6)
        await tick(ctrl, 30)
        assert float(hass.states.get(DHW_HYST).state) == 7
        end = ctrl.snapshot()["log"][0]
        assert (end["kind"], end["detail"]) == ("dhw_end", f"{DHW_HYST} → 7 K")
        assert end["text"] == "Das Warmwasser hat 57,6 °C erreicht (Soll 58,0 °C)."

        # Höchstens einmal am Tag
        hass.states.set(STATUS, "Aus")
        hass.states.set(DHW, 50)
        await tick(ctrl, 20)
        assert float(hass.states.get(DHW_HYST).state) == 7
        assert ctrl.snapshot()["state"]["dhw_reload"]["wait"] == "heute schon nachgeladen"
        assert [e["kind"] for e in ctrl.snapshot()["log"]].count("dhw_start") == 1

    asyncio.run(run())


def test_reload_survives_a_restart_and_retries_the_restore():
    async def run():
        hass, ctrl = make_reload()
        await ctrl.async_start()
        await tick(ctrl)
        await tick(ctrl, 10)
        assert float(hass.states.get(DHW_HYST).state) == 2
        await ctrl.async_stop()

        # Neustart nach zwei Stunden, Modbus antwortet zunächst nicht
        CLOCK.advance(minutes=120)
        again = controller_mod.Controller(hass, ctrl.entry)
        await again.async_start()
        hass.services.fail = True
        await tick(again)
        assert float(hass.states.get(DHW_HYST).state) == 2
        assert any("Warmwasser-Hysterese ließ sich nicht setzen" in p for p in again.problems)
        assert again.snapshot()["state"]["dhw_reload"]["hyst_base"] == 7
        hass.services.fail = False
        await tick(again, 2)
        assert float(hass.states.get(DHW_HYST).state) == 2  # nächster Versuch erst nach 5 min
        await tick(again, 4)
        assert float(hass.states.get(DHW_HYST).state) == 7
        assert again.problems == [] and again.snapshot()["state"]["dhw_reload"]["hyst_base"] is None
        kinds = [e["kind"] for e in again.snapshot()["log"]]
        assert kinds[:3] == ["reapply", "dhw_end", "error"]  # neueste zuerst

    asyncio.run(run())


def test_reload_in_dry_run_and_without_sun_integration():
    async def run():
        hass, ctrl = make_reload(c.ACT_DRY_RUN)
        hass.states.set("sun.sun", "unavailable")  # ohne Sonnenstand gilt ab 13 Uhr als Nachmittag
        await ctrl.async_start()
        await tick(ctrl)
        await tick(ctrl, 10)
        assert float(hass.states.get(DHW_HYST).state) == 7  # nichts geschrieben
        entry = ctrl.snapshot()["log"][0]
        assert (entry["kind"], entry["result"]) == ("dhw_start", "simulated")
        hass.states.set(DHW, 58)
        await tick(ctrl)
        assert ctrl.snapshot()["log"][0]["kind"] == "dhw_end"

        # vormittags (Sonne steigt) wird nicht nachgeladen
        hass, ctrl = make_reload()
        hass.states.set("sun.sun", "above_horizon", rising=True)
        await ctrl.async_start()
        await tick(ctrl)
        await tick(ctrl, 10)
        assert ctrl.snapshot()["state"]["dhw_reload"]["wait"] == "erst nach Mittag"

    asyncio.run(run())
