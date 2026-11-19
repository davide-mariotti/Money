# Money

Analisi locale degli estratti conto: legge i PDF, smista le spese in categorie (macro › micro › sotto) e mostra dove vanno i soldi.

**Privacy:** tutto gira su questo computer. Nessuna chiamata di rete, telemetria Streamlit disattivata, server raggiungibile solo da `localhost`. I dati stanno in `data/` (ignorata da git).

## Avvio

Doppio click su `Money.bat` (la prima volta crea `.venv` e installa le dipendenze), poi si apre il browser su http://localhost:8599.

## Uso

1. Metti i PDF (carta Nexi o conto Crédit Agricole) in `data/nuovi/` o trascinali in **Importa**. All'avvio vengono letti, verificati sui totali stampati e archiviati in `data/carta/` e `data/conto/` con nomi ordinati (`2020-01_nexi.pdf`, `2020-Q1_conto.pdf`). Reimportare non duplica nulla. Si parte dal 1/1/2020.
2. **Da categorizzare**: scegli la categoria per ogni esercente sconosciuto. Diventa una regola, e i movimenti uguali (presenti e futuri) vengono categorizzati da soli. Accorcia la regola per renderla più generica (`coffeevending` invece di `abcdefghijcoffeevendingcitta`).
3. **Panoramica**: spese per categoria (clic per il dettaglio), budget del mese, trend, top esercenti, spese ricorrenti. **Andamento**: entrate, uscite, risparmio, saldo dei conti, anno su anno. **Stipendio**: buste paga (Zucchetti) con netto, aumenti e cambi di livello, ferie e permessi, TFR, voci per anno, anomalie e confronto con gli accrediti in banca. **Mutuo**: capitale vs interessi e debito residuo. **Etichette**: spese raggruppate (es. un viaggio). **Detrazioni 730**: stima delle spese detraibili per anno.
4. **Categorie e regole**: aggiungi/rinomina categorie (`Casa > Utenze > Luce`), assegna un'icona ([Material Symbols](https://fonts.google.com/icons), es. `bolt`; vuota = eredita dal livello sopra) e modifica le regole.

Macro speciali: `Entrate` (contano come entrate) e `Trasferimenti` (esclusi dalle spese: ricariche Revolut, addebito carta sul conto, rateizzazioni già contate).

## Backup

I PDF vengono compressi all'import e caricati su Google Drive con `drive.py` (pilota Chrome con il debug remoto attivo). Per un backup completo copia anche `data/money.db` (movimenti, regole, categorie).

## Formati supportati

- Nexi (carta di credito, estratto mensile)
- Crédit Agricole (conto corrente, estratto trimestrale)
- PayPal (export attività CSV)
- Hype (lista movimenti PDF mensile)
- Revolut (estratto consolidato CSV)

Nuovo formato = una funzione `parse_*` in `money.py` aggiunta a `PARSERS`.

## Test

```
.venv\Scripts\python test_money.py
```
