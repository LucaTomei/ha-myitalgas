"""Integrazione MyItalgas: letture del contatore gas dal portale clienti Italgas."""

from __future__ import annotations

import logging
from types import MappingProxyType

from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .api import ItalgasClient
from .const import (
    COEFFICIENTE_DEFAULT,
    CONF_COEFFICIENTE,
    CONF_DAL,
    CONF_PREZZO_SC1,
    CONF_PREZZO_SC2,
    CONF_PREZZO_SC3,
    CONF_PREZZO_UNICO,
    CONF_QUOTA_FISSA,
    DOMAIN,
    STORAGE_VERSION,
    SUBENTRY_TARIFFA,
)
from .coordinator import ItalgasConfigEntry, ItalgasCoordinator
from .servizi import async_registra_servizi

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

DAL_PREZZO_UNICO = "1900-01-01"

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Registra le azioni, disponibili anche prima che le forniture siano avviate."""
    async_registra_servizi(hass)
    return True


def id_issue_coefficiente(entry_id: str) -> str:
    """Identificativo della segnalazione "coefficiente C non impostato"."""
    return f"coefficiente_{entry_id}"


async def async_setup_entry(hass: HomeAssistant, entry: ItalgasConfigEntry) -> bool:
    """Configura una fornitura MyItalgas."""
    # Sessione dedicata: i cookie del portale non vanno condivisi con altre integrazioni.
    client = ItalgasClient(
        async_create_clientsession(hass),
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    coordinator = ItalgasCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    _aggiorna_issue_coefficiente(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # opzioni, credenziali o periodi tariffari modificati: si ricarica la fornitura
    entry.async_on_unload(entry.add_update_listener(_async_ricarica))
    return True


async def _async_ricarica(hass: HomeAssistant, entry: ItalgasConfigEntry) -> None:
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ItalgasConfigEntry) -> bool:
    """Rimuove le entità della fornitura."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ItalgasConfigEntry) -> None:
    """Cancella lo storico salvato quando l'integrazione viene eliminata."""
    ir.async_delete_issue(hass, DOMAIN, id_issue_coefficiente(entry.entry_id))
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()


async def async_migrate_entry(hass: HomeAssistant, entry: ItalgasConfigEntry) -> bool:
    """Aggiorna le configurazioni create dalle versioni precedenti."""
    if entry.version > 1:
        # configurazione creata da una versione più recente dell'integrazione
        return False
    if entry.minor_version < 2:
        # 1.x: prezzo unico nelle opzioni -> periodo tariffario valido da sempre
        opzioni = dict(entry.options)
        prezzo = opzioni.pop(CONF_PREZZO_UNICO, None)
        if prezzo:
            hass.config_entries.async_add_subentry(
                entry,
                ConfigSubentry(
                    data=MappingProxyType(
                        {
                            CONF_DAL: DAL_PREZZO_UNICO,
                            CONF_PREZZO_SC1: float(prezzo),
                            CONF_PREZZO_SC2: float(prezzo),
                            CONF_PREZZO_SC3: float(prezzo),
                            CONF_QUOTA_FISSA: 0.0,
                        }
                    ),
                    subentry_type=SUBENTRY_TARIFFA,
                    title="Prezzo unico (versione 1.x)",
                    unique_id=DAL_PREZZO_UNICO,
                ),
            )
        hass.config_entries.async_update_entry(entry, options=opzioni, minor_version=2)
        _LOGGER.debug("Configurazione MyItalgas aggiornata alla versione 1.2")
    return True


def _aggiorna_issue_coefficiente(hass: HomeAssistant, entry: ItalgasConfigEntry) -> None:
    """Segnala in Riparazioni se il coefficiente C non è stato impostato."""
    coefficiente = entry.options.get(CONF_COEFFICIENTE, COEFFICIENTE_DEFAULT)
    if coefficiente == COEFFICIENTE_DEFAULT:
        ir.async_create_issue(
            hass,
            DOMAIN,
            id_issue_coefficiente(entry.entry_id),
            is_fixable=True,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="coefficiente_non_impostato",
            translation_placeholders={"nome": entry.title},
            data={"entry_id": entry.entry_id},
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, id_issue_coefficiente(entry.entry_id))
