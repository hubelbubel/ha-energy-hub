"""Einrichtung und Einstellungen für Energy Hub."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import const as c

STEP_HEATPUMP = "heatpump"
STEP_POWER = "power"
STEP_PV = "pv"
STEP_INVERTER = "inverter"
STEP_STORAGE = "storage"
STEP_RULES = "rules"
STEP_ACTUATOR = "actuator"
STEP_EXPORT = "export"


def _entity(*domains: str) -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=list(domains)))


def _number(
    low: float, high: float, step: float, unit: str | None = None
) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=low,
            max=high,
            step=step,
            unit_of_measurement=unit,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _select(options: tuple[str, ...], translation_key: str) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=list(options),
            translation_key=translation_key,
            mode=selector.SelectSelectorMode.LIST,
        )
    )


# Felder je Schritt: (Schlüssel, Selector, Pflichtfeld)
FIELDS: dict[str, list[tuple[str, Any, bool]]] = {
    STEP_HEATPUMP: [
        (c.CONF_ENT_FLOW, _entity("sensor"), False),
        (c.CONF_ENT_RETURN, _entity("sensor"), False),
        (c.CONF_ENT_RETURN_TARGET, _entity("sensor"), False),
        (c.CONF_ENT_DHW, _entity("sensor"), False),
        (c.CONF_ENT_DHW_TARGET, _entity("sensor"), False),
        (c.CONF_ENT_OUTDOOR, _entity("sensor"), False),
        (c.CONF_ENT_STATUS, _entity("sensor"), False),
        (c.CONF_ENT_COMPRESSOR, _entity("binary_sensor"), False),
        (c.CONF_ENT_POWER_EL, _entity("sensor"), False),
        (c.CONF_ENT_POWER_HEAT, _entity("sensor"), False),
    ],
    STEP_POWER: [
        (c.CONF_ENT_GRID, _entity("sensor"), False),
        (
            c.CONF_GRID_SIGN,
            _select((c.GRID_IMPORT_POSITIVE, c.GRID_EXPORT_POSITIVE), "grid_sign"),
            True,
        ),
        (c.CONF_ENT_PV, _entity("sensor"), False),
        (c.CONF_ENT_BATTERY, _entity("sensor"), False),
        (
            c.CONF_BATTERY_SIGN,
            _select((c.BATTERY_DISCHARGE_POSITIVE, c.BATTERY_CHARGE_POSITIVE), "battery_sign"),
            True,
        ),
        (c.CONF_ENT_BATTERY_SOC, _entity("sensor"), False),
        (c.CONF_ENT_HOUSE, _entity("sensor"), False),
        (c.CONF_ENT_WALLBOX, _entity("sensor"), False),
        (
            c.CONF_CONSUMERS,
            selector.EntitySelector(selector.EntitySelectorConfig(domain=["sensor"], multiple=True)),
            False,
        ),
    ],
    STEP_PV: [
        (c.CONF_ENT_SURPLUS, _entity("sensor"), False),
        (
            c.CONF_SURPLUS_SIGN,
            _select((c.SIGN_SURPLUS_POSITIVE, c.SIGN_EXPORT_NEGATIVE), "surplus_sign"),
            True,
        ),
        (c.CONF_ENT_FORECAST_TODAY, _entity("sensor"), False),
        (c.CONF_ENT_FORECAST_TOMORROW, _entity("sensor"), False),
    ],
    STEP_INVERTER: [
        (c.CONF_ENT_INV_STATUS, _entity("sensor"), False),
        (c.CONF_ENT_MPPT1_POWER, _entity("sensor"), False),
        (c.CONF_ENT_MPPT1_VOLTAGE, _entity("sensor"), False),
        (c.CONF_ENT_MPPT1_CURRENT, _entity("sensor"), False),
        (c.CONF_ENT_MPPT2_POWER, _entity("sensor"), False),
        (c.CONF_ENT_MPPT2_VOLTAGE, _entity("sensor"), False),
        (c.CONF_ENT_MPPT2_CURRENT, _entity("sensor"), False),
        (c.CONF_ENT_PV_ENERGY_TODAY, _entity("sensor"), False),
        (c.CONF_ENT_PV_ENERGY_TOTAL, _entity("sensor"), False),
        (c.CONF_ENT_LOAD_ENERGY_TODAY, _entity("sensor"), False),
        (c.CONF_ENT_LOAD_ENERGY_TOTAL, _entity("sensor"), False),
        (c.CONF_ENT_IMPORT_ENERGY_TODAY, _entity("sensor"), False),
        (c.CONF_ENT_IMPORT_ENERGY_TOTAL, _entity("sensor"), False),
        (c.CONF_ENT_EXPORT_ENERGY_TODAY, _entity("sensor"), False),
        (c.CONF_ENT_EXPORT_ENERGY_TOTAL, _entity("sensor"), False),
        (c.CONF_ENT_GRID_FREQUENCY, _entity("sensor"), False),
        (c.CONF_TIGO_MPPT1, selector.TextSelector(), False),
        (c.CONF_TIGO_MPPT2, selector.TextSelector(), False),
    ],
    STEP_STORAGE: [
        (c.CONF_ENT_STORAGE, _entity("sensor"), False),
        (c.CONF_STORAGE_READY_DELTA_K, _number(2, 20, 0.5, "K"), True),
        (c.CONF_STORAGE_READY_C, _number(10, 95, 0.5, "°C"), True),
        (c.CONF_STORAGE_BLOCKS_BOOST, selector.BooleanSelector(), True),
        (c.CONF_ENT_LOCK, _entity("sensor"), False),
        (c.CONF_LOCK_REGEN_VALUE, selector.TextSelector(), True),
        (c.CONF_ENT_FIREPLACE, _entity("sensor"), False),
        (c.CONF_FIREPLACE_ON_C, _number(20, 600, 1, "°C"), True),
        (c.CONF_ENT_FIREPLACE_STATUS, _entity("sensor"), False),
    ],
    STEP_RULES: [
        (c.CONF_BOOST_ON_W, _number(0, 20000, 50, "W"), True),
        (c.CONF_BOOST_ON_MIN, _number(0, 120, 1, "min"), True),
        (c.CONF_BOOST_OFF_W, _number(-5000, 20000, 50, "W"), True),
        (c.CONF_BOOST_OFF_MIN, _number(0, 120, 1, "min"), True),
        (c.CONF_MIN_HOLD_MIN, _number(0, 240, 1, "min"), True),
        (c.CONF_SETBACK_ENABLED, selector.BooleanSelector(), True),
        (c.CONF_SETBACK_START, selector.TimeSelector(), True),
        (c.CONF_SETBACK_END, selector.TimeSelector(), True),
        (c.CONF_SETBACK_MIN_FORECAST, _number(0, 200, 0.5, "kWh"), True),
        (c.CONF_SETBACK_MIN_OUTDOOR, _number(-30, 30, 0.5, "°C"), False),
        (c.CONF_SETBACK_MIN_DHW, _number(20, 70, 0.5, "°C"), False),
    ],
    STEP_ACTUATOR: [
        (c.CONF_ACTUATOR, _select(c.ACTUATORS, "actuator"), True),
        (c.CONF_ENT_SMART_GRID, _entity("select"), False),
        (c.CONF_OPT_NORMAL, selector.TextSelector(), True),
        (c.CONF_OPT_BOOST, selector.TextSelector(), True),
        (c.CONF_OPT_SETBACK, selector.TextSelector(), True),
        (c.CONF_ENT_SHIFT, _entity("number"), False),
        (c.CONF_SHIFT_BOOST_K, _number(0, 10, 1, "K"), True),
        (c.CONF_SHIFT_SETBACK_K, _number(0, 10, 1, "K"), True),
    ],
    STEP_EXPORT: [
        (c.CONF_ENT_ENERGY_EL, _entity("sensor"), False),
        (c.CONF_ENT_ENERGY_HEAT, _entity("sensor"), False),
        (c.CONF_ENT_ENERGY_DHW, _entity("sensor"), False),
        (c.CONF_ENT_ENERGY_ENV, _entity("sensor"), False),
        (c.CONF_ENT_HEATER, _entity("binary_sensor"), False),
        (c.CONF_ENT_SECOND_HEAT, _entity("binary_sensor"), False),
        (
            c.CONF_EXPORT_EXTRA,
            selector.EntitySelector(selector.EntitySelectorConfig(multiple=True)),
            False,
        ),
    ],
}


def _existing_only(suggestion: Any, existing: set[str] | None) -> Any:
    """Vorschlag nur, wenn es die Entität gibt; bei Listen nur die vorhandenen."""
    if existing is None or suggestion is None:
        return suggestion
    if isinstance(suggestion, list):
        return [entity_id for entity_id in suggestion if entity_id in existing] or None
    return suggestion if suggestion in existing else None


def build_schema(
    step: str, values: dict[str, Any], *, initial: bool, existing: set[str] | None = None
) -> vol.Schema:
    """Formular eines Schritts mit Vorschlägen für die Entitäten.

    existing: vorhandene Entitäten. Vorgeschlagen wird nur, was es in diesem Home Assistant
    gibt; wer keine Dimplex-Wärmepumpe oder keinen Azzurro hat, bekommt leere Felder.
    Bei der Ersteinrichtung gilt das für alle Schritte. Der Schritt „Wechselrichter“ kam
    erst mit 0.5 dazu; wer schon eingerichtet ist, bekommt dort beim ersten Öffnen die
    Vorschläge. Sobald ein Feld belegt ist, gilt nur noch das Gespeicherte.
    """
    schema: dict[Any, Any] = {}
    fresh = (
        existing is not None
        and step == STEP_INVERTER
        and not any(key in values for key, _sel, _req in FIELDS[step])
    )
    for key, sel, required in FIELDS[step]:
        suggestion = _existing_only(c.SUGGESTED_ENTITIES.get(key), existing)
        if key in values:
            current = values[key]
        elif initial:
            current = c.DEFAULTS.get(key, suggestion)
        elif fresh and isinstance(suggestion, str):
            current = suggestion
        else:
            current = c.DEFAULTS.get(key) if required else None
        if required:
            schema[vol.Required(key, default=current)] = sel
        else:
            schema[vol.Optional(key, description={"suggested_value": current})] = sel
    return vol.Schema(schema)


def merge_step(step: str, values: dict[str, Any], user_input: dict[str, Any]) -> dict[str, Any]:
    """Übernimmt einen Schritt vollständig: geleerte Felder verschwinden."""
    keys = {key for key, _sel, _req in FIELDS[step]}
    merged = {k: v for k, v in values.items() if k not in keys}
    merged.update({k: v for k, v in user_input.items() if v not in (None, "", [])})
    return merged


def validate_step(step: str, data: dict[str, Any]) -> dict[str, str]:
    """Prüfungen über mehrere Felder."""
    errors: dict[str, str] = {}
    if step == STEP_RULES and data[c.CONF_BOOST_OFF_W] >= data[c.CONF_BOOST_ON_W]:
        errors["base"] = "thresholds"
    if step == STEP_ACTUATOR:
        actuator = data[c.CONF_ACTUATOR]
        if actuator == c.ACT_SMART_GRID and not data.get(c.CONF_ENT_SMART_GRID):
            errors[c.CONF_ENT_SMART_GRID] = "entity_required"
        if actuator == c.ACT_SHIFT and not data.get(c.CONF_ENT_SHIFT):
            errors[c.CONF_ENT_SHIFT] = "entity_required"
    return errors


class EnergyHubConfigFlow(ConfigFlow, domain=c.DOMAIN):
    """Ersteinrichtung in acht Schritten."""

    VERSION = 1

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}

    async def _step(
        self, step: str, step_id: str, user_input: dict[str, Any] | None, next_step: str | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = validate_step(step, user_input)
            if not errors:
                self._values = merge_step(step, self._values, user_input)
                if next_step is None:
                    return self.async_create_entry(title=c.TITLE, data={}, options=self._values)
                return await getattr(self, f"async_step_{next_step}")()
        values = {**self._values, **(user_input or {})}
        return self.async_show_form(
            step_id=step_id,
            data_schema=build_schema(
                step, values, initial=user_input is None, existing=set(self.hass.states.async_entity_ids())
            ),
            errors=errors,
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_HEATPUMP, "user", user_input, STEP_POWER)

    async def async_step_power(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_POWER, STEP_POWER, user_input, STEP_PV)

    async def async_step_pv(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_PV, STEP_PV, user_input, STEP_INVERTER)

    async def async_step_inverter(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_INVERTER, STEP_INVERTER, user_input, STEP_STORAGE)

    async def async_step_storage(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_STORAGE, STEP_STORAGE, user_input, STEP_RULES)

    async def async_step_rules(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_RULES, STEP_RULES, user_input, STEP_ACTUATOR)

    async def async_step_actuator(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_ACTUATOR, STEP_ACTUATOR, user_input, STEP_EXPORT)

    async def async_step_export(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_EXPORT, STEP_EXPORT, user_input, None)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EnergyHubOptionsFlow()


class EnergyHubOptionsFlow(OptionsFlow):
    """Einstellungen nachträglich ändern."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                STEP_HEATPUMP,
                STEP_POWER,
                STEP_PV,
                STEP_INVERTER,
                STEP_STORAGE,
                STEP_RULES,
                STEP_ACTUATOR,
                STEP_EXPORT,
            ],
        )

    async def _step(self, step: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = dict(self.config_entry.options)
        if user_input is not None:
            errors = validate_step(step, user_input)
            if not errors:
                return self.async_create_entry(data=merge_step(step, current, user_input))
        values = {**current, **(user_input or {})}
        existing = None if user_input is not None else set(self.hass.states.async_entity_ids())
        return self.async_show_form(
            step_id=step,
            data_schema=build_schema(step, values, initial=False, existing=existing),
            errors=errors,
        )

    async def async_step_heatpump(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_HEATPUMP, user_input)

    async def async_step_power(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_POWER, user_input)

    async def async_step_pv(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_PV, user_input)

    async def async_step_inverter(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_INVERTER, user_input)

    async def async_step_storage(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_STORAGE, user_input)

    async def async_step_rules(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_RULES, user_input)

    async def async_step_actuator(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_ACTUATOR, user_input)

    async def async_step_export(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_EXPORT, user_input)
