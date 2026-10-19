"""Test del calcolo di consumi, costi e statistiche."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from custom_components.myitalgas import calcoli
from custom_components.myitalgas.calcoli import Distribuzione, Tariffa
from custom_components.myitalgas.parser import Lettura


def _l(giorno: str, valore: float, matricola: str = "M1", tipo: str = "Telelettura") -> Lettura:
    return Lettura(date.fromisoformat(giorno), valore, tipo, matricola)


def _t(dal: str, sc1: float, sc2: float | None = None, sc3: float | None = None, fissa=0.0):
    sc2 = sc1 if sc2 is None else sc2
    sc3 = sc2 if sc3 is None else sc3
    return Tariffa(date.fromisoformat(dal), sc1, sc2, sc3, fissa)


def _giorni(inizio: str, n: int) -> list[date]:
    primo = date.fromisoformat(inizio)
    return [primo + timedelta(days=i) for i in range(n)]


# --------------------------------------------------------------------------- letture e periodi


def test_ordine_e_periodi() -> None:
    """Letture in ordine sparso: periodi consecutivi con consumo, giorni e media."""
    letture = calcoli.ordina([_l("2026-02-28", 150), _l("2025-12-31", 40), _l("2026-01-31", 100)])
    assert [x.valore for x in letture] == [40, 100, 150]
    periodi = calcoli.periodi(letture)
    assert [(p.consumo, p.giorni) for p in periodi] == [(60, 31), (50, 28)]
    assert periodi[0].media_giornaliera == 60 / 31
    assert periodi[0].date()[0] == date(2026, 1, 1)
    assert periodi[0].date()[-1] == date(2026, 1, 31)


def test_sostituzione_contatore() -> None:
    """Nello stesso giorno: chiusura del vecchio contatore e installazione del nuovo."""
    letture = calcoli.ordina(
        [
            _l("2026-01-31", 1000, "VECCHIO"),
            _l("2026-02-15", 0, "NUOVO", "Lettura tecnica"),
            _l("2026-02-15", 1030, "VECCHIO", "Lettura tecnica"),
            _l("2026-02-28", 26, "NUOVO"),
        ]
    )
    assert [(x.matricola, x.valore) for x in letture] == [
        ("VECCHIO", 1000),
        ("VECCHIO", 1030),
        ("NUOVO", 0),
        ("NUOVO", 26),
    ]
    periodi = calcoli.periodi(letture)
    assert [(p.inizio.matricola, p.consumo) for p in periodi] == [("VECCHIO", 30), ("NUOVO", 26)]
    # il cumulato non salta al cambio contatore
    punti = calcoli.punti_consumo(
        letture, calcoli.calcola_giorni(letture, 1.0, []), Distribuzione.LETTURA, False
    )
    assert [(p.data.isoformat(), p.somma, p.lettura) for p in punti] == [
        ("2026-01-31", 0, 1000),
        ("2026-02-15", 30, 0),
        ("2026-02-28", 56, 26),
    ]


def test_decimali() -> None:
    """Nessun errore di arrotondamento binario nei consumi."""
    periodi = calcoli.periodi(calcoli.ordina([_l("2026-01-31", 100.1), _l("2026-02-28", 100.3)]))
    assert periodi[0].consumo == 0.2


def test_vuoto() -> None:
    """Nessuna lettura o una sola lettura."""
    assert calcoli.ordina([]) == []
    assert calcoli.periodi([]) == []
    assert calcoli.calcola_giorni([], 1.0, []) == []
    assert calcoli.calcola_giorni([_l("2026-01-31", 5)], 1.0, []) == []
    assert calcoli.punti_consumo([], [], Distribuzione.GIORNALIERA, False) == []
    assert calcoli.punti_costo([], [], Distribuzione.GIORNALIERA) == []


# --------------------------------------------------------------------------- ripartizione giornaliera


def test_ripartizione_uniforme() -> None:
    """Il consumo di un periodo è diviso in parti uguali sui suoi giorni."""
    periodi = calcoli.periodi([_l("2026-01-31", 100), _l("2026-03-03", 162)])
    consumi = calcoli.consumi_giornalieri(periodi)
    assert list(consumi) == _giorni("2026-02-01", 31)
    assert all(v == pytest.approx(2.0) for v in consumi.values())
    assert sum(consumi.values()) == pytest.approx(62)


def test_consumo_base() -> None:
    """Il consumo di base è la media più bassa tra i periodi abbastanza lunghi."""
    periodi = calcoli.periodi(
        [
            _l("2026-05-31", 0),
            _l("2026-06-30", 30),  # 1 m³/giorno: estate
            _l("2026-07-31", 62),  # 1 m³/giorno
            _l("2026-08-10", 62),  # 10 giorni: troppo breve per contare
            _l("2026-11-30", 1000),
        ]
    )
    assert calcoli.consumo_base(periodi) == pytest.approx(1.0)
    assert calcoli.consumo_base([]) == 0.0


def test_ripartizione_gradi_giorno() -> None:
    """Base uguale ogni giorno, il resto in proporzione ai gradi giorno."""
    letture = [
        _l("2026-06-30", 0),
        _l("2026-07-30", 30),  # estate: 1 m³/giorno, il consumo di base
        _l("2026-12-31", 30 + 154 * 2),  # autunno: 2 m³/giorno
        _l("2027-01-04", 338 + 34),  # 4 giorni, 34 m³
    ]
    periodi = calcoli.periodi(letture)
    temperature = {
        date(2027, 1, 1): 10.0,  # 10 GG
        date(2027, 1, 2): 15.0,  # 5 GG
        date(2027, 1, 3): 20.0,  # 0 GG
        date(2027, 1, 4): 5.0,  # 15 GG
    }
    consumi = calcoli.consumi_giornalieri(periodi, temperature)
    # base 1 m³/giorno (4 m³), riscaldamento 30 m³ su 30 GG -> 1 m³ per grado giorno
    assert consumi[date(2027, 1, 1)] == pytest.approx(1 + 10)
    assert consumi[date(2027, 1, 2)] == pytest.approx(1 + 5)
    assert consumi[date(2027, 1, 3)] == pytest.approx(1 + 0)
    assert consumi[date(2027, 1, 4)] == pytest.approx(1 + 15)
    assert sum(consumi[d] for d in _giorni("2027-01-01", 4)) == pytest.approx(34)


def test_gradi_giorno_casi_limite() -> None:
    """Senza dati sufficienti, in estate o con rettifiche si torna alla ripartizione uniforme."""
    letture = [_l("2027-01-01", 0), _l("2027-01-11", 100)]
    periodi = calcoli.periodi(letture)
    giorni = _giorni("2027-01-02", 10)
    # solo 5 giorni su 10 con temperatura: copertura insufficiente
    poche = dict.fromkeys(giorni[:5], 0.0)
    assert all(
        v == pytest.approx(10.0) for v in calcoli.consumi_giornalieri(periodi, poche).values()
    )
    # tutti i giorni sopra i 20 °C: nessun grado giorno
    caldo = dict.fromkeys(giorni, 25.0)
    assert all(
        v == pytest.approx(10.0) for v in calcoli.consumi_giornalieri(periodi, caldo).values()
    )
    # un giorno mancante prende la media dei gradi giorno degli altri
    quasi = dict.fromkeys(giorni[:9], 10.0)
    consumi = calcoli.consumi_giornalieri(periodi, quasi)
    assert all(v == pytest.approx(10.0) for v in consumi.values())
    # rettifica negativa: uniforme
    negativo = calcoli.periodi([_l("2027-01-01", 100), _l("2027-01-11", 90)])
    assert all(
        v == pytest.approx(-1.0) for v in calcoli.consumi_giornalieri(negativo, caldo).values()
    )


def test_gradi_giorno() -> None:
    """Gradi giorno con base 20 °C."""
    assert calcoli.gradi_giorno(5.0) == 15.0
    assert calcoli.gradi_giorno(20.0) == 0.0
    assert calcoli.gradi_giorno(28.0) == 0.0


# --------------------------------------------------------------------------- tariffe e scaglioni


def test_tariffa_in_vigore() -> None:
    """Vale l'ultima tariffa con decorrenza non successiva al giorno."""
    a, b = _t("2026-01-01", 1), _t("2026-07-01", 2)
    assert calcoli.tariffa_in_vigore([b, a], date(2025, 12, 31)) is None
    assert calcoli.tariffa_in_vigore([b, a], date(2026, 1, 1)) is a
    assert calcoli.tariffa_in_vigore([b, a], date(2026, 6, 30)) is a
    assert calcoli.tariffa_in_vigore([b, a], date(2026, 7, 1)) is b
    assert calcoli.tariffa_in_vigore([], date(2026, 7, 1)) is None


