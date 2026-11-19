"""Run: python test_money.py  (synthetic data only, never real statements)"""
import money

TEXT = """Nexi
DETTAGLIO DEI SUOI MOVIMENTI TITOLARE CARTANUMERO************1234
31/12/25 Debitoresiduoalmese precedente 0,00
09/09/26 PaypalSteamGames35314369001 5,00
09/09/26 PaypalSteamGames35314369001 5,00
10/09/26 Www.Amazon.Nf8uu5fi4Luxembourg 1.018,92
28/09/26 AmazonNu7yy7tt4Luxembourg -10,39
27/09/26 PaypalZalandose35314369001 - 31,40
12/09/26 Amazon.com 12,34 13,99 USD 1,1337
PrintifyLatvia
10/09/26 21,27 22,76USD 0,9160025
CommissionediconversioneapplicatadaNexi:0,42Euro*
28/08/26 APERTURA PIANOMULTISPESA DEL27/08/202623:29 -959,68
31/08/26 COMMISSIONEPIANOMULTISPESA DEL27/08/202623:29 4,60
29/09/26 AbcdefghijCoffeeVendingCitta 5,00
"""

detect, parse, _ = money.PARSERS[0]
assert detect(TEXT)
account, rows = parse(TEXT)
assert account == "Nexi *1234", account
assert len(rows) == 10, rows  # residuo skipped
assert rows[0] == ("2026-09-09", "PaypalSteamGames35314369001", -5.0)
assert rows[2][2] == -1018.92 and rows[3][2] == 10.39  # thousands, refund positive
assert rows[4][2] == 31.40  # refund printed as "- 31,40"
assert rows[5][2] == -12.34  # EUR column, not the foreign one
assert rows[6] == ("2026-09-10", "PrintifyLatvia", -21.27)  # FX row: merchant on the line above
total = f"TOTALESPESE {-sum(a for *_, a in rows):.2f}".replace(".", ",")
parse(TEXT + total)  # matches: no error
try:
    parse(TEXT + "TOTALESPESE 1,00")
    raise AssertionError("mismatching total must be refused")
except ValueError:
    pass

assert money.key("Revolut 6501Dublin") == "revolutdublin"
assert money.key("Www.Amazon.Nf8uu5fi4Luxembourg") == "wwwamazonluxembourg"
assert money.key("Decathlon00002995Empoli") == "decathlonempoli"
assert money.clean_conto(["POS CARTA 12345678 DEL 01/01/20 ORE 10.00 C/O 111111111111", "UNICOOP CITTA",
                          "IDENTIFICATIVO SCT:123"]) == "POS UNICOOP CITTA"

money.DB = ":memory:"
db = money.connect()
rules = db.execute("SELECT pattern, category FROM rules").fetchall()
cat = lambda d: money.match(rules, money.key(d))
assert cat("AmazonNu7yy7tt4Luxembourg") == "Shopping > Online"
assert cat("APERTURA PIANOMULTISPESA DEL27/08/2026") == "Trasferimenti > Rateizzazione carta"
assert cat("COMMISSIONEPIANOMULTISPESA DEL27/08") == "Finanza > Commissioni"  # longest wins
assert cat("AbcdefghijCoffeeVendingCitta") == "Ristorazione > Bar e caffè"
assert cat(money.clean_conto(["F24HB KEY:N1234-ABCDEF00A00A000A"])) == "Tasse"
assert cat("BarSoleCitta") is None

db.execute("INSERT INTO tx (id,date,description,amount,account) VALUES ('a','2026-09-29','BarSoleCitta',-5,'x')")
money.learn(db, "Bar Sole", "Ristorazione > Bar e caffè")
money.learn(db, "", "Tasse")  # ignored
assert db.execute("SELECT category FROM tx WHERE id='a'").fetchone()[0] == "Ristorazione > Bar e caffè"
assert not db.execute("SELECT 1 FROM rules WHERE pattern=''").fetchone()

