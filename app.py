import html
import json
import re
from urllib.parse import quote

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from PIL import Image

import money
from money import SEP

ICON = Image.open(money.Path(__file__).parent / "assets" / "icon.png")
st.set_page_config("Money", page_icon=ICON, layout="wide")
db = money.connect()

if "imported" not in st.session_state:  # auto-import new statements once per session
    st.session_state.imported = money.import_inbox(db)

PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]
GOOD, BAD, WARN = "#1baf7a", "#e34948", "#eda100"
OTHER, UNCAT = "#9aa0a9", "Da categorizzare"
MESI = "gen feb mar apr mag giu lug ago set ott nov dic".split()
DARK = (st.context.theme.type or "light") == "dark"
T = (dict(card="#1a1d23", border="#2a2e36", line="#23262d", muted="#9aa0a9", text="#e8eaed", hover="#22262d", track="#2a2e36")
     if DARK else
     dict(card="#ffffff", border="#e4e6eb", line="#f0f1f4", muted="#6b7280", text="#14161a", hover="#f5f6f8", track="#eef0f3"))
MUTED = T["muted"]

st.html("<style>:root {" + "".join(f"--{k}: {v};" for k, v in T.items()) + "}</style>" + """<style>
h1, h2, h3 { letter-spacing: -.02em }
[class*="st-key-card"] { background: var(--card); border: 1px solid var(--border); border-radius: 16px;
  padding: 18px 20px; box-shadow: 0 1px 2px rgba(16,24,40,.04) }
[data-testid="stMetric"] { background: var(--card) }
.ms { font-family: 'Material Symbols Rounded'; font-size: 20px; line-height: 1; font-weight: normal;
  font-style: normal; white-space: nowrap; font-feature-settings: 'liga'; -webkit-font-feature-settings: 'liga' }
.title { font-weight: 650; font-size: 15px; margin: 0 0 4px }
.hint { color: var(--muted); font-size: 13px; margin: 0 0 8px }
.row { display: flex; align-items: center; gap: 12px; padding: 9px 2px; border-bottom: 1px solid var(--line) }
.row:last-child { border-bottom: 0 }
.ic { width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center; flex: none;
  color: var(--c); background: color-mix(in srgb, var(--c) 13%, transparent) }
.tx { flex: 1; min-width: 0 }
.tx b { display: block; font-weight: 600; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis }
.tx small { color: var(--muted); font-size: 12px }
.bar { height: 4px; border-radius: 4px; background: var(--track); margin-top: 6px }
.bar i { display: block; height: 100%; border-radius: 4px; background: var(--c) }
.amt { font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap }
a.row { color: inherit; text-decoration: none; border-radius: 10px; padding-left: 6px; padding-right: 4px }
a.row:hover { background: var(--hover) }
.chev { color: #9aa0a9; font-size: 18px }
.crumbs { display: flex; align-items: center; gap: 4px; font-size: 13px; color: var(--muted) }
.crumbs a { color: var(--muted); text-decoration: none }
.crumbs a:hover { color: #2a78d6 }
.crumbs a:last-child { color: var(--text); font-weight: 600 }
.crumbs .ms { font-size: 16px }
.hero { display: flex; align-items: center; gap: 12px }
.hero h2 { margin: 0; padding: 0 }
.hero .ic { width: 44px; height: 44px; border-radius: 12px; font-size: 24px }
.chip { display: inline-flex; align-items: center; gap: 2px; color: var(--c); font-weight: 650; font-size: 14px;
  background: color-mix(in srgb, var(--c) 12%, transparent); border-radius: 999px; padding: 2px 10px 2px 6px }
.chip .ms { font-size: 16px }
.cmp { width: 100%; border-collapse: collapse }
.cmp th { color: var(--muted); font-weight: 500; font-size: 13px; text-align: left; padding: 4px 8px }
.cmp td { padding: 12px 8px; border-top: 1px solid var(--line); vertical-align: middle }
.cmp td small { display: block; color: var(--muted); font-size: 12px; margin-top: 4px }
.cmp td.v { font-weight: 650; font-size: 20px }
</style>""")


# ---------------------------------------------------------------- helpers

def eur(x, dec=2, sign=False):
    s = f"{x:{'+' if sign else ''},.{dec}f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".") + " €"


def mese(t):
    return f"{MESI[t.month - 1]} {t:%y}"


def pretty(desc):
    return " ".join(money.words(desc)) or desc


def header(title, hint=""):
    st.markdown(f"## {title}")
    if hint:
        st.html(f'<p class="hint">{hint}</p>')


def card_title(title, hint=""):
    st.html(f'<p class="title">{title}</p>' + (f'<p class="hint">{hint}</p>' if hint else ""))


def rows(items):
    """items: (icon, color, title, subtitle, amount, share 0..1 | None[, href]) -> modern list, clickable if href."""
    out = []
    for ic, c, t, sub, amt, share, *href in items:
        bar = f'<div class="bar"><i style="width:{max(share, .02):.0%}"></i></div>' if share is not None else ""
        inner = (f'<span class="ic ms">{ic}</span><div class="tx"><b>{html.escape(t)}</b><small>{html.escape(sub)}</small>'
                 f'{bar}</div><span class="amt">{amt}</span>')
        out.append(f'<a class="row" href="{html.escape(href[0])}" target="_self" style="--c:{c}">{inner}'
                   f'<span class="ms chev">chevron_right</span></a>'
                   if href and href[0] else f'<div class="row" style="--c:{c}">{inner}</div>')
    st.html("".join(out))


def link(path):
    return "review" if path == UNCAT else "categoria?c=" + quote(path)


