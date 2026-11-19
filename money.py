"""Core: PDF parsing, SQLite storage, rule-based categorization. No network, ever."""
import csv
import hashlib
import io
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

DATA = Path(os.environ.get("MONEY_DATA") or Path(__file__).parent / "data")  # desktop.py sets it for the exe
INBOX = DATA / "nuovi"  # drop new statements here (or anywhere in data/): import files them by content
ARCHIVE = DATA / "archivio"  # conflicts (same period, different content): never imported
DB = DATA / "money.db"
START = "2020-01-01"  # point zero: nothing before this date is imported
SEP = " > "
EXCLUDED = "Trasferimenti"  # moving money between own accounts: not spending
INCOME = "Entrate"
SAVINGS = "Risparmio"  # money kept, not spent: mortgage capital, investments (excluded from spending)
CAPITAL = "Risparmio > Capitale mutuo"
CARD = "Trasferimenti > Carta di credito"  # bank-side card charge: the card statement has the detail
CARD_GAP = "Carta di credito > Senza dettaglio"
PLAN = "Trasferimenti > Rateizzazione carta"  # Nexi instalment plan rows: the purchases were already counted
LOAN = "Finanza > Rate"  # a loan: money in (positive) and its instalments; what is left over time is the interest
PAYPAL = "Trasferimenti > PayPal"  # PayPal top-ups seen from card/bank: the purchases are in the PayPal export  # ...unless that statement is missing: then the charge is the spending

# "path | Material Symbols icon" (https://fonts.google.com/icons); children inherit the parent's icon
DEFAULT_CATEGORIES = """
Casa | home
Casa > Mutuo | account_balance
Casa > Affitto | key
Casa > Utenze | bolt
Casa > Utenze > Luce | lightbulb
Casa > Utenze > Gas | local_fire_department
Casa > Utenze > Acqua | water_drop
Casa > Utenze > Internet | wifi
Casa > Utenze > Rifiuti | delete
Casa > Manutenzione | build
Casa > Manutenzione > Controllo caldaia | mode_heat
Casa > Manutenzione > Riparazioni | handyman
Casa > Arredamento | chair
Casa > Condominio | apartment
Casa > Assicurazione | shield
Alimentari | shopping_cart
Alimentari > Supermercato | local_grocery_store
Alimentari > Negozi | storefront
Ristorazione | restaurant
Ristorazione > Ristoranti | restaurant_menu
Ristorazione > Bar e caffè | local_cafe
Ristorazione > Fast food | fastfood
Ristorazione > Delivery | delivery_dining
Trasporti | directions_car
Trasporti > Carburante | local_gas_station
Trasporti > Pedaggi | toll
Trasporti > Parcheggi | local_parking
Trasporti > Auto | directions_car
Trasporti > Auto > Manutenzione | car_repair
Trasporti > Auto > Assicurazione | shield
Trasporti > Auto > Bollo | receipt
Trasporti > Mezzi pubblici | directions_bus
Salute | medical_services
Salute > Farmacia | medication
Salute > Visite mediche | stethoscope
Salute > Dentista | dentistry
Sport | directions_bike
Sport > Attrezzatura | fitness_center
Sport > Abbonamenti | card_membership
Sport > Gare ed eventi | emoji_events
Svago | celebration
Svago > Videogiochi | sports_esports
Svago > Cinema ed eventi | theaters
Svago > Viaggi | flight
Svago > Libri | menu_book
Svago > Esperienze | wine_bar
Abbonamenti | autorenew
Abbonamenti > Streaming | live_tv
Abbonamenti > Software e cloud | cloud
Abbonamenti > Telefonia | smartphone
Shopping | shopping_bag
Shopping > Online | local_shipping
Shopping > Abbigliamento | checkroom
Shopping > Elettronica | devices
Shopping > Spedizioni | local_post_office
Cura personale | spa
Cura personale > Barbiere | content_cut
Finanza | account_balance
Finanza > Commissioni | percent
Finanza > Imposte e bolli | receipt_long
Finanza > Rate | credit_card
Regali e donazioni | redeem
Tasse | gavel
Entrate | payments
Entrate > Stipendio | work
Entrate > Rimborsi | undo
Entrate > Altro | add_circle
Trasferimenti | sync_alt
Trasferimenti > Revolut | account_balance_wallet
Trasferimenti > Carta di credito | credit_card
Trasferimenti > Rateizzazione carta | credit_score
Trasferimenti > Giroconto | swap_horiz
Carta di credito | credit_card
Carta di credito > Senza dettaglio | credit_card_off
Entrate > Mensilità aggiuntive | card_giftcard
Entrate > Vendite online | sell
Entrate > Regali ricevuti | volunteer_activism
Contanti | local_atm
Contanti > Prelievi | local_atm
Contanti > Versamenti | savings
Trasferimenti > Hype | account_balance_wallet
Trasferimenti > PayPal | sync_alt
Trasferimenti > Acquisto casa | house
Trasporti > Taxi | local_taxi
Trasporti > Multe | local_police
Casa > Utenze > Luce e gas | electric_bolt
Casa > Spese acquisto casa | real_estate_agent
Shopping > Spedizioni | local_post_office
Shopping > PayPal senza dettaglio | payments
Svago > Esperienze | wine_bar
Svago > Collezionismo | style
Svago > Feste | celebration
Svago > Quote con amici | groups
Svago > Giochi e scommesse | casino
Sport > Sci | downhill_skiing
Risparmio | savings
Risparmio > Capitale mutuo | house
Risparmio > Investimenti | show_chart
Casa > Mutuo > Interessi e oneri | percent
Finanza > Assicurazioni | shield
Cura personale > Prodotti | spa
"""

