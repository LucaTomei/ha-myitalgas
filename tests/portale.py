"""Portale MyItalgas simulato, costruito sulle pagine reali (anonimizzate) del portale."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import itertools
from pathlib import Path
import secrets
from urllib.parse import urlencode

from aiohttp import web
from aiohttp.test_utils import TestServer

FIXTURES = Path(__file__).parent / "fixtures"
COOKIE = "JSESSIONID"
TABELLA = "4012067"
MESSAGGIO_LIMITE = (
    "Il limite inferiore della data lettura è errato. Al massimo è possibile "
    "indicare la data di visualizzazione del PdR ({data})"
)


def _fixture(nome: str) -> str:
    return (FIXTURES / nome).read_text(encoding="utf-8")


def _riempi(modello: str, valori: dict[str, str]) -> str:
    for chiave, valore in valori.items():
        modello = modello.replace("{{" + chiave + "}}", valore)
    return modello


@dataclass
class LetturaFinta:
    """Lettura presente sul portale simulato."""

    data: date
    valore: float
    tipologia: str = "Telelettura"
    matricola: str = "MIT0000000000001"


@dataclass
class FornituraFinta:
    """Fornitura presente sul portale simulato."""

    pdr: str
    alias: str = "Casa"
    indirizzo: str = "VIA ROMA 1, ROMA (RM)"
    venditore: str = "VENDITORE GAS S.P.A."
    matricola: str = "MIT0000000000001"
    id: str = field(default_factory=lambda: secrets.token_urlsafe(16))
    letture: list[LetturaFinta] = field(default_factory=list)


def letture_mensili(
    inizio: date = date(2022, 12, 1),
    fine: date = date(2026, 9, 30),
    matricola: str = "MIT0000000000001",
) -> list[LetturaFinta]:
    """Lettura tecnica di installazione e poi una telelettura a fine mese."""
    consumi = {1: 95, 2: 80, 3: 60, 4: 30, 5: 15, 6: 8, 7: 6, 8: 5, 9: 9, 10: 25, 11: 55, 12: 85}
    letture = [LetturaFinta(inizio, 0, "Lettura tecnica", matricola)]
    valore = 0
    giorno = inizio
    while True:
        prossimo = date(giorno.year + giorno.month // 12, giorno.month % 12 + 1, 1)
        fine_mese = prossimo - timedelta(days=1)
        if fine_mese > fine:
            break
        valore += consumi[fine_mese.month]
        letture.append(LetturaFinta(fine_mese, valore, "Telelettura", matricola))
        giorno = prossimo
    return letture


class PortaleFinto:
    """Server HTTP che si comporta come clienti.italgas.it."""

    def __init__(self) -> None:
        """Stato iniziale: un utente con una fornitura e quattro anni di letture."""
        self.utenti: dict[str, str] = {"mario.rossi": "Segreta!1"}
        self.forniture: list[FornituraFinta] = [
            FornituraFinta(pdr="01234567890123", letture=letture_mensili())
        ]
        self.data_minima = date(2022, 12, 1)
        self.giorni_massimi = 700
        self.per_pagina = 10
        # (inizio, fine) -> True se il portale deve rispondere "Errore di sistema"
        self.errore_sistema: Callable[[date, date], bool] = lambda _a, _b: False
        self.csv_rotto = False
        self.errore_http: int | None = None
        self.captcha = False
        self.scadenza_ogni: int | None = None
        self.ricerche: list[tuple[date, date]] = []
        self.accessi = 0
        self.richieste: list[str] = []
        self._sessioni: dict[str, dict] = {}
        self._contatore = itertools.count(1)
        self._server: TestServer | None = None
        self.url = ""

    # ------------------------------------------------------------------ server

    async def avvia(self) -> str:
        """Avvia il server e ritorna l'indirizzo base del portale."""
        app = web.Application(middlewares=[self._middleware])
        app.router.add_get("/clienti/login.action", self._login_pagina)
        app.router.add_post("/clienti/login.action", self._login_invio)
        app.router.add_get("/clienti/home.action", self._home)
        app.router.add_get("/clienti/elencoLettForn.action", self._forniture)
        app.router.add_get("/clienti/elencoLetture.action", self._letture)
        app.router.add_post("/clienti/ricercaLetture.action", self._ricerca)
        app.router.add_get("/clienti/ricercaLetture.action", self._ricerca_get)
        self._server = TestServer(app, host="127.0.0.1")
        await self._server.start_server(access_log=None)
        # nome host e non IP: il cookie jar di aiohttp non accetta cookie da indirizzi IP
        self.url = f"http://localhost:{self._server.port}/clienti/"
        return self.url

    async def ferma(self) -> None:
        """Ferma il server."""
        if self._server is not None:
            await self._server.close()

    @web.middleware
    async def _middleware(self, request: web.Request, handler):
        self.richieste.append(f"{request.method} {request.path}")
        if self.errore_http:
            return web.Response(status=self.errore_http, text="errore")
        return await handler(request)

    # ------------------------------------------------------------------ sessione

    def _sessione(self, request: web.Request) -> dict | None:
        sid = request.cookies.get(COOKIE)
        sessione = self._sessioni.get(sid) if sid else None
        if sessione is None:
            return None
        if self.scadenza_ogni:
            sessione["richieste"] += 1
            if sessione["richieste"] > self.scadenza_ogni:
                del self._sessioni[sid]
                return None
        return sessione

    def scadi_sessioni(self) -> None:
        """Invalida tutte le sessioni aperte."""
        self._sessioni.clear()

    def _token(self) -> str:
        return f"TOKEN{next(self._contatore):027d}"

    def _pagina(self, modello: str, **valori: str) -> web.Response:
        valori.setdefault("TOKEN", self._token())
        testo = _riempi(_fixture(modello), valori)
        testo = testo.replace("{{TOKEN}}", self._token())
        return web.Response(text=testo, content_type="text/html", charset="utf-8")

    @staticmethod
    def _al_login() -> web.Response:
        raise web.HTTPFound("/clienti/login.action")

    # ------------------------------------------------------------------ pagine

    async def _login_pagina(self, request: web.Request) -> web.Response:
        if self._sessione(request) is not None:
            raise web.HTTPFound("/clienti/home.action")
        risposta = self._pagina("login.html")
        if self.captcha:
            risposta.text = risposta.text.replace(
                "</form>", '<div class="g-recaptcha"></div></form>', 1
            )
        return risposta

    async def _login_invio(self, request: web.Request) -> web.Response:
        dati = await request.post()
        if not str(request.content_type).startswith("multipart/form-data"):
            return web.Response(status=400, text="atteso multipart")
        if not dati.get("token"):
            return web.Response(status=400, text="token mancante")
        if self.captcha:
            return await self._login_pagina(request)
        utente = str(dati.get("username", ""))
        if self.utenti.get(utente) != dati.get("password"):
            return self._pagina("login_errato.html", USERNAME=utente)
        self.accessi += 1
        sid = secrets.token_hex(16)
        self._sessioni[sid] = {"richieste": 0, "pdr": None, "ricerca": None}
        risposta = web.HTTPFound("/clienti/home.action")
        risposta.set_cookie(COOKIE, sid, path="/clienti", httponly=True)
        raise risposta

    async def _home(self, request: web.Request) -> web.Response:
        if self._sessione(request) is None:
            self._al_login()
        return self._pagina("home.html")

    async def _forniture(self, request: web.Request) -> web.Response:
        if self._sessione(request) is None:
            self._al_login()
        return self._forniture_html()

    def _forniture_html(self) -> web.Response:
        riga = _fixture("fornitura_riga.html")
        righe = "".join(
            _riempi(
                riga,
                {
                    "PARITA": "odd" if i % 2 == 0 else "even",
                    "PDR": f.pdr,
                    "ALIAS": f.alias,
                    "INDIRIZZO": f.indirizzo,
                    "VENDITORE": f.venditore,
                    "MATRICOLA": f.matricola,
                    "ID": f.id,
                    "NUM": str(100000 + i),
                    "DATA_ASSOCIAZIONE": "17/10/2026",
                },
            )
            for i, f in enumerate(self.forniture)
        )
        n = len(self.forniture)
        banner = (
            "La ricerca non ha prodotto alcun risultato"
            if n == 0
            else "Un elemento trovato."
            if n == 1
            else f"{n} elementi trovati, visualizzati tutti gli elementi."
        )
        return self._pagina("forniture.html", FORNITURE=righe, BANNER=banner)

    def _pagina_letture(
        self,
        fornitura: FornituraFinta,
        da: str = "",
        a: str = "",
        *,
        risultati: str = "",
        errore: str = "",
        errore_data: str = "",
    ) -> web.Response:
        return self._pagina(
            "letture.html",
            PDR=fornitura.pdr,
            INDIRIZZO=fornitura.indirizzo,
            VENDITORE=fornitura.venditore,
            MATRICOLA=fornitura.matricola,
            DATA_DA=da,
            DATA_A=a,
            RISULTATI=risultati,
            ERRORE=_riempi(_fixture("errore_generale.html"), {"MESSAGGIO": errore})
            if errore
            else "",
            ERRORE_DATA_DA=_riempi(_fixture("errore_campo.html"), {"MESSAGGIO": errore_data})
            if errore_data
            else "",
        )

    async def _letture(self, request: web.Request) -> web.Response:
        sessione = self._sessione(request)
        if sessione is None:
            self._al_login()
        fornitura = next((f for f in self.forniture if f.id == request.query.get("id")), None)
        if fornitura is None:
            return self._pagina("home.html")
        sessione["pdr"] = fornitura.pdr
        return self._pagina_letture(fornitura)

    def _fornitura_sessione(self, sessione: dict) -> FornituraFinta | None:
        return next((f for f in self.forniture if f.pdr == sessione.get("pdr")), None)

    async def _ricerca(self, request: web.Request) -> web.Response:
        sessione = self._sessione(request)
        if sessione is None:
            self._al_login()
        dati = await request.post()
        fornitura = self._fornitura_sessione(sessione)
        if fornitura is None:
            return self._pagina("home.html")
        testo_da, testo_a = str(dati.get("dataDa", "")), str(dati.get("dataA", ""))
        try:
            da = datetime.strptime(testo_da, "%d/%m/%Y").date()
            a = datetime.strptime(testo_a, "%d/%m/%Y").date()
        except ValueError:
            return self._pagina_letture(
                fornitura, testo_da, testo_a, errore_data="La data lettura è errata"
            )
        self.ricerche.append((da, a))
        if da < self.data_minima:
            return self._pagina_letture(
                fornitura,
                testo_da,
                testo_a,
                errore_data=MESSAGGIO_LIMITE.format(data=self.data_minima.strftime("%d/%m/%Y")),
            )
        if (a - da).days > self.giorni_massimi or self.errore_sistema(da, a):
            return self._pagina_letture(fornitura, testo_da, testo_a, errore="Errore di sistema")
        trovate = sorted(
            (x for x in fornitura.letture if da <= x.data <= a),
            key=lambda x: x.data,
            reverse=True,
        )
        sessione["ricerca"] = (testo_da, testo_a, trovate)
        return self._pagina_letture(
            fornitura,
            testo_da,
            testo_a,
            risultati=self._risultati(fornitura, testo_da, testo_a, trovate),
        )

    def _query(self, fornitura: FornituraFinta, da: str, a: str, **altro: str) -> str:
        parametri = {"dataDa": da, "dataA": a, **altro}
        parametri.update(
            {"struts.token.name": "token", "pdr": fornitura.pdr, "token": self._token()}
        )
        return "?" + urlencode(parametri).replace("&", "&amp;")

    def _risultati(
        self,
        fornitura: FornituraFinta,
        da: str,
        a: str,
        trovate: list[LetturaFinta],
        *,
        pagina: int = 1,
    ) -> str:
        n = len(trovate)
        if n == 0:
            return (
                '<div class="table-responsive"><span class="pagebanner not-found">'
                "La ricerca non ha prodotto alcun risultato</span></div>"
            )
        inizio = (pagina - 1) * self.per_pagina
        visibili = trovate[inizio : inizio + self.per_pagina]
        if n == 1:
            banner = '<span class="pagebanner"> Un elemento trovato. </span>'
        elif n <= self.per_pagina:
            banner = f'<span class="pagebanner"> {n} elementi trovati, visualizzati tutti gli elementi. </span>'
        else:
            banner = (
                f'<span class="pagebanner"> {n} elementi trovati, visualizzati da {inizio + 1} '
                f"a {inizio + len(visibili)}. </span>"
                + self._link_pagine(fornitura, da, a, pagina, n)
            )
        righe = "".join(
            f'\n<tr class="{"odd" if i % 2 == 0 else "even"}">\n<td>{x.matricola}</td>\n'
            f"<td>{x.data:%d/%m/%Y}</td>\n<td>{x.valore:g}</td>\n<td>{x.tipologia}</td></tr>"
            for i, x in enumerate(visibili)
        )
        ordina = {
            f"ORDINA_{i}": self._query(
                fornitura,
                da,
                a,
                **{f"d-{TABELLA}-p": "1", f"d-{TABELLA}-o": "2", f"d-{TABELLA}-s": str(i)},
            )
            for i in range(3)
        }
        return _riempi(
            _fixture("risultati.html"),
            {
                "BANNER": banner,
                "RIGHE": righe,
                "EXPORT_CSV": self._query(
                    fornitura, da, a, **{"6578706f7274": "1", f"d-{TABELLA}-e": "1"}
                ),
                "EXPORT_XLS": self._query(
                    fornitura, da, a, **{"6578706f7274": "1", f"d-{TABELLA}-e": "2"}
                ),
                **ordina,
            },
        )

    def _link_pagine(self, fornitura: FornituraFinta, da: str, a: str, attuale: int, n: int) -> str:
        pagine = (n + self.per_pagina - 1) // self.per_pagina
        link = "".join(
            f'<span class="pl-page selected"><strong>{p}</strong></span>'
            if p == attuale
            else f'<span class="pl-page"><a href="{self._query(fornitura, da, a, **{f"d-{TABELLA}-p": str(p)})}"'
            f'  title="Vai a pagina {p}">{p}</a></span>'
            for p in range(1, pagine + 1)
        )
        return (
            '<div class="pagelinks"><ul class="pagination d-flex justify-content-between">'
            f'<li class="pagination_current">Pagina {attuale}</li> '
            f'<li class="paginate_button center"> {link} </li></ul></div>'
        )

    async def _ricerca_get(self, request: web.Request) -> web.Response:
        sessione = self._sessione(request)
        if sessione is None:
            self._al_login()
        fornitura = self._fornitura_sessione(sessione)
        if fornitura is None or sessione.get("ricerca") is None:
            return self._pagina("home.html")
        da, a, trovate = sessione["ricerca"]
        if request.query.get("6578706f7274") == "1":
            if self.csv_rotto:
                return self._pagina("home.html")
            righe = ["Matricola contatore;Data Lettura;Lettura;Tipologia lettura"] + [
                f"{x.matricola};{x.data:%d/%m/%Y};{float(x.valore):.1f};{x.tipologia}"
                for x in trovate
            ]
            return web.Response(
                body=("﻿" + "\n".join(righe) + "\n").encode("utf-8"),
                content_type="text/csv",
                charset="UTF-8",
                headers={"Content-Disposition": 'attachment; filename="dati_lettura.csv"'},
            )
        pagina = int(request.query.get(f"d-{TABELLA}-p", "1"))
        return self._pagina_letture(
            fornitura, da, a, risultati=self._risultati(fornitura, da, a, trovate, pagina=pagina)
        )
