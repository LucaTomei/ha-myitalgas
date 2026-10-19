"""Lettura delle pagine HTML del portale MyItalgas.

Usa solo la libreria standard (html.parser): nessuna dipendenza esterna.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
import csv
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
import io
import re

_VUOTI = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
# Tag che il browser chiude in automatico quando ne inizia uno "fratello".
_CHIUSURA_IMPLICITA: dict[str, frozenset[str]] = {
    "tr": frozenset({"td", "th", "tr"}),
    "td": frozenset({"td", "th"}),
    "th": frozenset({"td", "th"}),
    "li": frozenset({"li"}),
    "option": frozenset({"option"}),
    "p": frozenset({"p"}),
}
_SENZA_TESTO = frozenset({"script", "style", "template", "noscript"})

RE_PDR = re.compile(r"\b(\d{14})\b")
RE_DATA = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")
RE_PAGINA = re.compile(r"d-\d+-p=(\d+)")


class Nodo:
    """Elemento di un albero HTML minimale."""

    __slots__ = ("attrs", "figli", "padre", "tag")

    def __init__(self, tag: str, attrs: dict[str, str], padre: Nodo | None) -> None:
        """Crea il nodo."""
        self.tag = tag
        self.attrs = attrs
        self.padre = padre
        self.figli: list[Nodo | str] = []

    def get(self, nome: str, default: str = "") -> str:
        """Valore di un attributo."""
        return self.attrs.get(nome, default)

    @property
    def classi(self) -> set[str]:
        """Classi CSS dell'elemento."""
        return set(self.get("class").split())

    def _pezzi_testo(self) -> Iterator[str]:
        for figlio in self.figli:
            if isinstance(figlio, str):
                yield figlio
            elif figlio.tag not in _SENZA_TESTO:
                yield from figlio._pezzi_testo()

    @property
    def testo(self) -> str:
        """Testo contenuto, con gli spazi normalizzati."""
        return " ".join(" ".join(self._pezzi_testo()).split())

    def discendenti(self) -> Iterator[Nodo]:
        """Tutti gli elementi discendenti, in ordine di documento."""
        for figlio in self.figli:
            if isinstance(figlio, Nodo):
                yield figlio
                yield from figlio.discendenti()

    def trova_tutti(self, criterio: Callable[[Nodo], bool]) -> list[Nodo]:
        """Discendenti che soddisfano il criterio."""
        return [n for n in self.discendenti() if criterio(n)]

    def trova(self, criterio: Callable[[Nodo], bool]) -> Nodo | None:
        """Primo discendente che soddisfa il criterio."""
        return next((n for n in self.discendenti() if criterio(n)), None)

    def antenati(self) -> Iterator[Nodo]:
        """Elementi contenitori, dal più vicino alla radice."""
        nodo = self.padre
        while nodo is not None:
            yield nodo
            nodo = nodo.padre


