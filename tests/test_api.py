"""Test del client HTTP contro il portale simulato."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date

import aiohttp
import pytest

from custom_components.myitalgas.api import (
    ItalgasAuthError,
    ItalgasClient,
    ItalgasConnectionError,
    ItalgasPdrNotFoundError,
    ItalgasPortalError,
    blocchi,
)

from .conftest import PASSWORD, PDR, USERNAME
from .portale import FornituraFinta, LetturaFinta, PortaleFinto, letture_mensili

OGGI = date(2026, 10, 19)


@pytest.fixture
async def sessione() -> AsyncIterator[aiohttp.ClientSession]:
    """Sessione HTTP con cookie jar proprio (come quella creata dall'integrazione)."""
    async with aiohttp.ClientSession() as s:
        yield s


def _client(sessione: aiohttp.ClientSession, portale: PortaleFinto, password: str = PASSWORD):
    return ItalgasClient(sessione, USERNAME, password, portale.url)


def test_blocchi() -> None:
    """Intervalli contigui, senza buchi né sovrapposizioni."""
    assert list(blocchi(date(2024, 1, 1), date(2024, 1, 10), 4)) == [
        (date(2024, 1, 1), date(2024, 1, 4)),
        (date(2024, 1, 5), date(2024, 1, 8)),
        (date(2024, 1, 9), date(2024, 1, 10)),
    ]
    assert list(blocchi(date(2024, 1, 2), date(2024, 1, 1), 4)) == []
    assert list(blocchi(date(2024, 1, 1), date(2024, 1, 1), 365)) == [
        (date(2024, 1, 1), date(2024, 1, 1))
    ]


async def test_accesso_e_forniture(sessione, portale: PortaleFinto) -> None:
    """Accesso e elenco forniture."""
    client = _client(sessione, portale)
    forniture = await client.forniture()
    assert [f.pdr for f in forniture] == [PDR]
    assert forniture[0].alias == "Casa"
    assert forniture[0].matricola == "MIT0000000000001"
    assert portale.accessi == 1
    # sessione ancora valida: nessun nuovo accesso
    await client.forniture()
    await client.login()
    assert portale.accessi == 1


async def test_password_errata(sessione, portale: PortaleFinto) -> None:
    """Credenziali rifiutate."""
    with pytest.raises(ItalgasAuthError, match="Username o Password errati"):
        await _client(sessione, portale, "sbagliata").login()


async def test_captcha(sessione, portale: PortaleFinto) -> None:
    """Se il portale chiede un captcha l'errore è chiaro (e non è un errore di credenziali)."""
    portale.captcha = True
    with pytest.raises(ItalgasPortalError, match="captcha"):
        await _client(sessione, portale).login()


@pytest.mark.parametrize("stato", [500, 502, 503])
async def test_portale_in_errore(sessione, portale: PortaleFinto, stato: int) -> None:
    """Errori del server: portale non raggiungibile."""
    portale.errore_http = stato
    with pytest.raises(ItalgasConnectionError, match=str(stato)):
        await _client(sessione, portale).login()


async def test_pagina_non_trovata(sessione, portale: PortaleFinto) -> None:
    """Errore 4xx: risposta inattesa."""
    portale.errore_http = 404
    with pytest.raises(ItalgasPortalError, match="404"):
        await _client(sessione, portale).login()


async def test_portale_irraggiungibile(sessione, socket_enabled, unused_tcp_port: int) -> None:
    """Connessione rifiutata."""
    client = ItalgasClient(
        sessione, USERNAME, PASSWORD, f"http://127.0.0.1:{unused_tcp_port}/clienti/"
    )
    with pytest.raises(ItalgasConnectionError, match="non raggiungibile"):
        await client.login()


async def test_modulo_accesso_cambiato(sessione, portale: PortaleFinto) -> None:
    """Se il portale cambia la pagina di accesso l'errore è esplicito."""
    portale.errore_http = None
    portale.utenti = {}
    client = _client(sessione, portale)
    original = portale._pagina

    def senza_form(modello: str, **valori):
        risposta = original(modello, **valori)
        if modello == "login.html":
            risposta.text = risposta.text.replace('id="headerLogin"', 'id="altro"')
        return risposta

    portale._pagina = senza_form
    with pytest.raises(ItalgasPortalError, match="modulo di accesso"):
        await client.login()


async def test_storico_completo(sessione, portale: PortaleFinto) -> None:
    """Primo scaricamento: trova da solo l'inizio dello storico e scarica tutto."""
    risultato = await _client(sessione, portale).scarica_letture(PDR, None, OGGI)
    attese = letture_mensili()
    assert [(x.data, x.valore) for x in risultato.letture] == [
        (x.data, float(x.valore)) for x in attese
    ]
    assert risultato.mancanti == []
    assert risultato.data_minima == date(2022, 12, 1)
    # una sola ricerca "a vuoto" per scoprire la data minima, poi blocchi annuali
    assert portale.ricerche[0][0] == date(2000, 1, 1)
    assert portale.ricerche[1][0] == date(2022, 12, 1)
    assert len(portale.ricerche) == 5
    assert all((a - da).days < 366 for da, a in portale.ricerche)
    # le pagine con più di 10 risultati sono state lette tramite l'export CSV
    assert any(r.startswith("GET /clienti/ricercaLetture.action") for r in portale.richieste)


async def test_export_csv_non_disponibile(sessione, portale: PortaleFinto) -> None:
    """Se l'export CSV non funziona si leggono le pagine una per una."""
    portale.csv_rotto = True
    risultato = await _client(sessione, portale).scarica_letture(PDR, None, OGGI)
    assert len(risultato.letture) == 47


async def test_aggiornamento_incrementale(sessione, portale: PortaleFinto) -> None:
    """Con una data di inizio si scarica solo quel periodo."""
    risultato = await _client(sessione, portale).scarica_letture(PDR, date(2026, 7, 1), OGGI)
    assert [x.data for x in risultato.letture] == [
        date(2026, 7, 31),
        date(2026, 8, 31),
        date(2026, 9, 30),
    ]
    assert portale.ricerche == [(date(2026, 7, 1), OGGI)]
    assert risultato.data_minima is None


async def test_nessuna_lettura_nel_periodo(sessione, portale: PortaleFinto) -> None:
    """Periodo senza letture: risultato vuoto, nessun errore."""
    risultato = await _client(sessione, portale).scarica_letture(PDR, date(2026, 10, 1), OGGI)
    assert risultato.letture == []
    assert risultato.mancanti == []


async def test_errore_di_sistema_su_un_blocco(sessione, portale: PortaleFinto) -> None:
    """Un blocco in errore viene diviso a metà e recuperato."""
    portale.errore_sistema = lambda da, a: (a - da).days > 200 and da <= date(2024, 6, 1) <= a
    risultato = await _client(sessione, portale).scarica_letture(PDR, None, OGGI)
    assert len(risultato.letture) == 47
    assert risultato.mancanti == []


async def test_periodo_sempre_in_errore(sessione, portale: PortaleFinto) -> None:
    """Un periodo che fallisce anche alla dimensione minima viene segnalato, il resto è salvo."""
    portale.errore_sistema = lambda da, a: da <= date(2024, 6, 15) <= a
    risultato = await _client(sessione, portale).scarica_letture(PDR, None, OGGI)
    assert len(risultato.mancanti) == 1
    inizio, fine = risultato.mancanti[0]
    assert inizio <= date(2024, 6, 15) <= fine
    assert (fine - inizio).days < 31
    attese = [x.data for x in letture_mensili() if not inizio <= x.data <= fine]
    assert [x.data for x in risultato.letture] == attese


async def test_portale_sempre_in_errore(sessione, portale: PortaleFinto) -> None:
    """Se ogni ricerca fallisce ci si ferma con un errore."""
    portale.errore_sistema = lambda _da, _a: True
    with pytest.raises(ItalgasPortalError, match="Errore di sistema"):
        await _client(sessione, portale).scarica_letture(PDR, None, OGGI)
    assert len(portale.ricerche) <= 8


async def test_sessione_scaduta_durante_lo_scaricamento(sessione, portale: PortaleFinto) -> None:
    """Se la sessione scade a metà si rientra e si riprende dal blocco interrotto."""
    portale.scadenza_ogni = 5
    risultato = await _client(sessione, portale).scarica_letture(PDR, None, OGGI)
    assert len(risultato.letture) == 47
    assert portale.accessi >= 3


async def test_sessione_sempre_scaduta(sessione, portale: PortaleFinto) -> None:
    """Sessione che scade di continuo: errore invece di un ciclo infinito."""
    portale.scadenza_ogni = 2
    with pytest.raises(ItalgasPortalError):
        await _client(sessione, portale).scarica_letture(PDR, None, OGGI)
    assert portale.accessi <= 8


async def test_sessione_scaduta_tra_due_aggiornamenti(sessione, portale: PortaleFinto) -> None:
    """Il client rientra da solo se nel frattempo la sessione è scaduta."""
    client = _client(sessione, portale)
    await client.scarica_letture(PDR, date(2026, 9, 1), OGGI)
    portale.scadi_sessioni()
    risultato = await client.scarica_letture(PDR, date(2026, 9, 1), OGGI)
    assert len(risultato.letture) == 1
    assert portale.accessi == 2


async def test_pdr_non_associato(sessione, portale: PortaleFinto) -> None:
    """PDR non presente nel profilo."""
    with pytest.raises(ItalgasPdrNotFoundError, match="99999999999999"):
        await _client(sessione, portale).scarica_letture("99999999999999", None, OGGI)


async def test_piu_forniture(sessione, portale: PortaleFinto) -> None:
    """Con più forniture si scaricano le letture di quella richiesta."""
    portale.forniture.append(
        FornituraFinta(
            pdr="98765432109876",
            letture=[LetturaFinta(date(2026, 9, 30), 42.0, matricola="MIT2")],
        )
    )
    client = _client(sessione, portale)
    risultato = await client.scarica_letture("98765432109876", date(2026, 1, 1), OGGI)
    assert [(x.valore, x.matricola) for x in risultato.letture] == [(42.0, "MIT2")]
    risultato = await client.scarica_letture(PDR, date(2026, 9, 1), OGGI)
    assert [x.valore for x in risultato.letture] == [1812.0]


async def test_sostituzione_contatore_stesso_giorno(sessione, portale: PortaleFinto) -> None:
    """Due letture nello stesso giorno con matricole diverse vengono entrambe conservate."""
    portale.forniture[0].letture = [
        LetturaFinta(date(2026, 8, 31), 1500, matricola="VECCHIO"),
        LetturaFinta(date(2026, 9, 15), 1520, "Lettura tecnica", "VECCHIO"),
        LetturaFinta(date(2026, 9, 15), 0, "Lettura tecnica", "NUOVO"),
        LetturaFinta(date(2026, 9, 30), 12, matricola="NUOVO"),
    ]
    risultato = await _client(sessione, portale).scarica_letture(PDR, date(2026, 8, 1), OGGI)
    assert sorted((x.data, x.matricola) for x in risultato.letture) == [
        (date(2026, 8, 31), "VECCHIO"),
        (date(2026, 9, 15), "NUOVO"),
        (date(2026, 9, 15), "VECCHIO"),
        (date(2026, 9, 30), "NUOVO"),
    ]


async def test_storico_che_parte_oltre_la_fine(sessione, portale: PortaleFinto) -> None:
    """Fornitura appena attivata: data minima successiva alla fine richiesta."""
    portale.data_minima = date(2026, 10, 25)
    risultato = await _client(sessione, portale).scarica_letture(PDR, None, OGGI)
    assert risultato.letture == []
    assert risultato.data_minima == date(2026, 10, 25)
    assert len(portale.ricerche) == 1
