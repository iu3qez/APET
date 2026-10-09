# Review critica di APET (2019)

Revisione delle assunzioni e affermazioni del lavoro originale di Marco Cogoni IS0KYB
(`QEX_paper.pdf`, `WSPR_Antenna_Pattern.ipynb`, log FT8 di esempio), come base per reAPET.
Vedi `STRATEGY.md` per le scelte che ne derivano.

Stato: **Smentita** (contraddetta da dati o calcolo), **Da correggere** (corretta nell'idea,
sbagliata nell'esecuzione), **Da verificare** (plausibile ma non dimostrata), **Confermata**.

## Metodo

### 1. Media sulla polarizzazione — Smentita

Articolo: i 2 minuti di WSPR coprono "roughly one full polarization rotation", citando Epstein
(1969): 0,25 giri/min di giorno, quasi zero di notte.

0,25 giri/min × 2 min = **0,5 giri**, non uno. Con FT8 (12,64 s) si arriva a ~0,05 giri: il
singolo spot non media nulla. La media sulla polarizzazione esiste solo **tra spot diversi**,
quindi dipende dal numero di spot per settore, non dalla durata del modo. Di notte, con rotazione
quasi nulla, il confronto tra antenne a polarizzazione diversa (loop verticale vs Lazy H
orizzontale) resta sistematicamente distorto.

**reAPET:** l'affidabilità per settore deve derivare dal numero di spot indipendenti e dalla
coerenza interna, non da un'ipotesi di media intra-spot.

### 2. "SNR reale" del decoder modificato — Da correggere

Codice (`extract_ft8_data`): `snr = snr_weakmon + 10·log10(background_noise)`, poi in
`get_deltasnr_bycall` si sottrae la mediana di sessione del rumore di ciascun RX.
Ne risulta ΔS(per spot) − ΔN(mediana di sessione): l'idea è vicina alla separazione ΔS/ΔN
adottata da reAPET, ma:

- Regge solo se `snr_weakmon` è definito rispetto **allo stesso** `background_noise` del blocco
  (allora la somma ricostruisce S esattamente). **Da verificare** nel fork di weakmon.
- Il "background noise" non si comporta come rumore. Misurato sui log in repo (p5–p95 in dB
  relativi):

  | Log | blocchi | p5 | mediana | p95 | escursione |
  |---|---|---|---|---|---|
  | IS0KYB1 (Kiwi) | 1056 | 35,6 | 37,2 | 40,2 | 4,6 dB |
  | IS0KYB2 | 529 | 42,3 | 46,1 | 52,7 | 10,4 dB |
  | IU3QEZA1 | 438 | 25,1 | 46,4 | 60,5 | **35,4 dB** |
  | IU3QEZA2 | 426 | 25,3 | 44,1 | 54,6 | **29,3 dB** |

  Escursioni di 30 dB a distanza di decine di secondi non sono rumore esterno. Analisi della
  sessione IU3QEZA (2025-01-03, 10:53–13:02 UTC, contesto urbano):
  - correlazione per blocco tra "rumore" e numero di decodifiche: **+0,44 / +0,49**. La stima
    cresce con l'attività in banda, quindi **contiene i segnali**;
  - correlazione del "rumore" tra i due RX: +0,73, coerente con una causa comune (la banda);
  - nessuna firma di TX locale (rumore alto con decodifiche crollate). Su RX1 ci sono picchi
    sincroni con i cicli FT8 (:28/:58) con decodifiche normali: forse una stazione FT8 forte
    e vicina;
  - dopo una pausa di circa 20 minuti (11:30–11:40) su entrambi i RX, RX2 scende di ~12 dB e RX1
    no: è un gradino di livello nella catena 2, probabilmente un intervento dell'operatore;
  - dopo le 12:50 le decodifiche vanno a zero e il "rumore" crolla: fine della sessione.

  Usato come N, falsa ΔN. Il gradino a metà sessione mostra che l'offset tra le catene può
  cambiare senza che nessuno se ne accorga: il motore di misura deve rilevarlo e spezzare la
  sessione.
- ΔN non è mai riportato: per antenne da ricezione (bande basse) è la metà del risultato.

**reAPET:** ΔS dal rapporto dei livelli di segnale (catene uguali), ΔN misurato nelle pause tra
cicli FT8 con percentile basso, entrambi riportati separatamente.

### 3. Riferimento "quasi omnidirezionale" — Da verificare

Articolo: il loop LZ1AQ è "quasi omnidirectional on 14 MHz for elevation angles above 1-2
degrees". Un loop singolo verticale ha diagramma azimutale a 8 con nulli profondi; omni solo se
in configurazione a loop incrociati con combinazione in quadratura. La configurazione usata non è
dichiarata. Inoltre la Fig. 2 mostra che il loop smette di ricevere di notte: il riferimento ha una
risposta in elevazione molto diversa dall'antenna in prova, quindi ΔS mescola azimut ed elevazione
di entrambe.

**reAPET:** il riferimento è parte della misura; il report lo dichiara, non lo assume neutro.

### 4. SNR di WSJT-X inaffidabile — Confermata (motivazione da verificare)

La stima del rumore di WSJT-X cresce con l'affollamento della banda, quindi l'SNR di un segnale
dipende dagli altri segnali presenti. Il motivo dato nel README ("depends even on the window size
in pixels") non è documentato e probabilmente riguarda la finestra di decodifica in frequenza, non
i pixel. Irrilevante per reAPET: WSJT-X è escluso come fonte (vedi `STRATEGY.md`).

### 5. Offset tra catene RX — Confermata, peso minore

Misurati 3 dB (Kiwi vs TS-940S) e 1 dB (Kiwi vs Perseus). Con catene uguali e una dispersione del
ΔS di diversi dB, 1–2 dB sono entro il rumore di misura. Lo zero con splitter resta facoltativo,
ma è anche il test di validazione dello stimatore (bias in funzione di affollamento e livello).

## Analisi e presentazione

### 6. Simmetria + interpolazione cubica — Smentita come metodo generale

Ogni punto è duplicato a az+π e conteggiato come indipendente; `regularize_data` riempie i bin
vuoti con la media dei vicini e `interp1d(..., fill_value='extrapolate')` estrapola. Nel caso
pubblicato il Sud (Africa, quasi senza spot) è disegnato con dati altrui. La simmetria richiede
antenna, ambiente e riferimento simmetrici: in HF praticamente mai.

**reAPET:** settori senza dati vuoti; simmetria solo come opzione didattica, spenta di default.

### 7. Densità di spot letta come lobo — Rischio non trattato

Il numero di spot per direzione riflette dove sono gli OM e dove arriva lo skip, non il guadagno.
I grafici polari 2019 sovrappongono punti e curva senza separare densità e ΔS.

**reAPET:** il diagramma mostra solo ΔS; la copertura è un'informazione separata.

### 8. "Within 3 dB of the predicted" (Fig. 6) — Da verificare, probabilmente ottimistica

Confronto con la differenza di due modelli MMANA a 4 elevazioni (5–35°) scelte a posteriori, su
dati raddoppiati dalla simmetria e interpolati, senza incertezza dichiarata. Con 4 curve teoriche
a disposizione è facile che una cada entro 3 dB. I modelli NEC non vedono il terreno reale, che è
proprio la motivazione dichiarata del metodo.

### 9. Pesi e mediane — Incoerenza articolo/codice

L'articolo dice mediana per stazione e deviazione standard usata come peso per l'interpolazione.
Il codice (commit `ca984bc`, "abandon medians use all values") usa tutti i valori, senza pesi.

### 10. Scelta della finestra temporale — Gradi di libertà del ricercatore

"Evitare i periodi con pendenza ripida", scegliendo la finestra a occhio sul grafico. Il risultato
dipende da una scelta manuale non registrata.

**reAPET:** la finestra si sceglie con un criterio dichiarato, oppure il report mostra
l'evoluzione nel tempo invece di un unico diagramma.

## Difetti di codice (rilevanti solo per riuso)

- `extract_ft8_data`: `locator` non azzerato quando la riga non contiene un grid. Il call eredita
  il locator della riga precedente, quindi azimut sbagliato. `out.string` invece di `out.group(0)`.
- Timestamp in ora locale (`fromtimestamp`, `mktime`) nonostante i commenti "UTC": corretto solo
  su macchine in UTC (Colab).
- `extract_info`: `dist_dict` sovrascritto a ogni reporter.
- `regularize_data`: `np.linspace` con `num` float, che va in errore con numpy ≥ 1.18.
- `%pylab inline` deprecato; il notebook dipende dal suo namespace globale.
- `wspr_utils.py` è una copia divergente e non usata della cella 1 del notebook.
- Fonte WSPR (`wsprnet.org/olddb`, scraping HTML) presumibilmente non più disponibile.

Verificato e **non** problematico: l'accoppiamento degli spot tra i due RX per secondo esatto.
Con tolleranza ±7 s il numero di coppie non cambia (IU3QEZA: 1498 in entrambi i casi).

## Da fare per chiudere i punti aperti

1. Leggere il fork weakmon di Cogoni: come sono definiti `snr` e `Background noise` (punto 2).
2. Configurazione del loop LZ1AQ usato come riferimento (punto 3).
3. ~~Capire l'escursione di 30 dB del rumore nei log IU3QEZA~~: dipende soprattutto dallo
   stimatore, che include i segnali (vedi punto 2). Il gradino di −12 dB su RX2 dopo le 11:40
   non è ricostruibile: nessuno ricorda l'intervento. Lezione: il software registra da sé il
   contesto della sessione (livelli per catena, interruzioni, gradini rilevati).
