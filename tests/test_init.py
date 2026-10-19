"""Test dell'integrazione in Home Assistant: setup, sensori, statistiche, errori."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import partial
import json

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.myitalgas.const import (
    CONF_COEFFICIENTE,
    CONF_DISTRIBUZIONE,
    CONF_SENSORE_TEMPERATURA,
    CONF_STATISTICA_SMC,
    DOMAIN,
)
from custom_components.myitalgas.coordinator import id_statistica, id_statistica_costo
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    get_metadata,
    statistics_during_period,
)
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from .conftest import PASSWORD, PDR, USERNAME, crea_entry, tariffa
from .portale import LetturaFinta, PortaleFinto, letture_mensili

ADESSO = "2026-10-19 10:00:00+02:00"
# un punto per ogni giorno dalla prima all'ultima lettura (distribuzione giornaliera)
PUNTI_GIORNALIERI = (date(2026, 9, 30) - date(2022, 12, 1)).days + 1


@pytest.fixture(autouse=True)
def _ora(freezer: FrozenDateTimeFactory, fuso_roma: None) -> None:
    freezer.move_to(ADESSO)


def _entity_id(hass: HomeAssistant, chiave: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{PDR}_{chiave}")
    assert entity_id is not None, chiave
    return entity_id


def _stato(hass: HomeAssistant, chiave: str):
    stato = hass.states.get(_entity_id(hass, chiave))
    assert stato is not None, chiave
    return stato


async def _avvia(hass: HomeAssistant, tariffe=None, **opzioni) -> MockConfigEntry:
    """Configura la fornitura e attende anche il recupero dello storico in background."""
    entry = crea_entry(hass, tariffe=tariffe, **opzioni)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def _statistiche(hass: HomeAssistant, statistica: str | None = None) -> list[dict]:
    statistica = statistica or id_statistica(PDR)
    await async_wait_recording_done(hass)
    righe = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        datetime(2020, 1, 1, tzinfo=dt_util.UTC),
        None,
        {statistica},
        "hour",
        None,
        {"state", "sum"},
    )
    return righe.get(statistica, [])


async def test_sensori(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Primo avvio: storico completo e sensori con i valori attesi."""
    entry = await _avvia(hass)

    lettura = _stato(hass, "lettura")
    assert lettura.state == "1812.0"
    assert lettura.attributes["unit_of_measurement"] == "m³"
    assert lettura.attributes["device_class"] == "gas"
    assert lettura.attributes["state_class"] == "total_increasing"
    assert lettura.attributes["data_lettura"] == "2026-09-30"
    assert lettura.attributes["tipologia"] == "Telelettura"
    assert lettura.attributes["matricola"] == "MIT0000000000001"

    assert _stato(hass, "data_lettura").state == "2026-09-30"

    periodo = _stato(hass, "consumo_periodo")
    assert periodo.state == "9.0"
    assert periodo.attributes["dal"] == "2026-08-31"
    assert periodo.attributes["al"] == "2026-09-30"
    assert periodo.attributes["giorni"] == 30

    assert _stato(hass, "consumo_periodo_smc").state == "9.0"
    assert _stato(hass, "consumo_periodo_smc").attributes["unit_of_measurement"] == "Smc"
    assert _stato(hass, "media_giornaliera").state == "0.3"
    assert _stato(hass, "consumo_anno").state == "308.0"
    assert _stato(hass, "consumo_anno").attributes["anno"] == 2026
    assert _stato(hass, "consumo_anno_precedente").state == "473.0"
    assert _stato(hass, "consumo_anno_precedente").attributes["anno"] == 2025
    assert _stato(hass, "consumo_anno_smc").state == "308.0"
    # senza periodi tariffari i costi non sono noti
    assert _stato(hass, "costo_stimato_anno").state == "unknown"
    assert _stato(hass, "prezzo_marginale_attuale").state == "unknown"
    assert _stato(hass, "costo_stimato_anno").attributes["unit_of_measurement"] == "EUR"
    assert _stato(hass, "prezzo_marginale_attuale").attributes["unit_of_measurement"] == "EUR/Smc"

    aggiornamento = _stato(hass, "ultimo_aggiornamento")
    assert dt_util.parse_datetime(aggiornamento.state) == dt_util.parse_datetime(ADESSO)
    assert aggiornamento.attributes["periodi_non_scaricati"] == []
    entita = er.async_get(hass).async_get(_entity_id(hass, "ultimo_aggiornamento"))
    assert entita.entity_category is er.EntityCategory.DIAGNOSTIC

    dispositivi = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(dispositivi) == 1
    dispositivo = dispositivi[0]
    assert dispositivo.identifiers == {(DOMAIN, PDR)}
    assert dispositivo.name == "Gas Casa"
    assert dispositivo.manufacturer == "Italgas Reti"
    assert dispositivo.serial_number == "MIT0000000000001"


