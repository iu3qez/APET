---
title: Registratore IQ a doppio tuner - Plan
type: feat
date: 2026-10-09
topic: dual-tuner-iq-recorder
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
execution: code
---

# Registratore IQ a doppio tuner - Plan

## Goal Capsule

- **Objective:** al CQ WW DX CW del 2026-11-28 un OM registra un'ora di dati IQ da due antenne che si possono rianalizzare offline in modo affidabile, senza dover regolare nulla sul ricevitore.
- **Means:** un registratore reAPET che pilota direttamente un SDR a due tuner su Linux e Windows.
- **Product authority:** `STRATEGY.md` (track "Motore di misura con validazione") e questo Product Contract. L'analisi (decoder, ΔS, ΔN, rilevamento dei gradini di livello) non è in scope attivo.
- **Open blockers:** modello esatto dell'SDR e supporto del doppio tuner con guadagno impostabile, su Linux e su Windows (vedi Outstanding Questions).

---

## Product Contract

### Summary

Un registratore che imposta e blocca guadagni uguali sui due tuner, con AGC spento. Registra l'IQ di entrambi con marche temporali per blocco, marca la saturazione mentre registra e salva dati e contesto come un'unica sessione. All'avvio chiede solo il nome delle due antenne e il locator. Di default registra una fetta stretta (sottobanda FT8 più una porzione quieta vicina); la registrazione larga è un'opzione.

### Problem Frame

Ogni analisi di reAPET ha bisogno di registrazioni affidabili, e oggi non ne esistono. Le sessioni del 2019 e del 2025 hanno tre difetti, documentati in `docs/review-2019.md`:
- a metà sessione una catena è scesa di 12 dB senza che nessuno se ne accorgesse;
- manca il contesto: nessuno ricorda cosa fosse collegato;
- la posizione della finestra del rumore dipendeva da un orologio mai verificato.

Inoltre è stato salvato solo l'output del decoder. Ogni scelta sbagliata di stimatore è quindi irreversibile, perché i dati grezzi non ci sono più per rifare l'analisi.

Il CQ WW del 2026-11-28 è un raduno con amici che portano antenne: serve a mostrare lo strumento e a formare altri OM, non a raccogliere grandi quantità di dati. Le stazioni del contest in trasmissione nelle vicinanze satureranno probabilmente i ricevitori, e sarà possibile al massimo un'ora di registrazione di prova (loop magnetico contro un'antenna reale).

### Key Decisions

