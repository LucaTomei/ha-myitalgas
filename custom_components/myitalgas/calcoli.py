"""Calcolo di consumi, costi e statistiche a partire dalle letture del contatore."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from itertools import pairwise
import math

from .parser import Lettura

# Scaglioni annui di consumo (Smc dal 1° gennaio) su cui variano accisa,
# addizionale regionale, oneri e IVA: fino a 120, da 121 a 480, oltre 480.
SOGLIE_SCAGLIONI: tuple[float, float] = (120.0, 480.0)
# Temperatura di riferimento dei gradi giorno (DPR 412/1993).
TEMPERATURA_GRADI_GIORNO = 20.0
# Quota minima di giorni con temperatura nota per usare i gradi giorno in un periodo.
COPERTURA_MINIMA_TEMPERATURE = 0.8
# Periodi più brevi non bastano a stimare il consumo di base (cottura, acqua calda).
GIORNI_MINIMI_CONSUMO_BASE = 20


class Distribuzione(StrEnum):
    """Come distribuire nel tempo il consumo tra due letture."""

    GIORNALIERA = "giornaliera"
    GRADI_GIORNO = "gradi_giorno"
    LETTURA = "lettura"


@dataclass(frozen=True, slots=True)
class Periodo:
    """Consumo tra due letture consecutive dello stesso contatore."""

    inizio: Lettura
    fine: Lettura

    @property
    def consumo(self) -> float:
        """Metri cubi consumati nel periodo."""
        return round(self.fine.valore - self.inizio.valore, 3)

    @property
    def giorni(self) -> int:
        """Durata del periodo in giorni."""
        return (self.fine.data - self.inizio.data).days

    @property
    def media_giornaliera(self) -> float | None:
        """Consumo medio al giorno (m³/giorno)."""
        return self.consumo / self.giorni if self.giorni > 0 else None

    def date(self) -> list[date]:
        """Giorni coperti dal periodo: dal giorno dopo la lettura iniziale a quello della finale."""
        return [self.inizio.data + timedelta(days=i) for i in range(1, self.giorni + 1)]


@dataclass(frozen=True, slots=True)
class Tariffa:
    """Prezzi in vigore da una certa data (IVA e imposte incluse)."""

    dal: date
    prezzo_sc1: float
    prezzo_sc2: float
    prezzo_sc3: float
    quota_fissa: float = 0.0  # €/mese

    def prezzo(self, cumulato_smc: float) -> float:
        """Prezzo dello scaglione in cui cade il prossimo Smc dato il consumo dell'anno."""
        if cumulato_smc < SOGLIE_SCAGLIONI[0]:
            return self.prezzo_sc1
        if cumulato_smc < SOGLIE_SCAGLIONI[1]:
            return self.prezzo_sc2
        return self.prezzo_sc3

    def costo_variabile(self, cumulato_smc: float, smc: float) -> float:
        """Costo di `smc` Smc consumati partendo da `cumulato_smc` Smc nell'anno.

        Se il consumo attraversa una soglia viene diviso pro quota tra gli scaglioni.
        Un valore negativo (rettifica) restituisce il costo corrispondente in negativo.
        """
        if smc < 0:
            return -self.costo_variabile(max(cumulato_smc + smc, 0.0), -smc)
        costo = 0.0
        posizione = cumulato_smc
        resto = smc
        for limite, prezzo in (
            (SOGLIE_SCAGLIONI[0], self.prezzo_sc1),
            (SOGLIE_SCAGLIONI[1], self.prezzo_sc2),
            (math.inf, self.prezzo_sc3),
        ):
            if resto <= 0:
                break
            if posizione < limite:
                quota = min(resto, limite - posizione)
                costo += quota * prezzo
                resto -= quota
                posizione += quota
        return costo

    def quota_fissa_giornaliera(self, giorno: date) -> float:
        """Quota fissa di un giorno: dodici mensilità divise sui giorni dell'anno."""
        giorni_anno = 366 if _bisestile(giorno.year) else 365
        return self.quota_fissa * 12 / giorni_anno


@dataclass(frozen=True, slots=True)
class Giorno:
    """Consumo e costo stimati di un giorno."""

    data: date
    m3: float
    smc: float
    costo_variabile: float | None = None
    costo_fisso: float | None = None

    @property
    def costo(self) -> float | None:
        """Costo totale del giorno (None se nessuna tariffa era in vigore)."""
        if self.costo_variabile is None or self.costo_fisso is None:
            return None
        return self.costo_variabile + self.costo_fisso


@dataclass(frozen=True, slots=True)
class PuntoStatistica:
    """Valore cumulato in un giorno, per le statistiche a lungo termine."""

    data: date
    somma: float
    lettura: float | None = None


def _bisestile(anno: int) -> bool:
    return anno % 4 == 0 and (anno % 100 != 0 or anno % 400 == 0)


# --------------------------------------------------------------------------- letture


