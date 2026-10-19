"""Configurazione dell'integrazione MyItalgas dall'interfaccia."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    DateSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    ItalgasAuthError,
    ItalgasClient,
    ItalgasConnectionError,
    ItalgasError,
)
from .calcoli import Distribuzione
from .const import (
    COEFFICIENTE_DEFAULT,
    COEFFICIENTE_MAX,
    COEFFICIENTE_MIN,
    CONF_ALIAS,
    CONF_COEFFICIENTE,
    CONF_DAL,
    CONF_DISTRIBUZIONE,
    CONF_INDIRIZZO,
    CONF_INTERVALLO_ORE,
    CONF_MATRICOLA,
    CONF_PDR,
    CONF_PREZZO_SC1,
    CONF_PREZZO_SC2,
    CONF_PREZZO_SC3,
    CONF_QUOTA_FISSA,
    CONF_SENSORE_TEMPERATURA,
    CONF_STATISTICA_SMC,
    DISTRIBUZIONE_DEFAULT,
    DOMAIN,
    INTERVALLO_ORE_DEFAULT,
    INTERVALLO_ORE_MAX,
    INTERVALLO_ORE_MIN,
    SUBENTRY_TARIFFA,
)
from .parser import Fornitura

_LOGGER = logging.getLogger(__name__)


def _schema_credenziali(username: str | None = None) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME, default=username or vol.UNDEFINED): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="username")
            ),
            vol.Required(CONF_PASSWORD): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
            ),
        }
    )


async def _forniture(hass: HomeAssistant, username: str, password: str) -> list[Fornitura]:
    """Verifica le credenziali e ritorna le forniture del profilo."""
    session = async_create_clientsession(hass, auto_cleanup=False)
    try:
        client = ItalgasClient(session, username, password)
        await client.login()
        return await client.forniture()
    finally:
        session.detach()


async def _verifica(
    hass: HomeAssistant, dati: Mapping[str, Any]
) -> tuple[list[Fornitura], dict[str, str]]:
    """Ritorna (forniture, errori del form)."""
    try:
        forniture = await _forniture(hass, dati[CONF_USERNAME].strip(), dati[CONF_PASSWORD])
    except ItalgasAuthError:
        return [], {"base": "invalid_auth"}
    except ItalgasConnectionError:
        return [], {"base": "cannot_connect"}
    except ItalgasError as err:
        _LOGGER.warning("Risposta inattesa dal portale MyItalgas: %s", err)
        return [], {"base": "portal_error"}
    except Exception:
        _LOGGER.exception("Errore imprevisto durante la verifica delle credenziali")
        return [], {"base": "unknown"}
    if not forniture:
        return [], {"base": "no_pdr"}
    return forniture, {}


def _etichetta(fornitura: Fornitura) -> str:
    parti = [fornitura.pdr, fornitura.alias, fornitura.indirizzo]
    return " – ".join(p for p in parti if p)


class ItalgasConfigFlow(ConfigFlow, domain=DOMAIN):
    """Flusso di configurazione MyItalgas."""

    VERSION = 1
    # 1.2: prezzo unico sostituito dai periodi tariffari (sottovoci)
    MINOR_VERSION = 2

    def __init__(self) -> None:
        """Inizializza il flusso."""
        self._credenziali: dict[str, str] = {}
        self._forniture: list[Fornitura] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ItalgasOptionsFlow:
        """Opzioni dell'integrazione."""
        return ItalgasOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Sottovoci gestibili dall'interfaccia: i periodi tariffari."""
        return {SUBENTRY_TARIFFA: TariffaSubentryFlow}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Credenziali MyItalgas."""
        errori: dict[str, str] = {}
        if user_input is not None:
            forniture, errori = await _verifica(self.hass, user_input)
            if not errori:
                configurati = self._async_current_ids(include_ignore=False)
                libere = [f for f in forniture if f.pdr not in configurati]
                if not libere:
                    return self.async_abort(reason="already_configured")
                self._credenziali = {
                    CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                }
                self._forniture = libere
                if len(libere) == 1:
                    return await self._crea(libere[0])
                return await self.async_step_pdr()

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _schema_credenziali(), {CONF_USERNAME: (user_input or {}).get(CONF_USERNAME)}
            ),
            errors=errori,
        )

    async def async_step_pdr(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Scelta della fornitura, se il profilo ne ha più di una."""
        if user_input is not None:
            scelta = next(f for f in self._forniture if f.pdr == user_input[CONF_PDR])
            return await self._crea(scelta)
        opzioni = [SelectOptionDict(value=f.pdr, label=_etichetta(f)) for f in self._forniture]
        return self.async_show_form(
            step_id="pdr",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PDR): SelectSelector(
                        SelectSelectorConfig(options=opzioni, mode=SelectSelectorMode.LIST)
                    )
                }
            ),
        )

    async def _crea(self, fornitura: Fornitura) -> ConfigFlowResult:
        await self.async_set_unique_id(fornitura.pdr)
        self._abort_if_unique_id_configured()
        titolo = (
            f"{fornitura.alias} ({fornitura.pdr})" if fornitura.alias else f"PDR {fornitura.pdr}"
        )
        return self.async_create_entry(
            title=titolo,
            data={
                **self._credenziali,
                CONF_PDR: fornitura.pdr,
                CONF_ALIAS: fornitura.alias,
                CONF_INDIRIZZO: fornitura.indirizzo,
                CONF_MATRICOLA: fornitura.matricola,
            },
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Il portale ha rifiutato le credenziali salvate."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Nuove credenziali dopo un rifiuto."""
        return await self._aggiorna_credenziali(
            "reauth_confirm", self._get_reauth_entry(), user_input, "reauth_successful"
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Cambio delle credenziali su richiesta dell'utente."""
        return await self._aggiorna_credenziali(
            "reconfigure", self._get_reconfigure_entry(), user_input, "reconfigure_successful"
        )

    async def _aggiorna_credenziali(
        self,
        step_id: str,
        entry: ConfigEntry,
        user_input: dict[str, Any] | None,
        esito: str,
    ) -> ConfigFlowResult:
        errori: dict[str, str] = {}
        if user_input is not None:
            forniture, errori = await _verifica(self.hass, user_input)
            if not errori and not any(f.pdr == entry.data[CONF_PDR] for f in forniture):
                errori = {"base": "pdr_missing"}
            if not errori:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **entry.data,
                        CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
                if entry.state is not ConfigEntryState.LOADED:
                    # fornitura non avviata (credenziali rifiutate all'avvio): nessun
                    # listener attivo che la ricarichi
                    self.hass.config_entries.async_schedule_reload(entry.entry_id)
                return self.async_abort(reason=esito)
        return self.async_show_form(
            step_id=step_id,
            data_schema=_schema_credenziali(entry.data[CONF_USERNAME]),
            description_placeholders={"pdr": entry.data[CONF_PDR]},
            errors=errori,
        )


class ItalgasOptionsFlow(OptionsFlow):
    """Opzioni: aggiornamento, coefficiente di conversione, distribuzione dei consumi."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Modifica delle opzioni."""
        errori: dict[str, str] = {}
        if user_input is not None:
            distribuzione = user_input[CONF_DISTRIBUZIONE]
            sensore = user_input.get(CONF_SENSORE_TEMPERATURA) or None
            if distribuzione == Distribuzione.GRADI_GIORNO and not sensore:
                errori[CONF_SENSORE_TEMPERATURA] = "sensore_richiesto"
            else:
                opzioni = {
                    CONF_INTERVALLO_ORE: int(user_input[CONF_INTERVALLO_ORE]),
                    CONF_COEFFICIENTE: float(user_input[CONF_COEFFICIENTE]),
                    CONF_DISTRIBUZIONE: distribuzione,
                    CONF_STATISTICA_SMC: bool(user_input.get(CONF_STATISTICA_SMC, False)),
                }
                if sensore:
                    opzioni[CONF_SENSORE_TEMPERATURA] = sensore
                return self.async_create_entry(data=opzioni)

        attuali = dict(self.config_entry.options)
        if user_input is not None:
            attuali.update(user_input)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_INTERVALLO_ORE,
                    default=attuali.get(CONF_INTERVALLO_ORE, INTERVALLO_ORE_DEFAULT),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=INTERVALLO_ORE_MIN,
                        max=INTERVALLO_ORE_MAX,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="h",
                    )
                ),
                vol.Required(
                    CONF_COEFFICIENTE,
                    default=attuali.get(CONF_COEFFICIENTE, COEFFICIENTE_DEFAULT),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=COEFFICIENTE_MIN,
                        max=COEFFICIENTE_MAX,
                        step="any",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_DISTRIBUZIONE,
                    default=attuali.get(CONF_DISTRIBUZIONE, DISTRIBUZIONE_DEFAULT),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[d.value for d in Distribuzione],
                        mode=SelectSelectorMode.LIST,
                        translation_key=CONF_DISTRIBUZIONE,
                    )
                ),
                vol.Optional(
                    CONF_SENSORE_TEMPERATURA,
                    description={"suggested_value": attuali.get(CONF_SENSORE_TEMPERATURA)},
                ): EntitySelector(
                    EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Required(
                    CONF_STATISTICA_SMC,
                    default=attuali.get(CONF_STATISTICA_SMC, False),
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errori)


def _schema_tariffa(attuali: Mapping[str, Any]) -> vol.Schema:
    def prezzo() -> NumberSelector:
        return NumberSelector(
            NumberSelectorConfig(
                min=0, max=10, step="any", mode=NumberSelectorMode.BOX, unit_of_measurement="€/Smc"
            )
        )

    def suggerito(chiave: str) -> dict[str, Any]:
        return {"suggested_value": attuali.get(chiave)}

    return vol.Schema(
        {
            vol.Required(CONF_DAL, description=suggerito(CONF_DAL)): DateSelector(),
            vol.Required(CONF_PREZZO_SC1, description=suggerito(CONF_PREZZO_SC1)): prezzo(),
            vol.Optional(CONF_PREZZO_SC2, description=suggerito(CONF_PREZZO_SC2)): prezzo(),
            vol.Optional(CONF_PREZZO_SC3, description=suggerito(CONF_PREZZO_SC3)): prezzo(),
            vol.Optional(CONF_QUOTA_FISSA, description=suggerito(CONF_QUOTA_FISSA)): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=1000,
                    step="any",
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="€/mese",
                )
            ),
        }
    )


