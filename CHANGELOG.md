# Novità

Tutte le modifiche rilevanti di MyItalgas per Home Assistant.

## [1.1.1] - 2026-10-19

### Correzioni

- Installazione da HACS più affidabile: HACS ora scarica l'integrazione dall'archivio del
  repository, come per la grande maggioranza delle integrazioni, invece che dallo zip
  allegato alla release. Con alcune versioni di HACS e su alcune reti il download dello
  zip falliva con "Could not download". Lo zip resta allegato a ogni release per
  l'installazione manuale.

## [1.1.0] - 2026-10-19

### Novità

- Configurazione in pochi secondi: al primo avvio vengono scaricate subito le letture
  recenti, mentre lo storico completo viene recuperato in background e compare nel
  pannello Energia appena pronto. Se il recupero non riesce viene ritentato da solo.
- Nuovo attributo *Storico completo scaricato* sul sensore *Ultimo aggiornamento riuscito*.

### Miglioramenti

- Meno richieste al portale (accesso diretto, nessuna pagina superflua dopo l'accesso,
  link alla fornitura riutilizzato): configurazione e aggiornamenti circa tre volte più
  rapidi.
- Il PDR non compare più nei log dell'integrazione.
- Le operazioni sul portale vengono eseguite una alla volta anche quando l'aggiornamento
  periodico e il recupero dello storico coincidono.
- Compatibilità verificata con Home Assistant 2025.11 (versione minima) e con l'ultima
  versione.

## [1.0.0] - 2026-10-19

- Prima versione.
