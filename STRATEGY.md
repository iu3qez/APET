---
name: reAPET
last_updated: 2026-10-09
---

# reAPET Strategy

## Purpose

L'OM non ha un modo pratico per confrontare sperimentalmente due antenne HF, e il giudizio resta affidato alle sensazioni. Confrontare in TX è complicato, WSPR offre pochi campioni, RBN nessuna base statistica, e il commutatore A/B confronta istanti diversi, mescolando l'antenna con fading, stazioni e QRM che cambiano. Manca una misura contemporanea, in sola ricezione e con base statistica sufficiente.

## Positioning

Il rigore sta nel software, non nell'operatore: due ricevitori uguali, anche economici, due antenne, e nient'altro da fare. reAPET misura separatamente ΔS (guadagno relativo, spot per spot) e ΔN (rumore, stimato nelle pause tra i cicli FT8), con un decoder proprio e una stima dichiarata e verificabile. Il risultato è una misura datata e contestualizzata, inclusa la sua evoluzione nel tempo, non "il diagramma" dell'antenna.

## Users

**Primary:** Autocostruttore - ha appena realizzato o modificato un'antenna e usa reAPET per sapere, con dati e non a sensazione, se e in quali direzioni è migliore del suo riferimento, con un risultato che chiunque capisce senza spiegazioni.

## Boundaries

- Gli SNR di WSJT-X non sono mai una fonte di misura.
- Nessun confronto tra misure di OM o luoghi diversi (archivi pubblici, classifiche): ogni misura è relativa al proprio riferimento e contesto.
- Nessun numero unico come risultato, nessuna densità di spot presentata come lobo, nessun settore interpolato senza dati; la simmetria è solo un'opzione didattica, spenta di default.
- Nessuna procedura a carico dell'operatore (scambio antenne, tarature obbligatorie); lo zero con splitter resta facoltativo.
- Non ancora: angolo di arrivo e meccanismo propagativo (fase 2); intanto i dati registrati devono permetterla.

_Resist a change when:_ sposta lavoro o giudizio dal software all'operatore, o fa sembrare il risultato più completo o generale di quanto i dati della sessione permettano.

## Key metrics

- **Test di zero (splitter)** - bias e dispersione di ΔS e ΔN con la stessa antenna su entrambi i RX, anche in funzione di affollamento in banda e livello del segnale; banco di validazione del progetto.
- **Coerenza interna** - scarto tra i diagrammi di cicli pari e dispari della stessa sessione; dà la differenza minima rilevabile, calcolata per ogni sessione.
- **Tempo e attriti al primo risultato** - da "ho due ricevitori" al primo report, misurato con OM esterni al progetto.
- **Leggibilità** - un terzo, guardando solo il report, risponde correttamente a "quale antenna è migliore, verso dove, quando".

## Tracks

### Motore di misura con validazione

Acquisizione da due catene, decoder FT8, ΔS per spot, ΔN nelle pause, test di zero e coerenza interna; si parte senza un decoder.

_Why it serves the approach:_ è il punto in cui la misura si vince o si perde: senza una stima SNR difendibile il resto è un grafico sopra una sensazione.

### Zero attriti

Dall'installazione al primo risultato senza che l'OM debba comportarsi da tecnico di laboratorio.

_Why it serves the approach:_ l'oggettività dipende dal fatto che l'operatore intervenga il meno possibile.

### Report leggibile

Diagramma del ΔS solo dove ci sono dati, copertura e affidabilità per settore dichiarate, evoluzione nel tempo.

_Why it serves the approach:_ il risultato deve essere capito da chiunque senza confondere dove arrivano le stazioni con dove l'antenna guadagna.

## Milestones

- **2026-11-28** - CQ WW DX CW: banco prova sul campo con amici e antenne diverse; FT8 in banda affollata come stress test della stima ΔN, e prima verifica degli attriti con OM esterni.

## Brand

**One-liner:** APET Reborn
