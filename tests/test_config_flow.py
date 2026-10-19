"""Test della configurazione da interfaccia."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from custom_components.myitalgas.const import (
    CONF_ALIAS,
    CONF_COEFFICIENTE,
    CONF_INDIRIZZO,
    CONF_INTERVALLO_ORE,
    CONF_MATRICOLA,
    CONF_PDR,
    CONF_PREZZO,
    DOMAIN,
)
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import PASSWORD, PDR, USERNAME, crea_entry
from .portale import FornituraFinta, PortaleFinto


async def _inizia(hass: HomeAssistant) -> str:
    risultato = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert risultato["type"] is FlowResultType.FORM
    assert risultato["step_id"] == "user"
    assert risultato["errors"] == {}
    return risultato["flow_id"]


async def test_configurazione_una_fornitura(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Credenziali corrette e una sola fornitura: entry creata subito."""
    flow_id = await _inizia(hass)
    with patch("custom_components.myitalgas.async_setup_entry", return_value=True) as setup:
        risultato = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_USERNAME: f"  {USERNAME} ", CONF_PASSWORD: PASSWORD}
        )
        await hass.async_block_till_done()
    assert risultato["type"] is FlowResultType.CREATE_ENTRY
    assert risultato["title"] == f"Casa ({PDR})"
    assert risultato["result"].unique_id == PDR
    assert risultato["data"] == {
        CONF_USERNAME: USERNAME,
        CONF_PASSWORD: PASSWORD,
        CONF_PDR: PDR,
        CONF_ALIAS: "Casa",
        CONF_INDIRIZZO: "VIA ROMA 1, ROMA (RM)",
        CONF_MATRICOLA: "MIT0000000000001",
    }
    assert len(setup.mock_calls) == 1


async def test_scelta_tra_piu_forniture(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Più forniture: si sceglie quale aggiungere; poi resta solo l'altra."""
    portale.forniture.append(FornituraFinta(pdr="98765432109876", alias=""))
    flow_id = await _inizia(hass)
    risultato = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}
    )
    assert risultato["type"] is FlowResultType.FORM
    assert risultato["step_id"] == "pdr"
    with patch("custom_components.myitalgas.async_setup_entry", return_value=True):
        risultato = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_PDR: "98765432109876"}
        )
        await hass.async_block_till_done()
    assert risultato["type"] is FlowResultType.CREATE_ENTRY
    assert risultato["title"] == "PDR 98765432109876"
    assert risultato["data"][CONF_PDR] == "98765432109876"

    # seconda volta: l'unica fornitura rimasta viene aggiunta senza chiedere
    flow_id = await _inizia(hass)
    with patch("custom_components.myitalgas.async_setup_entry", return_value=True):
        risultato = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}
        )
        await hass.async_block_till_done()
    assert risultato["type"] is FlowResultType.CREATE_ENTRY
    assert risultato["data"][CONF_PDR] == PDR

    # terza volta: niente da aggiungere
    flow_id = await _inizia(hass)
    risultato = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}
    )
    assert risultato["type"] is FlowResultType.ABORT
    assert risultato["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("prepara", "errore"),
    [
        (lambda p: setattr(p, "utenti", {}), "invalid_auth"),
        (lambda p: setattr(p, "errore_http", 503), "cannot_connect"),
        (lambda p: setattr(p, "captcha", True), "portal_error"),
        (lambda p: setattr(p, "forniture", []), "no_pdr"),
    ],
)
async def test_errori(hass: HomeAssistant, portale: PortaleFinto, prepara, errore: str) -> None:
    """Gli errori vengono mostrati e si può riprovare."""
    prepara(portale)
    flow_id = await _inizia(hass)
    risultato = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}
    )
    assert risultato["type"] is FlowResultType.FORM
    assert risultato["errors"] == {"base": errore}

    # il portale torna normale: la configurazione si completa
    pulito = PortaleFinto()
    portale.utenti = pulito.utenti
    portale.errore_http = None
    portale.captcha = False
    portale.forniture = pulito.forniture
    with patch("custom_components.myitalgas.async_setup_entry", return_value=True):
        risultato = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}
        )
        await hass.async_block_till_done()
    assert risultato["type"] is FlowResultType.CREATE_ENTRY