# Generic chains only: anything personal is learned at runtime into the (git-ignored) db.
DEFAULT_RULES = {
    "amazon": "Shopping > Online", "amzn": "Shopping > Online",
    "unicoop": "Alimentari > Supermercato", "esselunga": "Alimentari > Supermercato",
    "conad": "Alimentari > Supermercato", "carrefour": "Alimentari > Supermercato",
    "lidl": "Alimentari > Supermercato", "eurospin": "Alimentari > Supermercato",
    "burgerking": "Ristorazione > Fast food", "mcdonald": "Ristorazione > Fast food",
    "deliveroo": "Ristorazione > Delivery", "glovo": "Ristorazione > Delivery", "justeat": "Ristorazione > Delivery",
    "steam": "Svago > Videogiochi", "playstation": "Svago > Videogiochi", "nintendo": "Svago > Videogiochi",
    "netflix": "Abbonamenti > Streaming", "spotify": "Abbonamenti > Streaming", "disneyplus": "Abbonamenti > Streaming",
    "googleone": "Abbonamenti > Software e cloud", "googlecloud": "Abbonamenti > Software e cloud", "googlepayment": "Abbonamenti > Software e cloud",
    "applecom": "Abbonamenti > Software e cloud", "anthropic": "Abbonamenti > Software e cloud",
    "openai": "Abbonamenti > Software e cloud", "iliad": "Abbonamenti > Telefonia",
    "agip": "Trasporti > Carburante", "tamoil": "Trasporti > Carburante",
    "autostrade": "Trasporti > Pedaggi", "telepass": "Trasporti > Pedaggi",
    "decathlon": "Sport > Attrezzatura", "farmacia": "Salute > Farmacia",
    "vinted": "Shopping > Abbigliamento", "carglass": "Trasporti > Auto > Manutenzione",
    "wahoofitness": "Sport > Attrezzatura", "ekoi": "Sport > Attrezzatura", "buycycle": "Sport > Attrezzatura",
    "rouvy": "Sport > Abbonamenti", "endusrl": "Sport > Gare ed eventi", "engagigo": "Sport > Gare ed eventi",
    "davidmayernaman": "Shopping > Abbigliamento", "eldorado": "Svago > Videogiochi",
    "booking": "Svago > Viaggi", "bricoio": "Casa > Manutenzione > Riparazioni", "pagainrate": "Finanza > Rate",
    "pasticceria": "Ristorazione > Bar e caffè", "gelateri": "Ristorazione > Bar e caffè",
    "coffeevending": "Ristorazione > Bar e caffè", "caffe": "Ristorazione > Bar e caffè",
    "pizza": "Ristorazione > Ristoranti", "ristorante": "Ristorazione > Ristoranti",
    "ristorazione": "Ristorazione > Ristoranti", "trattoria": "Ristorazione > Ristoranti",
    "osteria": "Ristorazione > Ristoranti", "sushi": "Ristorazione > Ristoranti", "kebab": "Ristorazione > Fast food",
    "revolut": "Trasferimenti > Revolut",
    "pianomultispesa": "Trasferimenti > Rateizzazione carta",  # purchases already counted when made
    "commissionepianomultispesa": "Finanza > Commissioni",
    # Italian bank statements (Credit Agricole wording, mostly generic)
    "accreditocompetenze": "Entrate > Stipendio", "stipendio": "Entrate > Stipendio",
    "accreditomensagg": "Entrate > Mensilità aggiuntive",
    "ordebay": "Entrate > Vendite online", "ordetsy": "Entrate > Vendite online", "ordpaypal": "Trasferimenti > PayPal",
    "ordnexispa": "Trasferimenti > Carta di credito", "creditopaypalpagainrate": "Trasferimenti > PayPal",
    "nexiestinzionepianorateale": "Trasferimenti > Rateizzazione carta", "nexirimborsosaldoacredito": "Trasferimenti > Carta di credito",
    "nexialtriaddebiti": "Finanza > Commissioni",
    "accreditooperazionicontestate": "Entrate > Rimborsi", "benvenutoinhype": "Entrate > Altro",
    "versamentogenericoconcarta": "Trasferimenti > Carta di credito", "prelievogenericoconcarta": "Trasferimenti > Carta di credito",
    "ebayvenditaa": "Entrate > Vendite online", "ebayacquistoda": "Shopping > Online",
    "imposteriscossedalpartner": "Tasse",
    "addebitospesecartadicredito": "Trasferimenti > Carta di credito",  # see CARD / CARD_GAP
    "versamentocontanti": "Contanti > Versamenti", "prelcon": "Contanti > Prelievi",
    "prelcarta": "Contanti > Prelievi", "prelievo": "Contanti > Prelievi",
    "commissioni": "Finanza > Commissioni", "addebitocommiss": "Finanza > Commissioni",
    "canonemensile": "Finanza > Commissioni", "canoneannuo": "Finanza > Commissioni", "quotaannua": "Finanza > Commissioni",
    "rinnovocarta": "Finanza > Commissioni", "speseemissionecarta": "Finanza > Commissioni",
    "impostadibollo": "Finanza > Imposte e bolli", "delegaimposte": "Tasse", "pagopa": "Tasse",
    "pagamentoincassivari": "Tasse",
    "mutuoipotecario": "Casa > Mutuo", "speseistruttoriafinanziamento": "Casa > Mutuo",
    "impostasostitutivafinanziamento": "Casa > Mutuo", "premiocpi": "Casa > Mutuo",
    "erogazionefinanziamento": "Trasferimenti > Acquisto casa", "studionotarile": "Casa > Spese acquisto casa",
    "mutuochirograf": "Finanza > Rate", "agosducato": "Finanza > Rate",
    "multiprotec": "Casa > Assicurazione", "premiorin": "Finanza > Assicurazioni", "premiopol": "Finanza > Assicurazioni",
    "telecomitalia": "Casa > Utenze > Internet", "sddaenispa": "Casa > Utenze > Luce e gas",
    "acquespa": "Casa > Utenze > Acqua",
    "sddapaypal": "Shopping > PayPal senza dettaglio",  # PayPal funded by direct debit: merchant not shown
    "sarletciescaeni": "Trasporti > Carburante", "ciescapvapp": "Trasporti > Carburante",
    "poseni": "Trasporti > Carburante", "poscoeni": "Trasporti > Carburante", "distributor": "Trasporti > Carburante",
    "metano": "Trasporti > Carburante", "beyfin": "Trasporti > Carburante",
    "parcheggio": "Trasporti > Parcheggi", "easypark": "Trasporti > Parcheggi", "flowbird": "Trasporti > Parcheggi",
    "trenitalia": "Trasporti > Mezzi pubblici", "trenord": "Trasporti > Mezzi pubblici",
    "ubertrip": "Trasporti > Taxi", "freenow": "Trasporti > Taxi",
    "zurich": "Trasporti > Auto > Assicurazione", "autolavaggio": "Trasporti > Auto > Manutenzione",
    "hotel": "Svago > Viaggi", "hostel": "Svago > Viaggi", "ryanair": "Svago > Viaggi", "easyjet": "Svago > Viaggi",
    "europcar": "Svago > Viaggi", "ordvueling": "Svago > Viaggi", "skipass": "Sport > Sci",
    "ristoran": "Ristorazione > Ristoranti", "restaur": "Ristorazione > Ristoranti", "pizz": "Ristorazione > Ristoranti",
    "agrituris": "Ristorazione > Ristoranti", "taverna": "Ristorazione > Ristoranti",
    "piadin": "Ristorazione > Fast food", "kfc": "Ristorazione > Fast food", "autogrill": "Ristorazione > Bar e caffè",
    "supermercato": "Alimentari > Supermercato", "pampanorama": "Alimentari > Supermercato",
    "zalando": "Shopping > Abbigliamento", "ovs": "Shopping > Abbigliamento", "primark": "Shopping > Abbigliamento",
    "intimissimi": "Shopping > Abbigliamento", "tezenis": "Shopping > Abbigliamento",
    "cisalfa": "Sport > Attrezzatura", "ikea": "Casa > Arredamento", "maisonsdumonde": "Casa > Arredamento",
    "leroymerlin": "Casa > Manutenzione > Riparazioni", "mediaworld": "Shopping > Elettronica",
    "sharkninja": "Shopping > Elettronica", "creditopaypalrestituito": "Trasferimenti > PayPal",
    "notino": "Cura personale > Prodotti", "google": "Abbonamenti > Software e cloud",
    "itunes": "Abbonamenti > Software e cloud", "patreon": "Abbonamenti > Streaming",
    "instantgaming": "Svago > Videogiochi", "roblox": "Svago > Videogiochi", "sammelkarte": "Svago > Collezionismo",
    "#Ricarica di *": "Trasferimenti > Revolut", "pagamentodapaypal": "Trasferimenti > PayPal",  # Revolut wording
    "pagamentoda": "Entrate > Rimborsi", "pagamentoafavoredi": "Svago > Quote con amici",
    "bwin": "Svago > Giochi e scommesse", "binance": "Risparmio > Investimenti", "coinbase": "Risparmio > Investimenti",
}


