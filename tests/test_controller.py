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
    """Frischer Regler um 12:00 Uhr mit 0 W Überschuss."""
    fake_ha.Store.saved = None
    CLOCK.now = CLOCK.now.replace(year=2026, month=11, day=16, hour=12, minute=0, second=0)
    hass = fake_ha.HomeAssistant()
    hass.states.set(SURPLUS, 0, unit_of_measurement="W")
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

        hass.states.set(SURPLUS, 50)
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

        hass.states.set(SURPLUS, 0)
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
        assert ctrl.mode == "normal"  # Sicherheitsfall wirkt sofort
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
        assert snap["version"] == "0.2.0"
        json.dumps(snap)

    asyncio.run(run())