def chart(fig, h, months=None, unit=" €"):
    fig.update_layout(height=h, margin=dict(t=8, b=32, l=56, r=8), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", separators=",.", bargap=0.38, barcornerradius=6,
                      font=dict(family="Inter, sans-serif", size=12, color=MUTED),
                      hoverlabel=dict(bgcolor=T["card"], bordercolor=T["border"], font=dict(family="Inter, sans-serif", color=T["text"])),
                      legend=dict(orientation="h", yanchor="top", y=-0.1, x=0, title_text=""))
    fig.update_xaxes(showgrid=False, title=None)
    fig.update_yaxes(gridcolor=T["track"], zeroline=False, title=None, ticksuffix=unit, tickformat=",.0f")
    if months and len(months) > 8:  # long periods: one label every few months, horizontal
        fig.update_xaxes(tickvals=months[::-(-len(months) // 8)], tickangle=0)
    st.plotly_chart(fig, theme=None, config={"displayModeBar": False}, width="stretch")


def load(split=True):
    """All movements. split=True turns each mortgage instalment into interest (spending) + capital (savings)."""
    df = pd.read_sql("SELECT * FROM tx ORDER BY date DESC", db, parse_dates=["date"])
    if split:
        parts = df.description.map(money.mortgage_split)
        m = parts.notna() & df.category.fillna("").str.startswith("Casa > Mutuo")
        if m.any():  # no mortgage (most people): nothing to split, and pandas refuses an empty assignment
            cap = parts[m].map(lambda p: p[0])
            capital = df[m].assign(amount=-cap, category=money.CAPITAL, id=df.id[m] + ":cap")
            df.loc[m, "amount"] = df.amount[m] + cap
            df.loc[m, "category"] = "Casa > Mutuo > Interessi e oneri"
            df = pd.concat([df, capital]).sort_values("date", ascending=False, ignore_index=True)  # unique index
    df["cat"] = df.category.fillna(UNCAT)
    lv = df.cat.str.split(SEP, expand=True).reindex(columns=range(3))
    df["macro"], df["micro"], df["sub"] = lv[0], lv[1], lv[2]
    df["month"] = df.date.dt.to_period("M").dt.to_timestamp()
    df["merchant"] = df.description.map(money.key)
    return df


def categories():
    return [r[0] for r in db.execute("SELECT path FROM categories ORDER BY path")]


def icons():
    return dict(db.execute("SELECT path, icon FROM categories")) | {UNCAT: "help"}


def spending(df):
    """Real spending, as a positive 'spesa': no transfers, income, savings, nor loans (Finanza > Rate: what was bought
    with that money is counted when bought)."""
    s = df[~df.macro.isin([money.EXCLUDED, money.INCOME, money.SAVINGS]) & (df.cat != money.LOAN)].copy()
    s["spesa"] = -s.amount
    return s


def under(df, path):
    return (df.cat == path) | df.cat.str.startswith(path + SEP)


def filters(df, f1):
    """Period pills rendered in f1 (all accounts together). Returns (filtered df, month index)."""
    period = f1.pills("Periodo", ["3 mesi", "6 mesi", "12 mesi", "Anno", "Tutto"], default="Tutto",
                      required=True, label_visibility="collapsed")
    end = df.month.max()
    start = {"3 mesi": end - pd.DateOffset(months=2), "6 mesi": end - pd.DateOffset(months=5),
             "12 mesi": end - pd.DateOffset(months=11), "Anno": pd.Timestamp(end.year, 1, 1)}.get(period, df.month.min())
    return df[df.month >= start], pd.date_range(start, end, freq="MS")


def colors(df):
    # Color follows the entity: fixed by all-time rank, so filters never repaint.
    top = spending(df).groupby("macro").spesa.sum().drop(UNCAT, errors="ignore").nlargest(len(PALETTE)).index
    return dict(zip(top, PALETTE))


def pct_color(p):
    return BAD if p > 1 else WARN if p > .8 else GOOD


# ---------------------------------------------------------------- pages

LIMITABLE = ["Ristorazione", "Shopping", "Svago", "Alimentari", "Abbonamenti", "Cura personale", "Sport",
             "Regali e donazioni", "Contanti > Prelievi"]  # spending you decide: where cutting back is possible


def voce(df):
    """'Macro > Micro' (or just 'Macro') of each row: the level where spending habits show."""
    return df.macro.where(df.micro.isna(), df.macro + SEP + df.micro)


def side(v):
    """Subtitle prefix of a voce: its macro, or 'generico' when the voce is the macro itself."""
    return v.split(SEP)[0] if SEP in v else "generico"


def window(df, end, n):
    """Rows of the n months ending with the monthly period `end`."""
    return df[df.month.between((end - n + 1).start_time, end.start_time)]


def flows(df, freq="M"):
    """Entrate, uscite (= spending(), one-offs included) and risparmio per period: 'M' months, 'Q' quarters, 'Y' years.
    'unatantum' = the part of uscite tagged 'Una tantum'."""
    s, inc = spending(df), df[df.macro == money.INCOME]
    one = s[s.tag.fillna("") == money.ONE_OFF]
    per = lambda x: x.date.dt.to_period(freq)
    f = pd.DataFrame({"entrate": inc.groupby(per(inc)).amount.sum(), "uscite": s.groupby(per(s)).spesa.sum(),
                      "unatantum": one.groupby(per(one)).spesa.sum()})
    p = per(df)
    f = f.reindex(pd.period_range(p.min(), p.max(), freq=freq)).fillna(0)
    return f.assign(risparmio=f.entrate - f.uscite)


def pick(periods, default, key, where=st):
    """Year pills + month (or quarter) pills instead of a long dropdown. periods: the selectable Periods, sorted.
    Changing year keeps the same month when that year has it."""
    freq = periods[-1].freqstr[0]
    years = sorted({p.year for p in periods}, reverse=True)
    last = st.session_state.get(f"{key}_last", default)
    if freq == "Y":
        y = where.pills("Anno", years, default=last.year, required=True, key=f"{key}_y", label_visibility="collapsed")
        p = next(p for p in periods if p.year == y)
    else:
        a, b = where.columns([max(len(years), 3), 9 if freq == "M" else 3], vertical_alignment="center")
        y = a.pills("Anno", years, default=last.year if last.year in years else years[0], required=True, key=f"{key}_y",
                    label_visibility="collapsed")
        sub = [p for p in periods if p.year == y]
        pos = (lambda p: p.month) if freq == "M" else (lambda p: p.quarter)
        p = b.pills("Mese" if freq == "M" else "Trimestre", sub, default=next((q for q in sub if pos(q) == pos(last)), sub[-1]),
                    format_func=lambda p: MESI[p.month - 1] if freq == "M" else f"T{p.quarter}", required=True,
                    key=f"{key}_{y}", label_visibility="collapsed")
    st.session_state[f"{key}_last"] = p
    return p


def plabel(p):
    return mese(p.start_time) if p.freqstr[0] == "M" else f"T{p.quarter} {p.year}" if p.freqstr[0] == "Q" else str(p.year)


def chip(d, up_is_good=True):
    """A change as a pill: arrow + amount, green when it is good news, red when it is not."""
    if abs(d) < .5:
        return f'<span class="chip" style="--c:{OTHER}">uguale</span>'
    c = GOOD if (d > 0) == up_is_good else BAD
    return f'<span class="chip" style="--c:{c}"><span class="ms">{"arrow_upward" if d > 0 else "arrow_downward"}</span>{eur(abs(d), 0)}</span>'


def io_chart(f, h=320, highlight=None):
    """Entrate and uscite as grouped bars per period, risparmio as a line: one € axis."""
    labels = [plabel(p) for p in f.index]
    fig = go.Figure()
    bar = dict(marker_line_width=0, marker_opacity=[1 if highlight is None or p == highlight else .5 for p in f.index],
               hovertemplate="%{x} · %{fullData.name}<br>%{y:,.0f} €<extra></extra>")
    usual = f.uscite - f.unatantum
    fig.add_bar(x=labels, y=f.entrate, name="Entrate", marker_color=PALETTE[0], offsetgroup="e", **bar)
    fig.add_bar(x=labels, y=usual, name="Uscite", marker_color=PALETTE[1], offsetgroup="u", **bar)
    if f.unatantum.any():  # stacked on the same bar: counted, but visibly exceptional
        fig.add_bar(x=labels, y=f.unatantum, base=usual, name="di cui una tantum", marker_color=OTHER, offsetgroup="u", **bar)
    fig.add_scatter(x=labels, y=f.risparmio, name="Risparmio", mode="lines+markers", line=dict(color=T["text"], width=2),
                    marker=dict(size=8, line=dict(width=2, color=T["card"])),
                    hovertemplate="%{x} · Risparmio<br>%{y:,.0f} €<extra></extra>")
    chart(fig.update_layout(barmode="group"), h, labels)


def dashboard():
    df = load()
    if df.empty:
        header("Panoramica")
        st.info("Nessun movimento. Metti gli estratti in `data/nuovi` o usa **Importa**.", icon=":material/upload_file:")
        return
    ic, cmap = icons(), colors(df)
    col = lambda m: cmap.get(m, OTHER)
    f = flows(df)
    done = [p for p in f.index if p < pd.Period(pd.Timestamp.today(), "M")] or list(f.index)
    header("Panoramica", "Tutti i conti insieme. Uscite = spese vere: niente giroconti, capitale del mutuo o rate dei "
                         "prestiti (un acquisto a rate conta quando lo fai).")
    m = pick(done, done[-1], "pano")
    y, before, name = f.loc[m - 11:m], f.loc[:m - 1].tail(12), plabel(m)
    usual = lambda c: dict(delta=eur(f[c][m] - before[c].mean(), 0, sign=True),
                           delta_description="rispetto alla media dei 12 mesi prima") if len(before) else {}
    k = st.columns(3)
    k[0].metric(f"Uscite di {name}", eur(f.uscite[m], 0), border=True, height="stretch", delta_color="inverse",
                chart_data=y.uscite.round().tolist(), chart_type="bar", **usual("uscite"))
    k[1].metric(f"Entrate di {name}", eur(f.entrate[m], 0), border=True, height="stretch",
                chart_data=y.entrate.round().tolist(), chart_type="bar", **usual("entrate"))
    k[2].metric(f"Risparmio di {name}", eur(f.risparmio[m], 0), border=True, height="stretch",
                chart_data=y.risparmio.round().tolist(), chart_type="bar", delta_color="off", delta_arrow="off",
                delta=f"{f.risparmio[m] / f.entrate[m]:.0%} delle entrate" if f.entrate[m] > 0 else None)

    l, r = st.columns([3, 2])
    with l, st.container(key="card_io"):
        card_title("Entrate e uscite, ultimi 12 mesi", f"in media entrano {eur(y.entrate.mean(), 0)} ed escono "
                                                       f"{eur(y.uscite.mean(), 0)} al mese"
                   + (f" · in grigio le spese una tantum ({eur(y.unatantum.sum(), 0)} in 12 mesi)" if y.unatantum.sum() > 1 else ""))
        io_chart(y, 340, m)
    with r, st.container(key="card_where"):
        s, sp = spending(window(df, m, 12)), spending(window(df, m - 12, 12))
        by, pv = s.groupby("macro").spesa.sum() / 12, sp.groupby("macro").spesa.sum() / 12
        by = by[by > 0].sort_values(ascending=False)
        trend = lambda d: "" if sp.empty else " · come l'anno prima" if abs(d) < 5 else f" · {eur(d, 0, sign=True)} sull'anno prima"
        card_title("Dove vanno i soldi", "media al mese negli ultimi 12 mesi · clicca per il dettaglio")
        with st.container(height=340, border=False):
            rows([(money.icon(ic, c), col(c), c, f"{v / by.sum():.0%}{trend(v - pv.get(c, 0))}", eur(v, 0), v / by.iloc[0], link(c))
                  for c, v in by.items()])

    lim = spending(df[(df.macro.isin(LIMITABLE) | df.cat.isin(LIMITABLE)) & (df.tag.fillna("") != money.ONE_OFF)])
    lim["voce"] = voce(lim)
    d = pd.concat([(window(lim, m, 3).groupby("voce").spesa.sum() / 3).rename("ora"),
                   (window(lim, m - 3, 12).groupby("voce").spesa.sum() / 12).rename("solito")], axis=1).fillna(0)
    d["delta"] = d.ora - d.solito
    up = d[d.delta >= 10].sort_values("delta", ascending=False).head(6)
    pats = [p for (p,) in db.execute("SELECT pattern FROM rules") if not p.startswith("#")]
    rule = lambda k: max(((len(p), p) for p in pats if p in k), default=(0, k))[1]  # one service, many description variants
    sub = spending(df[(df.macro == "Abbonamenti") | (df.cat == "Sport > Abbonamenti")])
    sub["who"] = sub.merchant.map(rule)
    subs = window(sub, m, 12)
    subs = subs[subs.who.isin(set(window(sub, m, 3).who))]  # still active: charged in the last 3 months
    subs = subs.groupby("who").agg(desc=("description", "first"), cat=("cat", "first"), n=("spesa", "size"), tot=("spesa", "sum"))
    subs = subs[subs.tot > 0].sort_values("tot", ascending=False)
    with st.container(key="card_limit"):
        card_title("Dove puoi limitarti", "spese che decidi tu (niente casa, auto, salute, tasse): ultimi 3 mesi rispetto ai 12 prima")
        a, b = st.columns(2)
        with a:
            st.html('<p class="title">Stai spendendo più del solito</p>')
            rows([("trending_up", WARN, v.split(SEP)[-1], f"{side(v)} · da {eur(x.solito, 0)} a {eur(x.ora, 0)} al mese · "
                   f"{eur(x.delta * 12, 0)} in più l'anno", f"+{eur(x.delta, 0)}/mese", None, link(v)) for v, x in up.iterrows()]
                 or [("task_alt", GOOD, "Niente sopra il solito", "le spese a tua scelta sono in linea con l'anno prima", "", None)])
        with b:
            st.html(f'<p class="title">Abbonamenti attivi · {eur(subs.tot.sum(), 0)} l\'anno</p>')
            rows([(money.icon(ic, t.cat), col(t.cat.split(SEP)[0]), pretty(t.desc), f"{t.cat.split(SEP)[-1]} · {t.n} addebit{'o' if t.n == 1 else 'i'} in 12 mesi",
                   f"{eur(t.tot, 0)}/anno", None) for t in subs.head(8).itertuples()]
                 or [("task_alt", GOOD, "Nessun abbonamento attivo", "", "", None)])

    budgets = db.execute("SELECT path, amount FROM budgets ORDER BY path").fetchall()
    if budgets:
        last = spending(df[df.month == m.start_time])
        with st.container(key="card_budget"):
            card_title(f"Budget di {name}", "spesa del mese rispetto al tetto che hai fissato")
            items = []
            for path, cap in budgets:
                spent = last[under(last, path)].spesa.sum()
                p = spent / cap if cap else 0
                items.append((money.icon(ic, path), pct_color(p), path.split(SEP)[-1], f"{eur(spent, 0)} di {eur(cap, 0)}",
                              f"{p:.0%}", min(p, 1), link(path)))
            cols = st.columns(3)
            for i, c in enumerate(cols):
                with c:
                    rows(items[i::3])

    goal_card()


def goal_card():
    """Debts first (phase 1), then the savings goal (phase 2)."""
    cash = sum(b for _, b in money.cash_balances(db).values())
    goal, by = float(money.setting(db, "goal_amount", 5000)), pd.Timestamp(money.setting(db, "goal_date", "2027-12-31"))
    owed = money.debts(db)
    total_owed = sum(d["residual"] for d in owed)
    speed, used = money.pace(db)
    speed1 = speed + sum(d.get("capital_month", 0) for d in owed)  # loan instalments also shrink the debt
    free = cash - total_owed
    today = pd.Timestamp.today()
    when = lambda gap, v: ("mai, a questo ritmo" if v <= 0 else "oltre 10 anni" if gap / v > 120
                           else mese(today + pd.DateOffset(months=-(-gap // v))))
    with st.container(key="card_goal"):
        if free < 0:
            card_title("Obiettivo · fase 1: zero debiti", f"poi la fase 2: {eur(goal, 0)} da parte · mutuo escluso")
            a, b, c = st.columns(3)
            with a:
                rows([("account_balance_wallet", PALETTE[0], "Da pagare in tutto", f"{len(owed)} voci · sui conti hai {eur(cash, 0)}",
                       eur(total_owed, 0), None)])
            with b:
                rows([("savings", BAD, "Ti mancano", "per poter chiudere tutto", eur(-free, 0), max(cash, 0) / total_owed)])
            with c:
                rows([("trending_up" if speed1 > 0 else "trending_down", GOOD if speed1 > 300 else WARN if speed1 > 0 else BAD,
                       "Al tuo ritmo", f"media {used} mesi, una tantum esclusi · zero debiti: {when(-free, speed1)}",
                       f"{eur(speed1, 0, sign=True)}/mese", None)])
            with st.expander("I debiti, in ordine di priorità"):
                order = sorted(owed, key=lambda d: ("Saldo carta" in d["name"], -(d.get("saving") or 0), -d["tan"], -d["residual"]))
                rows([("priority_high" if i == 0 else "credit_card" if "carta" in d["name"].lower() else "receipt_long",
                       BAD if d["tan"] >= .08 else WARN if d["tan"] > 0 else OTHER, f"{i + 1}. {d['name']}",
                       f"TAN {d['tan']:.1%} · " + (f"chiudendolo risparmi {eur(d['saving'], 0)} · " if d.get("saving") else "") + d["note"],
                       eur(d["residual"]), None) for i, d in enumerate(order)])
        else:
            left = max((by.year - today.year) * 12 + by.month - today.month, 1)
            card_title(f"Obiettivo · fase 2: {eur(goal, 0)} da parte entro {mese(by)}", "nessun debito da pagare (mutuo escluso)")
            a, b, c = st.columns(3)
            with a:
                rows([("savings", GOOD, "Soldi liberi", f"{min(free / goal, 1):.0%} dell'obiettivo", eur(free, 0), min(free / goal, 1))])
            with b:
                rows([("flag", PALETTE[0], "Servono", f"mancano {eur(max(goal - free, 0), 0)} in {left} mesi",
                       f"{eur(max(goal - free, 0) / left, 0)}/mese", None)])
            with c:
                rows([("trending_up" if speed > 0 else "trending_down", GOOD if speed > 0 else BAD, "Al tuo ritmo",
                       f"arrivo: {'raggiunto' if free >= goal else when(goal - free, speed)}", f"{eur(speed, 0, sign=True)}/mese", None)])


def compare():
    df = load()
    header("Confronti", "Un periodo contro quello prima e contro lo stesso periodo dell'anno scorso.")
    kind = st.pills("Periodo", ["Mese", "Trimestre", "Anno"], default="Mese", required=True, label_visibility="collapsed")
    freq = {"Mese": "M", "Trimestre": "Q", "Anno": "Y"}[kind]
    f = flows(df, freq)
    now = pd.Period(pd.Timestamp.today(), freq)
    p = pick(list(f.index), max([q for q in f.index if q < now] or list(f.index)), f"cmp_{freq}")
    refs = [q for q in dict.fromkeys([p - 1, p - {"M": 12, "Q": 4, "Y": 1}[freq]]) if q in f.index]

    with st.container(key="card_cmp"):
        card_title(plabel(p) + (" · in corso, parziale" if p >= now else ""), "frecce verdi = meglio, rosse = peggio")
        body = "".join(f"<tr><td>{n.capitalize()}</td><td class='v'>{eur(f[n][p], 0)}</td>"
                       + "".join(f"<td>{chip(f[n][p] - f[n][q], up)}<small>{plabel(q)}: {eur(f[n][q], 0)}</small></td>" for q in refs)
                       + "</tr>" for n, up in (("entrate", True), ("uscite", False), ("risparmio", True)))
        head = "".join(f"<th>rispetto a {plabel(q)}</th>" for q in refs)
        st.html(f"<table class='cmp'><tr><th></th><th>{plabel(p)}</th>{head}</tr>{body}</table>")

    l, r = st.columns([3, 2])
    with l, st.container(key="card_time"):
        card_title("Nel tempo", "il periodo scelto è in evidenza")
        io_chart(f.loc[:p].tail({"M": 13, "Q": 9, "Y": 20}[freq]), 360, p)
    with r, st.container(key="card_changes"):
        card_title("Cosa è cambiato nelle uscite", "le voci che si sono mosse di più · clicca per il dettaglio")
        s = spending(df)
        s["voce"] = voce(s)
        per = s.date.dt.to_period(freq)
        tot = lambda q: s[per == q].groupby("voce").spesa.sum()
        for t, q in zip(st.tabs([f"rispetto a {plabel(q)}" for q in refs]) if refs else [], refs):
            d = pd.concat([tot(p).rename("ora"), tot(q).rename("prima")], axis=1).fillna(0)
            d["delta"] = d.ora - d.prima
            d = d[d.delta.abs() >= 5].sort_values("delta", key=abs, ascending=False).head(8)
            with t, st.container(height=300, border=False):
                rows([("trending_up" if x.delta > 0 else "trending_down", BAD if x.delta > 0 else GOOD, v.split(SEP)[-1],
                       f"{side(v)} · da {eur(x.prima, 0)} a {eur(x.ora, 0)}", eur(x.delta, 0, sign=True), None, link(v))
                      for v, x in d.iterrows()] or [("check", OTHER, "Nessuna differenza rilevante", "", "", None)])

    yr, mm = p.year, flows(df)
    g = pd.DataFrame([(MESI[q.month - 1], str(q.year), v) for q, v in mm.uscite.items() if q.year in (yr - 1, yr)],
                     columns=["mese", "anno", "uscite"])
    old, new = (mm.uscite[mm.index.year == y_] for y_ in (yr - 1, yr))
    with st.container(key="card_yoy"):
        card_title(f"Uscite mese per mese: {yr} contro {yr - 1}",
                   f"media al mese {eur(new.mean(), 0)} nel {yr}" + (f", {eur(old.mean(), 0)} nel {yr - 1}" if len(old) else "")
                   + " · il mese in corso è parziale")
        fig = px.bar(g, x="mese", y="uscite", color="anno", barmode="group", category_orders={"mese": MESI, "anno": [str(yr - 1), str(yr)]},
                     color_discrete_map={str(yr - 1): OTHER, str(yr): PALETTE[0]})
        fig.update_traces(marker_line_width=0, hovertemplate="%{x} %{fullData.name}<br>%{y:,.0f} €<extra></extra>")
        chart(fig, 300)


def focus(title, hint, roots):
    """Detail page for a group of categories (bills, car): monthly cost, item by item, year by year, last payments."""
    header(title, hint)
    df = load()
    d = df[pd.concat([under(df, r) for r in roots], axis=1).any(axis=1)].copy()
    if d.empty:
        st.info("Nessun movimento in queste categorie.", icon=":material/info:")
        return
    d["spesa"] = -d.amount
    root = d.cat.map(lambda c: next(r for r in roots if c == r or c.startswith(r + SEP)))
    d["path"] = [c if c == r else r + SEP + c[len(r) + len(SEP):].split(SEP)[0] for c, r in zip(d.cat, root)]
    d["voce"] = d.path.str.split(SEP).str[-1]
    ic = icons()
    order = d.groupby("voce").spesa.sum().sort_values(ascending=False).index
    vc = {v: PALETTE[i] if i < len(PALETTE) else OTHER for i, v in enumerate(order)}  # fixed by all-time weight
    today = pd.Timestamp.today()
    now = pd.Period(today, "M")
    years = sorted({int(y) for y in d.date.dt.year}, reverse=True)
    sel = st.pills("Periodo", ["Ultimi 12 mesi", *years], default="Ultimi 12 mesi", required=True, label_visibility="collapsed")
    if sel == "Ultimi 12 mesi":
        first, to, name = now - 12, now - 1, "negli ultimi 12 mesi"  # complete months only
    else:
        first, to = pd.Period(f"{sel}-01", "M"), min(pd.Period(f"{sel}-12", "M"), now)
        name = f"nel {sel}" + (" finora" if to == now else "")
    months = pd.period_range(max(first, pd.Period(d.date.min(), "M")), to, freq="M")  # no average over months before the first bill
    n = len(months)
    cur, old = window(d, to, n), window(d, to - 12, n)
    old = old[old.date <= today - pd.DateOffset(years=1)]  # year in progress: same days of the year before
    tot, prev = cur.spesa.sum(), old.spesa.sum()
    partial = " · il mese in corso è parziale" if to == now else ""
    by = cur.groupby("voce").spesa.sum().sort_values(ascending=False)

    k = st.columns(3)
    k[0].metric("Al mese", eur(tot / n, 0), border=True, height="stretch", delta_color="inverse",
                delta=eur((tot - prev) / n, 0, sign=True) if len(old) else None,
                delta_description=f"media {name} rispetto allo stesso periodo un anno prima")
    k[1].metric(name.capitalize(), eur(tot, 0), border=True, height="stretch", delta_color="inverse",
                delta=eur(tot - prev, 0, sign=True) if len(old) else None, delta_description="rispetto allo stesso periodo un anno prima")
    if len(by):
        k[2].metric("Pesa di più", by.index[0], border=True, height="stretch", delta_color="off", delta_arrow="off",
                    delta=f"{by.iloc[0] / by.sum():.0%} del totale · {eur(by.iloc[0] / n, 0)} al mese")

    labels = [plabel(q) for q in months]
    l, r = st.columns([3, 2])
    with l, st.container(key="card_fmonth"):
        card_title("Mese per mese", f"{name} · la linea è la media ({eur(tot / n, 0)}){partial}")
        g = cur.groupby(["month", "voce"], as_index=False).spesa.sum().assign(mese=lambda x: x.month.map(mese))
        fig = px.bar(g, x="mese", y="spesa", color="voce", color_discrete_map=vc, category_orders={"mese": labels, "voce": list(order)})
        fig.add_hline(y=tot / n, line_dash="dot", line_width=1, line_color=MUTED)
        fig.update_traces(marker_line_width=0, hovertemplate="%{x} · %{fullData.name}<br>%{y:,.2f} €<extra></extra>")
        chart(fig, 340, labels)
    with r, st.container(key="card_fitems"):
        card_title("Voce per voce", f"{name} · clicca per tutti i movimenti")
        last = cur.sort_values("date").groupby("voce").last()
        with st.container(height=340, border=False):
            rows([(money.icon(ic, last.path[v]), vc[v], v, f"{eur(t / n, 0)} al mese · ultimo il {last.date[v]:%d/%m/%y}: "
                   f"{eur(last.spesa[v], 0)}", eur(t, 0), t / by.iloc[0], link(last.path[v])) for v, t in by.items()]
                 or [("info", OTHER, f"Niente {name}", "", "", None)])

    l, r = st.columns([2, 3])
    with l, st.container(key="card_fyear"):
        card_title("Anno per anno", f"il {today.year} è parziale")
        g = d.assign(anno=d.date.dt.year.astype(str)).groupby(["anno", "voce"], as_index=False).spesa.sum()
        fig = px.bar(g, x="anno", y="spesa", color="voce", color_discrete_map=vc, category_orders={"voce": list(order)})
        fig.update_traces(marker_line_width=0, hovertemplate="%{x} · %{fullData.name}<br>%{y:,.0f} €<extra></extra>")
        chart(fig, 320)
    with r, st.container(key="card_flast"):
        card_title("Pagamenti", f"{len(cur)} {name}")
        v = cur.sort_values("date", ascending=False)
        st.dataframe(v[["date", "description", "voce", "spesa"]].assign(description=v.description.map(pretty)), hide_index=True,
                     width="stretch", height=320, column_config={
                         "date": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                         "description": st.column_config.TextColumn("Descrizione", width="medium"), "voce": "Voce",
                         "spesa": st.column_config.NumberColumn("Importo", format="euro")})
    return first, to, name


def bills():
    if p := focus("Casa e bollette", "Luce, gas, acqua, internet e rifiuti: le utenze della casa (il mutuo ha la sua pagina).",
                  ["Casa > Utenze"]):
        energy(*p)


UTILITIES = [("luce", "kWh", 2), ("gas", "Smc", 2), ("acqua", "m³", 3)]  # kind in 'bills', unit, months per bar


def energy(first, to, name):
    """Utility bills (table 'bills': Eni luce/gas, Acque): consumption and real unit price (TV licence left out),
    against the same bimesters (quarters for water) a year before."""
    b = pd.DataFrame([json.loads(d) for d, in db.execute("SELECT data FROM bills")])
    if b.empty:
        return
    s, e = pd.to_datetime(b.start), pd.to_datetime(b.end)
    mid = s + (e - s) / 2  # water periods straddle months (27/02-27/05): the middle day says where a bill belongs
    span = b.kind.map({k: n for k, _, n in UTILITIES}).fillna(2).astype(int)
    slot = lambda m, n: f"{MESI[(m - 1) // n * n]}–<br>{MESI[(m - 1) // n * n + n - 1]}"  # 2 lines: narrow cards
    b["slot"] = [slot(m, n) for m, n in zip(mid.dt.month, span)]
    b["month"], b["anno"] = mid.dt.to_period("M"), mid.dt.year
    b["netto"] = (b.total - b.canone).where(b.qty > 0, 0)  # no use (contract, canone only): not a unit price
    b["prezzo"] = b.netto / b.qty.where(b.qty > 0)
    b["periodo"] = [f"{x:%d/%m}–{y:%d/%m/%y}" for x, y in zip(s, e)]
    b["days"] = (e - s).dt.days + 1
    num = lambda x, d=0: f"{x:,.{d}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    cur = b[b.month.between(first, to)]
    key = lambda df, dy=0: list(zip(df.kind, df.anno + dy, df.slot))
    old = b[[k in set(key(cur, -1)) for k in key(b)]]  # the same bimesters/quarters a year before
    same = cur[[k in set(key(old, 1)) for k in key(cur)]]  # ...and the current ones that have a match there
    kinds = [u for u in UTILITIES if (b.kind == u[0]).any()]
    st.markdown("#### Consumi e prezzi")
    rows = st.columns(len(kinds)), st.columns(len(kinds))
    for i, (kind, unit, n) in enumerate(kinds):
        c, o, m = (x[x.kind == kind] for x in (cur, old, same))
        q, oq, mq = c.qty.sum(), o.qty.sum(), m.qty.sum()
        p, mp, op = (x.netto.sum() / y if y else None for x, y in ((c, q), (m, mq), (o, oq)))
        rows[0][i].metric(f"{kind.capitalize()} · {c.days.sum() / 30.44:.0f} mesi in bolletta", f"{num(q)} {unit}", border=True, delta_color="inverse",
                          delta=f"{(mq - oq) / oq:+.0%}" if oq else None, delta_description="un anno prima",
                          help=f"Consumo fatturato {name} (l'ultima bolletta può non essere ancora arrivata); la variazione confronta gli stessi {'bimestri' if n == 2 else 'trimestri'} un anno prima.")
        rows[1][i].metric(f"Prezzo {kind}", f"{num(p, 3)} €/{unit}" if p else "—", border=True, delta_color="inverse",
                          delta=f"{(mp - op) / op:+.0%}" if mp and op else None, delta_description="un anno prima",
                          help="Quanto paghi davvero per unità: tutto compreso (quote fisse, oneri, imposte), canone RAI escluso.")
    years = [str(y) for y in sorted(b.anno.unique())[-3:]]
    yc = {y: PALETTE[i] for i, y in enumerate(reversed(years))}  # this year always blue
    for col, (kind, unit, n) in zip(st.columns(len(kinds)), kinds):
        with col, st.container(key=f"card_e{kind}"):
            card_title(f"{kind.capitalize()}: consumo per {'bimestre' if n == 2 else 'trimestre'}", f"{unit} · " +
                       " ".join(f'<b style="color:{yc[y]}">{y}</b>' for y in years))  # the legend, without its space
            g = b[(b.kind == kind) & (b.qty > 0) & b.anno.astype(str).isin(years)].assign(anno=lambda x: x.anno.astype(str))
            fig = px.bar(g, x="slot", y="qty", color="anno", barmode="group", custom_data=["netto", "prezzo", "periodo"],
                         color_discrete_map=yc, category_orders={"anno": years, "slot": [slot(m, n) for m in range(1, 13, n)]})
            fig.update_layout(showlegend=False)
            fig.update_traces(marker_line_width=0, hovertemplate=f"%{{customdata[2]}}<br>%{{y:,.0f}} {unit} · "
                              f"%{{customdata[0]:,.2f}} € · %{{customdata[1]:,.3f}} €/{unit}<extra></extra>")
            chart(fig, 300, unit=f" {unit}")
    with st.container(key="card_ebills"):
        tv = cur.canone.sum()
        card_title("Bollette", f"{len(cur)} {name}" + (f" · nelle bollette luce c'è anche il canone RAI: {eur(tv)}" if tv else ""))
        v = cur.sort_values(["start", "kind"], ascending=False)
        st.dataframe(v.assign(kind=v.kind.str.capitalize(), consumo=[f"{num(q)} {u}" for q, u in zip(v.qty, v.unit)],
                              due=pd.to_datetime(v.due),
                              prezzo=[f"{num(x, 3)} €/{u}" if x == x else "—" for x, u in zip(v.prezzo, v.unit)])
                     [["periodo", "kind", "consumo", "total", "canone", "prezzo", "due"]], hide_index=True, width="stretch",
                     column_config={"periodo": "Periodo", "kind": "Tipo", "consumo": "Consumo",
                                    "total": st.column_config.NumberColumn("Importo", format="euro"),
                                    "canone": st.column_config.NumberColumn("Canone RAI", format="euro"),
                                    "prezzo": "Prezzo",
                                    "due": st.column_config.DateColumn("Scadenza", format="DD/MM/YYYY")})


def car():
    focus("Auto", "Tutto quello che costa la macchina: carburante, assicurazione, bollo, manutenzione, pedaggi, parcheggi, "
                  "multe e finanziamento.",
          ["Trasporti > Auto", "Trasporti > Carburante", "Trasporti > Pedaggi", "Trasporti > Parcheggi", "Trasporti > Multe"])


def mortgage():
    header("Mutuo", "Ogni rata divisa in capitale (resta tuo: è casa) e interessi (il costo vero). Dati dalle descrizioni delle rate.")
    df = load(split=False)
    m = df[df.description.map(money.mortgage_split).notna()].copy()
    if m.empty:
        st.info("Nessuna rata di mutuo trovata.", icon=":material/info:")
        return
    m[["capitale", "interessi"]] = m.description.map(money.mortgage_split).tolist()
    m["oneri"] = -m.amount - m.capitale - m.interessi
    fin = re.search(r"FIN\. (\d+)", m.description.iloc[0])[1]
    erog = df[df.description.str.startswith("EROGAZIONE FINANZIAMENTO")]
    principal = erog[erog.description.map(lambda d: re.search(r"NUM\. (\d+)", d)[1] in fin)].amount.sum()
    paid = m.capitale.sum()

    k = st.columns(5)
    k[0].metric("Importo del mutuo", eur(principal, 0), border=True, height="stretch")
    k[1].metric("Capitale restituito", eur(paid, 0), border=True, height="stretch",
                delta=f"{paid / principal:.1%} del mutuo" if principal else None, delta_color="off", delta_arrow="off")
    k[2].metric("Debito residuo", eur(principal - paid, 0), border=True, height="stretch")
    k[3].metric("Interessi pagati", eur(m.interessi.sum(), 0), border=True, height="stretch",
                delta=f"+ {eur(m.oneri.sum(), 0)} di spese incasso", delta_color="off", delta_arrow="off")
    k[4].metric("Rate pagate", len(m), border=True, height="stretch",
                delta=f"ultima {m.date.max():%d/%m/%Y}", delta_color="off", delta_arrow="off")

    l, r = st.columns([3, 2])
    with l, st.container(key="card_mrate"):
        card_title("Composizione delle rate", "la quota capitale cresce, quella interessi cala")
        g = m.assign(mese=m.date.map(lambda t: mese(t)))
        labels = [mese(t) for t in sorted(m.date)]
        g = g.melt(id_vars=["mese"], value_vars=["capitale", "interessi", "oneri"], var_name="quota", value_name="euro")
        fig = px.bar(g, x="mese", y="euro", color="quota", category_orders={"mese": labels},
                     color_discrete_map={"capitale": PALETTE[0], "interessi": PALETTE[1], "oneri": OTHER})
        fig.update_traces(marker_line_width=0, hovertemplate="%{fullData.name}<br>%{y:,.2f} €<extra></extra>")
        chart(fig, 340, labels)
    with r, st.container(key="card_myear"):
        card_title("Per anno")
        y = m.groupby(m.date.dt.year)[["capitale", "interessi", "oneri"]].sum()
        rows([("calendar_month", PALETTE[0], str(yr), f"capitale {eur(v.capitale, 0)} · interessi {eur(v.interessi, 0)}",
               eur(v.sum(), 0), v.capitale / v.sum()) for yr, v in y.iloc[::-1].iterrows()])


KIND = {"mese": "Mensile", "tredicesima": "13ª", "quattordicesima": "14ª", "tfr": "TFR"}
PAY = {"MINIMO": "minimo contrattuale", "SCATTI": "scatti di anzianità", "SUP.ASS.": "superminimo", "PR.PROD.": "premio di produzione"}


def payslips():
    """One row per payslip: parse_busta() + busta_split(); stip = net pay without TFR advances and expense refunds."""
    rows = [json.loads(d) | {"name": n} for n, d in db.execute("SELECT name, data FROM payslips")]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([r | money.busta_split(r) for r in rows])
    df["date"] = pd.to_datetime(df.period)
    df["stip"] = df.net - df.tfr_paid - df.rimborsi
    return df.sort_values(["period", "kind"], ignore_index=True)


def voce_label(v):
    """'Addizionale regionale 2023 TOSCANA' -> 'Addizionale regionale': same item across years."""
    return re.sub(r" (?:\d{4}|\d\d/\d\d)\b.*$", "", v["desc"]) + (" (non in busta)" if v["fig"] else "")


def voci_sum(p, pay_only=False):
    """{label: amount} of one payslip (competenze +, trattenute −). pay_only: just what makes the net pay (no TFR,
    expense refunds or benefits)."""
    out = {}
    for v in p.voci:
        k = money.voce_kind(v)
        if (k or v["fig"] and v["amount"]) and not (pay_only and k in (None, "tfr_paid", "rimborsi", "benefit"))                 and not v["desc"].startswith("Smart Work"):  # SW: hours valued, already in the pay
            out[voce_label(v)] = out.get(voce_label(v), 0) + v["amount"]
    return out


def salary():
    df = payslips()
    if df.empty:
        header("Stipendio")
        st.info("Nessuna busta paga. Mettile in `data/nuovi`: vengono riconosciute e archiviate in `data/stipendio`.",
                icon=":material/work:")
        return
    m = df[df.kind == "mese"].reset_index(drop=True)
    last = m.iloc[-1]
    header("Stipendio", f"{len(df)} buste paga da {mese(df.date.min())} a {mese(df.date.max())} · {html.escape(last.employer)} · "
                        f"{html.escape(last.role.capitalize())}, livello {last.level}. Netto = senza rimborsi spese e anticipi TFR.")

    ago = m[m.date <= last.date - pd.DateOffset(months=12)]
    prev = ago.iloc[-1] if len(ago) else m.iloc[0]
    y12 = df[(df.date > last.date - pd.DateOffset(months=12)) & (df.kind != "tfr")]
    n_extra = y12.kind.isin(["tredicesima", "quattordicesima"]).sum()
    t = last.tfr or {}
    tfr_now = t.get("fondo", 0) + t.get("rival", 0) - t.get("imposta", 0) + t.get("anno", 0) - t.get("anticipi", 0)
    fe, par = ((last.leave.get(x) or [0] * 4)[3] or 0 for x in ("Ferie", "PAR"))
    off = dict(delta_color="off", delta_arrow="off", border=True, height="stretch")
    k = st.columns(4)
    k[0].metric(f"Netto {mese(last.date)}", eur(last.stip, 0), border=True, height="stretch", chart_type="bar",
                chart_data=m.stip.tail(24).round(2).tolist(), delta=eur(last.stip - prev.stip, 0, sign=True),
                delta_description=f"vs {mese(prev.date)}")
    k[1].metric("Paga base lorda", eur(last.base, 0), border=True, height="stretch", help="Minimo + scatti + superminimo + premi fissi, al mese.",
                delta=f"{last.base / prev.base - 1:+.1%} in un anno".replace(".", ",") if prev.base else None,
                delta_description=f"vs {mese(prev.date)}")
    k[2].metric("RAL", eur(last.base * (12 + n_extra), 0), help="Paga base × mensilità (12 + tredicesima/quattordicesima degli ultimi 12 mesi).",
                delta=f"{12 + n_extra} mensilità", **off)
    k[3].metric("Ferie e permessi", f"{(fe + par) / 8:.0f} giorni", delta=f"ferie {fe:.0f} h · PAR {par:.0f} h", **off,
                help="Saldo dell'ultima busta: ore non ancora godute (8 ore = 1 giorno).")

    # pay rises: every change of base pay or level, explained by which component moved
    steps, before = [], None
    for p in m.itertuples():
        if before is not None and (abs(p.base - before.base) > .005 or p.level != before.level):
            why = [f"nuovo contratto dal {p.hired.replace('-', '/')} {p.contract}".strip()] if p.hired != before.hired else []
            why += [f"livello {before.level or '?'} → {p.level or '?'}"] if p.level != before.level else []
            for c in dict.fromkeys([*before.pay, *p.pay]):
                dv = p.pay.get(c, 0) - before.pay.get(c, 0)
                if abs(dv) > .005:  # a contract raise can absorb the individual superminimo
                    why.append(f"{'superminimo assorbito' if c == 'SUP.ASS.' and dv < 0 else PAY.get(c, c)} {eur(dv, 2, sign=True)}")
            steps.append((p.date, before.base, p.base, " · ".join(why)))
        before = p
    items = anomalies(df, m, last, par)
    urgent = sum(i[0] <= 1 for i in items)

    t1, t2, t3, t4, t5, t6 = st.tabs([":material/trending_up: Aumenti", ":material/payments: Netto e tasse",
                                      ":material/calendar_month: Anno per anno", ":material/beach_access: Ferie e TFR",
                                      f":material/rule: Controlli ({urgent})" if urgent else ":material/rule: Controlli",
                                      ":material/description: Buste paga"])
    with t1:
        l, r = st.columns([3, 2])
        with l, st.container(key="card_base"):
            nxt = f" · prossimo scatto di anzianità: {last.next_step.replace('-', '/')}" if last.next_step else ""
            card_title("Paga base lorda mensile", f"da {eur(m.base.iloc[0], 0)} a {eur(last.base, 0)} "
                                                  f"({last.base / m.base.iloc[0] - 1:+.0%}){nxt}")
            fig = px.line(m, x="date", y="base", line_shape="hv", color_discrete_sequence=[PALETTE[0]], custom_data=["level"])
            fig.update_traces(line_width=2, hovertemplate="%{x|%m/%Y} · livello %{customdata[0]}<br>%{y:,.2f} €<extra></extra>")
            chart(fig, 340)
        with r, st.container(key="card_raises"):
            card_title("Aumenti e cambi di livello", f"{len(steps)} variazioni · cosa è cambiato in busta")
            with st.container(height=340, border=False):
                rows([("trending_up" if b >= a else "trending_down", GOOD if b >= a else BAD, f"{mese(d)} · {eur(b, 0)}",
                       why or "nessuna voce cambiata", f"{b / a - 1:+.1%}".replace(".", ",") if a else "", None)
                      for d, a, b, why in reversed(steps)])
    with t2:
        l, r = st.columns([3, 2])
        with l, st.container(key="card_net"):
            card_title("Netto di ogni busta", f"netto negli ultimi 12 mesi {eur(y12.stip.sum(), 0)}, mediana mensile "
                                              f"{eur(m.stip.tail(12).median(), 0)} · "
                                              "le barre fuori scala sono di solito conguagli, rimborsi 730 o arretrati")
            g = df[df.kind != "tfr"].assign(tipo=lambda x: x.kind.map(KIND))
            fig = px.bar(g, x="date", y="stip", color="tipo", color_discrete_map={"Mensile": PALETTE[0], "13ª": PALETTE[3], "14ª": PALETTE[2]},
                         custom_data=["tipo"])
            fig.update_traces(marker_line_width=0, hovertemplate="%{x|%m/%Y} · %{customdata[0]}<br>%{y:,.2f} €<extra></extra>")
            chart(fig.update_layout(barmode="stack", bargap=0.15), 340)
        with r, st.container(key="card_gross"):
            card_title("Dal lordo al netto", "per anno: dove va la retribuzione lorda")
            y = df.groupby(df.date.dt.year)[["stip", "tasse", "contributi", "altre"]].sum()
            g = y.rename(columns={"stip": "Netto", "tasse": "IRPEF e addizionali", "contributi": "Contributi INPS", "altre": "Altre trattenute"})
            g = g.reset_index(names="anno").melt(id_vars="anno", var_name="voce", value_name="euro").assign(anno=lambda x: x.anno.astype(str))
            fig = px.bar(g, x="anno", y="euro", color="voce", color_discrete_map={
                "Netto": PALETTE[2], "IRPEF e addizionali": PALETTE[1], "Contributi INPS": PALETTE[0], "Altre trattenute": OTHER})
            fig.update_traces(marker_line_width=0, hovertemplate="%{fullData.name}<br>%{y:,.2f} €<extra></extra>")
            chart(fig, 340)

    vs = pd.DataFrame([{"anno": p.date.year, **voci_sum(p)} for p in df.itertuples()]).groupby("anno").sum()
    with t3, st.container(key="card_years"):
        over = vs[[c for c in vs if re.search(r"straord|lavorat|supplem", c, re.I)]].sum(axis=1)
        sick = df.assign(h=df.hours.map(lambda h: h.get("Malattia", 0))).groupby(df.date.dt.year).h.sum()
        eoy = m.groupby(m.date.dt.year).last()  # leave columns are year-to-date: the last payslip has the year's total
        used = lambda x: eoy.leave.map(lambda v: (v.get(x) or [0] * 4)[2] or 0)
        yt = df.groupby(df.date.dt.year).agg(buste=("name", "size"), lordo=("lordo", "sum"), netto=("stip", "sum"), tasse=("tasse", "sum"),
                                             contributi=("contributi", "sum"), rimborsi=("rimborsi", "sum"), benefit=("benefit", "sum"))
        yt = yt.assign(quota=yt.netto / yt.lordo, ferie=used("Ferie"), par=used("PAR"), malattia=sick / 8, extra=over).iloc[::-1]
        card_title("Anno per anno", "l'anno in corso è parziale · ferie e PAR goduti in ore · malattia in giorni")
        st.dataframe(yt, width="stretch", height=420, column_config={
            "_index": st.column_config.NumberColumn("Anno", format="%d"), "buste": "Buste",
            **{c: st.column_config.NumberColumn(n, format="euro") for c, n in [
                ("lordo", "Lordo"), ("netto", "Netto"), ("tasse", "IRPEF"), ("contributi", "INPS"), ("rimborsi", "Rimborsi spese"),
                ("benefit", "Buoni pasto e benefit"), ("extra", "Straordinari e festivi")]},
            "quota": st.column_config.NumberColumn("Netto/lordo", format="percent"),
            "ferie": st.column_config.NumberColumn("Ferie (h)", format="%.0f"), "par": st.column_config.NumberColumn("PAR (h)", format="%.0f"),
            "malattia": st.column_config.NumberColumn("Malattia (gg)", format="%.0f")})
    with t4:
        l, r = st.columns([3, 2])
        with l, st.container(key="card_leave"):
            card_title("Ferie e permessi non goduti", "saldo in ore, busta per busta")
            lv = pd.DataFrame([(p.date, x, (p.leave.get(x) or [0] * 4)[3] or 0) for p in m.itertuples() for x in ("Ferie", "PAR")],
                              columns=["date", "tipo", "ore"])
            fig = px.line(lv, x="date", y="ore", color="tipo", color_discrete_map={"Ferie": PALETTE[2], "PAR": PALETTE[4]})
            fig.update_traces(line_width=2, hovertemplate="%{fullData.name}<br>%{y:,.0f} ore<extra></extra>")
            chart(fig, 320, unit=" h")
        with r, st.container(key="card_tfr"):
            card_title("TFR e saldo ferie", f"dall'ultima busta, {mese(last.date)}")
            rows([("savings", PALETTE[0], "TFR maturato in azienda", f"+ {eur(t.get('anno', 0), 0)} nel {last.date.year} · "
                   "fondo al 31/12 + rivalutazione netta + quota dell'anno − anticipi", eur(tfr_now, 0), None),
                  ("beach_access", PALETTE[2], "Ferie da godere", f"{fe / 8:.0f} giorni", f"{fe:.0f} h", None),
                  ("event_available", PALETTE[4], "PAR da godere", f"{par / 8:.0f} giorni", f"{par:.0f} h", None)])
    with t5, st.container(key="card_checks"):
        card_title("Anomalie e cose da sapere", f"{len(items)} segnalazioni · prima le più importanti")
        rows([i[1:] for i in sorted(items, key=lambda i: i[0])] or [("task_alt", GOOD, "Nessuna anomalia", "", "", None)])
    with t6:
        with st.container(key="card_slip"):
            card_title("Dettaglio busta", "confronto con la busta precedente dello stesso tipo")
            names = df.iloc[::-1]
            pick = st.selectbox("Busta", names.name, format_func=lambda n: f"{mese(df.date[df.name == n].iloc[0])} · "
                                                                            f"{KIND[df.kind[df.name == n].iloc[0]]}", label_visibility="collapsed")
            p = df[df.name == pick].iloc[0]
            same = df[(df.kind == p.kind) & (df.date < p.date)]
            a, b = voci_sum(p), voci_sum(same.iloc[-1]) if len(same) else {}
            d = pd.DataFrame({"Voce": list(dict.fromkeys([*a, *b]))})
            d["Importo"], d["Busta prima"] = d.Voce.map(a), d.Voce.map(b)
            d["Differenza"] = d.Importo.fillna(0) - d["Busta prima"].fillna(0)
            c1, c2 = st.columns([1, 2])
            with c1:
                rows([("payments", GOOD, "Netto", f"competenze {eur(p.comp)} − trattenute {eur(p.tratt)}", eur(p.net), None),
                      ("account_balance", PALETTE[1], "IRPEF e addizionali", "al netto di bonus e rimborsi 730", eur(p.tasse), None),
                      ("shield", PALETTE[0], "Contributi INPS", "", eur(p.contributi), None),
                      ("badge", OTHER, f"Livello {p.level}", f"{p.role.capitalize()} · paga base {eur(p.base)}", "", None)])
            c2.dataframe(d.sort_values("Differenza", key=abs, ascending=False), hide_index=True, width="stretch", height=380, column_config={
                c: st.column_config.NumberColumn(c, format="euro") for c in ("Importo", "Busta prima", "Differenza")})
        with st.container(key="card_voci"):
            card_title("Tutte le voci, per anno", "competenze positive, trattenute negative · '(non in busta)' = benefit non pagati in contanti")
            pv = vs.T.loc[lambda x: x.abs().sum(axis=1) > 0]
            pv = pv.loc[pv.abs().sum(axis=1).sort_values(ascending=False).index, ::-1]
            st.dataframe(pv, width="stretch", height=480, column_config={
                "_index": st.column_config.TextColumn("Voce", width="medium"),
                **{c: st.column_config.NumberColumn(str(c), format="euro") for c in pv.columns}})

def anomalies(df, m, last, par):
    """(priority, icon, color, title, subtitle, amount, None): missing payslips, net pay vs bank credit, unusual
    months with the voci that explain them, tax adjustments, TFR advances, sick leave, unused leave."""
    out = []
    months = pd.date_range(m.date.min(), m.date.max(), freq="MS")
    bank = load(split=False)
    bank = bank[bank.category.isin(["Entrate > Stipendio", "Entrate > Mensilità aggiuntive"])]
    for d in months.difference(m.date):
        paid = bank[(bank.month == d + pd.DateOffset(months=1)) & (bank.category == "Entrate > Stipendio")].amount.sum()
        out.append((0, "error", BAD, f"Busta di {mese(d)} mancante", "scaricala dal portale e mettila in data/nuovi"
                    + (f" · in banca sono arrivati {eur(paid)}" if paid else ""), "", None))
    for yr in sorted(set(m.date.dt.year)):
        for kind, month in (("tredicesima", 12), ("quattordicesima", 6)):
            first = df[df.kind == kind].date.min()
            if (pd.notna(first) and pd.Timestamp(yr, month, 1) >= first and pd.Timestamp(yr, month, 1) in set(m.date)
                    and not ((df.kind == kind) & (df.date.dt.year == yr)).any()):
                out.append((0, "error", BAD, f"{KIND[kind]} {yr} mancante", "c'è la busta del mese ma non quella aggiuntiva", "", None))
    # net pay vs bank credit: monthly pay arrives the month after, 13ª/14ª the same month
    if len(bank):
        got = bank.groupby([bank.month, bank.category.str.endswith("aggiuntive")]).amount.sum()
        e = df[df.kind != "tfr"]
        exp = e.groupby([e.date.where(e.kind != "mese", e.date + pd.DateOffset(months=1)), e.kind != "mese"]).net.sum()
        both = pd.concat([exp.rename("busta"), got.rename("banca")], axis=1).fillna(0)
        both = both[(both.index.get_level_values(0) >= pd.Timestamp(money.START)) & (both.index.get_level_values(0) <= bank.month.max())]
        for (mo, extra), v in both[((both.busta - both.banca).abs() > 1) & (both.busta > 0)].iterrows():  # no payslip: see above
            what = "mensilità aggiuntiva" if extra else f"stipendio di {mese(mo - pd.DateOffset(months=1))}"
            out.append((1, "account_balance", WARN, f"Accredito di {mese(mo)} diverso dalla busta",
                        f"{what}: busta {eur(v.busta)}, in banca {eur(v.banca)}", eur(v.banca - v.busta, 2, sign=True), None))
    # unusual months: far from the median of the previous 6, explained by the voci that differ most from their average
    for i in range(6, len(m)):
        p, med = m.iloc[i], m.stip.iloc[i - 6:i].median()
        if abs(p.stip - med) > .12 * med:
            a = voci_sum(p, pay_only=True)
            b = pd.DataFrame([voci_sum(q, pay_only=True) for q in m.iloc[i - 6:i].itertuples()]).fillna(0).mean()
            diff = sorted(((k, a.get(k, 0) - b.get(k, 0)) for k in {*a, *b.index}), key=lambda x: -abs(x[1]))[:3]
            out.append((2, "trending_up" if p.stip > med else "trending_down", PALETTE[0] if p.stip > med else WARN,
                        f"{mese(p.date)}: netto {eur(p.stip, 0)} ({p.stip / med - 1:+.0%})",
                        " · ".join(f"{k} {eur(v, 0, sign=True)}" for k, v in diff if abs(v) >= 1), "", None))
    for p in df.itertuples():
        for v in p.voci:
            a, c = v["amount"], v["code"]
            if a is None or v["fig"]:
                continue
            if c == "F09100":
                out.append((3, "receipt_long", PALETTE[0] if a > 0 else WARN, f"Conguaglio IRPEF · {mese(p.date)}",
                            "a credito: ti hanno restituito imposte" if a > 0 else "a debito: imposte trattenute in più", eur(a, 2, sign=True), None))
            elif c == "F00880":
                out.append((3, "receipt_long", GOOD, f"Rimborso 730 · {mese(p.date)}", v["desc"], eur(a, 2, sign=True), None))
            elif "Anticipazione T.F.R." in v["desc"]:
                out.append((3, "savings", WARN, f"Anticipo TFR · {mese(p.date)}", f"netto dopo le tasse {eur(p.tfr_paid)}", eur(a), None))
            elif re.search(r"non god|Restituzione", v["desc"]) and not v["desc"].startswith("Festivit"):
                out.append((3, "beach_access", PALETTE[4], f"{v['desc']} · {mese(p.date)}", "pagati perché non goduti" if a else "", eur(a), None))
        if p.hours.get("Malattia"):
            out.append((4, "sick", OTHER, f"Malattia · {mese(p.date)}", f"{p.hours['Malattia'] / 8:.0f} giorn{'o' if round(p.hours['Malattia'] / 8) == 1 else 'i'}", "", None))
    for a, b in zip(m.itertuples(), m.iloc[1:].itertuples()):
        if b.base < a.base - .005 and a.hired == b.hired:  # a new contract (e.g. apprenticeship) starts from its own pay
            out.append((0, "trending_down", BAD, f"Paga base scesa · {mese(b.date)}", f"da {eur(a.base)} a {eur(b.base)}", "", None))
    year = m[m.date.dt.year == last.date.year - 1]
    par_year = ((year.iloc[-1].leave.get("PAR") or [0] * 4)[1] or 0) if len(year) else 0
    if par_year and par > 2 * par_year:
        out.append((1, "event_busy", WARN, f"{par:.0f} ore di PAR accumulate ({par / 8:.0f} giorni)",
                    f"ne maturi {par_year:.0f} l'anno: quelli vecchi possono essere pagati invece che goduti, controlla il contratto", "", None))
    return out


def tags():
    df = load()
    t = df.dropna(subset=["tag"])
    sel = st.query_params.get("t")
    if not sel or sel not in set(t.tag):
        header("Etichette", "Raggruppano spese di categorie diverse, per esempio un viaggio. "
                            "Si assegnano dalla pagina <b>Movimenti</b> (anche a tutti i movimenti filtrati).")
        if t.empty:
            st.info("Nessuna etichetta ancora.", icon=":material/sell:")
            return
        s = spending(t)
        g = s.groupby("tag").agg(tot=("spesa", "sum"), n=("spesa", "size"), da=("date", "min"), a=("date", "max"))
        g = g.sort_values("da", ascending=False)
        with st.container(key="card_tags"):
            rows([("sell", PALETTE[i % len(PALETTE)], tag, f"{v.da:%d/%m/%Y} – {v.a:%d/%m/%Y} · {v.n} movimenti",
                   eur(v.tot, 0), v.tot / g.tot.max(), "etichette?t=" + quote(tag)) for i, (tag, v) in enumerate(g.iterrows())])
        return
    st.html('<nav class="crumbs"><a href="etichette" target="_self">Etichette</a><span class="ms">chevron_right</span>'
            f'<a href="etichette?t={quote(sel)}" target="_self">{html.escape(sel)}</a></nav>')
    header(sel)
    d = t[t.tag == sel]
    s = spending(d)
    days = (d.date.max() - d.date.min()).days + 1
    k = st.columns(4)
    k[0].metric("Totale", eur(s.spesa.sum(), 0), border=True, height="stretch")
    k[1].metric("Periodo", f"{days} giorni", border=True, height="stretch",
                delta=f"{d.date.min():%d/%m/%Y} – {d.date.max():%d/%m/%Y}", delta_color="off", delta_arrow="off")
    k[2].metric("Al giorno", eur(s.spesa.sum() / days, 0), border=True, height="stretch")
    k[3].metric("Movimenti", len(d), border=True, height="stretch")
    ic, cmap = icons(), colors(df)
    l, r = st.columns([2, 3])
    with l, st.container(key="card_tcat"):
        card_title("Per categoria")
        by = s.groupby("cat").spesa.sum().sort_values(ascending=False)
        rows([(money.icon(ic, c), cmap.get(c.split(SEP)[0], OTHER), c, "", eur(v, 0), v / by.max()) for c, v in by.items()])
        new = st.text_input("Rinomina", value=sel, label_visibility="collapsed")
        a, b = st.columns(2)
        if a.button("Rinomina", icon=":material/edit:", disabled=not new or new == sel):
            db.execute("UPDATE tx SET tag=? WHERE tag=?", (new.strip(), sel))
            db.commit()
            st.query_params["t"] = new.strip()
            st.rerun()
        if b.button("Elimina etichetta", icon=":material/delete:"):
            db.execute("UPDATE tx SET tag=NULL WHERE tag=?", (sel,))
            db.commit()
            del st.query_params["t"]
            st.rerun()
    with r, st.container(key="card_ttx"):
        card_title("Movimenti")
        st.dataframe(d[["date", "description", "amount", "cat"]].assign(description=d.description.map(pretty)),
                     hide_index=True, width="stretch", height=440, column_config={
                         "date": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                         "description": "Descrizione", "amount": st.column_config.NumberColumn("Importo", format="euro"),
                         "cat": "Categoria"})


def deductions():
    header("Detrazioni 730", "Stima indicativa delle spese detraibili al 19%: controlla sempre con la precompilata "
                             "o con il CAF. In farmacia valgono solo i farmaci con scontrino parlante (codice fiscale).")
    df = load()
    years = sorted(df.date.dt.year.unique(), reverse=True)
    y = st.pills("Anno", years, default=years[1] if len(years) > 1 else years[0], required=True, label_visibility="collapsed")
    d = df[df.date.dt.year == y]
    san = d[d.macro == "Salute"]
    vita = d[d.cat == "Finanza > Assicurazioni"]
    mort = load(split=False)
    mort = mort[mort.date.dt.year == y]
    interest = mort.description.map(money.mortgage_split).dropna().map(lambda p: p[1])
    s_tot, i_tot, v_tot = -san.amount.sum(), interest.sum(), -vita.amount.sum()
    s_det, i_det, v_det = max(s_tot - 129.11, 0) * .19, min(i_tot, 4000) * .19, min(v_tot, 530) * .19

    k = st.columns(4)
    k[0].metric("Spese sanitarie", eur(s_tot, 0), border=True, height="stretch",
                delta=f"detrazione {eur(s_det, 0)} (19% oltre 129,11 €)", delta_color="off", delta_arrow="off")
    k[1].metric("Interessi mutuo prima casa", eur(i_tot, 0), border=True, height="stretch",
                delta=f"detrazione {eur(i_det, 0)} (19% fino a 4.000 €)", delta_color="off", delta_arrow="off")
    k[2].metric("Assicurazione vita", eur(v_tot, 0), border=True, height="stretch",
                delta=f"detrazione {eur(v_det, 0)} (19% fino a 530 €)", delta_color="off", delta_arrow="off")
    k[3].metric("Detrazione stimata", eur(s_det + i_det + v_det, 0), border=True, height="stretch",
                delta=f"redditi {y} · 730 del {y + 1}", delta_color="off", delta_arrow="off")

    items = pd.concat([san.assign(voce="Spese sanitarie"), vita.assign(voce="Assicurazione vita"),
                       mort[mort.description.map(money.mortgage_split).notna()].assign(
                           voce="Interessi mutuo", amount=-interest)])
    with st.container(key="card_ded"):
        card_title("Movimenti considerati", f"{len(items)} movimenti nel {y}")
        view = items[["date", "voce", "description", "amount"]].assign(description=items.description.map(pretty))
        st.dataframe(view.sort_values("date"), hide_index=True, width="stretch", height=420, column_config={
            "date": st.column_config.DateColumn("Data", format="DD/MM/YYYY"), "voce": "Voce",
            "description": "Descrizione", "amount": st.column_config.NumberColumn("Importo", format="euro")})
        st.download_button("Scarica CSV per il 730", view.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                           file_name=f"detrazioni_{y}.csv", mime="text/csv", icon=":material/download:")


def category():
    df = load()
    path = st.query_params.get("c", "")
    parts = path.split(SEP)
    st.html('<nav class="crumbs">' + '<span class="ms">chevron_right</span>'.join(
        ['<a href="./" target="_self">Panoramica</a>'] +
        [f'<a href="{link(SEP.join(parts[:i + 1]))}" target="_self">{html.escape(p)}</a>' for i, p in enumerate(parts) if p]) + "</nav>")
    inside = under(df, path)
    if not path or not inside.any():
        st.info("Nessun movimento per questa categoria.", icon=":material/info:")
        return
    ic, cmap = icons(), colors(df)
    color = cmap.get(parts[0], OTHER)
    h, f1 = st.columns([3, 4], vertical_alignment="bottom")
    h.html(f'<div class="hero" style="--c:{color}"><span class="ic ms">{money.icon(ic, path)}</span>'
           f'<h2>{html.escape(parts[-1])}</h2></div>')
    f, idx = filters(df, f1)
    sign = 1 if parts[0] == money.INCOME else -1  # both income and spending shown as positive amounts
    d = f[under(f, path)].assign(spesa=lambda x: sign * x.amount)
    d["child"] = d.cat.str.split(SEP).str[len(parts)].fillna("Generico")
    d["rel"] = d.cat.str[len(path) + len(SEP):]  # path below the current level
    monthly = d.groupby("month").spesa.sum().reindex(idx, fill_value=0)
    total, all_spend = monthly.sum(), spending(f).spesa.sum()

    k = st.columns(4)
    k[0].metric("Totale nel periodo", eur(total, 0), border=True, height="stretch",
                chart_data=monthly.round(2).tolist(), chart_type="bar")
    k[1].metric(mese(idx[-1]).capitalize(), eur(monthly.iloc[-1], 0), border=True, height="stretch", delta_color="inverse",
                delta=eur(monthly.iloc[-1] - monthly.iloc[-2], 0, sign=True) if len(monthly) > 1 else None,
                delta_description="vs mese prima")
    k[2].metric("Media mensile", eur(monthly.mean(), 0), border=True, height="stretch")
    k[3].metric("Quota sulle spese", f"{total / all_spend:.0%}" if all_spend > 0 and parts[0] not in (money.EXCLUDED, money.INCOME, money.SAVINGS) else "—",
                border=True, height="stretch", delta=f"{len(d)} movimenti", delta_color="off", delta_arrow="off")
    if d.empty:
        st.info("Nessun movimento nel periodo selezionato.", icon=":material/info:")
        return

    children = d.groupby("child").spesa.agg(["sum", "size"]).sort_values("sum", ascending=False)
    ccol = {n: PALETTE[i % len(PALETTE)] for i, n in enumerate(children.index)}
    best = children["sum"].iloc[0] or 1
    nested = list(children.index) != ["Generico"]
    l, r = st.columns([5, 4]) if nested else (st.container(), None)
    with l, st.container(key="card_ctrend"):
        card_title("Andamento mensile", f"media {eur(monthly.mean(), 0)} al mese")
        g = d.assign(mese=d.month.map(mese)).groupby(["month", "mese", "child"], as_index=False).spesa.sum()
        fig = px.bar(g, x="mese", y="spesa", color="child", color_discrete_map=ccol,
                     category_orders={"mese": [mese(t) for t in idx], "child": list(ccol)})
        fig.add_hline(y=monthly.mean(), line_dash="dot", line_width=1, line_color=MUTED)
        fig.update_traces(marker_line_width=0, hovertemplate="%{fullData.name}<br>%{y:,.2f} €<extra></extra>")
        chart(fig.update_layout(showlegend=nested), 320, [mese(t) for t in idx])
    if nested:
        with r, st.container(key="card_children"):
            card_title("Sottocategorie", "clicca per entrare nel dettaglio")
            with st.container(height=320, border=False):
                rows([(money.icon(ic, path if n == "Generico" else f"{path}{SEP}{n}"), ccol[n], n,
                       f"{z} movimenti · {v / total:.0%}" if total else f"{z} movimenti", eur(v, 0), v / best,
                       None if n == "Generico" else link(f"{path}{SEP}{n}")) for n, v, z in children.itertuples()])

    l, r = st.columns([3, 2])
    with l, st.container(key="card_ctx"):
        card_title("Movimenti", f"{len(d)} nel periodo")
        st.dataframe(d[["date", "description", "spesa", "rel"]].assign(description=d.description.map(pretty)),
                     hide_index=True, width="stretch", height=420, column_config={
                         "date": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                         "description": st.column_config.TextColumn("Descrizione", width="medium"),
                         "spesa": st.column_config.NumberColumn("Importo", format="euro"),
                         "rel": "Sottocategoria"},
                     column_order=["date", "description", "spesa"] + (["rel"] if nested else []))
    with r, st.container(key="card_cmerch"):
        card_title("Esercenti", "dove spendi di più in questa categoria")
        top = d.groupby("merchant").agg(desc=("description", "first"), cat=("cat", "first"), n=("spesa", "size"),
                                        tot=("spesa", "sum")).nlargest(8, "tot")
        rows([(money.icon(ic, t.cat), color, pretty(t.desc), f"{t.n} volte", eur(t.tot, 0), t.tot / (top.tot.iloc[0] or 1))
              for t in top.itertuples()])


def transactions():
    df = load(split=False)
    header("Movimenti", "Correggi la categoria di un movimento (non crea regole) o assegna un'etichetta.")
    a, b, c, d = st.columns([3, 2, 2, 2])
    q = a.text_input("Cerca", placeholder="Cerca descrizione o categoria…", icon=":material/search:",
                     label_visibility="collapsed")
    macro = b.selectbox("Macro", ["Tutte le categorie"] + sorted(df.macro.unique()), label_visibility="collapsed")
    tagset = sorted(df.tag.dropna().unique())
    tag = c.selectbox("Etichetta", ["Tutte le etichette", "Senza etichetta"] + tagset, label_visibility="collapsed")
    span = d.date_input("Periodo", (df.date.min(), df.date.max()), format="DD/MM/YYYY", label_visibility="collapsed")
    if q:
        df = df[df.description.str.contains(q, case=False, regex=False) | df.category.fillna("").str.contains(q, case=False, regex=False)]
    if macro != "Tutte le categorie":
        df = df[df.macro == macro]
    if tag == "Senza etichetta":
        df = df[df.tag.isna()]
    elif tag != "Tutte le etichette":
        df = df[df.tag == tag]
    if len(span) == 2:
        df = df[df.date.dt.date.between(*span)]
    view = df[["id", "date", "description", "amount", "account", "category", "tag"]].assign(description=df.description.map(pretty))
    edited = st.data_editor(view, hide_index=True, width="stretch", height=600, disabled=["date", "description", "amount", "account"],
                            column_order=["date", "description", "amount", "category", "tag", "account"], column_config={
                                "date": st.column_config.DateColumn("Data", format="DD/MM/YYYY", width="small"),
                                "description": st.column_config.TextColumn("Descrizione", width="large"),
                                "account": st.column_config.TextColumn("Conto", width="small"),
                                "amount": st.column_config.NumberColumn("Importo", format="euro", width="small"),
                                "category": st.column_config.SelectboxColumn("Categoria", options=categories(), width="medium"),
                                "tag": st.column_config.TextColumn("Etichetta", width="small")})
    st.caption(f"{len(df)} movimenti · totale {eur(df.amount.sum())}")
    cat_changed = edited[edited.category.fillna("") != view.category.fillna("")]
    tag_changed = edited[edited.tag.fillna("") != view.tag.fillna("")]
    a, b, c = st.columns([2, 2, 3], vertical_alignment="bottom")
    if len(cat_changed) + len(tag_changed) and a.button(f"Salva {len(cat_changed) + len(tag_changed)} modifiche",
                                                         type="primary", icon=":material/save:"):
        db.executemany("UPDATE tx SET category=?, manual=1 WHERE id=?", cat_changed[["category", "id"]].values.tolist())
        db.executemany("UPDATE tx SET tag=? WHERE id=?",
                       [((t or "").strip() or None, i) for t, i in tag_changed[["tag", "id"]].values])
        db.commit()
        st.rerun()
    bulk = b.text_input("Etichetta per tutti", placeholder="es. Lisbona 2024", label_visibility="collapsed")
    if c.button(f"Applica a tutti i {len(df)} movimenti filtrati", icon=":material/sell:", disabled=not bulk.strip() or df.empty):
        db.executemany("UPDATE tx SET tag=? WHERE id=?", [(bulk.strip(), i) for i in df.id])
        db.commit()
        st.rerun()


def review():
    df = load(split=False)
    u = df[df.macro == UNCAT]
    header("Da categorizzare", "Scegli una categoria: diventa una regola e i movimenti uguali, presenti e futuri, "
                               "finiranno lì da soli. Accorcia la <b>regola</b> per renderla più generica.")
    if u.empty:
        st.success("Tutto categorizzato.", icon=":material/task_alt:")
        return
    g = (u.groupby("merchant").agg(Esempio=("description", "first"), Volte=("id", "size"), Totale=("amount", "sum"))
         .reset_index().sort_values("Volte", ascending=False))
    g["Esempio"], g["Regola"], g["Categoria"] = g.Esempio.map(pretty), g.merchant, None
    edited = st.data_editor(g, hide_index=True, width="stretch", height="auto",
                            disabled=["Esempio", "Volte", "Totale"],
                            column_order=["Esempio", "Volte", "Totale", "Regola", "Categoria"], column_config={
                                "Esempio": st.column_config.TextColumn(width="large"),
                                "Totale": st.column_config.NumberColumn(format="euro"),
                                "Categoria": st.column_config.SelectboxColumn(options=categories(), width="large")})
    todo = edited.dropna(subset=["Categoria"])
    if len(todo) and st.button(f"Impara {len(todo)} regole", type="primary", icon=":material/school:"):
        for pattern, cat in todo[["Regola", "Categoria"]].values:
            money.learn(db, pattern or "", cat)
        st.rerun()


def settings():
    header("Categorie e regole")
    t1, t2, t3 = st.tabs([":material/category: Categorie", ":material/rule: Regole", ":material/savings: Budget"])
    with t1:
        st.html(f'<p class="hint">Livelli separati da <code>{SEP.strip()}</code>. Icone: nome da '
                '<a href="https://fonts.google.com/icons" target="_blank">Material Symbols</a> (es. <code>bolt</code>); '
                f'vuota = eredita dal livello sopra. <b>{money.INCOME}</b> = entrate, <b>{money.EXCLUDED}</b> = esclusi dalle spese, '
                f'<b>{money.SAVINGS}</b> = soldi messi da parte (esclusi dalle spese).</p>')
        a, b = st.columns([3, 2])
        cats = pd.read_sql("SELECT path, icon FROM categories ORDER BY path", db)
        with a:
            edited = st.data_editor(cats, num_rows="dynamic", hide_index=True, width="stretch", height=560, column_config={
                "path": st.column_config.TextColumn("Categoria", required=True, width="large"),
                "icon": st.column_config.TextColumn("Icona")})
            if st.button("Salva categorie", type="primary", icon=":material/save:"):
                clean = {SEP.join(p.strip() for p in path.split(SEP.strip())): (i or "").strip() or None
                         for path, i in edited.values if path and path.strip()}
                db.execute("DELETE FROM categories")
                db.executemany("INSERT INTO categories VALUES (?,?)", clean.items())
                db.commit()
                st.rerun()
        with b, st.container(key="card_preview", height=600):
            card_title("Anteprima")
            ic = dict(edited.dropna(subset=["path"]).values)
            rows([(money.icon(ic, p), PALETTE[0] if SEP not in p else OTHER, " " * p.count(SEP) + p.split(SEP)[-1],
                   "", "", None) for p in edited.path.dropna()])
    with t2:
        st.html('<p class="hint">Il testo della regola si cerca dentro la descrizione normalizzata '
                '(minuscolo, senza codici). Vince la più lunga. Con <code>#</code> davanti si cerca nel testo originale, '
                'numeri compresi: utile per codici cliente o numeri di polizza (es. <code>#123456789012</code>).</p>')
        rules = pd.read_sql("SELECT pattern, category FROM rules ORDER BY category, pattern", db)
        edited = st.data_editor(rules, num_rows="dynamic", hide_index=True, width="stretch", height=560, column_config={
            "pattern": "Regola", "category": st.column_config.SelectboxColumn("Categoria", options=categories())})
        if st.button("Salva e riapplica", type="primary", icon=":material/sync:"):
            db.execute("DELETE FROM rules")
            db.executemany("INSERT OR REPLACE INTO rules VALUES (?,?)",
                           [(money.rule_pattern(p), c) for p, c in edited.dropna().values if money.rule_pattern(p)])
            money.categorize(db)
            st.rerun()
    with t3:
        st.html('<p class="hint">Tetto di spesa mensile per categoria (anche una macro: include le sottocategorie). '
                'In Panoramica vedi quanto hai speso nel mese: verde fino all\'80%, giallo fino al 100%, rosso oltre.</p>')
        budgets = pd.read_sql("SELECT path, amount FROM budgets ORDER BY path", db)
        edited = st.data_editor(budgets, num_rows="dynamic", hide_index=True, width="stretch", column_config={
            "path": st.column_config.SelectboxColumn("Categoria", options=categories(), required=True, width="large"),
            "amount": st.column_config.NumberColumn("Al mese", format="euro", min_value=0, required=True)})
        a, b = st.columns(2)
        g_amount = a.number_input("Obiettivo di risparmio (€)", min_value=0, step=500,
                                  value=int(float(money.setting(db, "goal_amount", 5000))))
        g_date = b.date_input("Entro il", value=pd.Timestamp(money.setting(db, "goal_date", "2027-12-31")), format="DD/MM/YYYY")
        st.html(f'<p class="hint">Il ritmo esclude i movimenti con etichetta <b>{money.ONE_OFF}</b>: mettila (da Movimenti) '
                'sulle spese o entrate eccezionali, così la previsione resta realistica.</p>')
        if st.button("Salva budget", type="primary", icon=":material/save:"):
            money.set_setting(db, "goal_amount", g_amount)
            money.set_setting(db, "goal_date", g_date.isoformat())
            db.execute("DELETE FROM budgets")
            db.executemany("INSERT OR REPLACE INTO budgets VALUES (?,?)", edited.dropna().values.tolist())
            db.commit()
            st.rerun()


def importer():
    header("Importa", f"Metti gli estratti in <code>{money.INBOX}</code> (o trascinali qui): all'avvio vengono letti, "
                      f"verificati sui totali e archiviati per conto. Si parte dal {money.START[8:]}/"
                      f"{money.START[5:7]}/{money.START[:4]}. Tutto resta su questo computer.")
    for f in st.file_uploader("Estratti conto (PDF o CSV)", type=["pdf", "csv"], accept_multiple_files=True,
                              label_visibility="collapsed") or []:
        (money.INBOX / f.name).write_bytes(f.getvalue())
    if st.button("Leggi nuovi estratti", type="primary", icon=":material/refresh:"):
        st.session_state.imported = money.import_inbox(db)
    res = st.session_state.imported
    unknown = [n for n, v in res.items() if v is None]
    errors = {n: v for n, v in res.items() if isinstance(v, str)}
    new = sum(v for v in res.values() if isinstance(v, int))
    if unknown:
        st.warning("Formato non riconosciuto: " + ", ".join(unknown), icon=":material/help:")
    for n, e in errors.items():
        st.error(f"{n}: {e}", icon=":material/error:")
    if new:
        st.success(f"Importati {new} nuovi movimenti.", icon=":material/check:")
    r = money.reconcile(db)
    if r:
        with st.container(key="card_check"):
            ok = abs(r["gap"]) < 100
            card_title("Controllo di quadratura", "i movimenti spiegano davvero i soldi che hai?")
            rows([("account_balance", PALETTE[0], "Conti oggi meno conti al punto zero", f"{eur(r['cash_end'])} − {eur(r['cash_start'])}",
                   eur(r["cash_end"] - r["cash_start"]), None),
                  ("credit_card", PALETTE[1], "Meno debiti carta e rate (oggi − al punto zero)", f"{eur(r['debt_end'])} − {eur(r['debt_start'])}",
                   eur(-(r["debt_end"] - r["debt_start"])), None),
                  ("functions", PALETTE[2], "Entrate meno tutte le uscite registrate", "secondo i movimenti importati", eur(r["flows"]), None),
                  ("check_circle" if ok else "error", GOOD if ok else BAD, "Scarto", "sotto i 100 € è normale (arrotondamenti, storni)" if ok
                   else "c'è qualcosa che manca o è contato due volte: confronta mese per mese", eur(r["gap"]), None)])
    with st.container(key="card_files"):
        card_title("Estratti importati")
        rows([("credit_card" if acct.startswith("Nexi") else "account_balance", PALETTE[0], name, acct, f"{n} mov.", None)
              for name, acct, n in db.execute("SELECT name, account, rows FROM files WHERE account != 'Busta paga' ORDER BY name DESC")]
             or [("inbox", OTHER, "Nessun estratto", "", "", None)])


uncat = db.execute("SELECT COUNT(*) FROM tx WHERE category IS NULL").fetchone()[0]
st.logo(ICON, size="large")
pg = st.navigation({"": [
    st.Page(dashboard, title="Panoramica", icon=":material/space_dashboard:", default=True),
    st.Page(compare, title="Confronti", icon=":material/compare_arrows:", url_path="confronti"),
    st.Page(bills, title="Casa e bollette", icon=":material/bolt:", url_path="bollette"),
    st.Page(car, title="Auto", icon=":material/directions_car:", url_path="auto"),
    st.Page(salary, title="Stipendio", icon=":material/work:", url_path="stipendio"),
], "Altro": [
    st.Page(mortgage, title="Mutuo", icon=":material/house:", url_path="mutuo"),
    st.Page(tags, title="Etichette", icon=":material/sell:", url_path="etichette"),
    st.Page(deductions, title="Detrazioni 730", icon=":material/receipt:", url_path="detrazioni"),
    st.Page(category, title="Categoria", icon=":material/category:", url_path="categoria", visibility="hidden"),
], "Gestione": [
    st.Page(review, title=f"Da categorizzare ({uncat})" if uncat else "Da categorizzare", icon=":material/label:", url_path="review"),
    st.Page(transactions, title="Movimenti", icon=":material/receipt_long:", url_path="movimenti"),
    st.Page(importer, title="Importa", icon=":material/upload_file:", url_path="importa"),
    st.Page(settings, title="Categorie e regole", icon=":material/tune:", url_path="impostazioni"),
]})
st.sidebar.html('<p class="hint" style="margin-top:24px"><span class="ms" style="font-size:16px;vertical-align:-3px">lock</span>'
                ' 100% locale · nessun dato online</p>')
st.set_page_config(page_title=f"{pg.title} · Money", page_icon=ICON)  # own icon: no favicon fetched from Google
pg.run()
