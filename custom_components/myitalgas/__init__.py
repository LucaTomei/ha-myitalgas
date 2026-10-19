"""Integrazione MyItalgas: letture del contatore gas dal portale clienti Italgas."""

from __future__ import annotations

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.storage import Store

from .api import ItalgasClient
from .const import DOMAIN, STORAGE_VERSION
from .coordinator import ItalgasConfigEntry, ItalgasCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


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

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ItalgasConfigEntry) -> bool:
    """Rimuove le entità della fornitura."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ItalgasConfigEntry) -> None:
    """Cancella lo storico salvato quando l'integrazione viene eliminata."""
    await Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()
