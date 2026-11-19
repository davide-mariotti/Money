"use strict";
// Money's window. It talks to desktop.py through window.pywebview.api; nothing here touches the network.

const $ = id => document.getElementById(id);
const icon = (n, cls) => `<svg class="i ${cls || ""}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n] || ICONS.info}</svg>`;
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// ── words ────────────────────────────────────────────────────────────────
const TEXT = {
  it: {
    locale: "it-IT",
    local: "Tutto su questo PC",
    folder: "Apri la cartella dei dati",
    kicker: "Estratti conto · bollette · buste paga",
    title: 'I tuoi soldi, <span class="serif grad">messi in fila</span>',
    empty: "Archivio vuoto: si parte dai file qui sotto",
    facts: s => [`${num(s.tx)} movimenti`, s.first && `${month(s.first)} → ${month(s.last)}`, `${num(s.bills)} bollette`, `${num(s.payslips)} buste paga`],
    dropTitle: "Trascina qui i tuoi file",
    dropText: "Estratti conto e carte, movimenti in CSV, bollette, buste paga. Money capisce da solo cosa sono, controlla i totali e li mette in ordine. I tuoi file restano dove sono: lavora su una copia.",
    pick: "Scegli i file",
    reading: n => n === 1 ? "Lettura in corso…" : `Lettura di ${n} file in corso…`,
    status: { ok: "Letto", dup: "Già presente", unknown: "Formato non riconosciuto", error: "Non importato" },
    moves: n => n === 0 ? "nessun movimento nuovo" : n === 1 ? "1 movimento nuovo" : `${num(n)} movimenti nuovi`,
    bill: t => `Bolletta ${t}`, bills: { luce: "luce", gas: "gas", acqua: "acqua" },
    payslip: "Busta paga",
    dup: "Lo stesso file, o lo stesso periodo, c'è già.",
    unknown: "Non è tra i formati che Money legge già. Resta da parte nella cartella dei dati, non si perde.",
    failed: "Qualcosa è andato storto",
    kpi: {
      tx: ["Movimenti", s => s.first ? `dal ${month(s.first)} al ${month(s.last)}` : "nessuno ancora"],
      todo: ["Da categorizzare", () => "movimenti senza categoria"],
      bills: ["Bollette", () => "luce, gas e acqua"],
      payslips: ["Buste paga", () => "netto, tasse, ferie"],
    },
    fmtKicker: "Formati",
    fmtTitle: 'Quello che Money <span class="serif grad">sa già leggere</span>',
    fmtSide: "Ogni file viene controllato sui totali stampati. Se non tornano, non entra.",
    formats: ["Crédit Agricole · estratto e CSV", "Nexi · carta di credito", "Hype", "Revolut · CSV", "PayPal · CSV", "Eni Plenitude · luce e gas", "Acque SpA", "Buste paga Zucchetti"],
    fmtNote: "Le altre banche e gli altri fornitori arrivano con le prossime versioni. Intanto i file che Money non riconosce restano da parte.",
    footer: v => `Money ${v} · fatto da Davide Mariotti · niente internet, niente telemetria`,
  },
  en: {
    locale: "en-GB",
    local: "All on this PC",
    folder: "Open the data folder",
    kicker: "Bank statements · bills · payslips",
    title: 'Your money, <span class="serif grad">lined up</span>',
    empty: "Nothing here yet: start with the files below",
    facts: s => [`${num(s.tx)} transactions`, s.first && `${month(s.first)} → ${month(s.last)}`, `${num(s.bills)} bills`, `${num(s.payslips)} payslips`],
    dropTitle: "Drop your files here",
    dropText: "Bank and card statements, CSV transactions, bills, payslips. Money works out what they are, checks the totals and files them. Your files stay where they are: it works on a copy.",
    pick: "Choose files",
    reading: n => n === 1 ? "Reading…" : `Reading ${n} files…`,
    status: { ok: "Read", dup: "Already there", unknown: "Unknown format", error: "Not imported" },
    moves: n => n === 0 ? "no new transactions" : n === 1 ? "1 new transaction" : `${num(n)} new transactions`,
    bill: t => `${t} bill`, bills: { luce: "Electricity", gas: "Gas", acqua: "Water" },
    payslip: "Payslip",
    dup: "The same file, or the same period, is already there.",
    unknown: "Not one of the formats Money reads yet. It's kept aside in the data folder, nothing is lost.",
    failed: "Something went wrong",
    kpi: {
      tx: ["Transactions", s => s.first ? `${month(s.first)} to ${month(s.last)}` : "none yet"],
      todo: ["To categorise", () => "transactions with no category"],
      bills: ["Bills", () => "electricity, gas and water"],
      payslips: ["Payslips", () => "net pay, taxes, holidays"],
    },
    fmtKicker: "Formats",
    fmtTitle: 'What Money <span class="serif grad">already reads</span>',
    fmtSide: "Every file is checked against its printed totals. If they don't add up, it stays out.",
    formats: ["Crédit Agricole · statement and CSV", "Nexi · credit card", "Hype", "Revolut · CSV", "PayPal · CSV", "Eni Plenitude · power and gas", "Acque SpA", "Zucchetti payslips"],
    fmtNote: "Other banks and suppliers come with the next versions. Meanwhile, files Money doesn't recognise are kept aside.",
    footer: v => `Money ${v} · made by Davide Mariotti · no internet, no telemetry`,
  },
};

let T, api;
const num = n => new Intl.NumberFormat(T.locale).format(n || 0);
const month = iso => new Intl.DateTimeFormat(T.locale, { month: "short", year: "numeric" }).format(new Date(iso + "T00:00"));

