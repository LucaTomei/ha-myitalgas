"""Coordinatore degli aggiornamenti MyItalgas."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import VolumeConverter

from . import calcoli
from .api import (
    ItalgasAuthError,
    ItalgasClient,
    ItalgasError,
    ItalgasPdrNotFoundError,
    RisultatoLetture,
)
from .calcoli import Distribuzione, Giorno, Periodo, PuntoStatistica, Tariffa
from .const import (
    COEFFICIENTE_DEFAULT,
    CONF_ALIAS,
    CONF_COEFFICIENTE,
    CONF_DAL,
    CONF_DISTRIBUZIONE,
    CONF_INTERVALLO_ORE,
    CONF_PDR,
    CONF_PREZZO_SC1,
    CONF_PREZZO_SC2,
    CONF_PREZZO_SC3,
    CONF_QUOTA_FISSA,
    CONF_SENSORE_TEMPERATURA,
    CONF_STATISTICA_SMC,
    DISTRIBUZIONE_DEFAULT,
    DOMAIN,
    GIORNI_PRIMO_AVVIO,
    GIORNI_RILETTURA,
    INTERVALLO_ORE_DEFAULT,
    STORAGE_VERSION,
    SUBENTRY_TARIFFA,
)
from .parser import Lettura

_LOGGER = logging.getLogger(__name__)

type ItalgasConfigEntry = ConfigEntry[ItalgasCoordinator]


@dataclass(frozen=True, slots=True)
class Impostazioni:
    """Opzioni e periodi tariffari della fornitura."""

    coefficiente: float
    distribuzione: Distribuzione
    sensore_temperatura: str | None
    statistica_smc: bool
    tariffe: list[Tariffa]

    @classmethod
    def da_entry(cls, entry: ConfigEntry) -> Impostazioni:
        """Legge le impostazioni dalla config entry."""
        opzioni = entry.options
        try:
            distribuzione = Distribuzione(opzioni.get(CONF_DISTRIBUZIONE, DISTRIBUZIONE_DEFAULT))
        except ValueError:
            distribuzione = Distribuzione(DISTRIBUZIONE_DEFAULT)
        return cls(
            coefficiente=float(opzioni.get(CONF_COEFFICIENTE, COEFFICIENTE_DEFAULT)),
            distribuzione=distribuzione,
            sensore_temperatura=opzioni.get(CONF_SENSORE_TEMPERATURA) or None,
            statistica_smc=bool(opzioni.get(CONF_STATISTICA_SMC, False)),
            tariffe=tariffe_da_entry(entry),
        )


def tariffa_da_dati(dati: dict[str, Any]) -> Tariffa:
    """Periodo tariffario a partire dai dati di una sottovoce."""
    sc1 = float(dati[CONF_PREZZO_SC1])
    sc2 = dati.get(CONF_PREZZO_SC2)
    sc3 = dati.get(CONF_PREZZO_SC3)
    sc2 = sc1 if sc2 is None else float(sc2)
    sc3 = sc2 if sc3 is None else float(sc3)
    return Tariffa(
        dal=date.fromisoformat(dati[CONF_DAL]),
        prezzo_sc1=sc1,
        prezzo_sc2=sc2,
        prezzo_sc3=sc3,
        quota_fissa=float(dati.get(CONF_QUOTA_FISSA) or 0.0),
    )


def tariffe_da_entry(entry: ConfigEntry) -> list[Tariffa]:
    """Periodi tariffari configurati, in ordine di decorrenza."""
    tariffe = []
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TARIFFA:
            continue
        try:
            tariffe.append(tariffa_da_dati(dict(subentry.data)))
        except (KeyError, TypeError, ValueError):
            _LOGGER.warning("Periodo tariffario '%s' non valido, ignorato", subentry.title)
    return sorted(tariffe, key=lambda t: t.dal)


@dataclass(slots=True)
class DatiItalgas:
    """Dati esposti alle entità."""

    letture: list[Lettura]
    periodi: list[Periodo]
    giorni: list[Giorno] = field(default_factory=list)
    tariffe: list[Tariffa] = field(default_factory=list)
    coefficiente: float = COEFFICIENTE_DEFAULT
    mancanti: list[tuple[date, date]] = field(default_factory=list)
    ultimo_aggiornamento: datetime | None = None
    storico_completo: bool = False

    @property
    def ultima(self) -> Lettura | None:
        """Lettura più recente."""
        return self.letture[-1] if self.letture else None

    @property
    def ultimo_periodo(self) -> Periodo | None:
        """Periodo che termina con la lettura più recente."""
        if not self.periodi or self.ultima is None:
            return None
        periodo = self.periodi[-1]
        return periodo if periodo.fine == self.ultima else None


def id_statistica(pdr: str) -> str:
    """Identificativo della statistica esterna dei consumi del PDR."""
    return f"{DOMAIN}:consumo_gas_{pdr}"


def id_statistica_costo(pdr: str) -> str:
    """Identificativo della statistica esterna dei costi stimati del PDR."""
    return f"{DOMAIN}:costo_gas_{pdr}"


class ItalgasCoordinator(DataUpdateCoordinator[DatiItalgas]):
    """Scarica periodicamente le letture e ne conserva lo storico."""

    config_entry: ItalgasConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ItalgasConfigEntry, client: ItalgasClient
    ) -> None:
        """Inizializza il coordinatore."""
        ore = entry.options.get(CONF_INTERVALLO_ORE, INTERVALLO_ORE_DEFAULT)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            # niente PDR nel nome: compare nei log che gli utenti condividono
            name=f"{DOMAIN} {entry.data.get(CONF_ALIAS) or entry.data[CONF_PDR][-4:]}",
            update_interval=timedelta(hours=ore),
        )
        self.client = client
        self.pdr: str = entry.data[CONF_PDR]
        self.impostazioni = Impostazioni.da_entry(entry)
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._letture: dict[tuple[date, str], Lettura] = {}
        self._mancanti: list[tuple[date, date]] = []
        self._data_minima: date | None = None
        self._ultimo_aggiornamento: datetime | None = None
        self._storico_completo = False
        self._firma_statistiche: str | None = None
        self._recupero: asyncio.Task[None] | None = None

    async def _async_setup(self) -> None:
        """Carica lo storico salvato."""
        if not self.impostazioni.tariffe:
            # nessun periodo tariffario (o tutti rimossi): niente statistica dei costi
            get_instance(self.hass).async_clear_statistics([id_statistica_costo(self.pdr)])
        salvati = await self._store.async_load()
        if not salvati:
            return
        try:
            for voce in salvati.get("letture", []):
                lettura = Lettura.da_dict(voce)
                self._letture[(lettura.data, lettura.matricola)] = lettura
            self._mancanti = [
                (date.fromisoformat(a), date.fromisoformat(b))
                for a, b in salvati.get("mancanti", [])
            ]
            if minima := salvati.get("data_minima"):
                self._data_minima = date.fromisoformat(minima)
            if ultimo := salvati.get("ultimo_aggiornamento"):
                self._ultimo_aggiornamento = dt_util.parse_datetime(ultimo)
            # la versione 1.0.0 scaricava sempre tutto lo storico al primo avvio
            self._storico_completo = bool(salvati.get("storico_completo", self._letture))
            self._firma_statistiche = salvati.get("firma_statistiche")
        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.warning("Storico salvato non leggibile, verrà riscaricato: %s", err)
            self._letture.clear()
            self._mancanti.clear()
            self._data_minima = None
            self._storico_completo = False
            self._firma_statistiche = None

    def _inizio_ricerca(self, oggi: date) -> date:
        """Da quando scaricare: le ultime settimane e gli eventuali periodi mancanti."""
        if not self._letture:
            return oggi - timedelta(days=GIORNI_PRIMO_AVVIO)
        inizio = max(d for d, _ in self._letture) - timedelta(days=GIORNI_RILETTURA)
        if self._mancanti:
            inizio = min(inizio, *(a for a, _ in self._mancanti))
        if self._data_minima:
            inizio = max(inizio, self._data_minima)
        return min(inizio, oggi)

    async def _temperature(self, letture: list[Lettura]) -> dict[date, float] | None:
        """Temperature medie giornaliere (°C) dalle statistiche del sensore scelto."""
        imp = self.impostazioni
        if imp.distribuzione is not Distribuzione.GRADI_GIORNO or not imp.sensore_temperatura:
            return None
        if len(letture) < 2:
            return {}
        inizio = dt_util.start_of_local_day(letture[0].data)
        fine = dt_util.start_of_local_day(letture[-1].data + timedelta(days=1))
        righe = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            inizio,
            fine,
            {imp.sensore_temperatura},
            "day",
            {"temperature": UnitOfTemperature.CELSIUS},
            {"mean"},
        )
        temperature = {
            dt_util.as_local(dt_util.utc_from_timestamp(r["start"])).date(): r["mean"]
            for r in righe.get(imp.sensore_temperatura, [])
            if r.get("mean") is not None
        }
        _LOGGER.debug("Temperature disponibili per %d giorni", len(temperature))
        return temperature

    async def _calcola(self) -> DatiItalgas:
        imp = self.impostazioni
        letture = calcoli.ordina(self._letture.values())
        giorni = calcoli.calcola_giorni(
            letture, imp.coefficiente, imp.tariffe, await self._temperature(letture)
        )
        return DatiItalgas(
            letture=letture,
            periodi=calcoli.periodi(letture),
            giorni=giorni,
            tariffe=imp.tariffe,
            coefficiente=imp.coefficiente,
            mancanti=list(self._mancanti),
            ultimo_aggiornamento=self._ultimo_aggiornamento,
            storico_completo=self._storico_completo,
        )

    async def _async_update_data(self) -> DatiItalgas:
        """Scarica le letture nuove e aggiorna storico e statistiche."""
        oggi = dt_util.now().date()
        inizio = self._inizio_ricerca(oggi)
        try:
            risultato = await self.client.scarica_letture(self.pdr, inizio, oggi)
        except ItalgasAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except ItalgasPdrNotFoundError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="pdr_not_found",
                translation_placeholders={"pdr": self.pdr},
            ) from err
        except ItalgasError as err:
            if self.data is None and self._letture:
                # Primo avvio con storico salvato: si mostrano i dati noti e si riprova
                # al prossimo aggiornamento.
                _LOGGER.warning("Aggiornamento MyItalgas non riuscito: %s", err)
                dati = await self._calcola()
                await self._importa_statistiche(dati)
                return dati
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"errore": str(err)},
            ) from err

        dati = await self._unisci(inizio, risultato)
        if not self._storico_completo and self._recupero is None:
            self._recupero = self.config_entry.async_create_background_task(
                self.hass, self._recupera_storico(), f"{DOMAIN} storico {self.pdr[-4:]}"
            )
        return dati

    async def _unisci(self, inizio: date | None, risultato: RisultatoLetture) -> DatiItalgas:
        """Aggiunge le letture scaricate allo storico, lo salva e aggiorna le statistiche."""
        for lettura in risultato.letture:
            self._letture[(lettura.data, lettura.matricola)] = lettura
        # i periodi mancanti dentro l'intervallo appena scaricato sono stati riprovati
        precedenti = {m for m in self._mancanti if inizio is not None and m[1] < inizio}
        self._mancanti = sorted(precedenti | set(risultato.mancanti))
        if risultato.data_minima:
            self._data_minima = risultato.data_minima
        self._ultimo_aggiornamento = dt_util.utcnow()
        dati = await self._calcola()
        await self._importa_statistiche(dati)
        await self._salva()
        return dati

    async def _recupera_storico(self) -> None:
        """Scarica in background lo storico completo dopo la prima configurazione."""
        try:
            risultato = await self.client.scarica_letture(self.pdr, None, dt_util.now().date())
        except ItalgasError as err:
            _LOGGER.warning(
                "Storico MyItalgas non ancora scaricato, nuovo tentativo al prossimo "
                "aggiornamento: %s",
                err,
            )
            return
        finally:
            self._recupero = None
        self._storico_completo = True
        self.async_set_updated_data(await self._unisci(None, risultato))
        _LOGGER.debug("Storico completo scaricato: %d letture", len(self._letture))

    async def _salva(self) -> None:
        await self._store.async_save(
            {
                "letture": [
                    x.come_dict() for x in sorted(self._letture.values(), key=lambda x: x.data)
                ],
                "mancanti": [[a.isoformat(), b.isoformat()] for a, b in self._mancanti],
                "data_minima": self._data_minima.isoformat() if self._data_minima else None,
                "ultimo_aggiornamento": (
                    self._ultimo_aggiornamento.isoformat() if self._ultimo_aggiornamento else None
                ),
                "storico_completo": self._storico_completo,
                "firma_statistiche": self._firma_statistiche,
            }
        )

    async def _importa_statistiche(self, dati: DatiItalgas) -> None:
        """Statistiche esterne di consumi e costi per il pannello Energia.

        I consumi sono collocati nei giorni a cui si riferiscono (ripartiti tra due
        letture, oppure tutti nel giorno della lettura). Se la disposizione dei punti
        cambia, le statistiche vengono svuotate prima di reimportarle, così non restano
        punti orfani con valori vecchi.
        """
        imp = self.impostazioni
        punti = calcoli.punti_consumo(
            dati.letture, dati.giorni, imp.distribuzione, imp.statistica_smc
        )
        if not punti:
            return
        costi = calcoli.punti_costo(dati.letture, dati.giorni, imp.distribuzione)
        modo = "letture" if imp.distribuzione is Distribuzione.LETTURA else "giorni"
        firma = f"{modo}|{punti[0].data.isoformat()}|{costi[0].data.isoformat() if costi else '-'}"
        if firma != self._firma_statistiche:
            _LOGGER.debug("Disposizione delle statistiche cambiata, reimportazione completa")
            get_instance(self.hass).async_clear_statistics(
                [id_statistica(self.pdr), id_statistica_costo(self.pdr)]
            )
            self._firma_statistiche = firma

        alias = self.config_entry.data.get(CONF_ALIAS) or self.pdr
        async_add_external_statistics(
            self.hass,
            StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"MyItalgas {alias} consumo gas",
                source=DOMAIN,
                statistic_id=id_statistica(self.pdr),
                unit_class=VolumeConverter.UNIT_CLASS,
                unit_of_measurement=UnitOfVolume.CUBIC_METERS,
            ),
            _statistiche(punti),
        )
        if not costi:
            return
        async_add_external_statistics(
            self.hass,
            StatisticMetaData(
                mean_type=StatisticMeanType.NONE,
                has_sum=True,
                name=f"MyItalgas {alias} costo gas",
                source=DOMAIN,
                statistic_id=id_statistica_costo(self.pdr),
                unit_class=None,
                unit_of_measurement=self.hass.config.currency,
            ),
            _statistiche(costi),
        )


def _statistiche(punti: list[PuntoStatistica]) -> list[StatisticData]:
    righe = []
    for p in punti:
        riga = StatisticData(start=dt_util.start_of_local_day(p.data), sum=p.somma)
        if p.lettura is not None:
            riga["state"] = p.lettura
        righe.append(riga)
    return righe