def ordina(letture: Iterable[Lettura]) -> list[Lettura]:
    """Ordina per data. A parità di data (sostituzione del contatore) mette prima
    la lettura del contatore in uso fino a quel momento."""
    per_data: dict[date, list[Lettura]] = {}
    for lettura in letture:
        per_data.setdefault(lettura.data, []).append(lettura)
    ordinate: list[Lettura] = []
    for giorno in sorted(per_data):
        gruppo = sorted(per_data[giorno], key=lambda x: (x.matricola, x.valore))
        if ordinate and len(gruppo) > 1:
            attuale = ordinate[-1].matricola
            gruppo.sort(key=lambda x: x.matricola != attuale)
        ordinate.extend(gruppo)
    return ordinate


def periodi(letture: list[Lettura]) -> list[Periodo]:
    """Periodi tra letture consecutive (già ordinate) dello stesso contatore."""
    return [
        Periodo(prec, succ)
        for prec, succ in pairwise(letture)
        if prec.matricola == succ.matricola and succ.data > prec.data
    ]


# --------------------------------------------------------------------------- ripartizione


def consumo_base(lista_periodi: list[Periodo]) -> float:
    """Consumo giornaliero indipendente dal riscaldamento (cottura, acqua calda).

    Stimato come la media giornaliera più bassa tra i periodi abbastanza lunghi:
    è quella dei mesi senza riscaldamento.
    """
    medie = [
        p.consumo / p.giorni
        for p in lista_periodi
        if p.giorni >= GIORNI_MINIMI_CONSUMO_BASE and p.consumo >= 0
    ]
    return min(medie) if medie else 0.0


def gradi_giorno(temperatura_media: float) -> float:
    """Gradi giorno di una giornata con la temperatura esterna media indicata."""
    return max(0.0, TEMPERATURA_GRADI_GIORNO - temperatura_media)


def _ripartisci_periodo(
    periodo: Periodo, temperature: Mapping[date, float] | None, base: float
) -> list[tuple[date, float]]:
    giorni = periodo.date()
    if not giorni:
        return []
    totale = periodo.consumo
    lineare = [(g, totale / len(giorni)) for g in giorni]
    if not temperature or totale <= 0:
        return lineare
    note = {g: gradi_giorno(temperature[g]) for g in giorni if g in temperature}
    if len(note) < COPERTURA_MINIMA_TEMPERATURE * len(giorni):
        return lineare
    media_note = sum(note.values()) / len(note)
    gg = {g: note.get(g, media_note) for g in giorni}
    totale_gg = sum(gg.values())
    quota_base = min(base, totale / len(giorni))
    riscaldamento = totale - quota_base * len(giorni)
    if totale_gg <= 0 or riscaldamento <= 0:
        return lineare
    return [(g, quota_base + riscaldamento * gg[g] / totale_gg) for g in giorni]


def consumi_giornalieri(
    lista_periodi: list[Periodo], temperature: Mapping[date, float] | None = None
) -> dict[date, float]:
    """Consumo stimato (m³) di ogni giorno coperto dalle letture.

    Senza temperature il consumo di ogni periodo è ripartito in parti uguali sui suoi
    giorni. Con le temperature medie giornaliere (°C) si separa il consumo di base,
    uguale ogni giorno, e il resto è ripartito in proporzione ai gradi giorno.
    In ogni caso la somma dei giorni coincide con il consumo del periodo.
    """
    base = consumo_base(lista_periodi) if temperature else 0.0
    consumi: dict[date, float] = {}
    for periodo in lista_periodi:
        for giorno, valore in _ripartisci_periodo(periodo, temperature, base):
            consumi[giorno] = consumi.get(giorno, 0.0) + valore
    return dict(sorted(consumi.items()))


# --------------------------------------------------------------------------- costi


def tariffa_in_vigore(tariffe: list[Tariffa], giorno: date) -> Tariffa | None:
    """Tariffa valida nel giorno indicato (l'ultima con decorrenza non successiva)."""
    valida = None
    for tariffa in sorted(tariffe, key=lambda t: t.dal):
        if tariffa.dal > giorno:
            break
        valida = tariffa
    return valida


def calcola_giorni(
    letture: list[Lettura],
    coefficiente: float,
    tariffe: list[Tariffa],
    temperature: Mapping[date, float] | None = None,
) -> list[Giorno]:
    """Consumi e costi di ogni giorno tra la prima e l'ultima lettura.

    Il costo variabile usa il prezzo della tariffa in vigore e dello scaglione in cui
    cade il consumo, calcolato sugli Smc cumulati dal 1° gennaio; la quota fissa è
    ripartita su ogni giorno.
    """
    if len(letture) < 2:
        return []
    consumi = consumi_giornalieri(periodi(letture), temperature)
    primo, ultimo = letture[0].data, letture[-1].data
    giorni: list[Giorno] = []
    cumulato = 0.0
    anno = None
    giorno = primo + timedelta(days=1)
    while giorno <= ultimo:
        if giorno.year != anno:
            anno, cumulato = giorno.year, 0.0
        m3 = consumi.get(giorno, 0.0)
        smc = m3 * coefficiente
        tariffa = tariffa_in_vigore(tariffe, giorno)
        if tariffa is None:
            giorni.append(Giorno(giorno, m3, smc))
        else:
            giorni.append(
                Giorno(
                    giorno,
                    m3,
                    smc,
                    costo_variabile=tariffa.costo_variabile(cumulato, smc),
                    costo_fisso=tariffa.quota_fissa_giornaliera(giorno),
                )
            )
        cumulato = max(cumulato + smc, 0.0)
        giorno += timedelta(days=1)
    return giorni


