# Novità

Tutte le modifiche rilevanti di MyItalgas per Home Assistant.

## [1.2.1] - 2026-10-19

### Correzioni

- Guida al prezzo: sulle quote fisse l'IVA è sempre al 22% (il 10% vale solo per i
  consumi fino a 480 Smc/anno). Corretto anche il suggerimento nel modulo del periodo
  tariffario.
- Guida al prezzo: chiarito che gli scaglioni si applicano sul consumo cumulato dal
  1° gennaio, come nelle bollette, e aggiunte le indicazioni per le offerte indicizzate.

## [1.2.0] - 2026-10-19

### Novità

- **Periodi tariffari** al posto del prezzo unico: ognuno ha una data di decorrenza, tre
  prezzi variabili per gli scaglioni annui (fino a 120 Smc, da 121 a 480, oltre 480) e
  una quota fissa mensile, tutti IVA inclusa. Si aggiungono e modificano dalla pagina
  dell'integrazione. Cambiare prezzo non ricalcola più lo storico con il prezzo nuovo.
- **Costi calcolati come in bolletta**: consumo convertito in Smc con il coefficiente C,
  prezzo del periodo in vigore e dello scaglione raggiunto dal 1° gennaio (con divisione
  pro quota quando si attraversa una soglia o si cambia anno), più le quote fisse
  ripartite giorno per giorno.
- **Consumi distribuiti sui giorni** nel pannello Energia (predefinito): niente più picco
  nel giorno della lettura. In alternativa distribuzione in base ai gradi giorno di un
  sensore di temperatura esterna, oppure tutto nel giorno della lettura come prima.
- **Statistica dei consumi in Smc** (opzione): totali uguali agli Smc della bolletta.
- Nuovi sensori **Consumo anno corrente (Smc)**, **Costo stimato anno corrente** e
  **Prezzo marginale attuale**.
- **Riparazioni**: se il coefficiente C è ancora quello predefinito compare un promemoria
  da cui impostarlo direttamente.

### Miglioramenti

- I consumi annui dividono pro quota i periodi a cavallo di due anni.
- Cambiando la distribuzione le statistiche vengono ricalcolate da capo, senza lasciare
  punti con valori vecchi.
- README: nuova guida "Come calcolare il prezzo".

### Aggiornamento dalla 1.1

- Il prezzo unico impostato nelle opzioni diventa automaticamente un periodo tariffario
  valido da sempre, con lo stesso prezzo per i tre scaglioni e quota fissa zero.
  Aggiornalo con i prezzi della bolletta per avere costi più precisi.
- Le statistiche vengono ricalcolate con la distribuzione giornaliera al primo avvio.

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