PP = '''"Data","Orario","Fuso orario","Nome","Tipo","Stato","Valuta","Importo","Tariffe","Totale","Tasso di cambio","Codice ricevuta","Saldo","Codice transazione","Descrizione"
"14/02/2020","09:33:40","CET","Game Shop","Pagamento abbonamento","Completata","USD","-9,99","0,00","-9,99","","","-9,99","A",""
"14/02/2020","09:33:40","CET","","Conversione di valuta generica","Completata","EUR","-9,61","0,00","-9,61","","","-9,61","B",""
"14/02/2020","09:33:40","CET","","Conversione di valuta generica","Completata","USD","9,99","0,00","9,99","","","0,00","C",""
"14/02/2020","09:33:40","CET","","Versamento generico con carta","Completata","EUR","9,61","0,00","9,61","","","0,00","D",""
"15/02/2020","10:00:00","CET","Mario Rossi","Pagamento da cellulare","Completata","EUR","25,00","0,00","25,00","","","25,00","E",""
"16/02/2020","10:00:00","CET","Shop","Autorizzazione generica","In sospeso","EUR","-5,00","0,00","-5,00","","","25,00","F",""
"16/02/2020","11:00:00","CET","PayPal Inc.","Altro","Completata","EUR","-30,00","0,00","-30,00","","","25,00","G",""
"16/02/2020","11:00:00","CET","Fuel","Annullamento autorizzazione","Stornata","EUR","-30,00","0,00","-30,00","","","25,00","H",""
"16/02/2020","12:00:00","CET","","Pagamento credito acquirenti generico","Completata","EUR","-40,00","0,00","-40,00","","","25,00","I",""
'''
detect, parse, name = money.PARSERS[2]
assert detect(PP) and name(PP) == "paypal/2020-02-14_2020-02-16_paypal.csv"
assert parse(PP)[1] == [("2020-02-14", "Game Shop", -9.61),  # foreign purchase: EUR leg, merchant from the USD row
                        ("2020-02-14", "Versamento generico con carta", 9.61),  # card top-up (CARD gap logic)
                        ("2020-02-15", "PayPal ricevuto da Mario Rossi", 25.0),  # authorisation and cancelled one skipped
                        ("2020-02-16", money.PP_LOAN_BACK, -40.0)]  # a refund paid the PayPal credit back

REV = '''"Riepilogo delle transazioni",,,,,,,
Data,Descrizione,Categoria,"Denaro in entrata/uscita",Saldo,"Imposte ritenute","Altre imposte",Costi
"10 gen 2026","Ricarica di *1234",Ricarica,"10,00€","10,00€","0,00€","0,00€","0,00€"
"11 gen 2026",Shop,Esercente,"-6,99€","3,01€","0,00€","0,00€","0,00€"
Totale,,,"3,01€",,"0,00€","0,00€","0,00€"
'''
assert money.parse_revolut(REV) == ("Revolut", [("2026-01-10", "Ricarica di *1234", 10.0), ("2026-01-11", "Shop", -6.99)],
                                    ("2026-01-11", 3.01))  # last balance becomes the account anchor
try:
    money.parse_revolut(REV.replace('"3,01€","0,00€"', '"9,99€","0,00€"', 1))
    raise AssertionError("broken running balance must be refused")
except ValueError:
    pass
assert money.mortgage_split("PAG.RATA N. 1 MUTUO IPOTECARIO QUOTA CAPITALE : E. 273,65 QUOTA INTERESSI : E. 234,00 "
                            "ALTRI ONERI : E. 4,75") == (273.65, 234.0)
assert money.mortgage_split("PAG.RATA MUTUO CHIROGRAFARIO QUOTA CAPITALE : E. 23,16 QUOTA INTERESSI : E. 23,08-") is None

# Bank-side card charge: ignored if that month's card statement exists, counted as spending if it's missing.
charge = "SDD A : NEXI S.P.A. ADDEBITO SPESE CARTA DI CREDITO ESTRATTO CONTO DEL : 31/03/2026"
db.executemany("INSERT INTO files VALUES (?,?,'Nexi *1234',1)", [("s", "2026-03_nexi.pdf"), ("t", "2026-05_nexi.pdf")])
db.executemany("INSERT INTO tx (id,date,description,amount,account) VALUES (?,?,?,?,'Conto')",
               [("c1", "2026-04-15", charge, -300), ("c2", "2026-05-15", charge, -200), ("c3", "2026-01-15", charge, -9)])