def consumo_anno(giorni: list[Giorno], anno: int) -> float | None:
    """m³ consumati nell'anno (i periodi a cavallo di due anni sono divisi pro quota)."""
    valori = [g.m3 for g in giorni if g.data.year == anno]
    return round(sum(valori), 3) if valori else None


def smc_anno(giorni: list[Giorno], anno: int) -> float | None:
    """Smc consumati nell'anno."""
    valori = [g.smc for g in giorni if g.data.year == anno]
    return round(sum(valori), 3) if valori else None


def costo_anno(giorni: list[Giorno], anno: int) -> float | None:
    """Costo stimato dei giorni dell'anno coperti da una tariffa."""
    valori = [c for g in giorni if g.data.year == anno and (c := g.costo) is not None]
    return round(sum(valori), 2) if valori else None


def prezzo_marginale(giorni: list[Giorno], tariffe: list[Tariffa], oggi: date) -> float | None:
    """€/Smc del prossimo Smc: tariffa in vigore oggi, scaglione raggiunto quest'anno."""
    if (tariffa := tariffa_in_vigore(tariffe, oggi)) is None:
        return None
    cumulato = sum(g.smc for g in giorni if g.data.year == oggi.year and g.data <= oggi)
    return tariffa.prezzo(max(cumulato, 0.0))


def scaglione(cumulato_smc: float) -> int:
    """Numero dello scaglione (1, 2, 3) in cui cade il prossimo Smc."""
    if cumulato_smc < SOGLIE_SCAGLIONI[0]:
        return 1
    if cumulato_smc < SOGLIE_SCAGLIONI[1]:
        return 2
    return 3


# --------------------------------------------------------------------------- statistiche


def punti_consumo(
    letture: list[Lettura], giorni: list[Giorno], distribuzione: Distribuzione, in_smc: bool
) -> list[PuntoStatistica]:
    """Consumo cumulato da esportare nella statistica, partendo da zero.

    Con la distribuzione giornaliera c'è un punto per giorno, altrimenti uno per data
    di lettura. Al cambio di contatore il cumulato prosegue senza salti.
    """
    if not letture:
        return []
    primo = PuntoStatistica(letture[0].data, 0.0, None if in_smc else letture[0].valore)
    if distribuzione is not Distribuzione.LETTURA:
        punti = [primo]
        somma = 0.0
        for g in giorni:
            somma += g.smc if in_smc else g.m3
            punti.append(PuntoStatistica(g.data, round(somma, 4)))
        return punti
    cumulati = _cumulati(giorni, lambda g: g.smc if in_smc else g.m3)
    punti_per_data: dict[date, PuntoStatistica] = {primo.data: primo}
    for lettura in letture[1:]:
        punti_per_data[lettura.data] = PuntoStatistica(
            lettura.data,
            round(cumulati.get(lettura.data, 0.0), 4),
            None if in_smc else lettura.valore,
        )
    return list(punti_per_data.values())


def punti_costo(
    letture: list[Lettura], giorni: list[Giorno], distribuzione: Distribuzione
) -> list[PuntoStatistica]:
    """Costo cumulato da esportare nella statistica dei costi.

    Parte dal primo giorno coperto da una tariffa: prima non si conosce il prezzo.
    """
    con_costo = [g for g in giorni if g.costo is not None]
    if not con_costo:
        return []
    inizio = con_costo[0].data - timedelta(days=1)
    punti = [PuntoStatistica(inizio, 0.0)]
    if distribuzione is not Distribuzione.LETTURA:
        somma = 0.0
        for g in con_costo:
            somma += g.costo or 0.0
            punti.append(PuntoStatistica(g.data, round(somma, 4)))
        return punti
    cumulati = _cumulati(con_costo, lambda g: g.costo or 0.0)
    for lettura in letture:
        if lettura.data > inizio and lettura.data in cumulati and punti[-1].data != lettura.data:
            punti.append(PuntoStatistica(lettura.data, round(cumulati[lettura.data], 4)))
    return punti


def _cumulati(giorni: list[Giorno], valore) -> dict[date, float]:
    cumulati: dict[date, float] = {}
    somma = 0.0
    for g in giorni:
        somma += valore(g)
        cumulati[g.data] = somma
    return cumulati
