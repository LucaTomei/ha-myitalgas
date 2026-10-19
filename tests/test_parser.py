"""Test della lettura delle pagine del portale."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.myitalgas import parser
from custom_components.myitalgas.parser import Lettura

from .portale import FIXTURES, MESSAGGIO_LIMITE, FornituraFinta, PortaleFinto, letture_mensili


def _html(risposta) -> str:
    return risposta.text


def _pagina_risultati(n: int, pagina: int = 1) -> str:
    portale = PortaleFinto()
    fornitura = portale.forniture[0]
    trovate = sorted(fornitura.letture, key=lambda x: x.data, reverse=True)[:n]
    return _html(
        portale._pagina_letture(
            fornitura,
            "01/01/2025",
            "19/10/2026",
            risultati=portale._risultati(
                fornitura, "01/01/2025", "19/10/2026", trovate, pagina=pagina
            ),
        )
    )


def test_albero_tollerante() -> None:
    """Tag non chiusi, entità e script non rompono l'analisi."""
    radice = parser.analizza(
        "<div id=a><p>uno<p>due &amp; tre<table><tr><td>x<td>y<tr><td>z</table>"
        "<script>var s = '<td>nascosto</td>';</script><img src=x><br/>fine</div></span>"
    )
    div = radice.trova(lambda n: n.get("id") == "a")
    assert div is not None
    assert "due & tre" in div.testo
    assert "nascosto" not in div.testo
    righe = div.trova_tutti(lambda n: n.tag == "tr")
    assert [[td.testo for td in r.trova_tutti(lambda n: n.tag == "td")] for r in righe] == [
        ["x", "y"],
        ["z"],
    ]
    assert div.testo.endswith("fine")


def test_modulo_login() -> None:
    """Il form di accesso reale espone i campi attesi."""
    html = (FIXTURES / "login.html").read_text(encoding="utf-8").replace("{{TOKEN}}", "T1")
    radice = parser.analizza(html)
    form = parser.modulo(radice, "headerLogin")
    assert form is not None
    assert form.azione == "login.action"
    assert form.campi["username"] == ""
    assert form.campi["password"] == ""
    assert form.campi["token"] == "T1"
    assert form.campi["struts.token.name"] == "token"
    # checkbox non spuntata: il browser non la invia
    assert "ricordami" not in form.campi
    assert form.campi["__checkbox_ricordami"] == "true"
    assert not parser.e_autenticato(html)
    assert parser.modulo(radice, "inesistente") is None


def test_modulo_campi_vari() -> None:
    """Checkbox spuntate, select e textarea."""
    radice = parser.analizza(
        '<form id="f" action="x.action"><input type="checkbox" name="c" value="1" checked>'
        '<input type="radio" name="r" value="a"><input type="radio" name="r" value="b" checked>'
        '<select name="s"><option value="1">uno<option value="2" selected>due</select>'
        '<select name="s2"><option>solo</select>'
        '<textarea name="t">ciao  mondo</textarea><input name="senza_tipo" value="v">'
        '<input type="submit" name="invia" value="Invia"><input value="anonimo"></form>'
    )
    form = parser.modulo(radice, "f")
    assert form is not None
    assert form.campi == {
        "c": "1",
        "r": "b",
        "s": "2",
        "s2": "solo",
        "t": "ciao mondo",
        "senza_tipo": "v",
    }


def test_login_errato() -> None:
    """Il messaggio di credenziali errate viene riconosciuto."""
    html = (FIXTURES / "login_errato.html").read_text(encoding="utf-8")
    assert parser.messaggi_errore(parser.analizza(html)) == ["Username o Password errati"]


def test_pagina_autenticata() -> None:
    """La home dopo l'accesso contiene il link di uscita."""
    assert parser.e_autenticato((FIXTURES / "home.html").read_text(encoding="utf-8"))


def test_forniture() -> None:
    """Più forniture nella stessa pagina, ognuna con i suoi dati (desktop e mobile non duplicano)."""
    portale = PortaleFinto()
    portale.forniture.append(
        FornituraFinta(
            pdr="98765432109876",
            alias="Casa al mare",
            indirizzo="VIA DEL MARE 5, OSTIA (RM)",
            venditore="ALTRO VENDITORE S.R.L.",
            matricola="MIT0000000000002",
            id="ID-SECONDA",
        )
    )
    html = _html(portale._forniture_html())
    trovate = parser.forniture(parser.analizza(html))
    assert [f.pdr for f in trovate] == ["01234567890123", "98765432109876"]
    seconda = trovate[1]
    assert seconda.alias == "Casa al mare"
    assert seconda.indirizzo == "VIA DEL MARE 5, OSTIA (RM)"
    assert seconda.venditore == "ALTRO VENDITORE S.R.L."
    assert seconda.matricola == "MIT0000000000002"
    assert seconda.link == "elencoLetture.action?id=ID-SECONDA"


def test_forniture_vuote() -> None:
    """Profilo senza forniture."""
    portale = PortaleFinto()
    portale.forniture = []
    assert parser.forniture(parser.analizza(_html(portale._forniture_html()))) == []