def test_costo_scaglioni() -> None:
    """Un consumo che attraversa una o due soglie è diviso pro quota."""
    t = _t("2026-01-01", 1.0, 2.0, 3.0)
    assert t.costo_variabile(0, 50) == pytest.approx(50)
    assert t.costo_variabile(100, 50) == pytest.approx(20 * 1 + 30 * 2)
    assert t.costo_variabile(100, 400) == pytest.approx(20 * 1 + 360 * 2 + 20 * 3)
    assert t.costo_variabile(500, 10) == pytest.approx(30)
    # rettifica: il costo torna indietro allo stesso prezzo con cui era stato addebitato
    assert t.costo_variabile(130, -20) == pytest.approx(-(10 * 1 + 10 * 2))
    assert t.prezzo(119.9) == 1.0
    assert t.prezzo(120) == 2.0
    assert t.prezzo(480) == 3.0
    assert [calcoli.scaglione(x) for x in (0, 119.9, 120, 479.9, 480)] == [1, 1, 2, 2, 3]


def test_cambio_anno_azzera_gli_scaglioni() -> None:
    """Il cumulato per gli scaglioni riparte dal 1° gennaio."""
    letture = [_l("2025-11-30", 0), _l("2026-01-30", 610)]  # 61 giorni, 10 m³/giorno
    giorni = calcoli.calcola_giorni(letture, 1.0, [_t("1900-01-01", 1.0, 2.0, 3.0)])
    assert len(giorni) == 61
    dicembre = sum(g.costo_variabile for g in giorni if g.data.year == 2025)
    gennaio = sum(g.costo_variabile for g in giorni if g.data.year == 2026)
    # dicembre: 310 Smc -> 120 a 1 € + 190 a 2 € (lo storico parte dalla prima lettura)
    assert dicembre == pytest.approx(120 * 1 + 190 * 2)
    # gennaio: 300 Smc ripartono dal primo scaglione
    assert gennaio == pytest.approx(120 * 1 + 180 * 2)


