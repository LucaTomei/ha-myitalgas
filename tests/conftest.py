"""Fixture comuni dei test."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import patch

from aiohttp import ThreadedResolver
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import pytest_socket

from custom_components.myitalgas.const import (
    CONF_ALIAS,
    CONF_DAL,
    CONF_INDIRIZZO,
    CONF_MATRICOLA,
    CONF_PDR,
    CONF_PREZZO_SC1,
    CONF_PREZZO_SC2,
    CONF_PREZZO_SC3,
    CONF_QUOTA_FISSA,
    DOMAIN,
    SUBENTRY_TARIFFA,
)
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .portale import PortaleFinto

PDR = "01234567890123"
USERNAME = "mario.rossi"
PASSWORD = "Segreta!1"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations: None) -> None:
    """Abilita le integrazioni personalizzate e il recorder (dipendenza dell'integrazione)."""


@pytest.fixture
async def portale(socket_enabled: None) -> AsyncIterator[PortaleFinto]:
    """Portale MyItalgas simulato su 127.0.0.1; l'integrazione viene puntata su di esso."""
    pytest_socket.socket_allow_hosts(["127.0.0.1", "::1"])
    finto = PortaleFinto()
    url = await finto.avvia()
    # il resolver DNS dei test di Home Assistant è legato a un altro event loop
    resolver = ThreadedResolver()
    resolver.real_close = resolver.close
    with (
        patch("custom_components.myitalgas.api.PORTALE_URL", url),
        patch(
            "homeassistant.helpers.aiohttp_client._async_make_resolver",
            return_value=resolver,
        ),
    ):
        yield finto
    await finto.ferma()


@pytest.fixture
async def fuso_roma(hass: HomeAssistant) -> None:
    """Fuso orario italiano, come in un'installazione reale."""
    await hass.config.async_set_time_zone("Europe/Rome")


def tariffa(dal: str, sc1: float, sc2: float | None = None, sc3: float | None = None, fissa=0.0):
    """Sottovoce "periodo tariffario" come la salva il flusso di configurazione."""
    sc2 = sc1 if sc2 is None else sc2
    sc3 = sc2 if sc3 is None else sc3
    return ConfigSubentryData(
        data={
            CONF_DAL: dal,
            CONF_PREZZO_SC1: sc1,
            CONF_PREZZO_SC2: sc2,
            CONF_PREZZO_SC3: sc3,
            CONF_QUOTA_FISSA: fissa,
        },
        subentry_type=SUBENTRY_TARIFFA,
        title=f"Dal {dal}",
        unique_id=dal,
    )


def crea_entry(
    hass: HomeAssistant,
    tariffe: list[ConfigSubentryData] | None = None,
    minor_version: int = 2,
    **opzioni,
) -> MockConfigEntry:
    """Config entry già configurata per la fornitura del portale simulato."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=PDR,
        version=1,
        minor_version=minor_version,
        subentries_data=tariffe or [],
        title=f"Casa ({PDR})",
        data={
            CONF_USERNAME: USERNAME,
            CONF_PASSWORD: PASSWORD,
            CONF_PDR: PDR,
            CONF_ALIAS: "Casa",
            CONF_INDIRIZZO: "VIA ROMA 1, ROMA (RM)",
            CONF_MATRICOLA: "MIT0000000000001",
        },
        options=opzioni,
    )
    entry.add_to_hass(hass)
    return entry
