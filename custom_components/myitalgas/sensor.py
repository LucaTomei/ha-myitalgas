"""Sensori MyItalgas."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import calcoli
from .const import CONF_ALIAS, CONF_MATRICOLA, DOMAIN, PORTALE_URL
from .coordinator import DatiItalgas, ItalgasConfigEntry, ItalgasCoordinator

# Il coordinatore aggiorna tutte le entità insieme: nessun limite di parallelismo.
PARALLEL_UPDATES = 0

UNITA_SMC = "Smc"
UNITA_M3_GIORNO = "m³/d"

type Valore = float | int | str | date | datetime | None


@dataclass(frozen=True, kw_only=True)
class ItalgasSensorDescription(SensorEntityDescription):
    """Descrizione di un sensore MyItalgas."""

    valore: Callable[[DatiItalgas, float], Valore]
    attributi: Callable[[DatiItalgas], dict[str, Any] | None] = lambda _: None
    # unità di misura che dipende dalla valuta configurata in Home Assistant
    unita_valuta: Callable[[str], str] | None = None


def _data(giorno: date | None) -> str | None:
    return giorno.isoformat() if giorno else None


def _attributi_lettura(dati: DatiItalgas) -> dict[str, Any] | None:
    if (ultima := dati.ultima) is None:
        return None
    return {
        "data_lettura": _data(ultima.data),
        "tipologia": ultima.tipologia,
        "matricola": ultima.matricola,
    }


def _attributi_periodo(dati: DatiItalgas) -> dict[str, Any] | None:
    if (periodo := dati.ultimo_periodo) is None:
        return None
    return {
        "dal": _data(periodo.inizio.data),
        "al": _data(periodo.fine.data),
        "giorni": periodo.giorni,
    }


def _consumo_periodo(dati: DatiItalgas, coefficiente: float = 1.0) -> float | None:
    if (periodo := dati.ultimo_periodo) is None:
        return None
    # arrotondamento solo per togliere il rumore dei numeri in virgola mobile
    return round(periodo.consumo * coefficiente, 6)


def _media(dati: DatiItalgas, _coeff: float) -> float | None:
    periodo = dati.ultimo_periodo
    media = periodo.media_giornaliera if periodo else None
    return round(media, 3) if media is not None else None


def _per_anno(
    funzione: Callable[[list[calcoli.Giorno], int], float | None], scarto: int
) -> Callable[[DatiItalgas, float], float | None]:
    def valore(dati: DatiItalgas, _coeff: float) -> float | None:
        anno = dt_util.now().year - scarto
        risultato = funzione(dati.giorni, anno)
        if risultato is None and scarto == 0 and dati.giorni and dati.giorni[-1].data.year < anno:
            # nessuna lettura ancora arrivata quest'anno
            return 0.0
        return risultato

    return valore


def _costo_anno(dati: DatiItalgas, _coeff: float) -> float | None:
    if not dati.tariffe:
        return None
    return _per_anno(calcoli.costo_anno, 0)(dati, _coeff)


def _prezzo_marginale(dati: DatiItalgas, _coeff: float) -> float | None:
    return calcoli.prezzo_marginale(dati.giorni, dati.tariffe, dt_util.now().date())


def _attributi_prezzo(dati: DatiItalgas) -> dict[str, Any] | None:
    oggi = dt_util.now().date()
    if (tariffa := calcoli.tariffa_in_vigore(dati.tariffe, oggi)) is None:
        return None
    cumulato = sum(g.smc for g in dati.giorni if g.data.year == oggi.year)
    return {
        "scaglione": calcoli.scaglione(cumulato),
        "consumo_anno_smc": round(cumulato, 2),
        "tariffa_dal": tariffa.dal.isoformat(),
    }


def _attributi_anno(scarto: int) -> Callable[[DatiItalgas], dict[str, Any]]:
    return lambda _dati: {"anno": dt_util.now().year - scarto}


SENSORI: tuple[ItalgasSensorDescription, ...] = (
    ItalgasSensorDescription(
        key="lettura",
        translation_key="lettura",
        device_class=SensorDeviceClass.GAS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        valore=lambda d, _: d.ultima.valore if d.ultima else None,
        attributi=_attributi_lettura,
    ),
    ItalgasSensorDescription(
        key="data_lettura",
        translation_key="data_lettura",
        device_class=SensorDeviceClass.DATE,
        valore=lambda d, _: d.ultima.data if d.ultima else None,
        attributi=lambda d: {"tipologia": d.ultima.tipologia} if d.ultima else None,
    ),
    ItalgasSensorDescription(
        key="consumo_periodo",
        translation_key="consumo_periodo",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        valore=lambda d, _: _consumo_periodo(d),
        attributi=_attributi_periodo,
    ),
    ItalgasSensorDescription(
        key="consumo_periodo_smc",
        translation_key="consumo_periodo_smc",
        native_unit_of_measurement=UNITA_SMC,
        suggested_display_precision=2,
        valore=_consumo_periodo,
        attributi=_attributi_periodo,
    ),
    ItalgasSensorDescription(
        key="media_giornaliera",
        translation_key="media_giornaliera",
        native_unit_of_measurement=UNITA_M3_GIORNO,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        valore=_media,
        attributi=_attributi_periodo,
    ),
    ItalgasSensorDescription(
        key="consumo_anno",
        translation_key="consumo_anno",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=0,
        valore=_per_anno(calcoli.consumo_anno, 0),
        attributi=_attributi_anno(0),
    ),
    ItalgasSensorDescription(
        key="consumo_anno_smc",
        translation_key="consumo_anno_smc",
        native_unit_of_measurement=UNITA_SMC,
        suggested_display_precision=0,
        valore=_per_anno(calcoli.smc_anno, 0),
        attributi=_attributi_anno(0),
    ),
    ItalgasSensorDescription(
        key="consumo_anno_precedente",
        translation_key="consumo_anno_precedente",
        device_class=SensorDeviceClass.GAS,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=0,
        valore=_per_anno(calcoli.consumo_anno, 1),
        attributi=_attributi_anno(1),
    ),
    ItalgasSensorDescription(
        key="costo_stimato_anno",
        translation_key="costo_stimato_anno",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        valore=_costo_anno,
        attributi=_attributi_anno(0),
        unita_valuta=lambda valuta: valuta,
    ),
    ItalgasSensorDescription(
        key="prezzo_marginale_attuale",
        translation_key="prezzo_marginale_attuale",
        suggested_display_precision=3,
        valore=_prezzo_marginale,
        attributi=_attributi_prezzo,
        unita_valuta=lambda valuta: f"{valuta}/Smc",
    ),
    ItalgasSensorDescription(
        key="ultimo_aggiornamento",
        translation_key="ultimo_aggiornamento",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        valore=lambda d, _: d.ultimo_aggiornamento,
        attributi=lambda d: {
            "storico_completo": d.storico_completo,
            "periodi_non_scaricati": [f"{a.isoformat()}/{b.isoformat()}" for a, b in d.mancanti],
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ItalgasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crea i sensori della fornitura."""
    coordinator = entry.runtime_data
    async_add_entities(ItalgasSensor(coordinator, descrizione) for descrizione in SENSORI)


