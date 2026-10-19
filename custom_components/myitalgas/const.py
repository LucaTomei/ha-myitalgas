"""Costanti dell'integrazione MyItalgas."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "myitalgas"

CONF_PDR: Final = "pdr"
CONF_ALIAS: Final = "alias"
CONF_INDIRIZZO: Final = "indirizzo"
CONF_MATRICOLA: Final = "matricola"
CONF_COEFFICIENTE: Final = "coefficiente"
CONF_PREZZO: Final = "prezzo"
CONF_INTERVALLO_ORE: Final = "intervallo_ore"

COEFFICIENTE_DEFAULT: Final = 1.0
PREZZO_DEFAULT: Final = 0.0
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
