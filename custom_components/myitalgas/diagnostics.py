"""Diagnostica MyItalgas (dati personali oscurati)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_ALIAS, CONF_INDIRIZZO, CONF_MATRICOLA, CONF_PDR
from .coordinator import ItalgasConfigEntry

DA_OSCURARE = {
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_PDR,
    CONF_ALIAS,
    CONF_INDIRIZZO,
    CONF_MATRICOLA,
    "title",
    "unique_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ItalgasConfigEntry
) -> dict[str, Any]:
    """Diagnostica della fornitura."""
    dati = entry.runtime_data.data
    return {
        "entry": async_redact_data(entry.as_dict(), DA_OSCURARE),
        "letture": [
            {
                "data": x.data.isoformat(),
                "valore": x.valore,
                "tipologia": x.tipologia,
                "stesso_contatore_della_precedente": i > 0
                and dati.letture[i - 1].matricola == x.matricola,
            }
            for i, x in enumerate(dati.letture)
        ]
        if dati
        else None,
        "periodi_non_scaricati": [[a.isoformat(), b.isoformat()] for a, b in dati.mancanti]
        if dati
        else None,
        "ultimo_aggiornamento": dati.ultimo_aggiornamento.isoformat()
        if dati and dati.ultimo_aggiornamento
        else None,
        "ultimo_aggiornamento_riuscito": entry.runtime_data.last_update_success,
        "storico_completo": dati.storico_completo if dati else None,
    }