def words(desc):
    """'AmazonNu7yy7tt4Luxembourg' -> ['Amazon', 'Luxembourg']: split CamelCase,
    trim edge digits ('Decathlon00002995'), drop mixed codes ('Nu7yy7tt4')."""
    ws = (w.strip("0123456789") for w in re.findall(r"[^\W_]+", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", desc)))
    return [w for w in ws if w and not any(c.isdigit() for c in w)]


def key(desc):
    """Merchant fingerprint used by rules: 'amazonluxembourg'."""
    return "".join(words(desc)).lower()


def connect():
    INBOX.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS tx (
            id TEXT PRIMARY KEY, date TEXT, description TEXT, amount REAL,
            account TEXT, source TEXT, category TEXT, manual INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS rules (pattern TEXT PRIMARY KEY, category TEXT);
        CREATE TABLE IF NOT EXISTS categories (path TEXT PRIMARY KEY, icon TEXT);
        CREATE TABLE IF NOT EXISTS files (sha TEXT PRIMARY KEY, name TEXT, account TEXT, rows INTEGER);
        CREATE TABLE IF NOT EXISTS budgets (path TEXT PRIMARY KEY, amount REAL);  -- monthly cap per category
        CREATE TABLE IF NOT EXISTS balances (account TEXT PRIMARY KEY, date TEXT, balance REAL);  -- latest known balance
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS payslips (name TEXT PRIMARY KEY, data TEXT);  -- parse_busta() as JSON
        CREATE TABLE IF NOT EXISTS bills (name TEXT PRIMARY KEY, data TEXT);  -- parse_eni() as JSON
    """)
    if "tag" not in [c[1] for c in db.execute("PRAGMA table_info(tx)")]:
        db.execute("ALTER TABLE tx ADD COLUMN tag TEXT")  # free label across categories, e.g. a trip
    fresh = not db.execute("SELECT 1 FROM categories").fetchone()
    if "icon" not in [c[1] for c in db.execute("PRAGMA table_info(categories)")]:  # pre-icon db
        db.execute("ALTER TABLE categories ADD COLUMN icon TEXT")
        fresh = True
    if fresh:
        db.executemany("INSERT OR REPLACE INTO categories VALUES (?,?)",
                       [[x.strip() for x in l.split("|")] for l in DEFAULT_CATEGORIES.split("\n") if l])
        db.executemany("INSERT OR IGNORE INTO rules VALUES (?,?)", DEFAULT_RULES.items())
        db.commit()
    return db


# ---------- parsers: (detect(text) -> bool, parse(text) -> (account, rows)) ----------

AMOUNT = r"(?:- ?)?\d{1,3}(?:\.\d{3})*,\d\d"  # refunds can be printed as "- 31,40"


def eur(s):
    return float(s.replace(" ", "").replace(".", "").replace(",", "."))


MESI = "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre".split()


def parse_nexi(text, path=None):
    card = re.search(r"CARTA\s*NUMERO\s*\*+(\d{4})", text)
    account = f"Nexi *{card.group(1)}" if card else "Nexi"
    rows, prev = [], ""
    for line in text.splitlines():
        # foreign currency: "10/03/24 21,27 22,76USD 0,916" with the merchant on the line above
        fx = re.match(rf"(\d\d/\d\d/\d\d) ({AMOUNT}) [\d.,]+ ?[A-Z]{{3}}\b", line)
        m = fx or re.match(rf"(\d\d/\d\d/\d\d) (.+?) ({AMOUNT})(?: |$)", line)
        prev, last = line, prev
        if not m:
            continue
        d, desc, amt = (m.group(1), last, m.group(2)) if fx else m.groups()
        if "residuo" in desc.lower():  # "Debito residuo al mese precedente"
            continue
        rows.append((datetime.strptime(d, "%d/%m/%y").date().isoformat(), desc.strip(), -eur(amt)))  # spend = money out
    total = re.search(r"TOTALE\s*SPESE\s+(-?[\d.]+,\d\d)", text)
    if total and abs(eur(total.group(1)) + sum(a for *_, a in rows)) > .005:
        raise ValueError(f"somma movimenti {-sum(a for *_, a in rows):.2f} != TOTALE SPESE {total.group(1)}")
    # what the bank will be charged, when, and the instalment plans still to pay: the card's debt (see card_debt)
    flat = re.sub(r"\s", "", text)
    charge = re.search(r"(?:SARANNOADDEBITATI|IMPORTOADDEBITATO)Euro([\d.]+,\d\d)", flat)
    when = re.search(r"Indata(\d+)([A-Za-z]+)(\d{4})", flat)
    plans = re.search(r"Importoresiduodeipianiratealiattivi\(comprensivodicommissioni\):([\d.]+,\d\d)", flat)
    if charge and when:
        rows += nexi_extras(flat, text, -sum(a for *_, a in rows), eur(charge[1]))
        day = f"{when[3]}-{MESI.index(when[2].lower()) + 1:02d}-{int(when[1]):02d}"
        return account, rows, (day, -eur(charge[1]), -eur(plans[1]) if plans else 0.0)
    return account, rows


def nexi_extras(flat, text, detail, charge):
    """Summary items charged to the bank but not listed among the movements (stamp duty, annual fee, early payoff
    of an instalment plan, a credit balance refunded by bank transfer). With them, movements == bank charge."""
    close = re.search(r"Milano,\s*(\d+)\s*([A-Za-z]+)\s*(\d{4})", text)
    day = f"{close[3]}-{MESI.index(close[2].lower()) + 1:02d}-{int(close[1]):02d}"
    left, out = round(charge - detail, 2), []
    for label, rx in (("Nexi imposta di bollo", r"Impostadibollo([\d.]+,\d\d)"),
                      ("Nexi quota annuale", r"QuotaAnnua\w*?([\d.]+,\d\d)"),
                      ("Nexi estinzione piano rateale", r"PIANOMULTISPESADEL\d\d/\d\d/\d{4}\d\d:\d\d([\d.]+,\d\d)(?!.{0,3}RATA)")):
        m = re.search(rx, flat)
        if m and 0 < eur(m[1]) <= left + .005:
            out.append((day, label, -eur(m[1])))
            left = round(left - eur(m[1]), 2)
    if abs(left) > .005:  # e.g. a credit balance paid back to the bank account instead of charged
        out.append((day, "Nexi rimborso saldo a credito" if left > 0 and charge == 0 else "Nexi altri addebiti", -left))
    return out


def name_nexi(text):
    d = re.search(r"Milano,\s*\d+\s*([A-Za-z]+)\s*(\d{4})", text)
    return f"carta/{d.group(2)}-{MESI.index(d.group(1).lower()) + 1:02d}_nexi.pdf"


DATE = re.compile(r"\d\d\.\d\d\.\d\d$")
NOISE = re.compile(r"^(IDENTIFICATIVO|IBAN:|DA:|RIFERIMENTO|ADDEBITO SDD NUMERO|ABI\d)")


def clean_conto(lines):
    """Bank description: drop reference noise, keep merchant / payee / reason."""
    lines = [l.replace("<*>", "").replace("DESCR.OPERAZIONE SCT:", "") for l in lines if not NOISE.match(l)]
    first = re.sub(r"CARTA (CA DEBIT VISA N\. )?\S+ DEL \S+ ORE \S+( C/O \d+)?", "", lines[0])  # POS / PREL. card refs
    if first.startswith("F24"):  # "F24HB KEY:N2535..." is all codes: give rules a word to match
        first = "F24 DELEGA IMPOSTE " + first
    return " ".join([first.replace("  ", " ").strip()] + lines[1:]).strip()


def parse_conto(text, path):
    """Credit Agricole quarterly statement. Debit vs credit is told apart by column position."""
    import pdfplumber
    acct = re.search(r"corrispondenzan\.\d+/0*(\d+)", text.replace(" ", ""))
    account = f"Conto *{acct.group(1)[-4:]}" if acct else "Conto"
    rows, cur, opening, closing = [], None, None, None
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page = page.filter(upright)
            words = page.extract_words(x_tolerance=1.5)
            head = next((w for w in words if w["text"] == "avere"), None)
            if not head:
                continue
            split = max(w["x0"] for w in words if w["text"] == "Movimenti" and abs(w["top"] - head["top"]) < 3)
            lines = []
            for w in sorted((w for w in words if w["top"] > head["top"] + 5), key=lambda w: (round(w["top"]), w["x0"])):
                if lines and abs(w["top"] - lines[-1][0]) <= 3:  # desc first line sits ~1px above the dates
                    lines[-1][1].append(w)
                else:
                    lines.append([w["top"], [w]])
            for _, ws in lines:
                ws.sort(key=lambda w: w["x0"])
                desc = " ".join(w["text"] for w in ws if 240 <= w["x0"] < 525)
                if ws[0]["x0"] < 40 and DATE.match(ws[0]["text"]):
                    a = next((w for w in ws if 100 < w["x0"] < 240 and re.fullmatch(AMOUNT, w["text"])), None)
                    if not a:
                        raise ValueError(f"riga senza importo: {desc}")
                    amt = eur(a["text"]) * (1 if a["x0"] >= split else -1)
                    if desc.startswith("SALDO INIZIALE"):
                        opening = amt
                    elif desc.startswith("SALDO FINALE"):
                        closing = amt
                        break
                    else:
                        day = ws[1]["text"] if DATE.match(ws[1]["text"]) else ws[0]["text"]  # valuta = real date
                        cur = [datetime.strptime(day, "%d.%m.%y").date().isoformat(), [desc], amt]
                        rows.append(cur)
                elif cur and desc and ws[0]["x0"] >= 240:
                    cur[1].append(desc)
            if closing is not None:
                break
    if opening is None or closing is None or abs(opening + sum(r[2] for r in rows) - closing) > .005:
        raise ValueError(f"saldo non quadra: {opening} + {sum(r[2] for r in rows):.2f} != {closing}")
    end = re.search(r"ESTRATTO CONTO AL (\d\d)/(\d\d)/(\d{4})", text)
    return account, [(d, clean_conto(desc), amt) for d, desc, amt in rows], (f"{end[3]}-{end[2]}-{end[1]}", closing)


def name_conto(text):
    d = re.search(r"ESTRATTO CONTO AL (\d\d)/(\d\d)/(\d{4})", text)
    return f"conto/{d.group(3)}-Q{(int(d.group(2)) + 2) // 3}_conto.pdf"


PROVISIONAL = "conto/provvisori"  # bank CSV exports newer than the last quarterly PDF; replaced when the PDF arrives


def parse_conto_csv(text, path=None):
    """Credit Agricole 'Lista Movimenti' CSV: only to cover the days after the last quarterly PDF.
    Dated by booking date (Data Op.), like the PDF balances. The account is filled in by import_file."""
    out = []
    for r in csv.reader(io.StringIO(text), delimiter=";"):
        if r and re.fullmatch(r"\d\d/\d\d/\d{4}", r[0]):
            out.append((datetime.strptime(r[0], "%d/%m/%Y").date().isoformat(),
                        clean_conto([r[3].replace("<*>", " ")]), eur(r[4].lstrip("'"))))
    return "Conto", sorted(out)


def name_conto_csv(text):
    last = max(datetime.strptime(d, "%d/%m/%Y") for d in re.findall(r"^(\d\d/\d\d/\d{4});", text, re.M))
    return f"{PROVISIONAL}/{last:%Y-%m-%d}_movimenti.csv"


PP_SPEND = {  # PayPal rows that are real purchases / refunds / money received
    "Pagamento Express Checkout", "Pagamento preautorizzato utenza", "Pagamento su sito web", "Pagamento asta eBay",
    "Pagamento generico", "Pagamento da cellulare", "Pagamento cumulativo", "Pagamento abbonamento",
    "Pagamento donazione", "Rimborso di pagamento", "Riscatto incentivo/certificato generico",
    "Imposte riscosse dal partner", "Altro", "Richiesta ricevuta"}
PP_CARD = {"Versamento generico con carta", "Prelievo generico con carta"}  # card <-> PayPal (see CARD gap logic)
PP_CREDIT = "Pagamento con credito acquirenti PayPal"  # "Paga in 3 rate": PayPal lends the purchase amount
PP_LOAN = "Credito PayPal Paga in 3 rate"
PP_CREDIT_BACK = "Pagamento credito acquirenti generico"  # a merchant refund that paid the credit back at once
PP_LOAN_BACK = "Credito PayPal restituito"


def pp_desc(tipo, name, amt):
    if tipo in PP_CARD or not name:
        return tipo
    if tipo == "Pagamento asta eBay":
        return f"eBay {'vendita a' if amt > 0 else 'acquisto da'} {name}"
    if tipo in ("Pagamento da cellulare", "Pagamento generico"):  # person to person
        return f"PayPal {'ricevuto da' if amt > 0 else 'inviato a'} {name}"
    if tipo == "Riscatto incentivo/certificato generico":
        return f"Coupon {name}"
    return name


def parse_paypal(text, path=None):
    """PayPal activity CSV (two header variants). Keeps purchases, refunds and money received in EUR (foreign
    purchases via their EUR conversion leg) plus card top-ups. Bank top-ups/withdrawals are skipped: the bank
    side of those is booked as a transfer (see categorize)."""
    every = list(csv.DictReader(io.StringIO(text)))
    rows = [r for r in every if r["Stato"] == "Completata"]
    # "Altro" in the same second as an "Annullamento autorizzazione" is the bookkeeping of a cancelled pre-authorization
    # (fuel pumps, scooters, taxis): the balance doesn't move, no money was spent
    void = {(r["Data"], r["Orario"]) for r in every if r["Tipo"].strip() == "Annullamento autorizzazione"}
    net = lambda r: eur(r.get("Netto") or r.get("Totale"))
    # A foreign-currency movement is paired with its EUR conversion leg through the foreign leg of the same
    # conversion (same currency, opposite amount): the conversion can happen hours later (e.g. a USD payout).
    foreign = [r for r in rows if r["Tipo"].strip() in PP_SPEND and r["Valuta"] != "EUR"]
    legs = {(r["Data"], r["Orario"]): r for r in rows if r["Tipo"].strip() == "Conversione di valuta generica" and r["Valuta"] != "EUR"}
    spend = {}
    for when, leg in legs.items():
        src = next((f for f in foreign if f["Valuta"] == leg["Valuta"] and abs(net(f) + net(leg)) < .005), None)
        if src:
            foreign.remove(src)
            spend[when] = src
    out = []
    for r in rows:
        tipo, name = r["Tipo"].strip(), r["Nome"]
        if tipo in (PP_CREDIT, PP_CREDIT_BACK) and r["Valuta"] == "EUR":  # the loan; repaid by "PayPal inviato a PayPal (Europe)"
            out.append((datetime.strptime(r["Data"], "%d/%m/%Y").date().isoformat(), PP_LOAN if tipo == PP_CREDIT else PP_LOAN_BACK,
                        eur(r.get("Netto") or r.get("Totale"))))
            continue
        if r["Valuta"] != "EUR" or not (tipo in PP_SPEND or tipo in PP_CARD or tipo == "Conversione di valuta generica"):
            continue
        if tipo == "Altro" and (r["Data"], r["Orario"]) in void:
            continue
        if tipo == "Conversione di valuta generica":  # EUR leg of a foreign-currency payment: the real cost
            src = spend.get((r["Data"], r["Orario"]))
            if not src or src["Valuta"] == "EUR":
                continue
            tipo, name = src["Tipo"].strip(), src["Nome"]
        amt = eur(r.get("Netto") or r.get("Totale"))
        out.append((datetime.strptime(r["Data"], "%d/%m/%Y").date().isoformat(), pp_desc(tipo, name, amt), amt))
    return "PayPal", out


def name_paypal(text):
    """paypal/<first date>_<last date>_paypal.csv: exports can cover any period (and overlap: rows don't duplicate)."""
    days = sorted(datetime.strptime(d, "%d/%m/%Y") for d in re.findall(r'^﻿?"(\d\d/\d\d/\d{4})"', text, re.M))
    return f"paypal/{days[0]:%Y-%m-%d}_{days[-1]:%Y-%m-%d}_paypal.csv"


def parse_hype(text, path):
    """Hype 'Lista movimenti' PDF. Columns by x position; a movement runs from its date line to the next one.
    Checked against the printed 'Totale Entrate' / 'Totale Uscite'."""
    import pdfplumber
    rows, cur = [], None
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            words = page.filter(upright).extract_words(x_tolerance=1.5)
            head = next((w["top"] for w in words if w["text"] == "contabile"), None)
            if head is None:
                continue
            end = min([w["top"] for w in words if w["text"] in ("Pag.", "Totale") and w["top"] > head] + [page.height])
            lines = []
            for w in sorted((w for w in words if head + 3 < w["top"] < end - 2), key=lambda w: (round(w["top"]), w["x0"])):
                if lines and abs(w["top"] - lines[-1][0]) <= 2:
                    lines[-1][1].append(w)
                else:
                    lines.append([w["top"], [w]])
            for _, ws in lines:
                if re.fullmatch(r"\d\d/\d\d/\d{4}", ws[0]["text"]) and ws[0]["x0"] < 110:
                    cur = {"date": ws[0]["text"], "cols": {"t": [], "n": [], "d": [], "a": []}}
                    rows.append(cur)
                if not cur:
                    continue
                for w in ws:
                    col = "t" if 175 <= w["x0"] < 245 else "n" if 245 <= w["x0"] < 330 else "d" if 330 <= w["x0"] < 430 else "a" if w["x0"] >= 430 else None
                    if col:
                        cur["cols"][col].append(w["text"])
    out = []
    for r in rows:
        amt = re.sub(r"[^\d,.+-]", "", "".join(t for t in r["cols"]["a"] if re.fullmatch(r"[+-]|[\d.,]+\W?", t)))
        sign = -1 if amt.startswith("-") else 1
        c = r["cols"]
        desc = " ".join(c["t"] + c["n"] + c["d"])
        out.append((datetime.strptime(r["date"], "%d/%m/%Y").date().isoformat(), desc, sign * eur(amt.lstrip("+-"))))
    t_in = re.search(r"Totale Entrate:\s*([\d.,]+)", text)
    t_out = re.search(r"Totale Uscite:\s*([\d.,]+)", text)
    got_in, got_out = sum(a for *_, a in out if a > 0), -sum(a for *_, a in out if a < 0)
    if not (t_in and t_out) or abs(got_in - eur(t_in.group(1))) > .005 or abs(got_out - eur(t_out.group(1))) > .005:
        raise ValueError(f"totali non quadrano: entrate {got_in:.2f} uscite {got_out:.2f} vs "
                         f"{t_in and t_in.group(1)} / {t_out and t_out.group(1)}")
    return "Hype", out


def name_hype(text):
    d = re.search(r"dal \d\d/(\d\d)/(\d{4}) al", text)
    return f"hype/{d.group(2)}-{d.group(1)}_hype.pdf"


MESI3 = [m[:3] for m in MESI]


def parse_revolut(text, path=None):
    """Revolut 'consolidated statement' CSV: first transactions table (EUR personal account).
    Checked row by row against the running balance."""
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("Data,Descrizione,Categoria,"))
    out, balance = [], None
    for r in csv.reader(lines[start + 1:]):
        if not r or not r[0] or r[0] == "Totale" or r[0].startswith("-"):
            break
        d, m, y = r[0].split()
        amt, bal = eur(r[3].rstrip("€")), eur(r[4].rstrip("€"))
        if balance is not None and abs(balance + amt - bal) > .005:
            raise ValueError(f"saldo non quadra al {r[0]}: {balance} + {amt} != {bal}")
        balance = bal
        out.append((f"{y}-{MESI3.index(m) + 1:02d}-{int(d):02d}", r[1], amt))
    return "Revolut", out, (out[-1][0], balance)


def name_revolut(text):
    """One file per export period: revolut/<last 4 IBAN digits>_<last movement date>.csv (exports can overlap)."""
    last4 = re.search(r"Numero di conto \(IBAN\)\",\"\w+?(\d{4})\"", text).group(1)
    return f"revolut/{last4}_{parse_revolut(text)[1][-1][0]}_revolut.csv"


NUM = r"-?\d{1,3}(?:\.\d{3})*,\d+"


def parse_busta(text, path):
    """Zucchetti payslip (cedolino). Not movements: the net pay is already the bank credit. Returns a dict for the
    'payslips' table. Voci split into trattenute/competenze by column; checked: voci = competenze - trattenute and
    competenze - trattenute + arrotondamento = netto."""
    import pdfplumber
    voci, leave, tfr = [], {}, {}
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:  # long payslips continue the voci on the next page; totals are on the last
            words = page.filter(upright).extract_words(x_tolerance=1.5)
            lines = []
            for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
                if lines and abs(w["top"] - lines[-1][0]) <= 3:
                    lines[-1][1].append(w)
                else:
                    lines.append([w["top"], [w]])
            head = next((t for t, ws in lines if ws[0]["text"].startswith("VOCIsVARIABILI")), None)
            if head is None:
                continue
            end = next(t for t, ws in lines if ws[0]["text"] == "CONGUAGLIO")
            for i, (t, ws) in enumerate(lines):
                ws.sort(key=lambda w: w["x0"])
                code = next((w["text"] for w in ws if 35 < w["x0"] < 68 and re.fullmatch(r"[A-Z0-9]{6}", w["text"])), None)
                num = lambda lo, hi: next((eur(w["text"]) for w in ws if lo < w["x1"] <= hi and re.fullmatch(NUM, w["text"])), None)
                if head < t < end and code:
                    tr, co = num(430, 500), num(500, 600)
                    voci.append(dict(code=code, desc=" ".join(w["text"] for w in ws if 68 < w["x0"] < 280 and not re.fullmatch(NUM, w["text"])),
                                     base=num(280, 320), qty=num(320, 430), unit=next((w["text"] for w in ws if 400 < w["x0"] < 420 and w["text"].isalpha()), ""),
                                     amount=None if tr is None and co is None else (co or 0) - (tr or 0),
                                     fig=any(w["text"] == "(" for w in ws if w["x0"] > 430)))  # in brackets: shown, not paid
                elif ws[0]["text"] in ("Ferie", "Perm.P.A.R") and ws[0]["x0"] < 80:  # hours: residuo AP, maturato, goduto, saldo
                    leave["Ferie" if ws[0]["text"] == "Ferie" else "PAR"] = [num(100, 170), num(170, 240), num(240, 300), num(300, 370)]
                elif ws[0]["text"] == "T.F.R." and any(w["text"] == "F.do" for w in ws) and i + 1 < len(lines):
                    nxt = lines[i + 1][1]
                    pick = lambda lo, hi: next((eur(w["text"]) for w in nxt if lo < w["x1"] <= hi and re.fullmatch(NUM, w["text"])), 0)
                    tfr = dict(fondo=pick(0, 140), rival=pick(140, 240), imposta=pick(240, 300), anno=pick(300, 395), anticipi=pick(500, 600))
    get = lambda rx: eur(m[1]) if (m := re.search(rx, text)) else 0.0
    comp, tratt, arr = get(rf"TOTALEsCOMPETENZE ({NUM})"), get(rf"TOTALEsTRATTENUTE ({NUM})"), get(rf"ARROTONDAMENTO ({NUM})")
    net = get(rf"NETTOsDELsMESE\n({NUM})")
    paid = round(sum(v["amount"] for v in voci if v["amount"] is not None and not v["fig"]), 2)
    if abs(paid - (comp - tratt)) > .005 or abs(comp - tratt + arr - net) > .005:
        raise ValueError(f"busta non quadra: voci {paid:.2f}, competenze {comp} - trattenute {tratt} + arr. {arr} != netto {net}")
    per = re.search(r"TipoCosto : (\w+) (\d{4})( AGG\.)?", text)
    month = MESI.index(per[1].lower()) + 1
    codes = {v["code"] for v in voci}
    kind = (("tredicesima" if "Z50000" in codes else "quattordicesima") if per[3] else "tfr" if "ZP8130" in codes else "mese")
    lv = re.search(r"DatasCessazione .*?Liv\w*\.?(?: da acquisire)? (\S+) ?(.*)", text)
    dates = re.search(r"DatasCessazione.*\n\S+ (\S+)(?: (\S+))?\n(.+)", text)
    els = re.search(r"\n(?:SOGG )?((?:[A-Z.]+ )*[A-Z.]+)\nI I ((?:[\d.,]+ ?)+)\n", text)
    base = re.search(r"PROSSIMOSCATTO TOTALE\n(?:(\d+-\d{4}) )?([\d.,]+)", text)
    return dict(period=f"{per[2]}-{month:02d}", kind=kind, employer=re.search(r"RagionesSociale\n\d+ (.+)", text)[1].strip(),
                level=lv[1] if lv else "", contract=lv[2].strip() if lv else "", hired=dates[1], left=dates[2] or "", role=dates[3].strip(),
                pay=dict(zip(els[1].split(), map(eur, els[2].split()))) if els else {}, base=eur(base[2]) if base else 0.0,
                next_step=(base[1] or "") if base else "", comp=comp, tratt=tratt, arr=arr, net=net, voci=voci, leave=leave, tfr=tfr,
                tfr_month=get(r"\nQuota T\.F\.R\. ([\d.,]+)\n"),
                hours={m[2]: eur(m[3]) for m in re.finditer(r"(?:\b([A-Z0-9]{1,3}) )?([A-Za-z][^\d\n]*?) (\d+,\d\d)hm", text)})


def name_busta(text):
    per = re.search(r"TipoCosto : (\w+) (\d{4})( AGG\.)?", text)
    kind = ("tredicesima" if "13ma Mensilita" in text else "quattordicesima") if per[3] else "tfr" if "Fondo T.F.R. al" in text else "busta"
    return f"stipendio/{per[2]}-{MESI.index(per[1].lower()) + 1:02d}_{kind}.pdf"


def voce_kind(v):
    """Bucket of one payslip voce (see busta_split); None = shown but not paid, or not an amount."""
    a, c, d = v["amount"], v["code"], v["desc"]
    if a is None:
        return None
    if v["fig"]:  # in brackets: not part of the net pay
        return "benefit" if re.search(r"ticket|benefit|metasal", d, re.I) else None
    if c.startswith(("ZP81", "F07")) or "T.F.R." in d:
        return "tfr_paid"
    if d.lower().startswith("rimbors") and not c.startswith("F"):
        return "rimborsi"
    if c.startswith("F"):  # IRPEF, addizionali, conguagli, 730 refunds, tax credits (bonus 80/100 €)
        return "tasse"
    if d.startswith(("Contributo", "Esonero")):
        return "contributi"
    return "altre" if a < 0 else "lordo"


def busta_split(slip):
    """Where a payslip's money goes. lordo = pay; tfr_paid = TFR advance/settlement net of its tax; rimborsi = expenses
    paid back; tasse, contributi, altre = taken (positive); benefit = meal vouchers, flexible benefit, health fund (not
    cash). lordo + tfr_paid + rimborsi - tasse - contributi - altre = competenze - trattenute."""
    out = dict.fromkeys(("lordo", "tfr_paid", "rimborsi", "tasse", "contributi", "altre", "benefit"), 0.0)
    for v in slip["voci"]:
        if k := voce_kind(v):
            out[k] += -v["amount"] if k in ("tasse", "contributi", "altre") else v["amount"]
    return {k: round(v, 2) for k, v in out.items()}


def grab(rx, text):
    """re.search groups, or a readable ValueError (the import page shows it) when a field is missing."""
    if not (m := re.search(rx, text)):
        raise ValueError(f"manca {rx}")
    return m.groups()


def iso(d):
    """01/09/2026, 18.01.2023, 1 Gennaio 2023 -> 2026-09-01"""
    if m := re.fullmatch(r"(\d+) (\w+) (\d{4})", d):
        return f"{m[3]}-{MESI.index(m[2].lower()) + 1:02d}-{int(m[1]):02d}"
    g, m, y = re.split(r"[/.]", d)
    return f"{y}-{m}-{g}"


def parse_eni(text, path=None):
    """Eni Plenitude bill (luce or gas), both layouts (the one from Sep 2025 says "Bolletta Numero Cliente"). Not movements:
    the SDD on the account is the payment. Returns a dict for the 'bills' table; canone = TV licence inside luce bills."""
    get = lambda rx: grab(rx, text)
    if new := re.search(r"Bolletta Numero Cliente\n(Luce|Gas) \d", text):
        kind, num, issued = new[1].lower(), *get(r"Fattura elettronica numero (\d+) .*Data di emissione (\S+)")
        start, end = get(r"Periodo di fatturazione: ?dal (\S+) al (\S+)")
        due, total, qty = get(r"Totale da pagare entro il ?(\S+)\n([\d.]+,\d\d) Consumo (?:del periodo|totale)\n€ .*\n([\d.]+)\n")
    else:
        kind, (num, issued) = get(r"La mia bolletta\n(luce|gas)\n")[0], get(r"rif\. bolletta.*\n(\d+) (\S+)")
        start, end = get(r"\nda (\d+ \w+ \d{4}).*\na (\d+ \w+ \d{4})")
        total, = get(r"Quanto devo pagare\?\n([\d.]+,\d\d) €")
        qty, = get(r"Totale fornitura (?:luce kWh|gas smc) ([\d.]+)")
        due = None
    tv = re.search(r"Canone di abbonamento alla[^\n€]*?([\d.]+,\d\d) €", text)
    return dict(num=num, kind=kind, issued=iso(issued), start=iso(start), end=iso(end), due=due and iso(due),
                total=eur(total), qty=eur(qty), unit="kWh" if kind == "luce" else "Smc", canone=eur(tv[1]) if tv else 0.0)


def name_eni(text):
    b = parse_eni(text)
    return f"bollette/{b['start'][:7]}_{b['kind'] if b['qty'] else 'canone'}.pdf"


def parse_acque(text, path=None):
    """Acque SpA water bill, quarterly: an estimated 'Acconto', then a 'Conguaglio' on the real reading that gives the
    estimate back. Paid by pagoPA (card, PayPal, tabaccheria: see categorize). qty = net m³ of this bill (Consumo Totale
    column), so the bills add up to the real consumption. Checked: total due = TOTALE FATTURA, and qty = consumo
    fatturato - acconti restituiti."""
    t = text.replace("−", "-")  # minus sign
    (num,), (issued,) = grab(r"Numero Fattura (\d+)", t), grab(r"Emessa il (\S+)", t)
    due, total = grab(r"entro il (\S+) ([\d.]+,\d\d) €", t)
    start, end = grab(r"Periodo di riferimento (\S+) - (\S+)", t)
    rows = re.findall(r"\n(?:Acconto|Conguaglio) \d\d/\d\d/\d{4} \d\d/\d\d/\d{4} \d+ -?\d+(?: -?\d+)? (-?\d+)\n", t)
    qty = sum(map(int, rows))
    billed = re.search(r"\nConsumo fatturato (\d+) mc", t)
    back = re.search(r"\nConsumi in acconto già fatturati nelle bollette precedenti -(\d+) mc", t)
    if grab(r"TOTALE FATTURA ([\d.]+,\d\d)", t)[0] != total or qty != (int(billed[1]) if billed else 0) - (int(back[1]) if back else 0):
        raise ValueError(f"bolletta acqua {num}: totale o consumi non tornano")
    return dict(num=num, kind="acqua", issued=iso(issued), start=iso(start), end=iso(end), due=iso(due),
                total=eur(total), qty=float(qty), unit="m³", canone=0.0)


def name_acque(text):
    b = parse_acque(text)
    return f"bollette/{b['start'][:7]}_acqua{'' if b['qty'] else '_contratto'}.pdf"  # the first bill (contract) has no use


PARSERS = [  # (detect, parse, canonical file name)
    (lambda t: "Nexi" in t and "DETTAGLIO" in t.upper().replace(" ", ""), parse_nexi, name_nexi),
    (lambda t: "ESTRATTO CONTO AL" in t and "credit-agricole" in t.lower(), parse_conto, name_conto),
    (lambda t: t.lstrip("﻿").startswith('"Data","Orario","Fuso orario","Nome","Tipo"'), parse_paypal, name_paypal),
    (lambda t: "HYPE" in t and "Lista movimenti" in t, parse_hype, name_hype),
    (lambda t: t.lstrip("﻿").startswith("Data Op.;Data Val.;Causale;Descrizione;Importo"), parse_conto_csv, name_conto_csv),
    (lambda t: "Revolut" in t and "Riepilogo delle transazioni" in t, parse_revolut, name_revolut),
    (lambda t: "Zucchetti" in t and "NETTOsDELsMESE" in t, parse_busta, name_busta),
    (lambda t: "Eni Plenitude" in t and ("La mia bolletta" in t or "Bolletta Numero Cliente" in t), parse_eni, name_eni),
    (lambda t: "ACQUE SPA" in t and "TOTALE FATTURA" in t, parse_acque, name_acque),
]


def pdf_text(path):
    import pdfplumber  # lazy: heavy import, only needed on import
    with pdfplumber.open(path) as pdf:
        return "\n".join(p.filter(upright).extract_text(x_tolerance=1.5) or "" for p in pdf.pages)


def upright(obj):
    """pdfplumber filter: drop rotated characters (ads overlaid on some bank statements)."""
    return obj.get("object_type") != "char" or abs(obj["matrix"][1]) < 1e-6


def shrink_pdf(path):
    """Lighter PDF for disk and Drive: big images re-encoded as JPEG, object streams, linearized (fast web view).
    Kept only if smaller and every character (text, position, font) is unchanged, so parsing is unaffected."""
    import pikepdf, pdfplumber

    def chars(p):
        with pdfplumber.open(p) as doc:  # closed explicitly: Windows can't replace a file that is still open
            return [[(c["text"], c["x0"], c["top"], c["fontname"], c["size"], c["matrix"]) for c in page.chars]
                    for page in doc.pages]

    tmp = path.with_name(path.name + ".tmp")
    with pikepdf.open(path) as pdf:
        for img in pdf.objects:
            if not isinstance(img, pikepdf.Stream) or img.get("/Subtype") != "/Image" or img.get("/ImageMask"):
                continue
            raw, cs = len(img.read_raw_bytes()), img.get("/ColorSpace")
            # Adobe CMYK JPEG (Eni bills): inverted channels + Decode [1 0 ...]. PIL reads and writes that same convention,
            # so it is re-encoded as CMYK keeping ColorSpace and Decode (converting to RGB without ICC shifts the colours)
            adobe = cs == "/DeviceCMYK" and "/DCTDecode" in str(img.get("/Filter")) and                 [float(v) for v in img.get("/Decode", [])] == [1, 0] * 4
            if raw < 20_000 or img.get("/BitsPerComponent") != 8 or not (cs in ("/DeviceRGB", "/DeviceGray") or adobe or (
                    isinstance(cs, pikepdf.Array) and cs[0] == "/ICCBased" and int(cs[1].N) in (1, 3))):
                continue
            if not adobe and any(float(v) != i % 2 for i, v in enumerate(img.get("/Decode", []))):
                continue  # inverted/remapped colours: leave alone (identity [0 1 0 1 ...] is fine)
            try:
                im = pikepdf.PdfImage(img).as_pil_image()
            except Exception:  # exotic encoding: leave as is
                continue
            if im.mode not in ("CMYK" if adobe else ("RGB", "L")):
                continue
            im.thumbnail((1100, 1100) if adobe else (1650, 1650))  # ~140 dpi on A4: plenty for ads and scanned inserts;
            # the Eni CMYK ones are ads and leaflets already squeezed hard: they only get smaller if downscaled more
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=70, optimize=True)
            if buf.tell() < raw * 0.8:
                img.write(buf.getvalue(), filter=pikepdf.Name.DCTDecode)
                img.Width, img.Height = im.size
                for k in ("/DecodeParms",) if adobe else ("/DecodeParms", "/Decode"):
                    if k in img:
                        del img[k]
        pdf.remove_unreferenced_resources()
        pdf.save(tmp, compress_streams=True, recompress_flate=True, linearize=True,
                 object_stream_mode=pikepdf.ObjectStreamMode.generate)
    if tmp.stat().st_size < path.stat().st_size and chars(tmp) == chars(path):
        tmp.replace(path)
    else:
        tmp.unlink()


def file_away(path, target):
    """Move a statement to its canonical name. A copy of one already there (same bytes, or same text: the one on disk
    may be shrunk) is deleted and None returned; a different file for the same period goes to archivio/conflitti."""
    target = DATA / target
    if path == target:
        return path
    if target.exists():
        if target.read_bytes() == path.read_bytes() or (path.suffix.lower() == ".pdf" and pdf_text(target) == pdf_text(path)):
            path.unlink()
            return None
        target = ARCHIVE / "conflitti" / path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    return path.rename(target) if not target.exists() else path


def import_file(db, path):
    """Import one statement (PDF, or PayPal CSV). Returns number of new rows, None if the format is unknown,
    or an error string. Idempotent."""
    path = Path(path)
    if path.stat().st_size == 0:
        path.unlink()
        return "file vuoto, cancellato (riscaricalo)"
    if db.execute("SELECT 1 FROM files WHERE sha=?", (hashlib.sha256(path.read_bytes()).hexdigest(),)).fetchone():
        return 0  # already imported: skip the slow PDF parsing on every app start
    text = path.read_text(encoding="utf-8-sig") if path.suffix.lower() == ".csv" else pdf_text(path)
    kind = next((k for k in PARSERS if k[0](text)), None)
    if not kind:
        return None
    _, parse, name = kind
    path = file_away(path, name(text))
    if path is None or ARCHIVE in path.parents:  # duplicate (deleted) or conflict
        return 0
    if path.suffix.lower() == ".pdf":
        shrink_pdf(path)  # the sha below is the shrunk file's: next start skips it
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if db.execute("SELECT 1 FROM files WHERE sha=?", (sha,)).fetchone():
        return 0
    try:
        if parse in (parse_busta, parse_eni, parse_acque):  # documents, not movements: net pay and bills are bank rows
            table, kind = ("payslips", "Busta paga") if parse is parse_busta else ("bills", "Bolletta")
            db.execute(f"INSERT OR REPLACE INTO {table} VALUES (?,?)", (path.name, json.dumps(parse(text, path))))
            db.execute("INSERT INTO files VALUES (?,?,?,?)", (sha, path.name, kind, 0))
            if table == "bills":
                categorize(db)  # its payment may be waiting in Shopping or Tasse
            db.commit()
            return 0
        account, rows, *anchor = parse(text, path)
    except ValueError as e:
        return f"non quadra, non importato: {e}"
    if account == "Conto":  # the CSV doesn't carry the account number
        account = (db.execute("SELECT account FROM balances WHERE account LIKE 'Conto *%'").fetchone() or ["Conto"])[0]
    if PROVISIONAL in path.as_posix():  # only what came after the last known balance; that balance moves forward
        last = db.execute("SELECT date, balance FROM balances WHERE account=?", (account,)).fetchone()
        rows = [r for r in rows if not last or r[0] > last[0]]
        if last and rows:
            anchor = [(rows[-1][0], round(last[1] + sum(a for *_, a in rows), 2))]
    elif anchor and account.startswith("Conto"):  # the real statement replaces the provisional rows it covers
        db.execute("DELETE FROM tx WHERE account=? AND source LIKE '%_movimenti.csv' AND date<=?", (account, anchor[0][0]))
    if anchor and not db.execute("SELECT 1 FROM balances WHERE account=? AND date>=?", (account, anchor[0][0])).fetchone():
        db.execute("INSERT OR REPLACE INTO balances VALUES (?,?,?)", (account, *anchor[0][:2]))
        if len(anchor[0]) == 3:  # card: instalment plans still to pay
            db.execute("INSERT OR REPLACE INTO balances VALUES (?,?,?)", (account + " rate", anchor[0][0], anchor[0][2]))
    rows = [r for r in rows if r[0] >= START]
    seen, new = {}, 0
    for d, desc, amt in rows:
        base = f"{account}|{d}|{desc}|{amt}"
        seen[base] = seen.get(base, 0) + 1  # same coffee twice in a day is two coffees
        tid = hashlib.sha1(f"{base}|{seen[base]}".encode()).hexdigest()
        new += db.execute("INSERT OR IGNORE INTO tx (id,date,description,amount,account,source) VALUES (?,?,?,?,?,?)",
                          (tid, d, desc, amt, account, path.name)).rowcount
    db.execute("INSERT INTO files VALUES (?,?,?,?)", (sha, path.name, account, len(rows)))
    categorize(db)
    db.commit()
    return new


def import_inbox(db):
    """Import every PDF anywhere in data/ (archive excluded). Returns {filename: new_rows | None | error}."""
    INBOX.mkdir(parents=True, exist_ok=True)
    files = [p for p in DATA.rglob("*") if p.suffix.lower() in (".pdf", ".csv") and ARCHIVE not in p.parents
             and DATA / "conto" / "csv" not in p.parents]  # bank CSV exports: cross-check only
    res = {p.name: import_file(db, p) for p in sorted(files)}
    return {k: v for k, v in res.items() if v is not None or k.lower().endswith(".pdf")}  # ignore unrelated CSVs


def match(rules, k, desc=""):
    """Longest matching rule wins. Patterns starting with '#' match the raw description (e.g. a contract number)."""
    # ponytail: linear scan over rules, fine for thousands; index by prefix if it ever gets slow
    hits = [(len(p), c) for p, c in rules if (p[1:] in desc if p.startswith("#") else p in k)]
    return max(hits)[1] if hits else None


def categorize(db):
    """(Re)apply rules to every non-manual transaction. Longest matching pattern wins."""
    rules = db.execute("SELECT pattern, category FROM rules").fetchall()
    for tid, desc in db.execute("SELECT id, description FROM tx WHERE manual=0").fetchall():
        db.execute("UPDATE tx SET category=? WHERE id=?", (match(rules, key(desc), desc), tid))
    # A bank-side card charge (on ~15th) pays last month's statement: if that statement is missing, it IS the spending.
    # The same goes for PayPal top-ups from the card (same month, not the month after).
    have = {r[0][:7] for r in db.execute("SELECT name FROM files WHERE account LIKE 'Nexi%'")}
    for tid, d, acc in db.execute("SELECT id, date, account FROM tx WHERE category=? AND manual=0", (CARD,)).fetchall():
        y, m = int(d[:4]), int(d[5:7])
        if acc.startswith("Conto"):
            y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        month = f"{y}-{m:02d}"
        if START[:7] <= month <= max(have, default="") and month not in have:  # a statement not yet issued is not a gap
            db.execute("UPDATE tx SET category=? WHERE id=?", (CARD_GAP, tid))
    # With the PayPal detail imported, PayPal lines on card and bank only move money into PayPal.
    pp = {r[0] for r in db.execute("SELECT DISTINCT substr(date, 1, 7) FROM tx WHERE account='PayPal'")}
    for tid, d, desc, acc in db.execute("SELECT id, date, description, account FROM tx WHERE manual=0").fetchall():
        k = key(desc)
        if d[:7] in pp and (acc.startswith("Nexi") and k.startswith("paypal") or acc.startswith("Conto") and k.startswith("sddapaypal")):
            db.execute("UPDATE tx SET category=? WHERE id=?", (PAYPAL, tid))
    # A purchase financed in many instalments through PayPal (settings 'loans', "solo_rata"): its instalments read like
    # any "Paga in 3" one, only the amount tells them apart. Like any loan they are Finanza > Rate.
    for loan in json.loads(setting(db, "loans", "[]")):
        if loan.get("solo_rata"):
            db.execute("UPDATE tx SET category=? WHERE manual=0 AND description LIKE ? AND ABS(amount + ?) < .015",
                       (LOAN, f"%{loan['cerca']}%", loan["rata"] + loan.get("spese_rata", 0)))
    # Bills paid outside the SDD (water through pagoPA by card, PayPal, tabaccheria): the payment is the bill total, or
    # total + 1,50 of pagoPA fee, between the issue date and 60 days after the due date.
    # ponytail: amount + dates only, an unrelated purchase of the same amount in that window would be taken too
    for d, in db.execute("SELECT data FROM bills").fetchall():
        b = json.loads(d)
        db.execute(f"UPDATE tx SET category=? WHERE manual=0 AND category NOT LIKE '{EXCLUDED}%' AND date BETWEEN ? AND "
                   "date(?, '+60 day') AND (ABS(amount + ?) < .005 OR ABS(amount + ? + 1.5) < .005)",
                   (f"Casa > Utenze > {b['kind'].capitalize()}", b["issued"], b["due"] or b["issued"], b["total"], b["total"]))
    db.commit()


def it(x):
    """1234.5 -> '1.234,50'"""
    return f"{x:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def debts(db):
    """Everything still to pay (mortgage excluded), with its yearly cost: [{name, residual, tan, saving, note}].
    Card statement not yet charged, Nexi instalment plans, PayPal "Paga in 3" (per purchase: 3 equal instalments,
    minus those already paid), personal loans described in settings 'loans' (JSON, private)."""
    from datetime import date, timedelta
    out = []
    for acc, day, bal in db.execute("SELECT account, date, balance FROM balances WHERE account LIKE 'Nexi%'").fetchall():
        if acc.endswith(" rate"):
            if bal:
                # the printed residual includes the monthly fees still to come: future spending, not debt
                cap = db.execute("SELECT SUM(amount) FROM tx WHERE account=? AND category=?", (acc[:-5], PLAN)).fetchone()[0] or 0
                fees = round(-bal - cap, 2) if 0 < cap <= -bal else 0
                out.append(dict(name=f"Piani rateali {acc[:-5]}", residual=round(-bal - fees, 2), tan=.107, saving=None,
                                note="commissioni mensili: chi estingue prima non le paga più"
                                     + (f" ({it(fees)} € ancora da pagare)" if fees else "")))
        elif not db.execute("SELECT 1 FROM tx WHERE account LIKE 'Conto%' AND category IN (?,?) AND date >= date(?, '-3 days')",
                            (CARD, CARD_GAP, day)).fetchone() and bal:
            out.append(dict(name=f"Saldo carta {acc}", residual=-bal, tan=0, saving=None, note=f"addebito automatico il {day[8:]}/{day[5:7]}"))
    # Revolut/PayPal top-ups paid by card after the last statement: money already moved, owed on the next charge
    last = db.execute("SELECT MAX(name) FROM files WHERE account LIKE 'Nexi%'").fetchone()[0]
    if last:
        y, m = divmod(int(last[:4]) * 12 + int(last[5:7]) + 1, 12)  # next statement month, charged the month after
        topup = db.execute("""SELECT SUM(amount) FROM tx WHERE date > ? AND ((account='Revolut' AND description LIKE 'Ricarica di%')
                              OR (account='PayPal' AND description IN ('Versamento generico con carta', 'Prelievo generico con carta')))""",
                           (f"{last[:7]}-31",)).fetchone()[0]
        if topup:
            out.append(dict(name="Saldo carta: ricariche fatte con la carta", residual=round(topup, 2), tan=0, saving=None,
                            note=f"Revolut/PayPal ricaricati con la carta: arrivano nell'addebito del 15/{m % 12 + 1:02d}"))
    since = (date.today() - timedelta(days=95)).isoformat()
    # credits and instalments recategorized as a loan (Finanza > Rate) are counted with the loans below
    paid = [(d, -a) for d, a in db.execute("SELECT date, amount FROM tx WHERE account='PayPal' AND description LIKE 'PayPal inviato a PayPal (Europe)%' AND category LIKE 'Trasferimenti%' AND date >= ?", (since,))]
    back = [(d, -a) for d, a in db.execute("SELECT date, amount FROM tx WHERE account='PayPal' AND description=? AND date >= ?", (PP_LOAN_BACK, since))]
    left = 0.0
    for d, amt in db.execute("SELECT date, amount FROM tx WHERE account='PayPal' AND description=? AND amount > 0 AND category LIKE 'Trasferimenti%' AND date >= ?", (PP_LOAN, since)).fetchall():
        refund = next((b for b in back if b[0] >= d and abs(b[1] - amt) <= .02), None)
        if refund:  # the purchase was refunded and the refund paid the whole credit back
            back.remove(refund)
            continue
        inst = round(amt / 3, 2)
        done = [p for p in paid if p[0] >= d and abs(p[1] - inst) <= .02][:3]
        for p in done:
            paid.remove(p)
        left += max(amt - inst * len(done), 0)
    if left > .005:
        out.append(dict(name='PayPal "Paga in 3"', residual=round(left, 2), tan=0, saving=0, note="senza interessi: finiscono da sole"))
    for loan in json.loads(setting(db, "loans", "[]")):
        P, R, N, fee = loan["capitale"], loan["rata"], loan["rate"], loan.get("spese_rata", 0)
        by_amount = " AND category=? AND ABS(amount + ?) < .015" if loan.get("solo_rata") else ""  # same text, told apart by amount
        n_paid = db.execute("SELECT COUNT(*) FROM tx WHERE description LIKE ? AND amount < 0" + by_amount,
                            (f"%{loan['cerca']}%", *([LOAN, R + fee] if by_amount else []))).fetchone()[0]
        lo, hi = 1e-7, .2  # monthly rate of the annuity
        for _ in range(200):
            i = (lo + hi) / 2
            lo, hi = (i, hi) if R * (1 - (1 + i) ** -N) / i > P else (lo, i)
        res = P * (1 + i) ** n_paid - R * ((1 + i) ** n_paid - 1) / i
        k = N - n_paid
        penalty = res * (.01 if k > 12 else .005)
        if k > 0:
            out.append(dict(name=loan["nome"], residual=round(res, 2), tan=round(i * 12, 4), monthly=R + fee, left=k,
                            capital_month=round(R - res * i, 2), saving=round(k * (R + fee) - res - penalty, 2),
                            note=f"{k} rate da {it(R + fee)} € · chiudendolo oggi paghi {it(res + penalty)} € (penale {it(penalty)} €)"))
    return out


def card_debt(db):
    """Short-term debt already spent (card statement, instalment plans, Paga in 3): loans excluded."""
    return round(sum(d["residual"] for d in debts(db) if "left" not in d), 2)


def cash_balances(db):
    """{account: (date, balance)} for the accounts that hold money. Hype has no printed balance: it is the sum of
    its movements (account opened with its first top-up)."""
    out = {a: (d, b) for a, d, b in db.execute("SELECT account, date, balance FROM balances WHERE account NOT LIKE 'Nexi%' AND account NOT LIKE 'start:%'")}
    hype = db.execute("SELECT MAX(date), SUM(amount) FROM tx WHERE account='Hype'").fetchone()
    if hype[0]:
        out["Hype"] = (hype[0], round(hype[1], 2))
    return out


def reconcile(db):
    """Do the movements explain the money? (income - every outflow) must equal the change of the account balances
    minus the change of what is owed on cards/instalments. Starting values live in `balances` as 'start:<account>'."""
    q = lambda sql, *a: db.execute(sql, a).fetchone()[0] or 0
    start = dict(db.execute("SELECT account, balance FROM balances WHERE account LIKE 'start:%'"))
    if not start:
        return None
    cash_start = sum(v for k, v in start.items() if not k.startswith("start:Nexi"))
    debt_start = -sum(v for k, v in start.items() if k.startswith("start:Nexi"))
    cash_end, debt_end = sum(b for _, b in cash_balances(db).values()), card_debt(db)
    flows = q("SELECT SUM(amount) FROM tx WHERE category NOT LIKE 'Trasferimenti%' AND date >= ?", START)
    real = (cash_end - cash_start) - (debt_end - debt_start)
    return dict(flows=round(flows, 2), real=round(real, 2), gap=round(flows - real, 2), cash_start=cash_start,
                cash_end=round(cash_end, 2), debt_start=debt_start, debt_end=round(debt_end, 2))


ONE_OFF = "Una tantum"  # tag: exceptional movements left out of the "pace" used for forecasts


def setting(db, key, default=None):
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(db, key, value):
    db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, str(value)))
    db.commit()


