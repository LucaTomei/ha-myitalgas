<p align="center">
  <img src="custom_components/myitalgas/brand/logo.png" alt="Italgas" height="80">
</p>

<h1 align="center">MyItalgas per Home Assistant</h1>

<p align="center">
  <a href="https://github.com/hacs/integration"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS Custom"></a>
  <a href="https://github.com/LucaTomei/ha-myitalgas/releases"><img src="https://img.shields.io/github/v/release/LucaTomei/ha-myitalgas" alt="Release"></a>
  <a href="https://github.com/LucaTomei/ha-myitalgas/actions/workflows/validazione.yml"><img src="https://github.com/LucaTomei/ha-myitalgas/actions/workflows/validazione.yml/badge.svg" alt="Validazione"></a>
  <img src="https://img.shields.io/badge/Home%20Assistant-2025.11%2B-03A9F4" alt="Home Assistant 2025.11+">
  <a href="LICENSE"><img src="https://img.shields.io/github/license/LucaTomei/ha-myitalgas" alt="Licenza MIT"></a>
</p>

Porta in Home Assistant le letture del tuo contatore del gas dal portale clienti
**MyItalgas** ([clienti.italgas.it](https://clienti.italgas.it)): lettura del contatore,
consumi per periodo, media giornaliera, consumi annuali e lo **storico completo nel
pannello Energia**, con ogni consumo collocato alla data reale della lettura.

Non serve nessun componente aggiuntivo: l'integrazione usa solo librerie già presenti in
Home Assistant e funziona su qualunque installazione (Home Assistant OS, Container, Core,
Supervised).

---

## Indice

- [Cosa ottieni](#cosa-ottieni)
- [Requisiti](#requisiti)
- [Installazione con HACS (consigliata)](#installazione-con-hacs-consigliata)
- [Installazione manuale](#installazione-manuale)
- [Configurazione](#configurazione)
- [Opzioni](#opzioni)
- [Pannello Energia](#pannello-energia)
- [Entità](#entità)
- [Come funziona](#come-funziona)
- [Privacy e sicurezza](#privacy-e-sicurezza)
- [Risoluzione dei problemi](#risoluzione-dei-problemi)
- [Aggiornamento e rimozione](#aggiornamento-e-rimozione)
- [Sviluppo](#sviluppo)
- [Note legali](#note-legali)

---

## Cosa ottieni

- **Lettura del contatore** in m³, utilizzabile anche nelle automazioni.
- **Consumo dell'ultimo periodo** in m³ e in Smc (standard metri cubi, quelli della bolletta).
- **Media giornaliera**, **consumo dell'anno in corso** e **dell'anno precedente**.
- **Storico completo nel pannello Energia**: al primo avvio vengono scaricate tutte le
  letture disponibili sul portale; ogni consumo compare nel giorno a cui si riferisce,
  non nel momento in cui Home Assistant lo scopre.
- **Costi stimati** nel pannello Energia, se indichi il prezzo medio del gas.
- **Più forniture**: se il tuo profilo ha più PDR puoi aggiungerli tutti.
- **Robustezza**: sessione scaduta, errori temporanei del portale, password cambiata,
  sostituzione del contatore e rettifiche delle letture sono gestiti in automatico.

## Requisiti

1. **Home Assistant 2025.11 o successivo**. Il logo Italgas nell'elenco delle integrazioni
   compare da Home Assistant 2026.3; nelle versioni precedenti l'integrazione funziona
   identica, con un'icona generica.
2. Un **account MyItalgas** su [clienti.italgas.it](https://clienti.italgas.it) con la
   fornitura (PDR) associata al profilo. Per verificarlo accedi al portale e apri
   *Le mie letture*: se vedi la fornitura, è tutto pronto. Altrimenti aggiungila dalla
   sezione **PdR** del portale (il codice PDR, 14 cifre, è riportato in bolletta).

> Il portale MyItalgas è quello del **distributore** (Italgas Reti), diverso dal sito del
> tuo venditore di gas: le credenziali sono quelle di clienti.italgas.it.

## Installazione con HACS (consigliata)

Se non hai ancora HACS, segui la [guida ufficiale di installazione](https://hacs.xyz/docs/use/).

1. Clicca qui per aprire direttamente il repository in HACS:

   [![Apri in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=LucaTomei&repository=ha-myitalgas&category=integration)

   In alternativa, a mano:
   1. Apri **HACS** dalla barra laterale.
   2. Clicca sui **tre puntini** in alto a destra → **Repository personalizzati**.
   3. In *Repository* incolla `https://github.com/LucaTomei/ha-myitalgas`, in *Tipo* scegli
      **Integrazione** e clicca **Aggiungi**.
2. Cerca **MyItalgas** in HACS, aprilo e clicca **Scarica** (in basso a destra), poi
   conferma.
3. **Riavvia Home Assistant**: *Impostazioni → Sistema →* icona di accensione in alto a
   destra → **Riavvia Home Assistant**.

## Installazione manuale

1. Scarica `myitalgas.zip` dall'[ultima release](https://github.com/LucaTomei/ha-myitalgas/releases/latest).
2. Nella cartella di configurazione di Home Assistant (quella che contiene
   `configuration.yaml`) crea, se non esiste, la cartella `custom_components`.
3. Crea al suo interno la cartella `myitalgas` ed estrai lì il contenuto dello zip.
   Il risultato deve essere `custom_components/myitalgas/manifest.json` (e gli altri file).
4. Riavvia Home Assistant.

## Configurazione

1. Clicca qui:

   [![Aggiungi integrazione](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=myitalgas)

   oppure vai in **Impostazioni → Dispositivi e servizi → + Aggiungi integrazione** e
   cerca **MyItalgas**.
2. Inserisci **username** e **password** di clienti.italgas.it e conferma.
3. Se il profilo ha più forniture, scegli quella da aggiungere. Per aggiungere le altre
   ripeti la procedura: l'integrazione propone solo quelle non ancora configurate.
4. Al primo avvio viene scaricato tutto lo storico: il portale è lento e servono **circa
   1–2 minuti**. Al termine trovi il dispositivo **Gas *nome fornitura*** con i suoi sensori.

Se il portale rifiuta la password (ad esempio perché l'hai cambiata), Home Assistant ti
mostra una notifica per inserire le nuove credenziali. Puoi cambiarle anche quando vuoi
da **⋮ → Riconfigura** sulla scheda dell'integrazione.

## Opzioni

**Impostazioni → Dispositivi e servizi → MyItalgas → Configura**

| Opzione | Predefinito | Descrizione |
|---|---|---|
| Intervallo di aggiornamento | 12 h | Ogni quanto controllare se ci sono letture nuove (1–168 ore). I contatori elettronici vengono letti circa una volta al mese, a fine mese: non serve controllare più spesso. |
| Coefficiente di conversione (m³ → Smc) | 1 | Il **coefficiente C** della tua bolletta (dipende dal comune: altitudine e zona climatica, tipicamente tra 0,95 e 1,02). Serve a calcolare i consumi in Smc. |
| Prezzo medio del gas (€/Smc) | 0 (disattivato) | Facoltativo: prezzo medio per Smc, **tutto compreso** (totale bolletta diviso Smc fatturati). Se impostato, viene creata una statistica dei costi per il pannello Energia. Lo stesso prezzo viene applicato a tutto lo storico: è una stima. |

## Pannello Energia

1. Apri **Impostazioni → Pannelli → Energia**
   ([![Apri Energia](https://my.home-assistant.io/badges/config_energy.svg)](https://my.home-assistant.io/redirect/config_energy/)).
2. Nella sezione **Consumo di gas** clicca **Aggiungi fonte di gas**.
3. Come *Consumo di gas* scegli **MyItalgas *nome fornitura* consumo gas**.

   > Scegli questa statistica e **non** il sensore *Lettura contatore*: la statistica
   > contiene tutto lo storico e mette ogni consumo nel giorno giusto; il sensore
   > registrerebbe solo i consumi futuri, nel momento in cui vengono scoperti.
4. Per i costi:
   - se hai impostato il **prezzo medio** nelle opzioni, scegli l'opzione che usa
     un'entità con i **costi totali** e seleziona **MyItalgas *nome fornitura* costo gas**;
   - altrimenti lascia *Non tenere traccia dei costi*. Il pannello Energia non permette
     di indicare un prezzo fisso per le statistiche importate: per questo esiste
     l'opzione del prezzo medio.
5. Salva. Lo storico compare subito nelle viste per giorno, settimana, mese e anno.

Le teleletture arrivano una volta al mese: nel pannello vedrai quindi un consumo per
ciascun mese, collocato nel giorno della lettura (di solito l'ultimo del mese).

## Entità

Ogni fornitura crea un dispositivo **Gas *nome fornitura*** con:

| Entità | Unità | Descrizione | Attributi |
|---|---|---|---|
| Lettura contatore | m³ | Ultima lettura del totalizzatore. `state_class: total_increasing` | data lettura, tipologia, matricola |
| Data ultima lettura | data | Data dell'ultima lettura | tipologia |
| Consumo ultimo periodo | m³ | Differenza tra le ultime due letture | dal, al, giorni |
| Consumo ultimo periodo (Smc) | Smc | Come sopra, moltiplicato per il coefficiente C | dal, al, giorni |
| Media giornaliera | m³/d | Consumo medio al giorno nell'ultimo periodo | dal, al, giorni |
| Consumo anno corrente | m³ | Somma dei periodi che terminano nell'anno in corso | anno |
| Consumo anno precedente | m³ | Come sopra, per l'anno precedente | anno |
| Ultimo aggiornamento riuscito | data e ora | Diagnostica: ultimo scaricamento andato a buon fine | periodi non scaricati |

Inoltre vengono create le statistiche a lungo termine **MyItalgas *nome fornitura*
consumo gas** (m³) e, se hai indicato un prezzo, **MyItalgas *nome fornitura* costo gas** (€).

Esempio di automazione: avviso quando arriva una nuova lettura.

```yaml
automation:
  - alias: "Nuova lettura del gas"
    triggers:
      - trigger: state
        entity_id: sensor.gas_casa_data_ultima_lettura
    conditions:
      - condition: template
        value_template: "{{ trigger.from_state.state not in ['unknown', 'unavailable'] }}"
    actions:
      - action: notify.notify
        data:
          message: >
            Nuova lettura del gas: {{ states('sensor.gas_casa_lettura_contatore') }} m³,
            consumo {{ states('sensor.gas_casa_consumo_ultimo_periodo') }} m³
            in {{ state_attr('sensor.gas_casa_consumo_ultimo_periodo', 'giorni') }} giorni.
```

Gli `entity_id` dipendono dal nome della fornitura e dalla lingua di Home Assistant:
controllali in *Impostazioni → Dispositivi e servizi → Entità*.

## Come funziona

- L'integrazione accede a clienti.italgas.it come faresti tu dal browser e legge le
  letture dalla pagina *Le mie letture*.
- **Primo avvio**: scarica tutto lo storico disponibile (il portale lo conserva da quando
  la fornitura è visibile, di solito dall'attivazione del contatore elettronico). Il
  portale va in errore su intervalli lunghi, quindi lo storico viene letto a blocchi di
  un anno.
- **Aggiornamenti successivi**: ogni 12 ore (modificabile) riscarica solo gli ultimi 90
  giorni, così recepisce anche eventuali rettifiche del distributore.
- Lo storico è salvato in Home Assistant: dopo un riavvio non viene riscaricato e i
  sensori mostrano subito i valori anche se il portale è momentaneamente irraggiungibile.
- Se il portale risponde "Errore di sistema" su un periodo, il periodo viene diviso e
  riprovato; se un pezzo continua a fallire viene segnalato nell'attributo *periodi non
  scaricati* e recuperato automaticamente all'aggiornamento successivo.
- **Sostituzione del contatore**: le letture del vecchio e del nuovo contatore sono
  distinte per matricola; i consumi non hanno salti.

## Privacy e sicurezza

- Le credenziali sono salvate solo nella tua installazione di Home Assistant, come per
  ogni altra integrazione, e vengono inviate esclusivamente a `clienti.italgas.it`.
- Nessun dato viene inviato a terzi. Non c'è nessun server intermedio.
- La **diagnostica** scaricabile oscura credenziali, PDR, matricola e indirizzo.

## Risoluzione dei problemi

| Problema | Soluzione |
|---|---|
| *Username o password errati* | Verifica di riuscire ad accedere a [clienti.italgas.it](https://clienti.italgas.it) con le stesse credenziali. |
| *Nessuna fornitura associata* | Aggiungi il PDR nella sezione **PdR** del portale, poi riprova. |
| *Il portale ha dato una risposta inattesa* | Il portale potrebbe aver attivato un controllo anti-robot o cambiato pagina: verifica di riuscire ad accedere dal browser e riprova più tardi. Se persiste, apri una segnalazione. |
| *Portale non raggiungibile* | Il portale è temporaneamente fuori servizio: l'integrazione riprova da sola. |
| I sensori sono *sconosciuti* | La fornitura non ha ancora letture sul portale (ad esempio è stata appena attivata). |
| L'ultima lettura è vecchia di un mese | È normale: i contatori elettronici vengono letti una volta al mese. |

Per segnalare un problema:

1. **Impostazioni → Dispositivi e servizi → MyItalgas → ⋮ → Abilita il debug**.
2. Riproduci il problema (ad esempio con **⋮ → Ricarica**).
3. **⋮ → Disabilita il debug**: viene scaricato il file di log.
4. Apri una [segnalazione](https://github.com/LucaTomei/ha-myitalgas/issues/new/choose)
   allegando il log e, se utile, la diagnostica (**⋮ → Scarica diagnostica**).
   Controlla sempre che il log non contenga dati personali.

## Aggiornamento e rimozione

- **Aggiornamento**: HACS segnala le nuove versioni; clicca **Aggiorna** e riavvia Home
  Assistant.
- **Rimozione**: *Impostazioni → Dispositivi e servizi → MyItalgas → ⋮ → Elimina*. Lo
  storico salvato dall'integrazione viene cancellato; le statistiche già importate restano
  nel database di Home Assistant (togli la fonte dal pannello Energia se non ti servono
  più). Poi rimuovi l'integrazione da HACS e riavvia.

## Sviluppo

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt
ruff check . && ruff format --check .
pytest
```

I test girano contro un portale simulato, costruito sulle pagine reali del portale
(anonimizzate): nessuna richiesta verso clienti.italgas.it.

Per pubblicare una nuova versione:

```bash
scripts/rilascia.sh 1.1.0
```

Lo script aggiorna la versione nel manifest, crea il commit e il tag `v1.1.0` e li invia
a GitHub. Il tag avvia il workflow *Rilascio*: esegue hassfest, la validazione HACS, lint
e test, poi crea la release con le note generate dai commit e allega `myitalgas.zip`.
Se un controllo fallisce la release non viene creata: corretto il problema, basta
rilanciare lo script con la stessa versione.

## Note legali

Integrazione **non ufficiale**, realizzata in modo indipendente e non affiliata,
approvata o supportata da Italgas S.p.A. o Italgas Reti S.p.A. Il nome e il logo Italgas
sono marchi dei rispettivi titolari e sono usati solo per identificare il servizio a cui
l'integrazione si collega. Il funzionamento dipende dal portale clienti.italgas.it, che
può cambiare senza preavviso.

Distribuita con licenza [MIT](LICENSE).
