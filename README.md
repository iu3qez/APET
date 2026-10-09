# reAPET — APET Reborn

Confronto sperimentale di antenne HF in sola ricezione.

Un radioamatore che costruisce o modifica un'antenna oggi non ha un modo pratico per sapere, con dati e non a sensazione, se è davvero migliore di un'altra e in quali direzioni. Confrontare in trasmissione è complicato. WSPR offre pochi campioni, RBN non ha una base statistica. Il commutatore A/B confronta istanti diversi e mescola l'antenna con fading, stazioni e QRM che cambiano.

reAPET confronta due antenne **contemporaneamente**: ciascuna è collegata a uno dei due ricevitori dello stesso SDR. Per ogni stazione FT8 ricevuta da entrambe misura:

- **ΔS**, la differenza di livello del segnale, cioè il guadagno relativo nella direzione da cui arriva la stazione;
- **ΔN**, la differenza di rumore, stimata nelle pause tra un ciclo FT8 e il successivo.

Il risultato è una misura datata e legata al suo contesto: un diagramma del guadagno relativo dove ci sono dati, con la copertura e l'affidabilità dichiarate settore per settore, e la sua evoluzione nel tempo. Non è "il diagramma" dell'antenna, che dipende da propagazione, ora e luogo.

## Stato

Il progetto è in ripartenza. Il primo componente in sviluppo è un **registratore IQ a doppio ricevitore**, da provare sul campo al CQ WW DX CW del 28 novembre 2026. Il registratore:

- pilota un SDRplay RSPduo in doppio tuner tramite l'API SDRplay ufficiale, su un portatile Windows o macOS;
- imposta e blocca guadagni uguali sui due tuner, con AGC spento;
- marca saturazioni, sovraccarichi e interruzioni;
- salva dati e contesto (antenne, locator, stato dell'orologio) in formato SigMF, rianalizzabili offline.

Decoder, calcolo di ΔS e ΔN e report verranno dopo, costruiti sulle sessioni registrate.

## Documentazione

- [`STRATEGY.md`](STRATEGY.md): scopo, posizionamento, confini e metriche del progetto.
- [`docs/review-2019.md`](docs/review-2019.md): revisione critica del lavoro originale, con le verifiche fatte sui log.
- [`docs/plans/`](docs/plans/): piani di lavoro. Il piano del registratore è seguito nella issue [#1](https://github.com/iu3qez/reAPET/issues/1).

## Il lavoro originale

reAPET riparte da **APET** (Antenna Pattern Extraction Tool) di Marco Cogoni IS0KYB, scritto nel 2019 ([mcogoni/APET](https://github.com/mcogoni/APET)). L'idea di partenza e la prima implementazione sono sue: due catene di ricezione in parallelo, prima con WSPR e poi con FT8, per ricavare il diagramma azimutale di un'antenna rispetto a un riferimento e confrontarlo con il modello NEC. La bozza dell'articolo scritto per QEX e mai pubblicato è in [`QEX_paper.pdf`](QEX_paper.pdf).

Il codice originale è conservato nella radice del repository, così com'era:

- `WSPR_Antenna_Pattern.ipynb`: il notebook con tutta l'elaborazione;
- `coords_utils.py`: conversione Maidenhead e calcolo di distanza e azimut;
- `decoded_*.txt`: log FT8 di esempio, del 2019 (IS0KYB) e del 2025 (IU3QEZ);
- `LazyH-16m.csv`, `4cross_quads.csv`: diagrammi esportati da MMANA;
- `pattern.png`, `DeltaSNR_time.png`: esempi di risultati originali.

Non è stato aggiornato e non gira con le librerie Python attuali. Cosa regge e cosa no di quel lavoro è spiegato nella [review](docs/review-2019.md).

## Licenza

GPL v3, come il progetto originale. Vedi [`LICENSE`](LICENSE).

73 de IU3QEZ
