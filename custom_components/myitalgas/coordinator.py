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
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
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
from .calcoli import Periodo
from .const import (
    COEFFICIENTE_DEFAULT,
    CONF_ALIAS,
    CONF_COEFFICIENTE,
    CONF_INTERVALLO_ORE,
    CONF_PDR,
    CONF_PREZZO,
    DOMAIN,
    GIORNI_PRIMO_AVVIO,
    GIORNI_RILETTURA,
    INTERVALLO_ORE_DEFAULT,
    PREZZO_DEFAULT,
    STORAGE_VERSION,
)
from .parser import Lettura

_LOGGER = logging.getLogger(__name__)

type ItalgasConfigEntry = ConfigEntry[ItalgasCoordinator]


@dataclass(slots=True)
class DatiItalgas:
    """Dati esposti alle entità."""

    letture: list[Lettura]
    periodi: list[Periodo]
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
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._letture: dict[tuple[date, str], Lettura] = {}
        self._mancanti: list[tuple[date, date]] = []
        self._data_minima: date | None = None
        self._ultimo_aggiornamento: datetime | None = None
        self._storico_completo = False
        self._recupero: asyncio.Task[None] | None = None

    async def _async_setup(self) -> None:
        """Carica lo storico salvato."""
        if not self.config_entry.options.get(CONF_PREZZO, PREZZO_DEFAULT):
            # prezzo non impostato (o tolto): niente statistica dei costi
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
        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.warning("Storico salvato non leggibile, verrà riscaricato: %s", err)
            self._letture.clear()
            self._mancanti.clear()
            self._data_minima = None
            self._storico_completo = False

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

    def _dati(self) -> DatiItalgas:
        letture = calcoli.ordina(self._letture.values())
        return DatiItalgas(
            letture=letture,
            periodi=calcoli.periodi(letture),
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
                return self._dati()
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
        await self._salva()
        dati = self._dati()
        self._importa_statistiche(dati.letture)
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
            }
        )

    def _importa_statistiche(self, letture: list[Lettura]) -> None:
        """Statistica esterna con i consumi alla data reale di ogni lettura.

        È la fonte consigliata per il pannello Energia: i sensori registrano il
        consumo solo quando Home Assistant scopre la lettura, la statistica lo
        colloca nel giorno a cui si riferisce.
        """
        punti = calcoli.punti_statistica(letture)
        if not punti:
            return
        alias = self.config_entry.data.get(CONF_ALIAS) or self.pdr
        metadati = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"MyItalgas {alias} consumo gas",
            source=DOMAIN,
            statistic_id=id_statistica(self.pdr),
            unit_class=VolumeConverter.UNIT_CLASS,
            unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        )
        statistiche = [
            StatisticData(
                start=dt_util.start_of_local_day(p.data),
                state=p.lettura,
                sum=p.somma,
            )
            for p in punti
        ]
        async_add_external_statistics(self.hass, metadati, statistiche)

        opzioni = self.config_entry.options
        if not (prezzo := opzioni.get(CONF_PREZZO, PREZZO_DEFAULT)):
            return
        # Il pannello Energia non accetta un prezzo fisso per le statistiche esterne:
        # serve una statistica dei costi. Stima con un prezzo unico per tutto lo storico.
        euro_per_m3 = prezzo * opzioni.get(CONF_COEFFICIENTE, COEFFICIENTE_DEFAULT)
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
            [
                StatisticData(
                    start=dt_util.start_of_local_day(p.data),
                    sum=round(p.somma * euro_per_m3, 4),
                )
                for p in punti
            ],
        )