class _Costruttore(HTMLParser):
    """Costruisce un albero di Nodo tollerando l'HTML non perfettamente chiuso."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.radice = Nodo("#documento", {}, None)
        self._pila: list[Nodo] = [self.radice]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        chiude = _CHIUSURA_IMPLICITA.get(tag)
        if chiude:
            while len(self._pila) > 1 and self._pila[-1].tag in chiude:
                self._pila.pop()
        nodo = Nodo(tag, {k: v or "" for k, v in attrs}, self._pila[-1])
        self._pila[-1].figli.append(nodo)
        if tag not in _VUOTI:
            self._pila.append(nodo)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        nodo = Nodo(tag, {k: v or "" for k, v in attrs}, self._pila[-1])
        self._pila[-1].figli.append(nodo)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self._pila) - 1, 0, -1):
            if self._pila[i].tag == tag:
                del self._pila[i:]
                return

    def handle_data(self, data: str) -> None:
        self._pila[-1].figli.append(data)


def analizza(html: str) -> Nodo:
    """Trasforma una pagina HTML in un albero di Nodo."""
    costruttore = _Costruttore()
    costruttore.feed(html)
    costruttore.close()
    return costruttore.radice


# --------------------------------------------------------------------------- modelli


@dataclass(frozen=True, slots=True)
class Fornitura:
    """Fornitura (PDR) associata al profilo MyItalgas."""

    pdr: str
    link: str
    alias: str = ""
    indirizzo: str = ""
    venditore: str = ""
    matricola: str = ""


@dataclass(frozen=True, slots=True)
class Lettura:
    """Lettura del contatore."""

    data: date
    valore: float
    tipologia: str
    matricola: str

    def come_dict(self) -> dict[str, str | float]:
        """Rappresentazione serializzabile in JSON."""
        return {
            "data": self.data.isoformat(),
            "valore": self.valore,
            "tipologia": self.tipologia,
            "matricola": self.matricola,
        }

    @classmethod
    def da_dict(cls, dati: dict) -> Lettura:
        """Ricostruisce una lettura salvata con come_dict."""
        return cls(
            data=date.fromisoformat(dati["data"]),
            valore=float(dati["valore"]),
            tipologia=str(dati.get("tipologia", "")),
            matricola=str(dati.get("matricola", "")),
        )


@dataclass(frozen=True, slots=True)
class Modulo:
    """Form HTML: indirizzo di invio e campi che il browser invierebbe."""

    azione: str
    campi: dict[str, str]


@dataclass(slots=True)
class PaginaLetture:
    """Contenuto della pagina dei risultati di una ricerca letture."""

    letture: list[Lettura]
    totale: int | None
    errori: list[str]
    link_csv: str | None
    link_pagine: dict[int, str]


# --------------------------------------------------------------------------- pagine


def e_autenticato(html: str) -> bool:
    """Vero se la pagina è di un utente autenticato (c'è il link di uscita)."""
    return "logout.action" in html


def modulo(radice: Nodo, id_form: str) -> Modulo | None:
    """Form con l'id indicato, con i campi che il browser invierebbe."""
    form = radice.trova(lambda n: n.tag == "form" and n.get("id") == id_form)
    if form is None:
        return None
    campi: dict[str, str] = {}
    for campo in form.trova_tutti(lambda n: n.tag in ("input", "select", "textarea")):
        nome = campo.get("name")
        if not nome:
            continue
        tipo = campo.get("type", "text").lower()
        if tipo in ("submit", "button", "image", "reset", "file"):
            continue
        if tipo in ("checkbox", "radio") and "checked" not in campo.attrs:
            continue
        if campo.tag == "select":
            scelta = campo.trova(lambda n: n.tag == "option" and "selected" in n.attrs)
            scelta = scelta or campo.trova(lambda n: n.tag == "option")
            campi[nome] = (scelta.get("value", scelta.testo)) if scelta else ""
        elif campo.tag == "textarea":
            campi[nome] = campo.testo
        else:
            campi[nome] = campo.get("value")
    return Modulo(azione=form.get("action").strip(), campi=campi)


def messaggi_errore(radice: Nodo) -> list[str]:
    """Messaggi d'errore mostrati dal portale (generali e sui singoli campi)."""
    messaggi: list[str] = []
    for nodo in radice.discendenti():
        if (
            (
                nodo.classi & {"alert-danger", "errorMessage", "actionError"}
                or nodo.get("id").endswith("FieldError")
            )
            and (testo := nodo.testo)
            and testo not in messaggi
        ):
            messaggi.append(testo)
    return messaggi


def forniture(radice: Nodo) -> list[Fornitura]:
    """Elenco delle forniture nella pagina "Le mie letture"."""
    trovate: dict[str, Fornitura] = {}
    for link in radice.trova_tutti(
        lambda n: n.tag == "a" and "elencoLetture.action" in n.get("href")
    ):
        contenitore = next((a for a in link.antenati() if RE_PDR.search(a.testo)), None)
        if contenitore is None:
            continue
        testo = contenitore.testo
        pdr = RE_PDR.search(testo).group(1)  # type: ignore[union-attr]
        if pdr in trovate:
            continue
        alias = contenitore.trova(lambda n: "viewDesc" in n.classi)
        titoli = [
            n.testo
            for n in contenitore.trova_tutti(lambda n: n.tag in ("h4", "h5"))
            if n.testo and not RE_PDR.search(n.testo)
        ]
        sottotitoli = [
            n.testo
            for n in contenitore.trova_tutti(
                lambda n: "card-subtitle" in n.classi and "viewDesc" not in n.classi
            )
            if n.testo
        ]
        matricola = re.search(r"Matricola contatore\s+(\S+)", testo)
        trovate[pdr] = Fornitura(
            pdr=pdr,
            link=link.get("href").strip(),
            alias=alias.testo if alias else "",
            indirizzo=titoli[0] if titoli else "",
            venditore=sottotitoli[0] if sottotitoli else "",
            matricola=matricola.group(1) if matricola else "",
        )
    return list(trovate.values())


def numero(testo: str) -> float:
    """Converte un valore numerico del portale (es. "1637", "1637.0", "1.637,5")."""
    pulito = testo.strip().replace(" ", "").replace("\xa0", "")
    if "," in pulito:
        pulito = pulito.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", pulito):
        pulito = pulito.replace(".", "")
    return float(pulito)


def _indici_colonne(intestazioni: list[str]) -> dict[str, int]:
    indici = {"matricola": 0, "data": 1, "lettura": 2, "tipologia": 3}
    for chiave in indici:
        for i, testo in enumerate(intestazioni):
            if testo.strip().lower().startswith(chiave):
                indici[chiave] = i
                break
    return indici


def _letture_da_righe(intestazioni: list[str], righe: list[list[str]]) -> list[Lettura]:
    indici = _indici_colonne(intestazioni)
    letture: list[Lettura] = []
    for celle in righe:
        try:
            giorno = datetime.strptime(celle[indici["data"]].strip(), "%d/%m/%Y").date()
            valore = numero(celle[indici["lettura"]])
        except (ValueError, IndexError):
            continue
        letture.append(
            Lettura(
                data=giorno,
                valore=valore,
                tipologia=_cella(celle, indici["tipologia"]),
                matricola=_cella(celle, indici["matricola"]),
            )
        )
    return letture


def _cella(celle: list[str], indice: int) -> str:
    return celle[indice].strip() if indice < len(celle) else ""


def _totale(radice: Nodo) -> int | None:
    banner = radice.trova(lambda n: "pagebanner" in n.classi)
    if banner is None:
        return None
    testo = banner.testo.lower()
    if m := re.search(r"(\d+)\s+elementi", testo):
        return int(m.group(1))
    if "un elemento" in testo:
        return 1
    if "nessun" in testo or "non ha prodotto" in testo:
        return 0
    return None


def pagina_letture(radice: Nodo) -> PaginaLetture:
    """Analizza la pagina dei risultati della ricerca letture."""
    tabella = radice.trova(lambda n: n.tag == "table" and n.get("id") == "itemList")
    if tabella is None:
        tabella = radice.trova(lambda n: n.tag == "table" and "Data Lettura" in n.testo)
    letture: list[Lettura] = []
    if tabella is not None:
        intestazioni = [n.testo for n in tabella.trova_tutti(lambda n: n.tag == "th")]
        corpo = tabella.trova(lambda n: n.tag == "tbody") or tabella
        righe = [
            [td.testo for td in tr.trova_tutti(lambda n: n.tag == "td")]
            for tr in corpo.trova_tutti(lambda n: n.tag == "tr")
        ]
        letture = _letture_da_righe(intestazioni, righe)

    link_csv = None
    pagine: dict[int, str] = {}
    for a in radice.trova_tutti(lambda n: n.tag == "a" and n.get("href")):
        href = a.get("href")
        if "6578706f7274=1" in href and re.search(r"d-\d+-e=1\b", href):
            link_csv = link_csv or href
        elif (m := RE_PAGINA.search(href)) and not re.search(r"d-\d+-[so]=", href):
            pagine.setdefault(int(m.group(1)), href)

    return PaginaLetture(
        letture=letture,
        totale=_totale(radice),
        errori=messaggi_errore(radice),
        link_csv=link_csv,
        link_pagine=pagine,
    )


def letture_csv(testo: str) -> list[Lettura] | None:
    """Analizza l'export CSV del portale. None se il contenuto non è un CSV letture."""
    righe = list(csv.reader(io.StringIO(testo.lstrip("﻿")), delimiter=";"))
    if not righe or not any("data" in c.lower() for c in righe[0]):
        return None
    return _letture_da_righe(righe[0], [r for r in righe[1:] if any(c.strip() for c in r)])


def data_minima(errori: list[str]) -> date | None:
    """Data minima consultabile, se il portale segnala che quella chiesta è troppo vecchia."""
    for messaggio in errori:
        if "limite inferiore" in messaggio.lower() and (date_trovate := RE_DATA.findall(messaggio)):
            try:
                return datetime.strptime(date_trovate[-1], "%d/%m/%Y").date()
            except ValueError:
                return None
    return None
