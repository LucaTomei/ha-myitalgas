"""Configurazione dell'integrazione MyItalgas dall'interfaccia."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
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
from .const import (
    COEFFICIENTE_DEFAULT,
    CONF_ALIAS,
    CONF_COEFFICIENTE,
    CONF_INDIRIZZO,
    CONF_INTERVALLO_ORE,
    CONF_MATRICOLA,
    CONF_PDR,
    CONF_PREZZO,
    DOMAIN,
    INTERVALLO_ORE_DEFAULT,
    INTERVALLO_ORE_MAX,
    INTERVALLO_ORE_MIN,
    PREZZO_DEFAULT,
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

    def __init__(self) -> None:
        """Inizializza il flusso."""
        self._credenziali: dict[str, str] = {}
        self._forniture: list[Fornitura] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ItalgasOptionsFlow:
        """Opzioni dell'integrazione."""
        return ItalgasOptionsFlow()

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
            "reauth_confirm", self._get_reauth_entry(), user_input
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Cambio delle credenziali su richiesta dell'utente."""
        return await self._aggiorna_credenziali(
            "reconfigure", self._get_reconfigure_entry(), user_input
        )

    async def _aggiorna_credenziali(
        self, step_id: str, entry: ConfigEntry, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errori: dict[str, str] = {}
        if user_input is not None:
            forniture, errori = await _verifica(self.hass, user_input)
            if not errori and not any(f.pdr == entry.data[CONF_PDR] for f in forniture):
                errori = {"base": "pdr_missing"}
            if not errori:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
        return self.async_show_form(
            step_id=step_id,
            data_schema=_schema_credenziali(entry.data[CONF_USERNAME]),
            description_placeholders={"pdr": entry.data[CONF_PDR]},
            errors=errori,
        )


class ItalgasOptionsFlow(OptionsFlowWithReload):
    """Opzioni: frequenza di aggiornamento, coefficiente di conversione e prezzo."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Modifica delle opzioni."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_INTERVALLO_ORE: int(user_input[CONF_INTERVALLO_ORE]),
                    CONF_COEFFICIENTE: float(user_input[CONF_COEFFICIENTE]),
                    CONF_PREZZO: float(user_input.get(CONF_PREZZO) or 0),
                }
            )
        attuali = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
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
                            min=0.5, max=1.5, step="any", mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_PREZZO,
                        default=attuali.get(CONF_PREZZO, PREZZO_DEFAULT),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=20,
                            step="any",
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="€/Smc",
                        )
                    ),
                }
            ),
        )