// ── drawing ──────────────────────────────────────────────────────────────
function paint(init) {
  $("logo").innerHTML = icon("wallet");
  $("version").textContent = init.version;
  $("local").innerHTML = `<span class="dot"></span>${esc(T.local)}`;
  $("openFolder").innerHTML = icon("folder-open");
  $("openFolder").title = T.folder;
  $("kicker").textContent = T.kicker;
  $("title").innerHTML = T.title;
  $("dropIcon").innerHTML = icon("upload");
  $("dropTitle").textContent = T.dropTitle;
  $("dropText").textContent = T.dropText;
  $("pick").innerHTML = icon("files") + esc(T.pick);
  $("fmtHead").innerHTML = `<div><p class="kicker">${esc(T.fmtKicker)}</p><h2>${T.fmtTitle}</h2></div><p class="side">${esc(T.fmtSide)}</p>`;
  $("formats").innerHTML = T.formats.map(f => `<span class="chip">${icon("circle-check")}${esc(f)}</span>`).join("");
  $("fmtNote").innerHTML = icon("info") + `<span>${esc(T.fmtNote)}</span>`;
  $("footer").textContent = T.footer(init.version);
  stats(init.stats);
  document.querySelectorAll(".reveal").forEach((el, i) => { el.style.setProperty("--d", i * 90 + "ms"); requestAnimationFrame(() => el.classList.add("in")); });
}

function stats(s) {
  $("facts").innerHTML = s.tx || s.bills || s.payslips
    ? T.facts(s).filter(Boolean).map(f => `<span class="chip">${esc(f)}</span>`).join("")
    : `<span class="chip">${icon("info")}${esc(T.empty)}</span>`;
  const tiles = [["tx", "landmark", s.tx], ["todo", "tags", s.todo], ["bills", "zap", s.bills], ["payslips", "briefcase-business", s.payslips]];
  $("kpis").innerHTML = tiles.map(([k, ic, n]) =>
    `<div class="kpi spot"><div class="kpi-head"><span class="icon-tile">${icon(ic)}</span>${esc(T.kpi[k][0])}</div>` +
    `<div class="big">${num(n)}</div><p>${esc(T.kpi[k][1](s))}</p></div>`).join("");
}

function billType(stored) {
  const k = Object.keys(T.bills).find(t => stored.includes("_" + t));
  return k ? T.bills[k] : "";
}

function row(r) {
  let ic = "file-text", tile = "", chip = "ok", detail = "";
  if (r.status === "ok") {
    if (r.kind === "bill") { ic = r.stored.includes("_acqua") ? "droplet" : r.stored.includes("_gas") ? "flame" : "zap"; detail = T.bill(billType(r.stored)); }
    else if (r.kind === "payslip") { ic = "briefcase-business"; detail = T.payslip; }
    else { ic = r.kind === "card" ? "credit-card" : "landmark"; detail = `${r.account} · ${T.moves(r.new)}`; }
  } else if (r.status === "dup") { ic = "copy"; tile = "dim"; chip = ""; detail = T.dup; }
  else if (r.status === "unknown") { ic = "triangle-alert"; tile = "warm"; chip = "warm"; detail = T.unknown; }
  else { ic = "circle-x"; tile = "hot"; chip = "hot"; detail = r.msg || T.failed; }
  return `<div class="res"><span class="icon-tile sm ${tile}">${icon(ic)}</span>` +
    `<div class="what"><b>${esc(r.name)}</b><p>${esc(detail)}</p></div><span class="chip ${chip}">${esc(T.status[r.status])}</span></div>`;
}

// ── importing ────────────────────────────────────────────────────────────
async function run(count, job) {
  document.body.classList.add("busy");
  const pending = document.createElement("div");
  pending.className = "res";
  pending.innerHTML = `<span class="icon-tile sm dim spin">${icon("loader-circle")}</span><div class="what"><b>${esc(T.reading(count))}</b></div>`;
  $("results").prepend(pending);
  try {
    const out = await job();
    pending.outerHTML = out.results.map(row).join("");
    stats(out.stats);
  } catch (e) {
    pending.outerHTML = row({ name: T.failed, status: "error", msg: String(e && e.message || e) });
  } finally {
    document.body.classList.remove("busy");
  }
}

const read = f => new Promise((ok, ko) => {
  const r = new FileReader();
  r.onload = () => ok({ name: f.name, data: String(r.result).split(",")[1] || "" });
  r.onerror = () => ko(r.error);
  r.readAsDataURL(f);
});

let depth = 0;
const dragging = on => document.body.classList.toggle("dragging", on);
addEventListener("dragenter", e => { e.preventDefault(); depth++; dragging(true); });
addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; dragging(false); } });
addEventListener("dragover", e => e.preventDefault());  // without it WebView2 opens the file instead
addEventListener("drop", e => {
  e.preventDefault(); depth = 0; dragging(false);
  const files = [...e.dataTransfer.files];
  if (files.length && api) run(files.length, async () => api.import_files(await Promise.all(files.map(read))));
});

// card light that follows the pointer
addEventListener("pointermove", e => {
  const el = e.target.closest && e.target.closest(".spot");
  if (!el) return;
  const r = el.getBoundingClientRect();
  el.style.setProperty("--x", e.clientX - r.left + "px");
  el.style.setProperty("--y", e.clientY - r.top + "px");
});

async function start() {
  if (api) return;
  api = window.pywebview.api;
  const init = await api.init();
  T = TEXT[init.lang] || TEXT.en;
  document.documentElement.lang = init.lang;
  paint(init);
  $("drop").addEventListener("click", () => run(1, () => api.pick_files()));
  $("openFolder").addEventListener("click", () => api.open_folder());
}

if (window.pywebview && window.pywebview.api) start();
else addEventListener("pywebviewready", start);
