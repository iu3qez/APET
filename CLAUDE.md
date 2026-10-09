# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Cos'è questo repository

**reAPET** ("APET Reborn"): uno strumento per confrontare sperimentalmente due antenne HF con due ricevitori in contemporanea. Riparte dal lavoro di Marco Cogoni IS0KYB (APET, 2019); dal 2026 il repository non è più un fork. Documentazione e piani sono in italiano; i messaggi di commit in inglese.

Da leggere prima di qualsiasi lavoro non banale:
- `STRATEGY.md`: scopo, posizionamento, confini e metriche. I confini sono vincolanti (per esempio, gli SNR di WSJT-X non si usano mai come misura; nessuna procedura a carico dell'operatore; mai settori interpolati senza dati).
- `docs/review-2019.md`: revisione critica del lavoro originale, con le verifiche sui log. Spiega perché il metodo misura ΔS e ΔN separatamente e perché la finestra del rumore va posizionata dai DT.
- `docs/plans/`: piani di lavoro in formato Compound Engineering (`ce-unified-plan/v1`). Il piano attivo è il registratore IQ a doppio ricevitore (issue iu3qez/reAPET#1).

## Stato del codice

Il repository contiene oggi solo il codice storico del 2019; il nuovo pacchetto Python `reapet` è pianificato ma non ancora scritto.

**Codice storico (radice del repo), da non modificare:**
- `WSPR_Antenna_Pattern.ipynb` è il vero codice: tutte le funzioni sono definite nella cella 1, la cella 2 carica i dati (`mode = "FT8"` o `"WSPR"`, reporter, locator e finestra temporale sono cablati nella cella).
- `wspr_utils.py` è una copia divergente e non usata della cella 1 (l'import è commentato).
- `coords_utils.py`: locator Maidenhead ↔ lat/lon e `haversine` (distanza, azimut). È la parte riutilizzabile.
- `spot_processing.py`, `cty.py`, `cty.plist`: presi dal DX-Cluster-Parser di DH1TW, di fatto inutilizzati.
- `decoded_<REPORTER>.txt`: log FT8 del decoder weakmon modificato. Ogni blocco inizia con `------ TIME: <unix>, Background noise: <potenza> ------`, seguito da righe di 10 campi: `P<pass> <band> <secondo> <Hz> <start> <DT> <snr> <msg...>`. Il "background noise" contiene anche i segnali (vedi la review): non usarlo come rumore.
- `LazyH-16m.csv`, `4cross_quads.csv`: diagrammi 3D esportati da MMANA (`ZENITH,AZIMUTH,VERT,HORI,TOTAL`).

Il notebook non gira con le versioni in `requirements.txt` (numpy 2: `np.linspace` con `num` float in `regularize_data`; `%pylab` deprecato) e usa l'ora locale (`fromtimestamp`, `mktime`) nonostante i commenti dicano UTC. Il fork weakmon di Cogoni non va usato come base per niente.

## Direzione tecnica decisa (registratore)

Dettagli e motivazioni nel piano in `docs/plans/`. In breve:
- Pacchetto Python 3.12/3.13 con layout `src/reapet/`, comandi `reapet doctor`, `record`, `recover`; test con pytest, lint con ruff.
- Sul campo: RSPduo in doppio tuner su un portatile Windows o macOS, pilotato tramite l'**API SDRplay diretta** (binding `ctypes`). **Non** usare il driver SoapySDRPlay3 per l'RSPduo: in doppio tuner ignora l'indice del canale per guadagno/AGC/frequenza, non riallinea i canali e scarta `firstSampleNum` e gli eventi di overload. SoapySDR resta la strada per altri apparati (Orion MkII, TRX DUO via openHPSDR).
- I due canali si allineano per contatore dei campioni (`firstSampleNum`); un buco su un tuner apre un nuovo segmento su entrambe le registrazioni.
- Sessione in formato SigMF: una Collection con una registrazione per antenna, dati `ci16_le` nativi, contesto nel namespace `reapet:`, giornale append-only per resistere ai crash.
- Si acquisisce largo (~2 MS/s) per vedere la saturazione e si salva stretto (sottobanda FT8 più una porzione quieta adiacente).

## Artefatti Compound Engineering

Configurazione in `.compound-engineering/config.yaml` (tutto commentato); radice degli artefatti `docs/` (piani in `docs/plans/`). Lo spazio temporaneo `.context/compound-engineering/` è in `.gitignore`.