money.categorize(db)
got = dict(db.execute("SELECT id, category FROM tx WHERE id LIKE 'c%'"))
assert got == {"c1": money.CARD, "c2": money.CARD_GAP, "c3": money.CARD_GAP}, got  # Mar present, Apr/Dec missing (May arrived)
db.execute("INSERT INTO tx (id,date,description,amount,account) VALUES ('c4','2026-06-15',?,-50,'Conto')", (charge,))
money.categorize(db)  # charge for the May statement: present
assert db.execute("SELECT category FROM tx WHERE id='c4'").fetchone()[0] == money.CARD
db.execute("INSERT INTO tx (id,date,description,amount,account) VALUES ('r1','2026-06-02','Ricarica di *1234',200,'Revolut')")
top = [d for d in money.debts(db) if "ricariche" in d["name"]]
assert top[0]["residual"] == 200 and "15/07" in top[0]["note"], top  # topped up after the May statement: owed on the July charge

# Payslip: file name from the period, money split into buckets that add up to the net before rounding.
assert money.name_busta("TipoCosto : Giugno 2024 AGG.\n* * Z50022 14ma Mensilita' 9,9 173,0 ORE 1.711,05") == "stipendio/2024-06_quattordicesima.pdf"
assert money.name_busta("TipoCosto : Marzo 2024\n") == "stipendio/2024-03_busta.pdf"
v = lambda code, desc, amount, fig=False: dict(code=code, desc=desc, amount=amount, fig=fig)
slip = {"voci": [v("Z00001", "Retribuzione", 2000.0), v("Z00000", "Contributo IVS", -183.8), v("Z00317", "Esonero IVS DL", 120.0),
                 v("F03020", "Ritenute IRPEF", -268.62), v("F00880", "Rimborsi da 730", 500.0), v("000009", "Rimborso Km.", 30.0),
                 v("000081", "Anticipazione T.F.R.", 1000.0), v("F07020", "IRPEF netta TFR", -230.0), v("000357", "Addebito Mensa", -12.0),
                 v("000356", "Ticket Restaurant/Mensa", 63.48, True), v("F02000", "Imponibile IRPEF", None)]}
got = money.busta_split(slip)
assert got == dict(lordo=2000.0, tfr_paid=770.0, rimborsi=30.0, tasse=-231.38, contributi=63.8, altre=12.0, benefit=63.48), got
assert round(got["lordo"] + got["tfr_paid"] + got["rimborsi"] - got["tasse"] - got["contributi"] - got["altre"], 2) == \
       round(sum(x["amount"] for x in slip["voci"] if x["amount"] is not None and not x["fig"]), 2)

# shrink_pdf: a big image is recompressed, the text stays exactly the same.
import os, tempfile, pikepdf
from pathlib import Path
pdf = pikepdf.new()
pdf.add_blank_page()
img = pikepdf.Stream(pdf, os.urandom(2000 * 200 * 3), Type=pikepdf.Name.XObject, Subtype=pikepdf.Name.Image,
                     Width=2000, Height=200, ColorSpace=pikepdf.Name.DeviceRGB, BitsPerComponent=8)
font = pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica)
pdf.pages[0].Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font), XObject=pikepdf.Dictionary(Im0=img))
pdf.pages[0].Contents = pdf.make_stream(b"BT /F1 12 Tf 50 700 Td (TOTALE SPESE 12,34) Tj ET q 400 0 0 40 50 600 cm /Im0 Do Q")
with tempfile.TemporaryDirectory() as d:
    f = Path(d) / "t.pdf"
    pdf.save(f)
    before = f.stat().st_size
    money.shrink_pdf(f)
    assert f.stat().st_size < before / 2 and "TOTALE SPESE 12,34" in money.pdf_text(f), (before, f.stat().st_size)
    # Adobe CMYK JPEG (Eni bills): shrunk, but stays CMYK with its inverted Decode (RGB without ICC shifts colours)
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.frombytes("CMYK", (2400, 600), os.urandom(2400 * 600 * 4)).save(buf, "JPEG", quality=95)
    img.write(buf.getvalue(), filter=pikepdf.Name.DCTDecode)
    img.Width, img.Height, img.ColorSpace, img.Decode = 2400, 600, pikepdf.Name.DeviceCMYK, pikepdf.Array([1, 0] * 4)
    pdf.save(f)
    before = f.stat().st_size
    money.shrink_pdf(f)
    with pikepdf.open(f) as out:
        im = next(o for o in out.objects if isinstance(o, pikepdf.Stream) and o.get("/Subtype") == "/Image")
        assert f.stat().st_size < before / 2 and im.ColorSpace == "/DeviceCMYK" and list(im.Decode) == [1, 0] * 4 and im.Width == 1100