def test_coefficiente_e_cambio_tariffa() -> None:
    """I costi usano gli Smc (m³ × C) e il prezzo in vigore giorno per giorno."""
    letture = [_l("2026-01-31", 0), _l("2026-03-02", 300)]  # 30 giorni, 10 m³/giorno
    tariffe = [_t("2026-01-01", 1.0), _t("2026-02-16", 2.0)]
    giorni = calcoli.calcola_giorni(letture, 1.02, tariffe)
    assert sum(g.smc for g in giorni) == pytest.approx(306)
    # 1-15 febbraio a 1 €, dal 16 febbraio a 2 €
    assert sum(g.costo_variabile for g in giorni) == pytest.approx(15 * 10.2 * 1 + 15 * 10.2 * 2)


def test_quota_fissa_giornaliera() -> None:
    """La quota fissa di un anno intero torna a dodici mensilità, anche negli anni bisestili."""
    t = _t("2020-01-01", 0.0, fissa=30.5)
    for anno in (2026, 2028):
        letture = [_l(f"{anno - 1}-12-31", 0), _l(f"{anno}-12-31", 0)]
        giorni = calcoli.calcola_giorni(letture, 1.0, [t])
        assert len(giorni) == (366 if anno == 2028 else 365)
        assert sum(g.costo_fisso for g in giorni) == pytest.approx(12 * 30.5)
        assert calcoli.costo_anno(giorni, anno) == pytest.approx(366.0)


def test_giorni_senza_tariffa() -> None:
    """Prima del primo periodo tariffario il costo non è noto."""
    letture = [_l("2026-01-31", 0), _l("2026-03-02", 300)]
    giorni = calcoli.calcola_giorni(letture, 1.0, [_t("2026-02-16", 1.0)])
    assert all(g.costo is None for g in giorni if g.data < date(2026, 2, 16))
    assert all(g.costo is not None for g in giorni if g.data >= date(2026, 2, 16))
    assert calcoli.calcola_giorni(letture, 1.0, [])[0].costo is None


# --------------------------------------------------------------------------- consumi annui