class ItalgasSensor(CoordinatorEntity[ItalgasCoordinator], SensorEntity):
    """Sensore basato sulle letture MyItalgas."""

    _attr_has_entity_name = True
    entity_description: ItalgasSensorDescription

    def __init__(
        self, coordinator: ItalgasCoordinator, descrizione: ItalgasSensorDescription
    ) -> None:
        """Inizializza il sensore."""
        super().__init__(coordinator)
        self.entity_description = descrizione
        self._attr_unique_id = f"{coordinator.pdr}_{descrizione.key}"
        if descrizione.unita_valuta is not None:
            self._attr_native_unit_of_measurement = descrizione.unita_valuta(
                coordinator.hass.config.currency
            )
        dati_entry = coordinator.config_entry.data
        alias = dati_entry.get(CONF_ALIAS)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.pdr)},
            name=f"Gas {alias}" if alias else f"Gas PDR {coordinator.pdr}",
            manufacturer="Italgas Reti",
            model="Contatore gas",
            serial_number=(
                coordinator.data.ultima.matricola
                if coordinator.data and coordinator.data.ultima
                else dati_entry.get(CONF_MATRICOLA) or None
            ),
            configuration_url=PORTALE_URL,
        )

    @property
    def available(self) -> bool:
        """Le letture sono uno storico: restano valide anche se il portale non risponde."""
        return self.coordinator.data is not None and (
            self.coordinator.last_update_success or self.coordinator.data.ultima is not None
        )

    @property
    def native_value(self) -> Valore:
        """Valore del sensore."""
        return self.entity_description.valore(
            self.coordinator.data, self.coordinator.data.coefficiente
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Attributi aggiuntivi."""
        return self.entity_description.attributi(self.coordinator.data)