- **Registrazione prima dell'analisi.** L'IQ grezzo permette di rifare l'analisi sugli stessi dati cambiando decoder o stimatore, e solo la registrazione è vincolata alla data del 2026-11-28. (session-settled: user-approved — chosen over analisi per prima o decodifica in tempo reale: senza dati grezzi una sessione non è rianalizzabile.) Governs R1, R13.
- **IQ con marche temporali, non audio.** (session-settled: user-directed — chosen over registrazione audio: richiesta esplicita di IQ e marche temporali.) Governs R1, R5.
- **SDR a due tuner con clock condiviso come hardware di riferimento.** Elimina lo sfasamento tra due interfacce USB indipendenti, che in 48 h a 50 ppm arriva a circa 8 s. (session-settled: user-directed — chosen over due QMX, due SDR separati o hardware misto.) Governs R1.
- **Registratore reAPET che pilota l'SDR.** Guadagno e AGC non sono lasciati all'operatore, coerentemente con il confine "nessuna procedura a carico dell'operatore" di `STRATEGY.md`. (session-settled: user-approved — chosen over programma SDR esistente più diario reAPET: avrebbe lasciato guadagno e AGC all'operatore.) Governs R2, R3, R9.
- **Fetta stretta di default, larga come opzione.** Sessioni piccole e archiviabili, mentre la registrazione larga resta disponibile per sperimentare (per esempio con i segnali CW del contest). (session-settled: user-approved — chosen over registrazione larga di default.) Governs R4.
- **Due nomi e locator all'avvio.** (session-settled: user-approved — chosen over profilo salvato o annotazione a posteriori: un profilo invecchia senza che nessuno se ne accorga, e a distanza di tempo nessuno ricorda le antenne.) Governs R7.
- **Linux e Windows.** (session-settled: user-directed — aggiunto alla conferma della sintesi.) Governs R12.
- **Il guadagno lo propone reAPET, poi resta bloccato.** L'operatore non regola nulla. Governs R3.
- **La saturazione è un risultato accettabile purché dichiarata.** "Dati completi" significa senza buchi non dichiarati, non senza saturazione. Governs R9, R10.
- **L'orologio viene registrato, non preteso.** Sul campo può mancare internet. La posizione reale della pausa FT8 si ricostruisce in analisi dai DT (`docs/review-2019.md`, punto 2). Governs R6.

### Requirements

**Acquisizione**

- R1. reAPET registra contemporaneamente l'IQ dei due tuner dello stesso SDR, sullo stesso clock di campionamento.
- R2. Durante una sessione i due tuner hanno guadagno uguale, AGC spento e impostazioni bloccate, e nessuna regolazione è possibile fino alla chiusura della sessione.
- R3. Prima di registrare, reAPET esegue un breve controllo del margine e propone il guadagno da usare. All'operatore non viene chiesta nessuna regolazione.
- R4. Di default la porzione registrata copre la sottobanda FT8 della banda scelta più una porzione quieta adiacente; come opzione si può registrare l'intera larghezza del tuner.

**Tempo e contesto**

- R5. Ogni blocco di campioni registrato porta la propria marca temporale.
- R6. La sessione registra lo stato dell'orologio di sistema (sincronizzato o meno, e lo scarto se noto). La registrazione parte anche con l'orologio non sincronizzato.
- R7. All'avvio reAPET chiede il nome dell'antenna su ciascun tuner e il locator. Se un dato manca la registrazione parte comunque, e il dato è marcato come mancante.
- R8. Contesto e dati formano un'unica sessione, che contiene almeno: banda, frequenza centrale, frequenza di campionamento, guadagni, corrispondenza tuner–antenna, locator, versione di reAPET, inizio e fine.

**Integrità**

- R9. Durante la registrazione reAPET rileva la saturazione o il blocco di ciascun tuner e la registra nella sessione come intervalli temporali.
- R10. Ogni interruzione (campioni persi, disconnessione, disco pieno, arresto) è registrata nella sessione: nessun buco nei dati resta non dichiarato.

**Uso**

- R11. Durante la registrazione si vede uno stato minimo: se sta registrando, quanta saturazione c'è stata, lo spazio rimasto sul disco.
- R12. Il registratore funziona su Linux e su Windows.

**Rianalisi**

- R13. Una sessione si apre offline su un'altra macchina e contiene tutto ciò che serve all'analisi: decodifica FT8, ΔS, ΔN dentro o fuori la sottobanda e, per la fase 2, la stima dell'angolo di arrivo (marche temporali, frequenze, locator).

### Key Flows

- F1. Sessione di registrazione
  - **Trigger:** l'operatore avvia una registrazione con l'SDR collegato alle due antenne.
  - **Steps:** inserisce i due nomi e il locator (R7); reAPET controlla il margine e propone il guadagno (R3); i guadagni vengono bloccati (R2); parte la registrazione con lo stato visibile (R11); saturazioni e interruzioni vengono marcate mentre accadono (R9, R10); l'operatore ferma la registrazione.
  - **Outcome:** una sessione chiusa, dati più contesto, rianalizzabile offline (R8, R13).
  - **Covered by:** R2, R3, R7, R8, R9, R10, R11, R13

### Acceptance Examples

- AE1. **Covers R9.** **Given** una registrazione in corso durante il contest, **when** una stazione vicina trasmette e satura il tuner 1 per 40 s, **then** la sessione contiene quell'intervallo marcato come saturazione sul tuner 1, e la registrazione prosegue.
- AE2. **Covers R7.** **Given** l'avvio di una sessione, **when** l'operatore non inserisce il locator, **then** la registrazione parte e la sessione riporta il locator come mancante.
- AE3. **Covers R10.** **Given** una registrazione in corso, **when** l'SDR si disconnette per 5 s e poi torna, **then** la sessione dichiara l'interruzione con inizio e fine, senza buchi silenziosi.
- AE4. **Covers R6.** **Given** un PC senza internet e con l'orologio non sincronizzato, **when** si avvia la registrazione, **then** la registrazione parte e la sessione registra che l'orologio non era sincronizzato.

### Success Criteria

- Al CQ WW del 2026-11-28 si ottiene una sessione di circa un'ora, completa secondo R8–R10: IQ di entrambi i tuner, contesto, saturazioni e interruzioni dichiarate.

### Scope Boundaries

- Decoder FT8, calcolo di ΔS e ΔN, rilevamento dei gradini di livello, report: sono nell'area di analisi, che è la prossima.
- Registrazione simultanea su più bande.
- Pacchetto installabile e uso autonomo da parte di altri OM: al CQ WW reAPET lo usa l'autore, e gli altri guardano e imparano.
- Waterfall o visualizzazioni durante la registrazione oltre lo stato minimo di R11.
- Supporto a due ricevitori separati con clock indipendenti (due QMX, due SDR).

<!-- ce-section: work-relationships -->
### How This Work Fits Together

Questo piano copre la registrazione, prima area del motore di misura. La suddivisione che segue è la comprensione attuale, non una roadmap impegnata.

- Analisi (decoder, ΔS per spot, ΔN nella pausa FT8 posizionata dai DT e invalidata quando contaminata, rilevamento dei gradini di livello): Depends on questa registrazione (R13).
  - Validazione del metodo (test di zero con splitter, coerenza tra cicli pari e dispari): Depends on l'analisi; Shares le sessioni registrate.
- Report leggibile: Depends on l'analisi.
- Angolo di arrivo (fase 2): Depends on i dati conservati secondo R13.

### Dependencies / Assumptions

- Si assume che l'SDR a due tuner dell'autore sia pilotabile in doppio tuner con guadagno impostabile da software, su Linux e su Windows. Non è verificato.
- La protezione fisica dell'ingresso dell'SDR dalle trasmissioni vicine (limitatore, distanza tra le antenne) è un prerequisito di installazione a carico dell'utente, non una funzione del registratore.

### Outstanding Questions

**Resolve Before Planning**

- Modello esatto dell'SDR a due tuner che verrà usato al CQ WW.

**Deferred to Planning**

- Supporto in doppio tuner, con guadagno impostabile, su Linux e su Windows; comportamento se uno dei due sistemi non lo consente.
- Formato della sessione su disco e frequenza di campionamento di default della fetta stretta.
- Criterio del controllo del margine (R3) e soglie di rilevamento della saturazione (R9).

### Sources / Research

- `STRATEGY.md`: confini, metriche, traguardo del CQ WW.
- `docs/review-2019.md`: punto 2, il gradino di −12 dB su RX2, la posizione della finestra del rumore e la distribuzione dei DT.
- Fork weakmon `iu3qez/weakmon`, `ft8.py` (`find_background`, `snr_is0kyb`): il precedente salvava solo l'output del decoder.
