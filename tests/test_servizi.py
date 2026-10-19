"""Test delle azioni per i periodi tariffari."""

from __future__ import annotations

from freezegun.api import FrozenDateTimeFactory
import pytest
import voluptuous as vol

from custom_components.myitalgas.const import CONF_COEFFICIENTE, DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from .conftest import crea_entry
from .portale import PortaleFinto


@pytest.fixture(autouse=True)
def _ora(freezer: FrozenDateTimeFactory, fuso_roma: None) -> None:
    freezer.move_to("2026-10-19 10:00:00+02:00")


async def _avvia(hass: HomeAssistant):
    entry = crea_entry(hass, **{CONF_COEFFICIENTE: 1.0})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


async def test_imposta_crea_e_aggiorna(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """La stessa data aggiorna il periodo invece di crearne un altro; la fornitura si ricarica."""
    entry = await _avvia(hass)
    await hass.services.async_call(
        DOMAIN,
        "imposta_periodo_tariffario",
        {"config_entry_id": entry.entry_id, "dal": "2026-07-01", "prezzo_sc1": 1.0547},
        blocking=True,
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    (periodo,) = entry.subentries.values()
    assert periodo.title == "Dal 01/07/2026"
    assert dict(periodo.data) == {
        "dal": "2026-07-01",
        "prezzo_sc1": 1.0547,
        "prezzo_sc2": 1.0547,
        "prezzo_sc3": 1.0547,
        "quota_fissa": 0.0,
    }
    assert entry.state is ConfigEntryState.LOADED
    assert [t.prezzo_sc1 for t in entry.runtime_data.impostazioni.tariffe] == [1.0547]

    await hass.services.async_call(
        DOMAIN,
        "imposta_periodo_tariffario",
        {
            "config_entry_id": entry.entry_id,
            "dal": "2026-07-01",
            "prezzo_sc1": 1.0547,
            "prezzo_sc2": 1.4764,
            "prezzo_sc3": 1.6314,
            "quota_fissa": 17.6,
        },
        blocking=True,
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(entry.subentries) == 1
    (attiva,) = entry.runtime_data.impostazioni.tariffe
    assert (attiva.prezzo_sc2, attiva.prezzo_sc3, attiva.quota_fissa) == (1.4764, 1.6314, 17.6)
    assert hass.states.get("sensor.gas_casa_current_marginal_price").state == "1.4764"


async def test_rimuovi(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Rimozione di un periodo e errore se non esiste."""
    entry = await _avvia(hass)
    for dal in ("2026-06-01", "2026-07-01"):
        await hass.services.async_call(
            DOMAIN,
            "imposta_periodo_tariffario",
            {"config_entry_id": entry.entry_id, "dal": dal, "prezzo_sc1": 1.0},
            blocking=True,
        )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(entry.subentries) == 2

    await hass.services.async_call(
        DOMAIN,
        "rimuovi_periodo_tariffario",
        {"config_entry_id": entry.entry_id, "dal": "2026-06-01"},
        blocking=True,
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert [s.data["dal"] for s in entry.subentries.values()] == ["2026-07-01"]

    with pytest.raises(ServiceValidationError) as errore:
        await hass.services.async_call(
            DOMAIN,
            "rimuovi_periodo_tariffario",
            {"config_entry_id": entry.entry_id, "dal": "2026-06-01"},
            blocking=True,
        )
    assert errore.value.translation_key == "periodo_non_trovato"


async def test_fornitura_inesistente(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Identificativo sbagliato: errore chiaro."""
    await _avvia(hass)
    with pytest.raises(ServiceValidationError) as errore:
        await hass.services.async_call(
            DOMAIN,
            "imposta_periodo_tariffario",
            {"config_entry_id": "inesistente", "dal": "2026-07-01", "prezzo_sc1": 1.0},
            blocking=True,
        )
    assert errore.value.translation_key == "fornitura_non_trovata"


async def test_valori_non_validi(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Prezzi negativi o date non valide vengono rifiutati."""
    entry = await _avvia(hass)
    for dati in ({"dal": "2026-13-01", "prezzo_sc1": 1.0}, {"dal": "2026-07-01", "prezzo_sc1": -1}):
        with pytest.raises(vol.Invalid):
            await hass.services.async_call(
                DOMAIN,
                "imposta_periodo_tariffario",
                {"config_entry_id": entry.entry_id, **dati},
                blocking=True,
            )
    assert entry.subentries == {}
