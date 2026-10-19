"""Costanti dell'integrazione MyItalgas."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "myitalgas"

CONF_PDR: Final = "pdr"
CONF_ALIAS: Final = "alias"
CONF_INDIRIZZO: Final = "indirizzo"
CONF_MATRICOLA: Final = "matricola"
CONF_COEFFICIENTE: Final = "coefficiente"
CONF_INTERVALLO_ORE: Final = "intervallo_ore"
CONF_DISTRIBUZIONE: Final = "distribuzione"
CONF_SENSORE_TEMPERATURA: Final = "sensore_temperatura"
CONF_STATISTICA_SMC: Final = "statistica_smc"
# opzione della versione 1.x, convertita in un periodo tariffario
CONF_PREZZO_UNICO: Final = "prezzo"

# Periodi tariffari (sottovoci dell'integrazione)
SUBENTRY_TARIFFA: Final = "tariffa"
CONF_DAL: Final = "dal"
CONF_PREZZO_SC1: Final = "prezzo_sc1"
CONF_PREZZO_SC2: Final = "prezzo_sc2"
CONF_PREZZO_SC3: Final = "prezzo_sc3"
CONF_QUOTA_FISSA: Final = "quota_fissa"

COEFFICIENTE_DEFAULT: Final = 1.0
COEFFICIENTE_MIN: Final = 0.5
COEFFICIENTE_MAX: Final = 1.5
DISTRIBUZIONE_DEFAULT: Final = "giornaliera"
INTERVALLO_ORE_DEFAULT: Final = 12
INTERVALLO_ORE_MIN: Final = 1
INTERVALLO_ORE_MAX: Final = 168

# A ogni aggiornamento si riscaricano anche le ultime settimane già salvate,
# per recepire eventuali rettifiche fatte dal distributore.
GIORNI_RILETTURA: Final = 90
# Al primo avvio si scaricano subito solo le letture recenti (configurazione rapida);
# lo storico completo viene recuperato subito dopo, in background.
GIORNI_PRIMO_AVVIO: Final = 120

PORTALE_URL: Final = "https://clienti.italgas.it/clienti/"

STORAGE_VERSION: Final = 1