def pace(db, months=12):
    """Average monthly change of free money over the last complete months (income - every outflow),
    leaving out movements tagged 'Una tantum'. Returns (eur_per_month, months_used)."""
    rows = db.execute("""SELECT substr(date,1,7) m, SUM(amount) FROM tx WHERE category NOT LIKE 'Trasferimenti%'
                         AND COALESCE(tag, '') != ? AND date < date('now', 'start of month') GROUP BY m ORDER BY m DESC LIMIT ?""",
                      (ONE_OFF, months)).fetchall()
    return (round(sum(v for _, v in rows) / len(rows), 2), len(rows)) if rows else (0.0, 0)


def mortgage_split(desc):
    """(capital, interest) of a mortgage instalment, from the bank wording, or None."""
    m = re.search(r"MUTUO IPOTECARIO.*?QUOTA CAPITALE : E\. ([\d.,]+) QUOTA INTERESSI : E\. ([\d.,]+)", desc)
    return (eur(m[1]), eur(m[2])) if m else None


def icon(icons, path):
    """Own icon, else the closest ancestor's."""
    parts = (path or "").split(SEP)
    return next((icons[p] for i in range(len(parts), 0, -1) if icons.get(p := SEP.join(parts[:i]))), "label")


def rule_pattern(p):
    """'#text' stays raw (matched on the original description), anything else is normalised like the keys."""
    return p.strip() if p.strip().startswith("#") and len(p.strip()) > 1 else key(p)


def learn(db, pattern, category):
    if not rule_pattern(pattern):  # an empty pattern would match every transaction
        return
    db.execute("INSERT OR REPLACE INTO rules VALUES (?,?)", (rule_pattern(pattern), category))
    db.execute("INSERT OR IGNORE INTO categories (path) VALUES (?)", (category,))
    categorize(db)
