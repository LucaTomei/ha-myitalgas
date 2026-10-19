"""Client per il portale clienti MyItalgas (clienti.italgas.it)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
import logging
from typing import Any
from urllib.parse import urljoin

import aiohttp

from . import parser
from .const import PORTALE_URL
from .parser import Fornitura, Lettura, Nodo, PaginaLetture

_LOGGER = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
_INTESTAZIONI = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.5",
}
_TIMEOUT = aiohttp.ClientTimeout(total=60)

# Il portale va in "Errore di sistema" su intervalli di circa due anni:
# si cerca a blocchi di un anno, dimezzandoli in caso di errore.
GIORNI_BLOCCO = 365
GIORNI_BLOCCO_MIN = 31
# Data da cui partire quando non si conosce l'inizio dello storico: il portale
# risponde indicando la data minima consultabile e la ricerca riparte da lì.
INIZIO_STORICO = date(2000, 1, 1)
_MAX_ERRORI_DI_FILA = 6
# nuovi accessi consecutivi senza riuscire a completare nemmeno una ricerca
_MAX_NUOVI_ACCESSI = 2
_PAROLE_CREDENZIALI = ("password", "username", "credenzial", "utente")


class ItalgasError(Exception):
    """Errore generico del client MyItalgas."""


class ItalgasAuthError(ItalgasError):
    """Credenziali rifiutate dal portale."""


class ItalgasConnectionError(ItalgasError):
    """Portale non raggiungibile."""


class ItalgasPortalError(ItalgasError):
    """Il portale ha risposto in modo inatteso."""


class ItalgasPdrNotFoundError(ItalgasPortalError):
    """Il PDR non è associato al profilo."""


class _SessioneScaduta(Exception):
    """La sessione sul portale non è più valida."""


@dataclass(slots=True)
class RisultatoLetture:
    """Esito di uno scaricamento delle letture."""

    letture: list[Lettura]
    mancanti: list[tuple[date, date]] = field(default_factory=list)
    data_minima: date | None = None


def blocchi(inizio: date, fine: date, giorni: int) -> Iterator[tuple[date, date]]:
    """Divide [inizio, fine] in intervalli consecutivi di al massimo `giorni` giorni."""
    while inizio <= fine:
        termine = min(inizio + timedelta(days=giorni - 1), fine)
        yield inizio, termine
        inizio = termine + timedelta(days=1)


class ItalgasClient:
    """Accesso al portale MyItalgas tramite semplici richieste HTTP."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        base_url: str | None = None,
    ) -> None:
        """Inizializza il client. La sessione deve avere un proprio cookie jar."""
        self._session = session
        self._username = username
        self._password = password
        base = base_url or PORTALE_URL
        self._base = base if base.endswith("/") else base + "/"

    # ------------------------------------------------------------------ HTTP

    async def _richiesta(
        self, metodo: str, url: str, dati: dict[str, str] | None = None
    ) -> tuple[str, str]:
        """Esegue una richiesta e ritorna (url finale, testo della risposta)."""
        kwargs: dict[str, Any] = {"headers": _INTESTAZIONI, "timeout": _TIMEOUT}
        if dati is not None:
            # come il browser: multipart/form-data
            kwargs["data"] = aiohttp.FormData(dati, default_to_multipart=True)
            kwargs["headers"] = {**_INTESTAZIONI, "Referer": url}
        try:
            async with self._session.request(metodo, url, **kwargs) as risposta:
                testo = await risposta.text(errors="replace")
                if risposta.status >= 500:
                    raise ItalgasConnectionError(
                        f"il portale ha risposto con errore HTTP {risposta.status}"
                    )
                if risposta.status >= 400:
                    raise ItalgasPortalError(
                        f"il portale ha risposto con errore HTTP {risposta.status}"
                    )
                return str(risposta.url), testo
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ItalgasConnectionError(
                f"portale MyItalgas non raggiungibile: {str(err) or type(err).__name__}"
            ) from err

    def _url(self, percorso: str, rispetto_a: str | None = None) -> str:
        return urljoin(rispetto_a or self._base, percorso)

    # ------------------------------------------------------------------ accesso

    async def login(self) -> None:
        """Accede al portale con le credenziali configurate."""
        url, html = await self._richiesta("GET", self._url("login.action"))
        if parser.e_autenticato(html):
            return
        radice = parser.analizza(html)
        form = parser.modulo(radice, "headerLogin")
        if form is None or "username" not in form.campi or "password" not in form.campi:
            raise ItalgasPortalError("modulo di accesso del portale non riconosciuto")
        dati = {**form.campi, "username": self._username, "password": self._password}
        url, html = await self._richiesta(
            "POST", self._url(form.azione or "login.action", url), dati
        )
        if parser.e_autenticato(html):
            _LOGGER.debug("Accesso al portale MyItalgas effettuato")
            return
        radice = parser.analizza(html)
        errori = parser.messaggi_errore(radice)
        if any(p in e.lower() for e in errori for p in _PAROLE_CREDENZIALI):
            raise ItalgasAuthError(errori[0])
        if "captcha" in html.lower():
            raise ItalgasPortalError("il portale richiede un captcha per l'accesso")
        if errori:
            raise ItalgasPortalError(f"accesso non riuscito: {errori[0]}")
        raise ItalgasPortalError("accesso non riuscito: risposta inattesa del portale")

    async def _pagina_protetta(self, url: str) -> tuple[str, str]:
        """Apre una pagina riservata, rifacendo l'accesso se la sessione è scaduta."""
        url_finale, html = await self._richiesta("GET", url)
        if parser.e_autenticato(html):
            return url_finale, html
        await self.login()
        url_finale, html = await self._richiesta("GET", url)
        if not parser.e_autenticato(html):
            raise ItalgasPortalError("sessione non valida dopo l'accesso")
        return url_finale, html

    # ------------------------------------------------------------------ dati

    async def forniture(self) -> list[Fornitura]:
        """Forniture (PDR) associate al profilo."""
        _, html = await self._pagina_protetta(self._url("elencoLettForn.action"))
        return parser.forniture(parser.analizza(html))

    async def _apri_pdr(self, pdr: str) -> tuple[str, Nodo]:
        """Apre la pagina delle letture del PDR. Ritorna (url, pagina)."""
        fornitura = next((f for f in await self.forniture() if f.pdr == pdr), None)
        if fornitura is None:
            raise ItalgasPdrNotFoundError(f"il PDR {pdr} non è associato al profilo MyItalgas")
        url, html = await self._pagina_protetta(self._url(fornitura.link))
        radice = parser.analizza(html)
        if parser.modulo(radice, "ricercaLetture") is None:
            raise ItalgasPortalError("pagina delle letture non riconosciuta")
        return url, radice

    async def _cerca(
        self, url: str, pagina: Nodo, inizio: date, fine: date
    ) -> tuple[str, Nodo, PaginaLetture]:
        """Esegue la ricerca letture nell'intervallo, partendo dalla pagina corrente."""
        form = parser.modulo(pagina, "ricercaLetture")
        if form is None:
            raise _SessioneScaduta
        dati = {
            **form.campi,
            "dataDa": inizio.strftime("%d/%m/%Y"),
            "dataA": fine.strftime("%d/%m/%Y"),
        }
        url, html = await self._richiesta(
            "POST", self._url(form.azione or "ricercaLetture.action", url), dati
        )
        if not parser.e_autenticato(html):
            raise _SessioneScaduta
        radice = parser.analizza(html)
        return url, radice, parser.pagina_letture(radice)

    async def _tutte_le_righe(self, url: str, risultati: PaginaLetture) -> list[Lettura]:
        """Letture di tutte le pagine dei risultati (export CSV, o pagina per pagina)."""
        totale = risultati.totale or 0
        if risultati.link_csv:
            _, testo = await self._richiesta("GET", self._url(risultati.link_csv, url))
            letture = parser.letture_csv(testo)
            if letture is not None and len(letture) >= totale:
                return letture
            _LOGGER.debug("Export CSV non utilizzabile, lettura pagina per pagina")

        letture = list(risultati.letture)
        visitate = {1}
        da_visitare = dict(risultati.link_pagine)
        while da_visitare:
            numero = min(da_visitare)
            href = da_visitare.pop(numero)
            if numero in visitate:
                continue
            visitate.add(numero)
            _, html = await self._richiesta("GET", self._url(href, url))
            if not parser.e_autenticato(html):
                raise _SessioneScaduta
            pagina = parser.pagina_letture(parser.analizza(html))
            letture.extend(pagina.letture)
            for n, h in pagina.link_pagine.items():
                if n not in visitate:
                    da_visitare.setdefault(n, h)
        return letture

    async def scarica_letture(self, pdr: str, inizio: date | None, fine: date) -> RisultatoLetture:
        """Scarica le letture del PDR tra `inizio` (None = tutto lo storico) e `fine`."""
        url, pagina = await self._apri_pdr(pdr)
        trovate: dict[tuple[date, str], Lettura] = {}
        mancanti: list[tuple[date, date]] = []
        minima: date | None = None
        coda = list(blocchi(inizio or INIZIO_STORICO, fine, GIORNI_BLOCCO))
        errori_di_fila = 0
        nuovi_accessi = 0

        while coda:
            da, a = coda.pop(0)
            try:
                url, pagina, risultati = await self._cerca(url, pagina, da, a)
                letture = risultati.letture
                if risultati.totale is not None and risultati.totale > len(letture):
                    letture = await self._tutte_le_righe(url, risultati)
            except _SessioneScaduta:
                nuovi_accessi += 1
                if nuovi_accessi > _MAX_NUOVI_ACCESSI:
                    raise ItalgasPortalError("la sessione del portale scade di continuo") from None
                _LOGGER.debug("Sessione scaduta, nuovo accesso dal %s", da)
                await self.login()
                url, pagina = await self._apri_pdr(pdr)
                coda.insert(0, (da, a))
                continue

            if risultati.errori and not letture:
                nuova_minima = parser.data_minima(risultati.errori)
                if nuova_minima is not None and nuova_minima > da:
                    minima = nuova_minima
                    _LOGGER.debug("Storico disponibile dal %s", minima)
                    coda = list(blocchi(minima, fine, GIORNI_BLOCCO))
                    continue
                errori_di_fila += 1
                if errori_di_fila >= _MAX_ERRORI_DI_FILA:
                    raise ItalgasPortalError(
                        f"il portale continua a rispondere: {risultati.errori[0]}"
                    )
                giorni = (a - da).days + 1
                if giorni > GIORNI_BLOCCO_MIN:
                    meta = da + timedelta(days=giorni // 2)
                    coda[:0] = [(da, meta - timedelta(days=1)), (meta, a)]
                    _LOGGER.debug("%s-%s: %s, divido il periodo", da, a, risultati.errori[0])
                else:
                    _LOGGER.warning(
                        "Letture dal %s al %s non scaricate: %s", da, a, risultati.errori[0]
                    )
                    mancanti.append((da, a))
                continue

            errori_di_fila = 0
            nuovi_accessi = 0
            _LOGGER.debug("%s-%s: %d letture", da, a, len(letture))
            for lettura in letture:
                trovate[(lettura.data, lettura.matricola)] = lettura

        return RisultatoLetture(
            letture=sorted(trovate.values(), key=lambda x: x.data),
            mancanti=mancanti,
            data_minima=minima,
        )