async def test_errore_imprevisto(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Un errore non previsto non blocca il form."""
    flow_id = await _inizia(hass)
    with patch(
        "custom_components.myitalgas.config_flow.ItalgasClient.login",
        side_effect=RuntimeError("boom"),
    ):
        risultato = await hass.config_entries.flow.async_configure(
            flow_id, {CONF_USERNAME: USERNAME, CONF_PASSWORD: PASSWORD}
        )
    assert risultato["errors"] == {"base": "unknown"}


async def test_reauth(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Nuova password dopo un rifiuto."""
    entry = crea_entry(hass)
    portale.utenti = {USERNAME: "Nuova!2"}
    risultato = await entry.start_reauth_flow(hass)
    assert risultato["step_id"] == "reauth_confirm"
    assert risultato["description_placeholders"]["pdr"] == PDR

    risultato = await hass.config_entries.flow.async_configure(
        risultato["flow_id"], {CONF_USERNAME: USERNAME, CONF_PASSWORD: "ancora sbagliata"}
    )
    assert risultato["errors"] == {"base": "invalid_auth"}

    with patch("custom_components.myitalgas.async_setup_entry", return_value=True):
        risultato = await hass.config_entries.flow.async_configure(
            risultato["flow_id"], {CONF_USERNAME: USERNAME, CONF_PASSWORD: "Nuova!2"}
        )
        await hass.async_block_till_done()
    assert risultato["type"] is FlowResultType.ABORT
    assert risultato["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "Nuova!2"
    assert entry.data[CONF_PDR] == PDR


async def test_reauth_con_profilo_senza_il_pdr(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Le nuove credenziali devono vedere la stessa fornitura."""
    entry = crea_entry(hass)
    portale.utenti["altro.utente"] = "Altra!3"
    portale.forniture[0].pdr = "11111111111111"
    risultato = await entry.start_reauth_flow(hass)
    risultato = await hass.config_entries.flow.async_configure(
        risultato["flow_id"], {CONF_USERNAME: "altro.utente", CONF_PASSWORD: "Altra!3"}
    )
    assert risultato["errors"] == {"base": "pdr_missing"}
    assert entry.data[CONF_USERNAME] == USERNAME


async def test_riconfigurazione(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Cambio credenziali da "Riconfigura"."""
    entry = crea_entry(hass)
    portale.utenti = {"nuovo.utente": "Nuova!2"}
    portale.forniture[0].letture = []
    risultato = await entry.start_reconfigure_flow(hass)
    assert risultato["step_id"] == "reconfigure"
    with patch("custom_components.myitalgas.async_setup_entry", return_value=True):
        risultato = await hass.config_entries.flow.async_configure(
            risultato["flow_id"], {CONF_USERNAME: "nuovo.utente", CONF_PASSWORD: "Nuova!2"}
        )
        await hass.async_block_till_done()
    assert risultato["type"] is FlowResultType.ABORT
    assert risultato["reason"] == "reconfigure_successful"
    assert entry.data[CONF_USERNAME] == "nuovo.utente"


async def test_opzioni(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Le opzioni vengono salvate e l'integrazione ricaricata."""
    entry = crea_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.update_interval.total_seconds() == 12 * 3600

    risultato = await hass.config_entries.options.async_init(entry.entry_id)
    assert risultato["type"] is FlowResultType.FORM
    risultato = await hass.config_entries.options.async_configure(
        risultato["flow_id"],
        {CONF_INTERVALLO_ORE: 6, CONF_COEFFICIENTE: 1.0185, CONF_PREZZO: 1.25},
    )
    await hass.async_block_till_done()
    assert risultato["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_INTERVALLO_ORE: 6, CONF_COEFFICIENTE: 1.0185, CONF_PREZZO: 1.25}
    assert entry.runtime_data.update_interval.total_seconds() == 6 * 3600