def test_risultati_paginati() -> None:
    """Prima pagina di 21 risultati: 10 righe, totale, export CSV e link alle pagine."""
    pagina = parser.pagina_letture(parser.analizza(_pagina_risultati(21)))
    assert pagina.totale == 21
    assert len(pagina.letture) == 10
    assert pagina.letture[0] == Lettura(
        date(2026, 9, 30), 1812.0, "Telelettura", "MIT0000000000001"
    )
    assert pagina.errori == []
    assert pagina.link_csv is not None
    assert "6578706f7274=1" in pagina.link_csv
    assert "&amp;" not in pagina.link_csv
    assert sorted(pagina.link_pagine) == [2, 3]


@pytest.mark.parametrize(("n", "totale"), [(1, 1), (7, 7), (10, 10)])
def test_risultati_su_una_pagina(n: int, totale: int) -> None:
    """Banner "Un elemento trovato" e "visualizzati tutti gli elementi"."""
    pagina = parser.pagina_letture(parser.analizza(_pagina_risultati(n)))
    assert pagina.totale == totale
    assert len(pagina.letture) == n
    assert pagina.link_pagine == {}


def test_nessun_risultato() -> None:
    """Ricerca senza risultati: nessun errore, totale zero."""
    pagina = parser.pagina_letture(parser.analizza(_pagina_risultati(0)))
    assert pagina.totale == 0
    assert pagina.letture == []
    assert pagina.errori == []


def test_errore_di_sistema() -> None:
    """Errore generico del portale."""
    portale = PortaleFinto()
    html = _html(portale._pagina_letture(portale.forniture[0], errore="Errore di sistema"))
    pagina = parser.pagina_letture(parser.analizza(html))
    assert pagina.errori == ["Errore di sistema"]
    assert pagina.letture == []
    assert parser.data_minima(pagina.errori) is None
    assert parser.e_autenticato(html)


def test_data_minima() -> None:
    """La data minima consultabile si legge dal messaggio sul campo "Dal"."""
    portale = PortaleFinto()
    messaggio = MESSAGGIO_LIMITE.format(data="01/12/2022")
    html = _html(portale._pagina_letture(portale.forniture[0], errore_data=messaggio))
    pagina = parser.pagina_letture(parser.analizza(html))
    assert pagina.errori == [messaggio]
    assert parser.data_minima(pagina.errori) == date(2022, 12, 1)
    assert parser.data_minima(["limite inferiore errato (31/02/2022)"]) is None
    assert parser.data_minima(["limite inferiore errato"]) is None


def test_intestazioni_in_ordine_diverso() -> None:
    """Le colonne si riconoscono dall'intestazione, non dalla posizione."""
    html = (
        '<table id="itemList"><thead><tr><th>Lettura</th><th>Tipologia</th>'
        "<th>Data Lettura</th><th>Matricola contatore</th></tr></thead><tbody>"
        "<tr><td>1.234</td><td>Telelettura</td><td>31/01/2026</td><td>M1</td></tr>"
        "<tr><td>non numero</td><td>x</td><td>28/02/2026</td><td>M1</td></tr>"
        "<tr><td>10</td><td>x</td><td>31/02/2026</td><td>M1</td></tr>"
        "<tr><td colspan=4>Nessun dato</td></tr></tbody></table>"
    )
    pagina = parser.pagina_letture(parser.analizza(html))
    assert pagina.letture == [Lettura(date(2026, 1, 31), 1234.0, "Telelettura", "M1")]


@pytest.mark.parametrize(
    ("testo", "atteso"),
    [
        ("1637", 1637.0),
        ("1637.0", 1637.0),
        (" 1.637 ", 1637.0),
        ("1.637.250", 1637250.0),
        ("1.637,5", 1637.5),
        ("12,25", 12.25),
        ("0", 0.0),
        ("1\xa0637", 1637.0),
    ],
)
def test_numero(testo: str, atteso: float) -> None:
    """Formati numerici del portale (HTML e CSV)."""
    assert parser.numero(testo) == atteso


def test_csv() -> None:
    """Export CSV con BOM, separatore ; e valori decimali."""
    testo = (
        "﻿Matricola contatore;Data Lettura;Lettura;Tipologia lettura\n"
        "MIT1;30/09/2026;1637.0;Telelettura\r\n"
        "\n"
        "MIT1;31/08/2026;1620.5;Lettura tecnica\n"
    )
    assert parser.letture_csv(testo) == [
        Lettura(date(2026, 9, 30), 1637.0, "Telelettura", "MIT1"),
        Lettura(date(2026, 8, 31), 1620.5, "Lettura tecnica", "MIT1"),
    ]
    assert parser.letture_csv("<!DOCTYPE html><html>") is None
    assert parser.letture_csv("") is None


def test_lettura_serializzazione() -> None:
    """Le letture salvate si ricostruiscono identiche."""
    lettura = Lettura(date(2026, 9, 30), 1637.0, "Telelettura", "MIT1")
    assert Lettura.da_dict(lettura.come_dict()) == lettura


def test_letture_mensili_finte() -> None:
    """Controllo dei dati del portale simulato usati negli altri test."""
    letture = letture_mensili()
    assert letture[0].data == date(2022, 12, 1)
    assert letture[-1].data == date(2026, 9, 30)
    assert len(letture) == 47