def _dati_tariffa(user_input: Mapping[str, Any]) -> dict[str, Any]:
    """Normalizza il form: gli scaglioni non compilati prendono il prezzo del precedente."""
    sc1 = float(user_input[CONF_PREZZO_SC1])
    sc2 = user_input.get(CONF_PREZZO_SC2)
    sc2 = sc1 if sc2 is None else float(sc2)
    sc3 = user_input.get(CONF_PREZZO_SC3)
    sc3 = sc2 if sc3 is None else float(sc3)
    return {
        CONF_DAL: date.fromisoformat(str(user_input[CONF_DAL])).isoformat(),
        CONF_PREZZO_SC1: sc1,
        CONF_PREZZO_SC2: sc2,
        CONF_PREZZO_SC3: sc3,
        CONF_QUOTA_FISSA: float(user_input.get(CONF_QUOTA_FISSA) or 0.0),
    }


def _titolo_tariffa(dati: Mapping[str, Any]) -> str:
    return f"Dal {date.fromisoformat(dati[CONF_DAL]):%d/%m/%Y}"


class TariffaSubentryFlow(ConfigSubentryFlow):
    """Aggiunta e modifica di un periodo tariffario."""

    def _date_occupate(self, esclusa: str | None = None) -> set[str]:
        return {
            s.data.get(CONF_DAL)
            for s in self._get_entry().subentries.values()
            if s.subentry_type == SUBENTRY_TARIFFA and s.subentry_id != esclusa
        }

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Nuovo periodo tariffario."""
        errori: dict[str, str] = {}
        if user_input is not None:
            dati = _dati_tariffa(user_input)
            if dati[CONF_DAL] in self._date_occupate():
                errori[CONF_DAL] = "dal_esistente"
            else:
                return self.async_create_entry(
                    title=_titolo_tariffa(dati), data=dati, unique_id=dati[CONF_DAL]
                )
        return self.async_show_form(
            step_id="user", data_schema=_schema_tariffa(user_input or {}), errors=errori
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Modifica di un periodo tariffario esistente."""
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        errori: dict[str, str] = {}
        if user_input is not None:
            dati = _dati_tariffa(user_input)
            if dati[CONF_DAL] in self._date_occupate(esclusa=subentry.subentry_id):
                errori[CONF_DAL] = "dal_esistente"
            else:
                # il listener dell'integrazione ricarica la fornitura con i nuovi prezzi
                self.hass.config_entries.async_update_subentry(
                    entry,
                    subentry,
                    data=dati,
                    title=_titolo_tariffa(dati),
                    unique_id=dati[CONF_DAL],
                )
                return self.async_abort(reason="reconfigure_successful")
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema_tariffa(user_input or dict(subentry.data)),
            errors=errori,
        )