# Eni Plenitude bills, both layouts (made-up numbers): documents, not movements
OLD = """Eni Plenitude SpA
rif. bolletta* data di emissione numero cliente
2300000001 18.01.2023 111 222 333 444
La mia bolletta
luce
Periodo di riferimento VIA ROMA 1
da 3 Novembre 2022 00100 ROMA RM
a 31 Dicembre 2022
La mia fornitura - MERCATO LIBERO Quanto devo pagare?
1.117,34 €
Canone di abbonamento alla 18,00 €
consumo rilevato (dal 03.11.22 al 31.12.22) 148
Totale fornitura luce kWh 1.148 numero contratto: 1
"""
NEW = """Bolletta Numero Cliente
Gas 111222333444
Periodo di fatturazione: dal 01/09/2026 al 31/10/2026
Fattura elettronica numero 2600000002 valida ai fini fiscali - Data di emissione 10/11/2026
Gas
Totale da pagare entro il 03/12/2026
53,45 Consumo del periodo
€ di fatturazione
14
Smc
Servizio Clienti Eni Plenitude
"""
for t in (OLD, NEW):
    assert next(k for k in money.PARSERS if k[0](t))[1] is money.parse_eni
b = money.parse_eni(OLD)
assert b == dict(num="2300000001", kind="luce", issued="2023-01-18", start="2022-11-03", end="2022-12-31", due=None,
                 total=1117.34, qty=1148.0, unit="kWh", canone=18.0), b
b = money.parse_eni(NEW)
assert (b["kind"], b["start"], b["due"], b["total"], b["qty"], b["unit"], b["canone"]) == \
       ("gas", "2026-09-01", "2026-12-03", 53.45, 14.0, "Smc", 0.0), b
assert money.name_eni(NEW) == "bollette/2026-09_gas.pdf"
try:
    money.parse_eni(NEW.replace("Periodo di fatturazione", "Periodo"))
    raise AssertionError("missing field must be a readable ValueError")
except ValueError:
    pass

# Acque SpA water bill (made-up numbers): net use = billed - estimates given back; totals cross-checked
WATER = """DATI FORNITURA Quanto devo pagare?
MARIO ROSSI entro il 02/10/2026 72,36 €
Numero Fattura 6026000000000001
Emessa il 02/09/2026
Consumo fatturato 26 mc Periodo di riferimento 28/05/2026 - 21/08/2026
Consumi in acconto già fatturati nelle bollette precedenti −15 mc Periodo di conguaglio 27/02/2026 - 21/08/2026
TOTALE FATTURA 72,36
ACQUE SPA: SEDE LEGALE Via Roma 1
Conguaglio 27/02/2026 21/08/2026 176 26 −15 11
"""
assert next(k for k in money.PARSERS if k[0](WATER))[1] is money.parse_acque
b = money.parse_acque(WATER)
assert (b["kind"], b["start"], b["end"], b["due"], b["total"], b["qty"]) == ("acqua", "2026-05-28", "2026-08-21", "2026-10-02", 72.36, 11.0), b
assert money.name_acque(WATER) == "bollette/2026-05_acqua.pdf"
for bad in (WATER.replace("TOTALE FATTURA 72,36", "TOTALE FATTURA 72,63"), WATER.replace("26 −15 11", "26 −15 12")):
    try:
        money.parse_acque(bad)
        raise AssertionError("a bill that doesn't add up must not be imported")
    except ValueError:
        pass
print("ok")
