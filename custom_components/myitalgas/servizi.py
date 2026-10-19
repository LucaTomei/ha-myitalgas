"""Azioni MyItalgas: gestione dei periodi tariffari da automazioni e altre integrazioni."""

from __future__ import annotations

from types import MappingProxyType

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from . import tariffe
from .const import (
    CONF_DAL,
    CONF_PREZZO_SC1,
    CONF_PREZZO_SC2,
    CONF_PREZZO_SC3,
    CONF_QUOTA_FISSA,
    DOMAIN,
    SUBENTRY_TARIFFA,
)

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
SERVIZIO_IMPOSTA = "imposta_periodo_tariffario"
SERVIZIO_RIMUOVI = "rimuovi_periodo_tariffario"

_PREZZO = vol.All(vol.Coerce(float), vol.Range(min=0, max=10))

SCHEMA_IMPOSTA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(CONF_DAL): cv.date,
        vol.Required(CONF_PREZZO_SC1): _PREZZO,
        vol.Optional(CONF_PREZZO_SC2): _PREZZO,
        vol.Optional(CONF_PREZZO_SC3): _PREZZO,
        vol.Optional(CONF_QUOTA_FISSA): vol.All(vol.Coerce(float), vol.Range(min=0, max=1000)),
    }
)
SCHEMA_RIMUOVI = vol.Schema(
    {vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string, vol.Required(CONF_DAL): cv.date}
)


def _entry(hass: HomeAssistant, entry_id: str) -> ConfigEntry:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="fornitura_non_trovata",
            translation_placeholders={"entry_id": entry_id},
        )
    return entry


def _periodo(entry: ConfigEntry, dal: str) -> ConfigSubentry | None:
    return next(
        (
            s
            for s in entry.subentries.values()
            if s.subentry_type == SUBENTRY_TARIFFA and s.data.get(CONF_DAL) == dal
        ),
        None,
    )


@callback
def async_registra_servizi(hass: HomeAssistant) -> None:
    """Registra le azioni dell'integrazione."""

    @callback
    def imposta(call: ServiceCall) -> None:
        entry = _entry(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        dati = tariffe.normalizza(call.data)
        if (esistente := _periodo(entry, dati[CONF_DAL])) is not None:
            hass.config_entries.async_update_subentry(
                entry, esistente, data=dati, title=tariffe.titolo(dati)
            )
            return
        hass.config_entries.async_add_subentry(
            entry,
            ConfigSubentry(
                data=MappingProxyType(dati),
                subentry_type=SUBENTRY_TARIFFA,
                title=tariffe.titolo(dati),
                unique_id=dati[CONF_DAL],
            ),
        )

    @callback
    def rimuovi(call: ServiceCall) -> None:
        entry = _entry(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        dal = call.data[CONF_DAL].isoformat()
        if (esistente := _periodo(entry, dal)) is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="periodo_non_trovato",
                translation_placeholders={"dal": dal},
            )
        hass.config_entries.async_remove_subentry(entry, esistente.subentry_id)

    hass.services.async_register(DOMAIN, SERVIZIO_IMPOSTA, imposta, schema=SCHEMA_IMPOSTA)
    hass.services.async_register(DOMAIN, SERVIZIO_RIMUOVI, rimuovi, schema=SCHEMA_RIMUOVI)