def test_consumo_anno_pro_quota() -> None:
    """Un periodo a cavallo di due anni è diviso pro quota tra i due."""
    letture = [_l("2025-12-16", 0), _l("2026-01-15", 300)]  # 30 giorni, 10 m³/giorno
    giorni = calcoli.calcola_giorni(letture, 0.99, [_t("1900-01-01", 1.5, fissa=10)])
    assert calcoli.consumo_anno(giorni, 2025) == pytest.approx(150)
    assert calcoli.consumo_anno(giorni, 2026) == pytest.approx(150)
    assert calcoli.smc_anno(giorni, 2026) == pytest.approx(148.5)
    assert calcoli.costo_anno(giorni, 2026) == pytest.approx(
        148.5 * 1.5 + 15 * 10 * 12 / 365, abs=0.01
    )
    assert calcoli.consumo_anno(giorni, 2024) is None
    assert calcoli.costo_anno(calcoli.calcola_giorni(letture, 1.0, []), 2026) is None


def test_prezzo_marginale() -> None:
    """Prezzo dello scaglione raggiunto quest'anno, con la tariffa in vigore oggi."""
    letture = [_l("2025-12-31", 0), _l("2026-01-31", 130)]
    tariffe = [_t("1900-01-01", 1.0, 2.0, 3.0), _t("2026-06-01", 1.1, 2.2, 3.3)]
    giorni = calcoli.calcola_giorni(letture, 1.0, tariffe)
    assert calcoli.prezzo_marginale(giorni, tariffe, date(2026, 2, 10)) == 2.0
    assert calcoli.prezzo_marginale(giorni, tariffe, date(2026, 6, 10)) == 2.2
    # nuovo anno senza letture: si riparte dal primo scaglione
    assert calcoli.prezzo_marginale(giorni, tariffe, date(2027, 1, 5)) == 1.1
    assert calcoli.prezzo_marginale(giorni, [], date(2026, 2, 10)) is None
    assert calcoli.prezzo_marginale(giorni, [_t("2030-01-01", 1)], date(2026, 2, 10)) is None


# --------------------------------------------------------------------------- statistiche


def test_punti_giornalieri() -> None:
    """Un punto per giorno, cumulato da zero alla prima lettura."""
    letture = [_l("2026-01-31", 100), _l("2026-02-03", 106), _l("2026-02-05", 110)]
    giorni = calcoli.calcola_giorni(letture, 1.0, [])
    punti = calcoli.punti_consumo(letture, giorni, Distribuzione.GIORNALIERA, False)
    assert [(p.data.day, p.somma) for p in punti] == [
        (31, 0),
        (1, 2),
        (2, 4),
        (3, 6),
        (4, 8),
        (5, 10),
    ]
    assert punti[0].lettura == 100
    assert all(p.lettura is None for p in punti[1:])


def test_punti_in_smc() -> None:
    """Con la statistica in Smc i volumi sono moltiplicati per C e senza lettura."""
    letture = [_l("2026-01-31", 100), _l("2026-02-10", 200)]
    giorni = calcoli.calcola_giorni(letture, 1.02, [])
    punti = calcoli.punti_consumo(letture, giorni, Distribuzione.LETTURA, True)
    assert [(p.data.day, p.somma, p.lettura) for p in punti] == [(31, 0, None), (10, 102, None)]
    giornalieri = calcoli.punti_consumo(letture, giorni, Distribuzione.GRADI_GIORNO, True)
    assert giornalieri[-1].somma == pytest.approx(102)
    assert len(giornalieri) == 11


def test_punti_costo() -> None:
    """I costi partono dal giorno prima del primo coperto da una tariffa."""
    letture = [_l("2026-01-31", 0), _l("2026-02-10", 100), _l("2026-02-20", 200)]
    giorni = calcoli.calcola_giorni(letture, 1.0, [_t("2026-02-06", 1.0, fissa=0)])
    giornalieri = calcoli.punti_costo(letture, giorni, Distribuzione.GIORNALIERA)
    assert giornalieri[0].data == date(2026, 2, 5)
    assert giornalieri[0].somma == 0
    assert giornalieri[-1].somma == pytest.approx(150)  # 15 giorni da 10 Smc a 1 €
    per_lettura = calcoli.punti_costo(letture, giorni, Distribuzione.LETTURA)
    assert [(p.data.day, p.somma) for p in per_lettura] == [(5, 0), (10, 50), (20, 150)]
    assert (
        calcoli.punti_costo(
            letture, calcoli.calcola_giorni(letture, 1.0, []), Distribuzione.LETTURA
        )
        == []
    )