async def test_coefficiente(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Il consumo in Smc usa il coefficiente impostato nelle opzioni."""
    await _avvia(hass, **{CONF_COEFFICIENTE: 1.0185})
    assert _stato(hass, "consumo_periodo_smc").state == "9.1665"
    assert _stato(hass, "consumo_periodo").state == "9.0"


async def test_statistiche_energia(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Statistica esterna con il consumo distribuito giorno per giorno (predefinito)."""
    await _avvia(hass)
    righe = await _statistiche(hass)
    assert len(righe) == PUNTI_GIORNALIERI
    prima, ultima = righe[0], righe[-1]
    assert dt_util.utc_from_timestamp(prima["start"]) == dt_util.start_of_local_day(
        date(2022, 12, 1)
    )
    assert prima["sum"] == 0
    assert prima["state"] == 0
    assert dt_util.utc_from_timestamp(ultima["start"]) == dt_util.start_of_local_day(
        date(2026, 9, 30)
    )
    assert ultima["sum"] == pytest.approx(1812)
    # settembre 2026: 9 m³ in 30 giorni -> 0,3 m³ al giorno, nessun picco a fine mese
    per_giorno = {
        dt_util.as_local(dt_util.utc_from_timestamp(r["start"])).date(): r["sum"] for r in righe
    }
    assert per_giorno[date(2026, 9, 15)] - per_giorno[date(2026, 9, 14)] == pytest.approx(0.3)
    assert per_giorno[date(2026, 9, 30)] - per_giorno[date(2026, 9, 29)] == pytest.approx(0.3)

    metadati = await get_instance(hass).async_add_executor_job(
        partial(get_metadata, hass, statistic_ids={id_statistica(PDR)})
    )
    meta = metadati[id_statistica(PDR)][1]
    assert meta["source"] == DOMAIN
    assert meta["unit_of_measurement"] == "m³"
    assert meta["has_sum"] is True
    assert meta["name"] == "MyItalgas Casa consumo gas"


async def test_statistica_costi(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Con un periodo tariffario si crea la statistica dei costi, quote fisse incluse."""
    assert await _statistiche(hass, id_statistica_costo(PDR)) == []
    entry = await _avvia(
        hass,
        tariffe=[tariffa("1900-01-01", 1.25, fissa=10.0)],
        **{CONF_COEFFICIENTE: 0.99},
    )
    righe = await _statistiche(hass, id_statistica_costo(PDR))
    assert len(righe) == PUNTI_GIORNALIERI
    assert righe[0]["sum"] == 0
    # quota fissa: 120 €/anno ripartiti sui giorni dell'anno (il 2024 è bisestile)
    giorni = PUNTI_GIORNALIERI - 1
    fisso = 120.0 + 120.0 / 365 * (giorni - 366)
    assert righe[-1]["sum"] == pytest.approx(1812 * 0.99 * 1.25 + fisso, abs=0.01)
    metadati = await get_instance(hass).async_add_executor_job(
        partial(get_metadata, hass, statistic_ids={id_statistica_costo(PDR)})
    )
    assert metadati[id_statistica_costo(PDR)][1]["unit_of_measurement"] == hass.config.currency
    assert _stato(hass, "costo_stimato_anno").state != "unknown"
    assert _stato(hass, "prezzo_marginale_attuale").state == "1.25"

    # periodi tariffari rimossi: la statistica dei costi viene eliminata
    for subentry_id in list(entry.subentries):
        hass.config_entries.async_remove_subentry(entry, subentry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED
    assert await _statistiche(hass, id_statistica_costo(PDR)) == []
    assert len(await _statistiche(hass)) == PUNTI_GIORNALIERI
    assert _stato(hass, "costo_stimato_anno").state == "unknown"


async def test_aggiornamento_incrementale_e_nuova_lettura(
    hass: HomeAssistant, portale: PortaleFinto, freezer: FrozenDateTimeFactory
) -> None:
    """Gli aggiornamenti successivi scaricano solo le ultime settimane."""
    entry = await _avvia(hass)
    portale.ricerche.clear()
    portale.forniture[0].letture.append(LetturaFinta(date(2026, 10, 15), 1830))

    freezer.tick(timedelta(hours=12, minutes=1))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert portale.ricerche == [(date(2026, 7, 2), date(2026, 10, 19))]
    assert _stato(hass, "lettura").state == "1830.0"
    assert _stato(hass, "consumo_periodo").state == "18.0"
    assert _stato(hass, "consumo_periodo").attributes["giorni"] == 15
    assert _stato(hass, "consumo_anno").state == "326.0"
    righe = await _statistiche(hass)
    assert righe[-1]["sum"] == 1830


async def test_aggiornamento_automatico(
    hass: HomeAssistant, portale: PortaleFinto, freezer: FrozenDateTimeFactory
) -> None:
    """L'aggiornamento parte da solo allo scadere dell'intervallo."""
    await _avvia(hass)
    portale.ricerche.clear()
    freezer.tick(timedelta(hours=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert portale.ricerche == []

    freezer.tick(timedelta(hours=1, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(portale.ricerche) == 1


async def test_storico_salvato_tra_i_riavvii(
    hass: HomeAssistant, portale: PortaleFinto, hass_storage: dict
) -> None:
    """Dopo un riavvio non si riscarica tutto lo storico."""
    entry = await _avvia(hass)
    assert len(hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]["letture"]) == 47

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    # la ricerca riparte dalle ultime settimane, non dal 2000
    assert portale.ricerche[-1] == (date(2026, 7, 2), date(2026, 10, 19))
    assert _stato(hass, "lettura").state == "1812.0"


async def test_riavvio_con_portale_irraggiungibile(
    hass: HomeAssistant, portale: PortaleFinto
) -> None:
    """Con lo storico salvato i sensori funzionano anche se il portale non risponde."""
    entry = await _avvia(hass)
    portale.errore_http = 503
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert _stato(hass, "lettura").state == "1812.0"
    assert dt_util.parse_datetime(
        _stato(hass, "ultimo_aggiornamento").state
    ) == dt_util.parse_datetime(ADESSO)


async def test_portale_irraggiungibile_al_primo_avvio(
    hass: HomeAssistant, portale: PortaleFinto
) -> None:
    """Senza storico salvato e senza portale si riprova più tardi."""
    portale.errore_http = 503
    entry = crea_entry(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_errore_durante_un_aggiornamento(
    hass: HomeAssistant, portale: PortaleFinto, freezer: FrozenDateTimeFactory
) -> None:
    """Un errore temporaneo non rende indisponibili le letture già note."""
    entry = await _avvia(hass)
    portale.errore_sistema = lambda _da, _a: True
    freezer.tick(timedelta(hours=1))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert entry.runtime_data.last_update_success is False
    assert _stato(hass, "lettura").state == "1812.0"
    assert dt_util.parse_datetime(
        _stato(hass, "ultimo_aggiornamento").state
    ) == dt_util.parse_datetime(ADESSO)

    portale.errore_sistema = lambda _da, _a: False
    freezer.tick(timedelta(hours=1))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert entry.runtime_data.last_update_success is True
    ultimo = dt_util.parse_datetime(_stato(hass, "ultimo_aggiornamento").state)
    assert ultimo > dt_util.parse_datetime(ADESSO)


async def test_password_cambiata(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Credenziali non più valide: parte la richiesta di nuovo accesso."""
    entry = await _avvia(hass)
    portale.utenti = {USERNAME: "cambiata"}
    portale.scadi_sessioni()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    flussi = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flussi] == [SOURCE_REAUTH]


async def test_password_errata_al_primo_avvio(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """All'avvio con credenziali rifiutate: errore di setup e richiesta di nuovo accesso."""
    portale.utenti = {}
    entry = crea_entry(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flussi = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [f["context"]["source"] for f in flussi] == [SOURCE_REAUTH]


async def test_pdr_rimosso_dal_profilo(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Se la fornitura sparisce dal profilo l'aggiornamento fallisce con un messaggio chiaro."""
    portale.forniture[0].pdr = "11111111111111"
    entry = crea_entry(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert PDR in (entry.reason or "")


async def test_storico_salvato_illeggibile(
    hass: HomeAssistant, portale: PortaleFinto, hass_storage: dict
) -> None:
    """Uno storico salvato corrotto viene ignorato e riscaricato."""
    entry = crea_entry(hass)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {"letture": [{"data": "non una data", "valore": 1}]},
    }
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert _stato(hass, "lettura").state == "1812.0"
    # storico ignorato: viene riscaricato tutto
    assert date(2000, 1, 1) in [da for da, _ in portale.ricerche]
    assert len(await _statistiche(hass)) == PUNTI_GIORNALIERI


async def test_periodi_non_scaricati(
    hass: HomeAssistant, portale: PortaleFinto, freezer: FrozenDateTimeFactory
) -> None:
    """Un periodo non scaricato viene segnalato e recuperato al giro successivo."""
    portale.errore_sistema = lambda da, a: da <= date(2024, 6, 15) <= a
    entry = await _avvia(hass)
    mancanti = _stato(hass, "ultimo_aggiornamento").attributes["periodi_non_scaricati"]
    assert len(mancanti) == 1

    portale.errore_sistema = lambda _da, _a: False
    portale.ricerche.clear()
    freezer.tick(timedelta(hours=12, minutes=1))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert _stato(hass, "ultimo_aggiornamento").attributes["periodi_non_scaricati"] == []
    assert portale.ricerche[0][0] <= date.fromisoformat(mancanti[0].split("/")[0])
    assert len(await _statistiche(hass)) == PUNTI_GIORNALIERI


async def test_gennaio_senza_letture(
    hass: HomeAssistant, portale: PortaleFinto, freezer: FrozenDateTimeFactory
) -> None:
    """A gennaio, prima della prima lettura dell'anno, il consumo dell'anno è zero."""
    portale.forniture[0].letture = letture_mensili(fine=date(2026, 12, 31))
    freezer.move_to("2027-01-10 10:00:00+01:00")
    await _avvia(hass)
    assert _stato(hass, "consumo_anno").state == "0.0"
    assert _stato(hass, "consumo_anno").attributes["anno"] == 2027
    assert _stato(hass, "consumo_anno_precedente").state == "473.0"


async def test_fornitura_senza_letture(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Fornitura appena associata, ancora senza letture."""
    portale.forniture[0].letture = []
    await _avvia(hass)
    assert _stato(hass, "lettura").state == "unknown"
    assert _stato(hass, "consumo_periodo").state == "unknown"
    assert _stato(hass, "consumo_anno").state == "unknown"
    assert await _statistiche(hass) == []


async def test_diagnostica_senza_dati_personali(
    hass: HomeAssistant, portale: PortaleFinto, hass_client
) -> None:
    """La diagnostica non contiene credenziali né dati della fornitura."""
    entry = await _avvia(hass)
    diagnostica = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    testo = json.dumps(diagnostica)
    for segreto in (PASSWORD, USERNAME, PDR, "MIT0000000000001", "VIA ROMA"):
        assert segreto not in testo
    assert len(diagnostica["letture"]) == 47
    assert diagnostica["ultimo_aggiornamento_riuscito"] is True


async def test_rimozione(hass: HomeAssistant, portale: PortaleFinto, hass_storage: dict) -> None:
    """Rimuovendo l'integrazione si cancella lo storico salvato."""
    entry = await _avvia(hass)
    chiave = f"{DOMAIN}.{entry.entry_id}"
    assert chiave in hass_storage
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert chiave not in hass_storage
    assert hass.states.async_entity_ids("sensor") == []


async def test_scaricamento_entita(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Unload pulito."""
    entry = await _avvia(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_primo_avvio_rapido(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """La configurazione si chiude con le letture recenti; lo storico arriva in background."""
    entry = crea_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    # subito: solo gli ultimi 120 giorni, sensori già validi
    assert portale.ricerche[0] == (date(2026, 6, 21), date(2026, 10, 19))
    assert _stato(hass, "lettura").state == "1812.0"
    assert _stato(hass, "consumo_periodo").state == "9.0"

    await hass.async_block_till_done(wait_background_tasks=True)
    assert date(2000, 1, 1) in [da for da, _ in portale.ricerche]
    assert _stato(hass, "consumo_anno_precedente").state == "473.0"
    assert _stato(hass, "ultimo_aggiornamento").attributes["storico_completo"] is True
    assert len(await _statistiche(hass)) == PUNTI_GIORNALIERI
    assert entry.runtime_data.last_update_success is True


async def test_storico_in_background_non_riuscito(
    hass: HomeAssistant, portale: PortaleFinto, freezer: FrozenDateTimeFactory
) -> None:
    """Se il recupero dello storico fallisce, viene ritentato all'aggiornamento successivo."""
    portale.errore_sistema = lambda da, _a: da < date(2026, 1, 1)
    entry = await _avvia(hass)
    assert _stato(hass, "lettura").state == "1812.0"
    assert _stato(hass, "ultimo_aggiornamento").attributes["storico_completo"] is False
    assert _stato(hass, "consumo_anno_precedente").state == "unknown"

    portale.errore_sistema = lambda _da, _a: False
    freezer.tick(timedelta(hours=12, minutes=1))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert _stato(hass, "ultimo_aggiornamento").attributes["storico_completo"] is True
    assert _stato(hass, "consumo_anno_precedente").state == "473.0"
    assert len(await _statistiche(hass)) == PUNTI_GIORNALIERI


async def test_migrazione_dalla_versione_1_0_0(
    hass: HomeAssistant, portale: PortaleFinto, hass_storage: dict
) -> None:
    """Lo storico salvato dalla 1.0.0 (sempre completo) non viene riscaricato."""
    entry = crea_entry(hass)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {
            "letture": [
                {
                    "data": x.data.isoformat(),
                    "valore": x.valore,
                    "tipologia": x.tipologia,
                    "matricola": x.matricola,
                }
                for x in letture_mensili()
            ],
            "mancanti": [],
            "data_minima": "2022-12-01",
            "ultimo_aggiornamento": "2026-10-18T10:00:00+00:00",
        },
    }
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert portale.ricerche == [(date(2026, 7, 2), date(2026, 10, 19))]
    assert _stato(hass, "ultimo_aggiornamento").attributes["storico_completo"] is True


async def test_scaricamento_durante_il_recupero(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Rimuovere o ricaricare l'integrazione mentre scarica lo storico non lascia task appesi."""
    entry = crea_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data._recupero is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_pdr_non_compare_nei_log(
    hass: HomeAssistant, portale: PortaleFinto, caplog: pytest.LogCaptureFixture
) -> None:
    """Il PDR non finisce nei log dell'integrazione, che gli utenti allegano alle segnalazioni."""
    caplog.set_level("DEBUG", logger="custom_components.myitalgas")
    caplog.set_level("DEBUG", logger="homeassistant.helpers.update_coordinator")
    await _avvia(hass)
    righe = [
        r.getMessage()
        for r in caplog.records
        if r.name.startswith("custom_components.myitalgas")
        or (
            r.name.startswith("homeassistant.helpers.update_coordinator")
            and "myitalgas" in r.getMessage()
        )
    ]
    assert any("Finished fetching myitalgas Casa" in r for r in righe)
    assert not [r for r in righe if PDR in r]


async def test_migrazione_prezzo_unico(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Il prezzo unico della 1.x diventa un periodo tariffario valido da sempre."""
    entry = crea_entry(hass, minor_version=1, **{CONF_COEFFICIENTE: 0.99, "prezzo": 1.25})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.minor_version == 2
    assert "prezzo" not in entry.options
    assert entry.options[CONF_COEFFICIENTE] == 0.99
    (periodo,) = entry.subentries.values()
    assert periodo.subentry_type == "tariffa"
    assert dict(periodo.data) == {
        "dal": "1900-01-01",
        "prezzo_sc1": 1.25,
        "prezzo_sc2": 1.25,
        "prezzo_sc3": 1.25,
        "quota_fissa": 0.0,
    }
    righe = await _statistiche(hass, id_statistica_costo(PDR))
    assert righe[-1]["sum"] == pytest.approx(1812 * 0.99 * 1.25)


async def test_migrazione_senza_prezzo(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Senza prezzo nella 1.x non si crea nessun periodo tariffario."""
    entry = crea_entry(hass, minor_version=1, prezzo=0.0)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.minor_version == 2
    assert entry.subentries == {}
    assert entry.options == {}


async def test_distribuzione_alla_lettura_e_cambio(
    hass: HomeAssistant, portale: PortaleFinto
) -> None:
    """Tutto il consumo nel giorno della lettura; cambiando modalità non restano punti orfani."""
    entry = await _avvia(
        hass, tariffe=[tariffa("1900-01-01", 1.0)], **{CONF_DISTRIBUZIONE: "lettura"}
    )
    righe = await _statistiche(hass)
    assert len(righe) == len(letture_mensili())
    assert righe[-1]["state"] == 1812
    assert len(await _statistiche(hass, id_statistica_costo(PDR))) == len(letture_mensili())

    hass.config_entries.async_update_entry(entry, options={CONF_DISTRIBUZIONE: "giornaliera"})
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(await _statistiche(hass)) == PUNTI_GIORNALIERI
    assert len(await _statistiche(hass, id_statistica_costo(PDR))) == PUNTI_GIORNALIERI

    hass.config_entries.async_update_entry(entry, options={CONF_DISTRIBUZIONE: "lettura"})
    await hass.async_block_till_done(wait_background_tasks=True)
    righe = await _statistiche(hass)
    assert len(righe) == len(letture_mensili())
    assert righe[-1]["sum"] == pytest.approx(1812)


async def test_statistica_in_smc(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Con l'opzione attiva la statistica riporta gli Smc (m³ × C)."""
    await _avvia(hass, **{CONF_COEFFICIENTE: 1.02, CONF_STATISTICA_SMC: True})
    righe = await _statistiche(hass)
    assert righe[-1]["sum"] == pytest.approx(1812 * 1.02)
    assert righe[0].get("state") is None


async def test_distribuzione_gradi_giorno(hass: HomeAssistant, portale: PortaleFinto) -> None:
    """Con un sensore di temperatura i giorni più freddi ricevono più consumo."""
    sensore = "sensor.temperatura_esterna"
    righe_temperatura = []
    for giorno in range(1, 31):
        temperatura = 10.0 if giorno <= 15 else 15.0
        inizio = dt_util.start_of_local_day(date(2026, 9, giorno)) + timedelta(hours=12)
        righe_temperatura.append(
            StatisticData(start=inizio, mean=temperatura, min=temperatura, max=temperatura)
        )
    async_import_statistics(
        hass,
        StatisticMetaData(
            mean_type=StatisticMeanType.ARITHMETIC,
            has_sum=False,
            name="Temperatura esterna",
            source="recorder",
            statistic_id=sensore,
            unit_class="temperature",
            unit_of_measurement="°C",
        ),
        righe_temperatura,
    )
    await async_wait_recording_done(hass)

    await _avvia(hass, **{CONF_DISTRIBUZIONE: "gradi_giorno", CONF_SENSORE_TEMPERATURA: sensore})
    righe = await _statistiche(hass)
    per_giorno = {
        dt_util.as_local(dt_util.utc_from_timestamp(r["start"])).date(): r["sum"] for r in righe
    }
    freddo = per_giorno[date(2026, 9, 5)] - per_giorno[date(2026, 9, 4)]
    mite = per_giorno[date(2026, 9, 25)] - per_giorno[date(2026, 9, 24)]
    assert freddo > mite > 0
    # il consumo del mese resta quello letto dal contatore
    assert per_giorno[date(2026, 9, 30)] - per_giorno[date(2026, 8, 31)] == pytest.approx(9)
    # agosto, senza temperature: distribuzione uniforme
    agosto = per_giorno[date(2026, 8, 10)] - per_giorno[date(2026, 8, 9)]
    assert agosto == pytest.approx(5 / 31, abs=1e-3)


async def test_segnalazione_coefficiente(
    hass: HomeAssistant, portale: PortaleFinto, hass_client
) -> None:
    """Coefficiente C non impostato: segnalazione in Riparazioni, risolvibile da lì."""
    assert await async_setup_component(hass, "repairs", {})
    entry = await _avvia(hass)
    issue_id = f"coefficiente_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    client = await hass_client()
    risposta = await client.post(
        "/api/repairs/issues/fix", json={"handler": DOMAIN, "issue_id": issue_id}
    )
    assert risposta.status == 200
    flusso = await risposta.json()
    assert flusso["step_id"] == "coefficiente"
    risposta = await client.post(
        f"/api/repairs/issues/fix/{flusso['flow_id']}", json={"coefficiente": 0.99}
    )
    assert (await risposta.json())["type"] == "create_entry"
    await hass.async_block_till_done(wait_background_tasks=True)

    assert entry.options[CONF_COEFFICIENTE] == 0.99
    assert entry.state is ConfigEntryState.LOADED
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert _stato(hass, "consumo_periodo_smc").state == "8.91"


async def test_segnalazione_segue_il_coefficiente(
    hass: HomeAssistant, portale: PortaleFinto
) -> None:
    """La segnalazione compare solo con il coefficiente predefinito e sparisce con la fornitura."""
    entry = await _avvia(hass, **{CONF_COEFFICIENTE: 0.99})
    issue_id = f"coefficiente_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None

    hass.config_entries.async_update_entry(entry, options={})
    await hass.async_block_till_done(wait_background_tasks=True)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
