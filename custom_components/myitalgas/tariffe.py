"""Periodi tariffari: conversione tra dati delle sottovoci e modello di calcolo."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .calcoli import Tariffa
from .const import (
    CONF_DAL,
    CONF_PREZZO_SC1,
    CONF_PREZZO_SC2,
    CONF_PREZZO_SC3,
    CONF_QUOTA_FISSA,
    SUBENTRY_TARIFFA,
)

_LOGGER = logging.getLogger(__name__)


def normalizza(valori: Mapping[str, Any]) -> dict[str, Any]:
    """Dati di un periodo tariffario: gli scaglioni mancanti prendono il prezzo del precedente."""
    sc1 = float(valori[CONF_PREZZO_SC1])
    sc2 = valori.get(CONF_PREZZO_SC2)
    sc2 = sc1 if sc2 is None else float(sc2)
    sc3 = valori.get(CONF_PREZZO_SC3)
    sc3 = sc2 if sc3 is None else float(sc3)
    dal = valori[CONF_DAL]
    dal = dal if isinstance(dal, date) else date.fromisoformat(str(dal))
    return {
        CONF_DAL: dal.isoformat(),
        CONF_PREZZO_SC1: sc1,
        CONF_PREZZO_SC2: sc2,
        CONF_PREZZO_SC3: sc3,
        CONF_QUOTA_FISSA: float(valori.get(CONF_QUOTA_FISSA) or 0.0),
    }


def titolo(dati: Mapping[str, Any]) -> str:
    """Titolo della sottovoce, ad esempio "Dal 01/07/2026"."""
    return f"Dal {date.fromisoformat(dati[CONF_DAL]):%d/%m/%Y}"


def da_dati(dati: Mapping[str, Any]) -> Tariffa:
    """Periodo tariffario di calcolo a partire dai dati di una sottovoce."""
    valori = normalizza(dati)
    return Tariffa(
        dal=date.fromisoformat(valori[CONF_DAL]),
        prezzo_sc1=valori[CONF_PREZZO_SC1],
        prezzo_sc2=valori[CONF_PREZZO_SC2],
        prezzo_sc3=valori[CONF_PREZZO_SC3],
        quota_fissa=valori[CONF_QUOTA_FISSA],
    )


def da_entry(entry: ConfigEntry) -> list[Tariffa]:
    """Periodi tariffari configurati, in ordine di decorrenza."""
    tariffe = []
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TARIFFA:
            continue
        try:
            tariffe.append(da_dati(subentry.data))
        except (KeyError, TypeError, ValueError):
            _LOGGER.warning("Periodo tariffario '%s' non valido, ignorato", subentry.title)
    return sorted(tariffe, key=lambda t: t.dal)
