"""Test del calcolo dei consumi."""

from __future__ import annotations

from datetime import date

from custom_components.myitalgas import calcoli
from custom_components.myitalgas.parser import Lettura


def _l(giorno: str, valore: float, matricola: str = "M1", tipo: str = "Telelettura") -> Lettura:
    return Lettura(date.fromisoformat(giorno), valore, tipo, matricola)


def test_ordine_e_periodi() -> None:
    """Letture in ordine sparso: periodi consecutivi con consumo, giorni e media."""
    letture = calcoli.ordina([_l("2026-02-28", 150), _l("2025-12-31", 40), _l("2026-01-31", 100)])
    assert [x.valore for x in letture] == [40, 100, 150]
    periodi = calcoli.periodi(letture)
    assert [(p.consumo, p.giorni) for p in periodi] == [(60, 31), (50, 28)]
    assert periodi[0].media_giornaliera == 60 / 31


def test_sostituzione_contatore() -> None:
    """Nello stesso giorno: chiusura del vecchio contatore e installazione del nuovo."""
    letture = calcoli.ordina(
        [
            _l("2026-01-31", 1000, "VECCHIO"),
            _l("2026-02-15", 0, "NUOVO", "Lettura tecnica"),
            _l("2026-02-15", 1040, "VECCHIO", "Lettura tecnica"),
            _l("2026-02-28", 30, "NUOVO"),
        ]
    )
    assert [(x.matricola, x.valore) for x in letture] == [
        ("VECCHIO", 1000),
        ("VECCHIO", 1040),
        ("NUOVO", 0),
        ("NUOVO", 30),
    ]
    periodi = calcoli.periodi(letture)
    assert [(p.inizio.matricola, p.consumo) for p in periodi] == [("VECCHIO", 40), ("NUOVO", 30)]
    punti = calcoli.punti_statistica(letture)
    # un punto per giorno, il cumulato non salta al cambio contatore
    assert [(p.data.isoformat(), p.lettura, p.somma) for p in punti] == [
        ("2026-01-31", 1000, 0),
        ("2026-02-15", 0, 40),
        ("2026-02-28", 30, 70),
    ]


def test_rettifica_in_diminuzione() -> None:
    """Una rettifica che abbassa la lettura riduce il cumulato invece di ignorarla."""
    punti = calcoli.punti_statistica(
        calcoli.ordina([_l("2026-01-31", 100), _l("2026-02-28", 90), _l("2026-03-31", 120)])
    )
    assert [p.somma for p in punti] == [0, -10, 20]


def test_consumo_anno() -> None:
    """Il consumo è attribuito all'anno in cui termina il periodo."""
    letture = calcoli.ordina(
        [_l("2024-11-30", 0), _l("2024-12-31", 80), _l("2025-01-31", 170), _l("2025-02-28", 250)]
    )
    periodi = calcoli.periodi(letture)
    assert calcoli.consumo_anno(periodi, 2024) == 80
    assert calcoli.consumo_anno(periodi, 2025) == 170
    assert calcoli.consumo_anno(periodi, 2023) is None


def test_decimali() -> None:
    """Nessun errore di arrotondamento binario nei consumi."""
    periodi = calcoli.periodi(calcoli.ordina([_l("2026-01-31", 100.1), _l("2026-02-28", 100.3)]))
    assert periodi[0].consumo == 0.2


def test_vuoto() -> None:
    """Nessuna lettura."""
    assert calcoli.ordina([]) == []
    assert calcoli.periodi([]) == []
    assert calcoli.punti_statistica([]) == []
