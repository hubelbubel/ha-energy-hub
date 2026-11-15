"""Einrichtung und Einstellungen für WP Leitstand."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import const as c

STEP_HEATPUMP = "heatpump"
STEP_PV = "pv"
STEP_RULES = "rules"
STEP_ACTUATOR = "actuator"


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
}


def build_schema(step: str, values: dict[str, Any], *, initial: bool) -> vol.Schema:
    """Formular eines Schritts. Bei der Ersteinrichtung werden Vorschläge eingetragen."""
    schema: dict[Any, Any] = {}
    for key, sel, required in FIELDS[step]:
        if key in values:
            current = values[key]
        elif initial:
            current = c.DEFAULTS.get(key, c.SUGGESTED_ENTITIES.get(key))
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
    merged.update({k: v for k, v in user_input.items() if v not in (None, "")})
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


class WPLeitstandConfigFlow(ConfigFlow, domain=c.DOMAIN):
    """Ersteinrichtung in vier Schritten."""

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
            data_schema=build_schema(step, values, initial=user_input is None),
            errors=errors,
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_HEATPUMP, "user", user_input, STEP_PV)

    async def async_step_pv(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_PV, STEP_PV, user_input, STEP_RULES)

    async def async_step_rules(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_RULES, STEP_RULES, user_input, STEP_ACTUATOR)

    async def async_step_actuator(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_ACTUATOR, STEP_ACTUATOR, user_input, None)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return WPLeitstandOptionsFlow()


class WPLeitstandOptionsFlow(OptionsFlow):
    """Einstellungen nachträglich ändern."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=[STEP_HEATPUMP, STEP_PV, STEP_RULES, STEP_ACTUATOR],
        )

    async def _step(self, step: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = dict(self.config_entry.options)
        if user_input is not None:
            errors = validate_step(step, user_input)
            if not errors:
                return self.async_create_entry(data=merge_step(step, current, user_input))
        values = {**current, **(user_input or {})}
        return self.async_show_form(
            step_id=step,
            data_schema=build_schema(step, values, initial=False),
            errors=errors,
        )

    async def async_step_heatpump(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_HEATPUMP, user_input)

    async def async_step_pv(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_PV, user_input)

    async def async_step_rules(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_RULES, user_input)

    async def async_step_actuator(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._step(STEP_ACTUATOR, user_input)
