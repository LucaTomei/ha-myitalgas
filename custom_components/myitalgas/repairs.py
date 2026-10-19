"""Riparazioni MyItalgas: impostazione del coefficiente C dalla segnalazione."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import COEFFICIENTE_MAX, COEFFICIENTE_MIN, CONF_COEFFICIENTE


class CoefficienteFlow(RepairsFlow):
    """Chiede il coefficiente C riportato in bolletta."""

    def __init__(self, entry_id: str) -> None:
        """Inizializza il flusso."""
        self._entry_id = entry_id

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Primo (e unico) passo."""
        return await self.async_step_coefficiente()

    async def async_step_coefficiente(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Inserimento del coefficiente."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_rimossa")
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                entry,
                options={
                    **entry.options,
                    CONF_COEFFICIENTE: float(user_input[CONF_COEFFICIENTE]),
                },
            )
            return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="coefficiente",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_COEFFICIENTE): NumberSelector(
                        NumberSelectorConfig(
                            min=COEFFICIENTE_MIN,
                            max=COEFFICIENTE_MAX,
                            step="any",
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
            description_placeholders={"nome": entry.title},
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    """Crea il flusso di riparazione della segnalazione."""
    return CoefficienteFlow(str((data or {})["entry_id"]))
