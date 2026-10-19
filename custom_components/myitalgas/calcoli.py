"""Calcolo dei consumi a partire dalle letture del contatore."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from itertools import pairwise

from .parser import Lettura


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


@dataclass(frozen=True, slots=True)
class PuntoStatistica:
    """Valore cumulato alla data di una lettura, per le statistiche a lungo termine."""

    data: date
    lettura: float
    somma: float


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


def consumo_anno(lista_periodi: list[Periodo], anno: int) -> float | None:
    """Consumo dei periodi che terminano nell'anno indicato (None se non ce ne sono)."""
    valori = [p.consumo for p in lista_periodi if p.fine.data.year == anno]
    return round(sum(valori), 3) if valori else None


def punti_statistica(letture: list[Lettura]) -> list[PuntoStatistica]:
    """Consumo cumulato per data di lettura (uno per giorno), partendo da zero.

    Al cambio di contatore il cumulato riprende dalla nuova matricola senza salti.
    """
    punti: dict[date, PuntoStatistica] = {}
    somma = 0.0
    precedente: Lettura | None = None
    for lettura in letture:
        if precedente is not None and precedente.matricola == lettura.matricola:
            somma = round(somma + lettura.valore - precedente.valore, 3)
        punti[lettura.data] = PuntoStatistica(lettura.data, lettura.valore, somma)
        precedente = lettura
    return list(punti.values())
