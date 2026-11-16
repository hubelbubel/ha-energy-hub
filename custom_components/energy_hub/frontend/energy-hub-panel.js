/*
 * Energy Hub – Panel für die Seitenleiste von Home Assistant.
 * Reines JavaScript ohne Build-Schritt und ohne externe Abhängigkeiten.
 *
 * Bereiche:
 *   Übersicht – der Tag in einem Satz, Strombilanz, Verbrauch je Stunde nach Herkunft, Auswertung der Woche
 *   Strom     – Bilanz jetzt, Kennwerte von heute, Verlauf von Netz, Batterie und Verbrauchern, Rangliste
 *   Wärme     – Lage der Heizung mit Anlagenschema, Verlauf, Logbuch und Regeln, Export
 */

const DOMAIN = "energy_hub";
const SVG_NS = "http://www.w3.org/2000/svg";
const RANGES = [
  { hours: 24, label: "24 Stunden", buckets: 288 },
  { hours: 48, label: "48 Stunden", buckets: 288 },
  { hours: 168, label: "7 Tage", buckets: 168 },
];
const DURATIONS = [
  { minutes: 60, label: "1 Stunde" },
  { minutes: 120, label: "2 Stunden" },
  { minutes: 240, label: "4 Stunden" },
  { minutes: 480, label: "8 Stunden" },
  { minutes: null, label: "bis ich es beende" },
];
const MODE_NAME = { normal: "Normalbetrieb", boost: "Anheben", setback: "Absenken" };
const SERIES = [
  { key: "flow", ent: "ent_flow", name: "Vorlauf", cls: "s-flow" },
  { key: "return", ent: "ent_return", name: "Rücklauf", cls: "s-return" },
  { key: "dhw", ent: "ent_dhw", name: "Warmwasser", cls: "s-dhw" },
  { key: "outdoor", ent: "ent_outdoor", name: "Außen", cls: "s-outdoor" },
];

/* ---------------------------------------------------------------- Helfer */

const nf0 = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const tfTime = new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit" });
const tfDay = new Intl.DateTimeFormat("de-DE", { weekday: "long", day: "numeric", month: "long" });
const tfShortDay = new Intl.DateTimeFormat("de-DE", { weekday: "short", day: "2-digit", month: "2-digit" });

const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const fmtW = (v) => (isNum(v) ? `${nf0.format(v)} W` : "–");
const fmtKw = (v) => (!isNum(v) ? "–" : Math.abs(v) < 1000 ? `${nf0.format(v)} W` : `${nf1.format(v / 1000)} kW`);
const fmtKwh = (v) => (isNum(v) ? `${nf1.format(v)} kWh` : "–");
const fmtC = (v) => (isNum(v) ? `${nf1.format(v)} °C` : "–");
const fmtClock = (iso) => (iso ? `${tfTime.format(new Date(iso))} Uhr` : "");
const hhmm = (text) => String(text || "").slice(0, 5);

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return el;
}

function s(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v !== null && v !== undefined) el.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined) continue;
    el.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return el;
}

function minutesSince(iso) {
  return iso ? Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000)) : null;
}

function niceTicks(min, max, count = 4) {
  if (!(max > min)) return [min];
  const raw = (max - min) / count;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((st) => st >= raw) || raw;
  const ticks = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-6; v += step) {
    ticks.push(Math.round(v * 1e6) / 1e6);
  }
  return ticks;
}

/* ---------------------------------------------------------------- Export */

export const EXPORT_RANGES = [
  { hours: 24, step: 60e3, label: "24 Stunden", detail: "ein Wert je Minute" },
  { hours: 168, step: 300e3, label: "7 Tage", detail: "ein Wert je 5 Minuten" },
  { hours: 720, step: 900e3, label: "30 Tage", detail: "ein Wert je 15 Minuten" },
];

const GAP_STATES = new Set(["", "unknown", "unavailable", "none", "None"]);
const isGap = (raw) => raw === null || raw === undefined || GAP_STATES.has(String(raw));

/**
 * Zeitgewichteter Mittelwert je Raster. Home Assistant speichert nur Änderungen,
 * deshalb gilt ein Wert so lange, bis der nächste kommt. Zeiten ohne gültigen
 * Wert (unbekannt, nicht verfügbar) zählen nicht mit.
 * rows: [[Millisekunden, Rohzustand]] aufsteigend; tEnd: bis wann Daten vorliegen.
 */
export function stepSeries(rows, t0, step, n, tEnd, toNumber = Number) {
  const out = new Array(n).fill(null);
  const read = (raw) => {
    if (isGap(raw)) return null;
    const v = toNumber(raw);
    return Number.isFinite(v) ? v : null;
  };
  let i = 0;
  let value = null;
  while (i < rows.length && rows[i][0] <= t0) value = read(rows[i++][1]);
  for (let b = 0; b < n; b++) {
    const start = t0 + b * step;
    const end = Math.min(start + step, tEnd);
    if (end <= start) break;
    let cursor = start;
    let area = 0;
    let covered = 0;
    while (i < rows.length && rows[i][0] < end) {
      const t = rows[i][0];
      if (value !== null) {
        area += value * (t - cursor);
        covered += t - cursor;
      }
      cursor = t;
      value = read(rows[i++][1]);
    }
    if (value !== null) {
      area += value * (end - cursor);
      covered += end - cursor;
    }
    if (covered > 0) out[b] = area / covered;
  }
  return out;
}

/** Textzustand am Ende jedes Rasters. */
export function stepText(rows, t0, step, n, tEnd) {
  const out = new Array(n).fill(null);
  let i = 0;
  let value = null;
  for (let b = 0; b < n; b++) {
    const start = t0 + b * step;
    if (start >= tEnd) break;
    const end = Math.min(start + step, tEnd);
    while (i < rows.length && rows[i][0] <= end) {
      const raw = rows[i++][1];
      value = isGap(raw) ? null : String(raw);
    }
    out[b] = value;
  }
  return out;
}

/** Für Ein/Aus-Zustände: Anteil der Zeit "on" (0 bis 1) und Einschaltvorgänge je Raster. */
export function stepBinary(rows, t0, step, n, tEnd) {
  const share = stepSeries(rows, t0, step, n, tEnd, (raw) => (raw === "on" ? 1 : raw === "off" ? 0 : NaN));
  const starts = share.map((v) => (v === null ? null : 0));
  let prev = null;
  for (const [t, raw] of rows) {
    if (raw === "on" && prev === "off" && t > t0) {
      const b = Math.floor((t - t0) / step);
      if (b < n && starts[b] !== null) starts[b] += 1;
    }
    if (raw === "on" || raw === "off") prev = raw;
  }
  return { share, starts };
}

/**
 * Zeitabschnitte, in denen ein Zustand aktiv ist, beschnitten auf t0 bis tEnd.
 * began = der Abschnitt hat innerhalb des Zeitraums begonnen; open = er läuft bei tEnd noch.
 * Kurze Ausfälle des Sensors (nicht verfügbar) trennen einen Abschnitt nicht.
 */
export function episodes(rows, isActive, t0, tEnd) {
  const out = [];
  let start = null;
  for (const [t, raw] of rows) {
    if (isGap(raw) || t >= tEnd) continue;
    const active = Boolean(isActive(raw));
    if (active && start === null) start = t;
    else if (!active && start !== null) {
      if (t > t0) out.push({ start: Math.max(start, t0), end: t, began: start > t0, open: false });
      start = null;
    }
  }
  if (start !== null) out.push({ start: Math.max(start, t0), end: tEnd, began: start > t0, open: true });
  return out;
}

/** Vergleicht einen Zustand mit den hinterlegten Werten, z. B. "Regenerativ, 14". */
export function matcher(values) {
  const wanted = new Set(String(values ?? "").split(",").map((v) => v.trim().toLowerCase()).filter(Boolean));
  return (raw) => wanted.has(String(raw).trim().toLowerCase());
}

/** Ortszeit mit Zeitzonenversatz, z. B. 2026-11-16T12:05:00+01:00. */
export function isoLocal(ms) {
  const d = new Date(ms);
  const p = (v, l = 2) => String(v).padStart(l, "0");
  const off = -d.getTimezoneOffset();
  const sign = off < 0 ? "-" : "+";
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
    + `${sign}${p(Math.floor(Math.abs(off) / 60))}:${p(Math.abs(off) % 60)}`;
}

export function csvCell(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return Number.isFinite(v) ? String(Math.round(v * 1000) / 1000) : "";
  const text = String(v);
  return /[",\r\n]/.test(text) || text !== text.trim() ? `"${text.replaceAll('"', '""')}"` : text;
}

export function entryTitle(e) {
  if (e.kind === "switch") {
    if (e.to === "boost") return "Angehoben";
    if (e.to === "setback") return "Abgesenkt";
    if (e.from === "boost") return "Anheben beendet";
    if (e.from === "setback") return "Absenken beendet";
    return "Normalbetrieb";
  }
  return { override: "Handbetrieb", automation: "Automatik", error: "Fehler", reapply: "Erneut gesetzt" }[e.kind] || "Hinweis";
}

const RESULT_TEXT = { sent: "gesendet", simulated: "nur protokolliert", failed: "fehlgeschlagen" };

/**
 * Baut die CSV-Datei: Kopfzeilen mit "#" (Regeln, Zuordnung der Spalten), dann
 * eine Zeile je Raster. Logbuch-Einträge stehen in der Spalte "ereignisse" der
 * Zeile, in deren Raster sie fallen. Leere Zeilen am Anfang und Ende entfallen.
 * columns: [{ name, entity, unit, values: [n Werte] }]
 */
export function buildExport({ version, created, t0, step, n, columns, log, settings }) {
  const events = new Array(n).fill(null);
  for (const e of [...(log || [])].sort((a, b) => a.ts.localeCompare(b.ts))) {
    const t = new Date(e.ts).getTime();
    const b = Math.floor((t - t0) / step);
    if (!(b >= 0 && b < n)) continue;
    const result = RESULT_TEXT[e.result] ? ` [${RESULT_TEXT[e.result]}]` : "";
    const detail = e.detail ? ` (${e.detail})` : "";
    const line = `${isoLocal(t).slice(11, 19)} ${entryTitle(e)}${result}: ${e.text}${detail}`;
    events[b] = events[b] ? `${events[b]} | ${line}` : line;
  }
  const filled = (b) => events[b] !== null || columns.some((col) => col.values[b] !== null && col.values[b] !== undefined);
  let first = 0;
  let last = n - 1;
  while (first < n && !filled(first)) first++;
  while (last >= first && !filled(last)) last--;
  const rowCount = Math.max(0, last - first + 1);

  const meta = [
    "Energy Hub Export",
    `version: ${version}`,
    `erstellt: ${isoLocal(created)}`,
    `von: ${rowCount ? isoLocal(t0 + first * step) : ""}`,
    `bis: ${rowCount ? isoLocal(Math.min(created, t0 + (last + 1) * step)) : ""}`,
    `raster_sekunden: ${step / 1000}`,
    "zeit: Beginn des Rasters in Ortszeit",
    "zahlen: zeitgewichteter Mittelwert im Raster, Dezimalpunkt; leer = kein Wert aufgezeichnet",
    "texte: Zustand am Ende des Rasters",
    "_anteil: Anteil der Zeit im Zustand Ein (0 bis 1); _starts: Einschaltvorgänge im Raster",
    "pv_ueberschuss_w: positiv = Überschuss",
    "regelzustand: normal, boost (angehoben) oder setback (abgesenkt)",
    "ereignisse: Logbuch-Einträge im Raster, mehrere durch | getrennt",
    ...Object.entries(settings || {}).map(([k, v]) => `einstellung.${k}: ${v ?? ""}`),
    ...columns.map((col) => `spalte.${col.name}: ${col.entity || "nicht hinterlegt"}${col.unit ? ` [${col.unit}]` : ""}`),
  ];
  const lines = meta.map((m) => `# ${m.replace(/[\r\n]+/g, " ")}`);
  lines.push(["zeit", ...columns.map((col) => col.name), "ereignisse"].map(csvCell).join(","));
  for (let b = first; b <= last; b++) {
    lines.push([isoLocal(t0 + b * step), ...columns.map((col) => col.values[b]), events[b]].map(csvCell).join(","));
  }
  return { csv: `\ufeff${lines.join("\r\n")}\r\n`, rows: rowCount, columns: columns.length + 2 };
}

/* ------------------------------------------------------- Effizienz-Export */

/**
 * Läuft über mehrere Zustandsverläufe gleichzeitig und ruft onSegment für jeden
 * Abschnitt auf, in dem sich kein Wert ändert. Abschnitte enden außerdem an den
 * Rastergrenzen. values[i] ist der Rohzustand der i-ten Reihe (null = unbekannt).
 */
export function sweep(series, t0, tEnd, step, onSegment) {
  const k = series.length;
  const idx = new Array(k).fill(0);
  const values = new Array(k).fill(null);
  const advance = (limit) => {
    for (let i = 0; i < k; i++) {
      const rows = series[i];
      while (idx[i] < rows.length && rows[idx[i]][0] <= limit) values[i] = rows[idx[i]++][1];
    }
  };
  advance(t0);
  let cursor = t0;
  while (cursor < tEnd) {
    const bucket = Math.floor((cursor - t0) / step);
    let next = Math.min(tEnd, t0 + (bucket + 1) * step);
    for (let i = 0; i < k; i++) {
      const rows = series[i];
      if (idx[i] < rows.length && rows[idx[i]][0] < next) next = rows[idx[i]][0];
    }
    onSegment(bucket, cursor, next, values);
    advance(next);
    cursor = next;
  }
}

export const EFF_KEYS = [
  "comp", "status", "mode", "outdoor", "flow", "ret", "retTarget", "dhw", "dhwTarget",
  "pEl", "pHeat", "surplus", "heater", "second", "eEl", "eHeat", "eDhw", "eEnv",
  "storage", "fireplace", "lock",
];
const EFF_COUNTERS = ["eEl", "eHeat", "eDhw", "eEnv"];

export const HOUR_HEADER = [
  "zeit", "aussen_c", "vorlauf_lauf_c", "vorlauf_max_c", "ruecklauf_lauf_c", "ruecklauf_soll_c",
  "warmwasser_c", "warmwasser_soll_c", "verdichter_min", "verdichter_starts", "status_min",
  "heizstab_min", "zweiter_waermeerzeuger_min", "strom_aus_leistung_kwh", "waerme_aus_leistung_kwh",
  "strom_zaehler_kwh", "waerme_heizen_zaehler_kwh", "waerme_warmwasser_zaehler_kwh",
  "umweltenergie_zaehler_kwh", "pv_ueberschuss_kwh", "netzbezug_kwh", "angehoben_min", "abgesenkt_min",
  "speicher_c", "kamin_c", "kamin_min", "speicher_bereit_min", "sperre_regenerativ_min", "speicher_entnahmen",
];
export const DRAW_HEADER = [
  "start", "ende", "dauer_min", "speicher_start_c", "speicher_ende_c", "aussen_c", "hinweis",
];
export const CYCLE_HEADER = [
  "start", "ende", "dauer_min", "pause_davor_min", "betriebsart", "status_min", "regelzustand",
  "aussen_c", "vorlauf_c", "vorlauf_max_c", "ruecklauf_c", "warmwasser_start_c", "warmwasser_ende_c",
  "strom_kwh", "waerme_kwh", "heizstab_min", "hinweis",
];

const minutes = (ms) => Math.round(ms / 6000) / 10;
const mean = (pair) => (pair[1] > 0 ? pair[0] / pair[1] : null);
const statusText = (map) => [...map.entries()].sort((a, b) => b[1] - a[1])
  .map(([name, ms]) => `${name}=${minutes(ms)}`).join(";") || null;
const dominant = (map) => [...map.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;

/**
 * Wertet die Zustandsverläufe für die Effizienz aus.
 * data: { comp: [[ms, Zustand]], ... } mit den Schlüsseln aus EFF_KEYS (fehlende = nicht hinterlegt)
 * factors: Umrechnung je Schlüssel in W bzw. kWh (z. B. kW -> 1000)
 * Liefert Stundenwerte und eine Zeile je Verdichterlauf.
 */
export function analyseEfficiency(data, factors, t0, tEnd, step = 3600e3, opts = {}) {
  const regen = opts.regen || (() => false);
  const fireOn = opts.fireplaceOnC ?? null;
  const readyFixed = opts.storageReadyC ?? null;
  const readyDelta = opts.storageReadyDeltaK ?? null;
  const I = Object.fromEntries(EFF_KEYS.map((key, i) => [key, i]));
  const series = EFF_KEYS.map((key) => data[key] || []);
  const has = Object.fromEntries(EFF_KEYS.map((key) => [key, Boolean(data[key])]));
  const num = (values, key) => {
    const raw = values[I[key]];
    if (isGap(raw)) return null;
    const v = Number(raw) * (factors?.[key] ?? 1);
    return Number.isFinite(v) ? v : null;
  };
  const add = (pair, v, dt) => {
    if (v === null) return;
    pair[0] += v * dt;
    pair[1] += dt;
  };
  const n = Math.max(0, Math.ceil((tEnd - t0) / step));
  const hours = Array.from({ length: n }, () => ({
    outdoor: [0, 0], dhw: [0, 0], retTarget: [0, 0], dhwTarget: [0, 0], flowOn: [0, 0], retOn: [0, 0],
    flowMax: null, compMs: null, starts: null, status: new Map(), heaterMs: null, secondMs: null,
    elWh: null, heatWh: null, pvWh: null, gridWh: null, boostMs: null, setbackMs: null, end: {}, first: {},
    storage: [0, 0], fireplace: [0, 0], fireMs: null, readyMs: null, drawMs: null, draws: null,
  }));
  const draws = [];
  let draw = null;
  let drawState = null;
  const closeDraw = (end, note) => {
    const d = draw;
    draw = null;
    draws.push([
      isoLocal(d.start), isoLocal(end), minutes(end - d.start), d.storageStart, d.storageEnd, mean(d.outdoor),
      [d.note, note].filter(Boolean).join("; ") || null,
    ]);
  };
  const cycles = [];
  let cycle = null;
  let compState = null;
  let lastEnd = null;

  const closeCycle = (end, note) => {
    const c = cycle;
    cycle = null;
    lastEnd = end;
    cycles.push([
      isoLocal(c.start), isoLocal(end), minutes(end - c.start),
      c.pause === null ? null : minutes(c.pause), dominant(c.status), statusText(c.status), dominant(c.mode),
      mean(c.outdoor), mean(c.flow), c.flowMax, mean(c.ret), c.dhwStart, c.dhwEnd,
      c.elWh === null ? null : c.elWh / 1000, c.heatWh === null ? null : c.heatWh / 1000,
      c.heaterMs === null ? null : minutes(c.heaterMs), [c.note, note].filter(Boolean).join("; ") || null,
    ]);
  };

  sweep(series, t0, tEnd, step, (b, a, e, values) => {
    const dt = e - a;
    const h = hours[b];
    const raw = values[I.comp];
    if (raw === "on" || raw === "off") {
      if (raw === "on" && !cycle) {
        if (compState === "off") h.starts = (h.starts ?? 0) + 1;
        cycle = {
          start: a, pause: lastEnd === null ? null : a - lastEnd, note: compState === null ? "Beginn vor dem Exportzeitraum" : null,
          outdoor: [0, 0], flow: [0, 0], ret: [0, 0], flowMax: null, status: new Map(), mode: new Map(),
          dhwStart: null, dhwEnd: null, elWh: null, heatWh: null, heaterMs: null,
        };
      }
      if (raw === "off" && cycle) closeCycle(a, null);
      compState = raw;
    }
    const on = compState === "on";
    if (compState !== null) {
      h.compMs = (h.compMs ?? 0) + (on ? dt : 0);
      h.starts ??= 0;
    }
    const outdoor = num(values, "outdoor");
    const flow = num(values, "flow");
    const ret = num(values, "ret");
    const dhw = num(values, "dhw");
    const pEl = num(values, "pEl");
    const pHeat = num(values, "pHeat");
    const surplus = num(values, "surplus");
    const status = values[I.status];
    const mode = values[I.mode];
    const heater = values[I.heater];
    const second = values[I.second];

    add(h.outdoor, outdoor, dt);
    add(h.dhw, dhw, dt);
    add(h.retTarget, num(values, "retTarget"), dt);
    add(h.dhwTarget, num(values, "dhwTarget"), dt);
    if (!isGap(status)) h.status.set(status, (h.status.get(status) || 0) + dt);
    if (heater === "on" || heater === "off") h.heaterMs = (h.heaterMs ?? 0) + (heater === "on" ? dt : 0);
    if (second === "on" || second === "off") h.secondMs = (h.secondMs ?? 0) + (second === "on" ? dt : 0);
    if (pEl !== null) h.elWh = (h.elWh ?? 0) + (pEl * dt) / 3.6e6;
    if (pHeat !== null) h.heatWh = (h.heatWh ?? 0) + (pHeat * dt) / 3.6e6;
    if (surplus !== null) {
      h.pvWh = (h.pvWh ?? 0) + (Math.max(0, surplus) * dt) / 3.6e6;
      h.gridWh = (h.gridWh ?? 0) + (Math.max(0, -surplus) * dt) / 3.6e6;
    }
    if (!isGap(mode)) {
      h.boostMs = (h.boostMs ?? 0) + (mode === "boost" ? dt : 0);
      h.setbackMs = (h.setbackMs ?? 0) + (mode === "setback" ? dt : 0);
    }
    const storage = num(values, "storage");
    const fireplace = num(values, "fireplace");
    const lock = values[I.lock];
    add(h.storage, storage, dt);
    add(h.fireplace, fireplace, dt);
    if (fireplace !== null && fireOn !== null) h.fireMs = (h.fireMs ?? 0) + (fireplace >= fireOn ? dt : 0);
    if (storage !== null && readyFixed !== null) {
      // Bereit wie im Regler: Rücklaufsoll plus Differenz, sonst die feste Ersatz-Schwelle
      const target = readyDelta === null ? null : num(values, "retTarget");
      const limit = target === null ? readyFixed : target + readyDelta;
      h.readyMs = (h.readyMs ?? 0) + (storage >= limit ? dt : 0);
    }
    if (!isGap(lock)) {
      const active = Boolean(regen(lock));
      if (active && !draw) {
        if (drawState === false) h.draws = (h.draws ?? 0) + 1;
        draw = {
          start: a, storageStart: null, storageEnd: null, outdoor: [0, 0],
          note: drawState === null ? "Beginn vor dem Exportzeitraum" : null,
        };
      }
      if (!active && draw) closeDraw(a, null);
      drawState = active;
    }
    if (drawState !== null) {
      h.drawMs = (h.drawMs ?? 0) + (drawState ? dt : 0);
      h.draws ??= 0;
    }
    if (draw) {
      add(draw.outdoor, outdoor, dt);
      if (storage !== null) {
        draw.storageStart ??= storage;
        draw.storageEnd = storage;
      }
    }
    for (const key of EFF_COUNTERS) {
      const v = num(values, key);
      if (v === null) continue;
      h.first[key] ??= v;
      h.end[key] = v;
    }
    if (on) {
      add(h.flowOn, flow, dt);
      add(h.retOn, ret, dt);
      if (flow !== null) h.flowMax = h.flowMax === null ? flow : Math.max(h.flowMax, flow);
    }
    if (on && cycle) {
      const c = cycle;
      add(c.outdoor, outdoor, dt);
      add(c.flow, flow, dt);
      add(c.ret, ret, dt);
      if (flow !== null) c.flowMax = c.flowMax === null ? flow : Math.max(c.flowMax, flow);
      if (!isGap(status)) c.status.set(status, (c.status.get(status) || 0) + dt);
      if (!isGap(mode)) c.mode.set(mode, (c.mode.get(mode) || 0) + dt);
      if (dhw !== null) {
        c.dhwStart ??= dhw;
        c.dhwEnd = dhw;
      }
      if (pEl !== null) c.elWh = (c.elWh ?? 0) + (pEl * dt) / 3.6e6;
      if (pHeat !== null) c.heatWh = (c.heatWh ?? 0) + (pHeat * dt) / 3.6e6;
      if (heater === "on" || heater === "off") c.heaterMs = (c.heaterMs ?? 0) + (heater === "on" ? dt : 0);
    }
  });
  if (cycle) closeCycle(tEnd, "läuft bei Exportende noch");
  if (draw) closeDraw(tEnd, "läuft bei Exportende noch");

  const delta = (b, key) => {
    const end = hours[b].end[key];
    const before = b > 0 ? hours[b - 1].end[key] ?? hours[b].first[key] : hours[b].first[key];
    return end === undefined || before === undefined || end < before ? null : end - before;
  };
  const kwh = (wh) => (wh === null ? null : wh / 1000);
  const min = (ms) => (ms === null ? null : minutes(ms));
  const hourRows = hours.map((h, b) => [
    isoLocal(t0 + b * step), mean(h.outdoor), mean(h.flowOn), h.flowMax, mean(h.retOn), mean(h.retTarget),
    mean(h.dhw), mean(h.dhwTarget), min(h.compMs), h.starts, statusText(h.status),
    min(h.heaterMs), min(h.secondMs), kwh(h.elWh), kwh(h.heatWh),
    delta(b, "eEl"), delta(b, "eHeat"), delta(b, "eDhw"), delta(b, "eEnv"),
    kwh(h.pvWh), kwh(h.gridWh), min(h.boostMs), min(h.setbackMs),
    mean(h.storage), mean(h.fireplace), min(h.fireMs), min(h.readyMs), min(h.drawMs), h.draws,
  ]);
  return { hourRows, cycleRows: cycles, drawRows: draws, has };
}

/** CSV mit drei Tabellen: Stundenwerte, Verdichterläufe, Speicherentnahmen. Leere Stunden am Rand entfallen. */
export function buildEfficiencyExport({ version, created, t0, step, analysis, settings, entities }) {
  const { hourRows, cycleRows, drawRows = [] } = analysis;
  const filled = (row) => row.slice(1).some((v) => v !== null && v !== undefined);
  let first = 0;
  let last = hourRows.length - 1;
  while (first <= last && !filled(hourRows[first])) first++;
  while (last >= first && !filled(hourRows[last])) last--;
  const rows = hourRows.slice(first, last + 1);
  const meta = [
    "Energy Hub Effizienz-Export",
    `version: ${version}`,
    `erstellt: ${isoLocal(created)}`,
    `von: ${rows.length ? isoLocal(t0 + first * step) : ""}`,
    `bis: ${rows.length ? isoLocal(Math.min(created, t0 + (last + 1) * step)) : ""}`,
    "aufbau: drei Tabellen, jede beginnt mit einer Zeile '# tabelle: name'",
    "zahlen: Dezimalpunkt; leer = kein Wert aufgezeichnet oder Sensor nicht hinterlegt",
    "mittelwerte: zeitgewichtet; _lauf_ = nur während der Verdichter läuft",
    "_min: Minuten in der Stunde; status_min: Minuten je Betriebsstatus als name=minuten, getrennt durch ;",
    "strom_aus_leistung_kwh, waerme_aus_leistung_kwh: aus den Leistungs-Sensoren aufsummiert",
    "_zaehler_kwh: Zunahme des Zähler-Sensors in der Stunde",
    "pv_ueberschuss_kwh: aufsummierter positiver Anteil des Überschuss-Sensors; netzbezug_kwh: aufsummierter negativer Anteil",
    "verdichterlaeufe: eine Zeile je Lauf; betriebsart = Betriebsstatus mit dem größten Zeitanteil; strom_kwh und waerme_kwh aus den Leistungs-Sensoren",
    "kamin_min: Minuten mit Kamin über der Schwelle",
    "speicher_bereit_min: Minuten mit Speicher mindestens einstellung.storage_ready_delta_k über ruecklauf_soll; ohne Rücklaufsoll gilt einstellung.storage_ready_c",
    "sperre_regenerativ_min: Minuten, in denen die Wärmepumpe gesperrt war, weil der Speicher liefert; speicher_entnahmen: Beginne solcher Abschnitte",
    "speicherentnahmen: eine Zeile je Abschnitt mit Sperre Regenerativ. Wärme aus dem Speicher steht nicht in den Wärmemengen der Wärmepumpe",
    ...Object.entries(entities || {}).map(([k, v]) => `entitaet.${k}: ${v || "nicht hinterlegt"}`),
    ...Object.entries(settings || {}).map(([k, v]) => `einstellung.${k}: ${v ?? ""}`),
  ];
  const line = (cells) => cells.map(csvCell).join(",");
  const lines = [
    ...meta.map((m) => `# ${m.replace(/[\r\n]+/g, " ")}`),
    "# tabelle: stundenwerte",
    line(HOUR_HEADER), ...rows.map(line),
    "",
    "# tabelle: verdichterlaeufe",
    line(CYCLE_HEADER), ...cycleRows.map(line),
    "",
    "# tabelle: speicherentnahmen",
    line(DRAW_HEADER), ...drawRows.map(line),
  ];
  return { csv: `\ufeff${lines.join("\r\n")}\r\n`, rows: rows.length, cycles: cycleRows.length, draws: drawRows.length };
}

/* ----------------------------------------------------------------- Strom */

const clamp01 = (v) => Math.min(1, Math.max(0, v));
const fmtPct = (v) => (isNum(v) ? `${nf0.format(v * 100)} %` : "–");
const fmtDur = (min) => (min >= 60 ? `${Math.floor(min / 60)} h ${Math.round(min % 60)} min` : `${Math.round(min)} min`);

/** Verteilt Statistik-Zeilen [[Startzeit, Mittelwert]] auf ein festes Raster. */
export function rowsToGrid(rows, t0, step, n) {
  const sum = new Array(n).fill(0);
  const cnt = new Array(n).fill(0);
  for (const [t, v] of rows) {
    const b = Math.floor((t - t0) / step);
    if (b < 0 || b >= n || !isNum(v)) continue;
    sum[b] += v;
    cnt[b] += 1;
  }
  return sum.map((total, b) => (cnt[b] ? total / cnt[b] : null));
}

/**
 * Strombilanz je Raster aus den Leistungs-Sensoren (alles in Watt).
 * raw: { grid, pv, battery, house, wp, wallbox, consumers: [..] } als gleich lange Reihen, null = unbekannt.
 * Liefert Bezug/Einspeisung, Laden/Entladen, Verbrauch und woher der Verbrauch gedeckt wurde.
 * Ohne eigenen Verbrauchs-Sensor gilt: Verbrauch = PV + Bezug - Einspeisung + Entladen - Laden.
 */
export function energyBalance(raw, signs = {}) {
  const lists = [raw.grid, raw.pv, raw.battery, raw.house, raw.wp, raw.wallbox, ...(raw.consumers || [])];
  const n = Math.max(0, ...lists.filter(Boolean).map((a) => a.length));
  const gs = signs.gridSign === "export_positive" ? -1 : 1;
  const bs = signs.batterySign === "charge_positive" ? -1 : 1;
  const at = (arr, b) => (arr && isNum(arr[b]) ? arr[b] : null);
  const pos = (v) => (v === null ? null : Math.max(0, v));
  const keys = ["imp", "exp", "pv", "dis", "chg", "cons", "fromPv", "fromBat", "fromGrid", "wp", "wallbox", "small", "rest"];
  const out = Object.fromEntries(keys.map((k) => [k, new Array(n).fill(null)]));
  out.consumers = (raw.consumers || []).map(() => new Array(n).fill(null));
  for (let b = 0; b < n; b++) {
    const g = at(raw.grid, b);
    const bt = at(raw.battery, b);
    const imp = pos(g === null ? null : gs * g);
    const exp = pos(g === null ? null : -gs * g);
    const pv = pos(at(raw.pv, b));
    const dis = pos(bt === null ? null : bs * bt);
    const chg = pos(bt === null ? null : -bs * bt);
    let cons = pos(at(raw.house, b));
    if (cons === null && (imp !== null || pv !== null || dis !== null)) {
      cons = Math.max(0, (pv ?? 0) + (imp ?? 0) - (exp ?? 0) + (dis ?? 0) - (chg ?? 0));
    }
    const wp = pos(at(raw.wp, b));
    const wallbox = pos(at(raw.wallbox, b));
    let small = null;
    (raw.consumers || []).forEach((arr, i) => {
      const v = pos(at(arr, b));
      out.consumers[i][b] = v;
      if (v !== null) small = (small ?? 0) + v;
    });
    out.imp[b] = imp;
    out.exp[b] = exp;
    out.pv[b] = pv;
    out.dis[b] = dis;
    out.chg[b] = chg;
    out.cons[b] = cons;
    out.wp[b] = wp;
    out.wallbox[b] = wallbox;
    out.small[b] = small;
    if (cons !== null) {
      const fromBat = Math.min(dis ?? 0, cons);
      const fromGrid = Math.min(imp ?? 0, cons - fromBat);
      out.fromBat[b] = fromBat;
      out.fromGrid[b] = fromGrid;
      out.fromPv[b] = Math.max(0, cons - fromBat - fromGrid);
      out.rest[b] = Math.max(0, cons - (wp ?? 0) - (wallbox ?? 0) - (small ?? 0));
    }
  }
  return out;
}

/**
 * Energie in kWh über die Raster i0 bis i1, dazu Eigenverbrauch und Autarkie.
 * Eigenverbrauch = Anteil des Solarstroms, der nicht eingespeist wurde.
 * Autarkie = Anteil des Verbrauchs, der nicht aus dem Netz kam.
 */
export function energyTotals(bal, stepMs, i0 = 0, i1 = bal.cons.length) {
  const factor = stepMs / 3.6e9;
  const sum = (arr) => {
    let total = 0;
    let known = false;
    for (let b = Math.max(0, i0); b < Math.min(arr.length, i1); b++) {
      if (!isNum(arr[b])) continue;
      total += arr[b];
      known = true;
    }
    return known ? total * factor : null;
  };
  const t = {};
  for (const key of ["imp", "exp", "pv", "dis", "chg", "cons", "fromPv", "fromBat", "fromGrid", "wp", "wallbox", "small", "rest"]) {
    t[key] = sum(bal[key]);
  }
  t.consumers = bal.consumers.map(sum);
  t.selfUse = t.pv > 0 && t.exp !== null ? clamp01((t.pv - t.exp) / t.pv) : null;
  t.autarky = t.cons > 0 && t.imp !== null ? clamp01(1 - t.imp / t.cons) : null;
  return t;
}

/** Für einen Tag: je Stunde, woher der Verbrauch kam (kWh), dazu die PV-Erzeugung. */
export function hourlyMix(bal, t0, stepMs, dayStart) {
  const hours = Array.from({ length: 24 }, () => ({ fromPv: 0, fromBat: 0, fromGrid: 0, pv: 0, known: false }));
  const factor = stepMs / 3.6e9;
  for (let b = 0; b < bal.cons.length; b++) {
    const t = t0 + b * stepMs;
    if (t < dayStart || t >= dayStart + 86400e3 || bal.cons[b] === null) continue;
    const h = hours[Math.min(23, Math.floor((t - dayStart) / 3600e3))];
    h.known = true;
    h.fromPv += bal.fromPv[b] * factor;
    h.fromBat += bal.fromBat[b] * factor;
    h.fromGrid += bal.fromGrid[b] * factor;
    h.pv += (bal.pv[b] ?? 0) * factor;
  }
  return hours;
}

/**
 * Auffälligkeiten beim Strom aus der Bilanz eines Zeitraums (gedacht für 7 Tage).
 * Jede Aussage nennt ihre Zahlen. tone: "warn" = fällt auf, "good" = läuft gut, "info" = zur Einordnung.
 * names: { consumers: [..], wallbox: "Wallbox" }
 */
export function powerFindings(bal, soc, names, stepMs, t0) {
  const out = [];
  const n = bal.cons.length;
  const total = energyTotals(bal, stepMs);
  const factor = stepMs / 3.6e9;
  const kwh = (v) => `${nf1.format(v)} kWh`;
  if (!(total.cons > 0)) return out;

  if (total.autarky !== null) {
    out.push(total.autarky >= 0.6
      ? { tone: "good", area: "Strom", title: "Das Haus versorgt sich überwiegend selbst",
          text: `${fmtPct(total.autarky)} des Verbrauchs kamen vom Dach oder aus der Batterie. Aus dem Netz kamen ${kwh(total.imp)} von ${kwh(total.cons)}.` }
      : { tone: "info", area: "Strom", title: `Autarkie ${fmtPct(total.autarky)}`,
          text: `Von ${kwh(total.cons)} Verbrauch kamen ${kwh(total.imp)} aus dem Netz.` });
  }
  if (total.selfUse !== null && total.pv >= 1) {
    if (total.selfUse >= 0.8) {
      out.push({ tone: "good", area: "Strom", title: "Fast aller Solarstrom bleibt im Haus",
        text: `Von ${kwh(total.pv)} vom Dach wurden ${fmtPct(total.selfUse)} selbst genutzt oder gespeichert.` });
    } else if (total.selfUse < 0.5) {
      out.push({ tone: "warn", area: "Strom", title: "Viel Solarstrom geht ins Netz",
        text: `Von ${kwh(total.pv)} vom Dach wurden ${kwh(total.exp)} eingespeist. Selbst genutzt wurden ${fmtPct(total.selfUse)}.` });
    }
  }

  // Batterie: Einspeisung trotz Platz, Netzbezug trotz Ladung
  if (soc && total.exp !== null && total.imp !== null) {
    let exportLow = 0;
    let importHigh = 0;
    for (let b = 0; b < n; b++) {
      if (!isNum(soc[b])) continue;
      if (soc[b] < 95) exportLow += (bal.exp[b] ?? 0) * factor;
      if (soc[b] > 20) importHigh += (bal.imp[b] ?? 0) * factor;
    }
    if (exportLow >= 1 && exportLow >= 0.2 * total.exp) {
      out.push({ tone: "warn", area: "Strom", title: "Eingespeist, obwohl die Batterie nicht voll war",
        text: `${kwh(exportLow)} gingen ins Netz, während der Ladestand unter 95 % lag. Das passiert, wenn mehr Überschuss da ist, als die Batterie aufnehmen kann, oder wenn ihre Regelung nachhinkt.` });
    }
    if (importHigh >= 1 && importHigh >= 0.2 * total.imp) {
      out.push({ tone: "warn", area: "Strom", title: "Netzbezug, obwohl die Batterie geladen war",
        text: `${kwh(importHigh)} kamen aus dem Netz, während der Ladestand über 20 % lag. Das passiert, wenn große Verbraucher mehr ziehen, als die Batterie abgeben kann.` });
    }
  }

  // Grundlast: Verbrauch nachts ohne Wärmepumpe und Wallbox
  const night = [];
  for (let b = 0; b < n; b++) {
    const hour = new Date(t0 + b * stepMs).getHours();
    if (hour < 1 || hour >= 5 || bal.cons[b] === null) continue;
    night.push(Math.max(0, bal.cons[b] - (bal.wp[b] ?? 0) - (bal.wallbox[b] ?? 0)));
  }
  if (night.length >= 12) {
    night.sort((a, b) => a - b);
    const base = night[Math.floor(night.length / 2)];
    out.push({ tone: "info", area: "Strom", title: `Grundlast nachts ${nf0.format(base)} W`,
      text: `Zwischen 1 und 5 Uhr braucht das Haus ohne Wärmepumpe und Wallbox im Mittel ${nf0.format(base)} W. Über den Tag sind das ${kwh((base * 24) / 1000)}.` });
  }

  // Wärmepumpe: wie viel davon das Dach zeitgleich liefern konnte
  if (total.wp >= 1 && total.pv !== null) {
    let solar = 0;
    for (let b = 0; b < n; b++) solar += Math.min(bal.wp[b] ?? 0, bal.pv[b] ?? 0) * factor;
    const share = clamp01(solar / total.wp);
    out.push({ tone: share >= 0.5 ? "good" : "info", area: "Strom",
      title: share >= 0.5 ? "Die Wärmepumpe läuft überwiegend bei Sonne" : `Wärmepumpe: bis zu ${fmtPct(share)} Solarstrom`,
      text: `Die Wärmepumpe brauchte ${kwh(total.wp)}, das sind ${fmtPct(total.wp / total.cons)} des Verbrauchs. Bis zu ${fmtPct(share)} davon konnte das Dach zeitgleich liefern.` });
  }

  // Einzelne Verbraucher, die überwiegend mit Netzstrom laufen, obwohl Solarstrom eingespeist wurde
  const single = [
    ...(names?.consumers || []).map((name, i) => ({ name, arr: bal.consumers[i], e: total.consumers[i] })),
    ...(total.wallbox !== null ? [{ name: names?.wallbox || "Wallbox", arr: bal.wallbox, e: total.wallbox }] : []),
  ];
  const flagged = [];
  for (const c of single) {
    if (!(c.e >= 1) || !(total.exp > 0)) continue;
    let fromGrid = 0;
    for (let b = 0; b < n; b++) fromGrid += Math.min(c.arr[b] ?? 0, bal.imp[b] ?? 0) * factor;
    const share = clamp01(fromGrid / c.e);
    if (share >= 0.6 && total.exp >= 0.5 * c.e) flagged.push({ ...c, share });
  }
  flagged.sort((a, b) => b.e * b.share - a.e * a.share);
  for (const c of flagged.slice(0, 3)) {
    out.push({ tone: "warn", area: "Strom", title: `${c.name} läuft meist mit Netzstrom`,
      text: `${kwh(c.e)}, davon bis zu ${fmtPct(c.share)} aus dem Netz. Im selben Zeitraum wurden ${kwh(total.exp)} eingespeist.` });
  }
  return out;
}

/**
 * Auffälligkeiten bei der Wärme aus den Summen eines Zeitraums.
 * agg: { days, starts, cycles, meanRunMin, elKwh, heatKwh, heaterMin, draws, drawMin, boostMin, dryRun }
 */
export function heatFindings(agg) {
  const out = [];
  const kwh = (v) => `${nf1.format(v)} kWh`;
  if (agg.dryRun) {
    out.push({ tone: "warn", area: "Wärme", title: "Die Regelung läuft im Probebetrieb",
      text: "Entscheidungen werden nur protokolliert. An die Wärmepumpe wird nichts gesendet, bis in den Einstellungen ein Eingriff gewählt ist." });
  }
  if (agg.cycles >= 5 && isNum(agg.meanRunMin) && agg.days > 0) {
    const perDay = nf0.format(agg.starts / agg.days);
    const text = `${perDay} Starts am Tag, ein Lauf dauert im Mittel ${fmtDur(agg.meanRunMin)}.`;
    if (agg.meanRunMin < 10) {
      out.push({ tone: "warn", area: "Wärme", title: "Die Wärmepumpe taktet",
        text: `${text} Kurze Läufe kosten Effizienz und belasten den Verdichter.` });
    } else if (agg.meanRunMin >= 30) {
      out.push({ tone: "good", area: "Wärme", title: "Die Wärmepumpe läuft in langen Zügen", text });
    } else {
      out.push({ tone: "info", area: "Wärme", title: `Verdichter: ${perDay} Starts am Tag`, text });
    }
  }
  if (agg.elKwh >= 2 && agg.heatKwh > 0) {
    const cop = agg.heatKwh / agg.elKwh;
    const text = `${kwh(agg.heatKwh)} Wärme aus ${kwh(agg.elKwh)} Strom, berechnet aus den Leistungs-Sensoren der Wärmepumpe. Heizen und Warmwasser zusammen.`;
    out.push({ tone: cop >= 3.5 ? "good" : cop < 2.5 ? "warn" : "info", area: "Wärme",
      title: `Arbeitszahl ${nf1.format(cop)}`, text });
  }
  if (agg.heaterMin > 0) {
    out.push({ tone: "warn", area: "Wärme", title: `Der Heizstab lief ${fmtDur(agg.heaterMin)}`,
      text: "Ein Heizstab macht aus einer Kilowattstunde Strom nur eine Kilowattstunde Wärme. Läuft er regelmäßig, lohnt ein Blick auf Warmwasser-Sollwert und Bivalenzpunkt." });
  }
  if (agg.draws > 0) {
    out.push({ tone: "good", area: "Wärme", title: "Der Kamin-Speicher hat mitgeheizt",
      text: `${agg.draws}-mal, zusammen ${fmtDur(agg.drawMin)}. In dieser Zeit stand die Wärmepumpe.` });
  }
  if (agg.boostMin > 0) {
    out.push({ tone: "good", area: "Wärme", title: "PV-Überschuss floss in die Heizung",
      text: `Die Heizung war ${fmtDur(agg.boostMin)} angehoben.` });
  }
  return out;
}

/* ------------------------------------------------------------------ Stile */

const STYLE = `
:host {
  --ink: var(--primary-text-color, #1c1c1c);
  --ink-2: var(--secondary-text-color, #6b6b6b);
  --plane: var(--primary-background-color, #f6f6f4);
  --surface: var(--card-background-color, #ffffff);
  --rule: var(--divider-color, rgba(0, 0, 0, 0.12));
  --accent: var(--primary-color, #03a9f4);
  --radius: var(--ha-card-border-radius, 12px);
  --c-flow: #eb6834;
  --c-return: #2a78d6;
  --c-dhw: #1baf7a;
  --c-pv: #eda100;
  --c-store: #6250d6;
  --c-warn: #d03b3b;
  display: block;
  min-height: 100vh;
  background: var(--plane);
  color: var(--ink);
  font-family: var(--ha-font-family-body, var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif));
  font-size: 15px;
  line-height: 1.45;
  -webkit-font-smoothing: antialiased;
}
:host([dark]) {
  --c-flow: #d95926;
  --c-return: #3987e5;
  --c-dhw: #199e70;
  --c-pv: #c98500;
  --c-store: #9085e9;
  --c-warn: #e66767;
}
* { box-sizing: border-box; }
[hidden] { display: none !important; }
button, select { font: inherit; color: inherit; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

.bar {
  position: sticky; top: 0; z-index: 5;
  display: flex; align-items: center; gap: 4px;
  height: var(--header-height, 56px); padding: 0 12px;
  background: var(--app-header-background-color, var(--surface));
  color: var(--app-header-text-color, var(--ink));
  border-bottom: 1px solid var(--rule);
}
.bar h1 { flex: 1; margin: 0 0 0 8px; font-size: 20px; font-weight: 400; }
.bar a, .bar button { color: inherit; font-size: 14px; text-decoration: none; padding: 8px; border: 0; border-radius: 6px; background: transparent; cursor: pointer; }
.bar a:hover, .bar button:hover { background: color-mix(in srgb, currentColor 10%, transparent); }

main { max-width: 1240px; margin: 0 auto; padding: 28px 24px 64px; }
section + section { margin-top: 36px; }
h2 { margin: 0 0 14px; font-size: 16px; font-weight: 500; }

/* ---- Lage ---- */
.lage { display: grid; grid-template-columns: minmax(0, 5fr) minmax(0, 6fr); gap: 40px; align-items: start; }
.headline { margin: 4px 0 12px; font-size: 32px; line-height: 1.18; font-weight: 400; letter-spacing: -0.012em; max-width: 18em; text-wrap: balance; }
.reason { margin: 0; color: var(--ink-2); font-size: 16px; max-width: 34em; }
.reason + .reason { margin-top: 8px; }
.note { margin: 14px 0 0; padding: 10px 12px; border-left: 3px solid var(--c-pv); background: color-mix(in srgb, var(--c-pv) 9%, transparent); font-size: 14px; max-width: 38em; }
.note.error { border-left-color: var(--c-warn); background: color-mix(in srgb, var(--c-warn) 9%, transparent); }
.note[hidden] { display: none; }
.note a { color: inherit; }

.controls { margin-top: 26px; display: grid; gap: 14px; }
.row { display: grid; grid-template-columns: 84px minmax(0, 1fr); align-items: center; gap: 8px 10px; }
.row > .label { color: var(--ink-2); font-size: 14px; }
.row > .ctl { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.for { display: inline-flex; align-items: center; gap: 8px; white-space: nowrap; }
.switch { position: relative; width: 44px; height: 24px; padding: 0; border: 0; border-radius: 12px; background: color-mix(in srgb, var(--ink) 28%, transparent); cursor: pointer; transition: background 0.15s; }
.switch::after { content: ""; position: absolute; top: 3px; left: 3px; width: 18px; height: 18px; border-radius: 50%; background: var(--surface); transition: transform 0.15s; }
.switch[aria-checked="true"] { background: var(--accent); }
.switch[aria-checked="true"]::after { transform: translateX(20px); }
.switch-text { font-size: 14px; }
.seg { display: inline-flex; border: 1px solid var(--rule); border-radius: 8px; overflow: hidden; }
.seg button { padding: 7px 14px; border: 0; background: transparent; cursor: pointer; font-size: 14px; }
.seg button + button { border-left: 1px solid var(--rule); }
.seg button:hover { background: color-mix(in srgb, var(--ink) 6%, transparent); }
.seg button[aria-pressed="true"] { background: var(--ink); color: var(--plane); }
select { padding: 7px 8px; border: 1px solid var(--rule); border-radius: 8px; background: var(--surface); font-size: 14px; }
.plain { padding: 7px 12px; border: 1px solid var(--rule); border-radius: 8px; background: transparent; cursor: pointer; font-size: 14px; }
.plain:hover { background: color-mix(in srgb, var(--ink) 6%, transparent); }
.plain[hidden] { display: none; }

/* ---- Anlagenschema ---- */
.schema { width: 100%; max-width: 620px; height: auto; display: block; overflow: visible; }
.schema .box { fill: none; stroke: var(--ink-2); stroke-width: 1.5; }
.schema .tank { fill: color-mix(in srgb, var(--c-dhw) 12%, transparent); stroke: var(--c-dhw); stroke-width: 1.5; }
.schema .fan { fill: none; stroke: var(--ink-2); stroke-width: 1.5; transform-origin: 76px 169px; }
.schema .pipe { fill: none; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
.schema .pipe.flow { stroke: var(--c-flow); }
.schema .pipe.return { stroke: var(--c-return); }
.schema .pulse { fill: none; stroke: var(--plane); stroke-width: 3; stroke-linecap: butt; stroke-dasharray: 2 22; opacity: 0; }
.schema.running .pulse:not(.aux-pulse), .schema .pulse.on { opacity: 0.75; animation: flow 1.6s linear infinite; }
.schema.running .fan { animation: spin 2.4s linear infinite; }
.schema .pipe.aux { stroke: var(--ink-2); stroke-width: 1.5; }
.schema .pipe.aux.hot { stroke: var(--c-flow); stroke-width: 3; }
.schema .store { fill: none; stroke: var(--c-store); stroke-width: 1.5; }
.schema .store.ready { fill: color-mix(in srgb, var(--c-store) 14%, transparent); }
.schema .hide { display: none; }
.schema text { fill: var(--ink); font-size: 13px; }
.schema .cap { fill: var(--ink-2); font-size: 12px; }
.schema .val { font-size: 17px; font-weight: 500; }
@keyframes flow { to { stroke-dashoffset: -24; } }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .schema.running .pulse:not(.aux-pulse), .schema .pulse.on, .schema.running .fan { animation: none; }
  .switch, .switch::after { transition: none; }
}

/* ---- Kennwerte ---- */
.facts { display: flex; flex-wrap: wrap; gap: 18px 44px; margin: 0; padding: 18px 0; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); }
.facts div { min-width: 120px; }
.facts dt { color: var(--ink-2); font-size: 13px; }
.facts dd { margin: 2px 0 0; font-size: 24px; font-weight: 500; letter-spacing: -0.01em; }
.facts small { display: block; color: var(--ink-2); font-size: 12px; font-weight: 400; letter-spacing: 0; }

/* ---- Verlauf ---- */
.sheet { background: var(--surface); border: 1px solid var(--rule); border-radius: var(--radius); padding: 18px 20px 14px; }
.sheet-head { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 8px; }
.sheet-head h2 { margin: 0; flex: 1; }
.plot-title { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 18px; margin: 14px 0 2px; font-size: 13px; color: var(--ink-2); }
.plot-title b { color: var(--ink); font-weight: 500; font-size: 14px; }
.key { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.key i { width: 14px; height: 0; border-top: 2px solid currentColor; }
.key span { color: var(--ink); }
.s-flow { color: var(--c-flow); stroke: var(--c-flow); }
.s-return { color: var(--c-return); stroke: var(--c-return); }
.s-dhw { color: var(--c-dhw); stroke: var(--c-dhw); }
.s-outdoor { color: var(--ink-2); stroke: var(--ink-2); }
.s-pv { color: var(--c-pv); stroke: var(--c-pv); }
.s-store { color: var(--c-store); stroke: var(--c-store); }
.plots { position: relative; }
.plots.loading svg { opacity: 0.45; }
.plots svg { display: block; width: 100%; overflow: visible; }
.plots .grid { stroke: var(--rule); stroke-width: 1; }
.plots .axis { stroke: color-mix(in srgb, var(--ink) 35%, transparent); stroke-width: 1; }
.plots .tick { fill: var(--ink-2); font-size: 11px; font-variant-numeric: tabular-nums; }
.plots .line { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.plots .line.thin { stroke-width: 1.5; }
.plots .area { fill: var(--c-pv); opacity: 0.12; stroke: none; }
.plots .ref { stroke: var(--ink-2); stroke-width: 1; stroke-dasharray: 4 4; }
.plots path.ref { fill: none; }
.plots .ref-label { fill: var(--ink-2); font-size: 11px; paint-order: stroke; stroke: var(--surface); stroke-width: 4px; stroke-linejoin: round; }
.plots .block { fill: var(--ink); opacity: 0.72; }
.plots .lane { stroke: var(--rule); stroke-width: 1; }
.cross { position: absolute; top: 0; bottom: 22px; width: 1px; background: var(--ink); opacity: 0.5; pointer-events: none; display: none; }
.tip { position: absolute; top: 4px; z-index: 2; min-width: 190px; padding: 10px 12px; border: 1px solid var(--rule); border-radius: 8px; background: var(--surface); box-shadow: 0 6px 18px rgba(0, 0, 0, 0.14); font-size: 13px; pointer-events: none; display: none; }
.tip .when { color: var(--ink-2); margin-bottom: 6px; }
.tip .line { display: flex; align-items: center; gap: 8px; }
.tip .line i { width: 12px; border-top: 2px solid currentColor; }
.tip .line b { margin-left: auto; padding-left: 14px; color: var(--ink); font-weight: 500; font-variant-numeric: tabular-nums; }
.tip .line span { color: var(--ink-2); }
.empty { padding: 28px 0; color: var(--ink-2); }
.tablewrap { margin-top: 12px; max-height: 360px; overflow: auto; border-top: 1px solid var(--rule); }
.tablewrap[hidden] { display: none; }
table { width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }
th, td { padding: 6px 10px 6px 0; text-align: right; border-bottom: 1px solid var(--rule); white-space: nowrap; }
th { position: sticky; top: 0; background: var(--surface); color: var(--ink-2); font-weight: 400; }
th:first-child, td:first-child, th:last-child, td:last-child { text-align: left; }

/* ---- Export ---- */
dialog { width: min(460px, calc(100vw - 32px)); padding: 22px 24px 20px; border: 1px solid var(--rule); border-radius: var(--radius); background: var(--surface); color: var(--ink); }
dialog::backdrop { background: rgba(0, 0, 0, 0.5); }
dialog h2 { margin-bottom: 8px; font-size: 20px; font-weight: 400; }
dialog p { margin: 0 0 14px; color: var(--ink-2); font-size: 14px; }
dialog a { color: inherit; }
dialog fieldset { margin: 0 0 16px; padding: 0; border: 0; display: grid; gap: 4px; }
dialog legend { padding: 0; margin-bottom: 6px; font-size: 14px; }
dialog label { display: grid; grid-template-columns: 18px minmax(0, 1fr); gap: 10px; align-items: start; padding: 7px 0; cursor: pointer; }
dialog input[type="radio"] { width: 18px; height: 18px; margin: 2px 0 0; accent-color: var(--ink); }
.opt { display: flex; flex-wrap: wrap; gap: 0 10px; }
.opt .sub { color: var(--ink-2); }
.opt.stack .sub { flex-basis: 100%; font-size: 14px; }
.dlg-status { min-height: 1.45em; color: var(--ink); }
.dlg-status.error { color: var(--c-warn); }
.dlg-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 10px; }
.solid { padding: 8px 14px; border: 1px solid var(--ink); border-radius: 8px; background: var(--ink); color: var(--surface); cursor: pointer; font-size: 14px; }
.solid:disabled { opacity: 0.5; cursor: default; }
.solid[hidden] { display: none; }

/* ---- Bereiche ---- */
.bar { height: auto; flex-wrap: wrap; }
.bar h1 { line-height: var(--header-height, 56px); }
.bar button[hidden] { display: none; }
.bar .tabs { flex-basis: 100%; display: flex; gap: 4px; margin: -6px 0 0 4px; }
.bar .tabs button { padding: 8px 12px 9px; border-radius: 0; border-bottom: 2px solid transparent; font-size: 15px; opacity: 0.65; }
.bar .tabs button:hover { background: transparent; opacity: 1; }
.bar .tabs button[aria-selected="true"] { border-bottom-color: currentColor; opacity: 1; }
main[hidden] { display: none; }

/* ---- Strom und Übersicht ---- */
.s-ink { color: var(--ink); stroke: var(--ink); }
.s-grid { color: var(--ink-2); stroke: var(--ink-2); }
.s-bat { color: var(--c-dhw); stroke: var(--c-dhw); }
.plots .fillarea { fill: currentColor; stroke: none; opacity: 0.16; }
.k-pv { background: var(--c-pv); }
.k-bat { background: var(--c-dhw); }
.k-wp { background: var(--c-flow); }
.k-wb { background: var(--c-return); }
.k-small { background: color-mix(in srgb, var(--ink) 62%, transparent); }
.k-rest { background: color-mix(in srgb, var(--ink) 30%, transparent); }
.k-grid { background: transparent; box-shadow: inset 0 0 0 1.5px var(--ink-2); }
.bal-row { display: grid; grid-template-columns: 50px minmax(0, 1fr); align-items: center; gap: 10px; margin-top: 10px; }
.bal-row > span { color: var(--ink-2); font-size: 13px; }
.bal-bar { display: flex; gap: 2px; height: 30px; min-width: 6px; }
.bal-bar i { display: block; min-width: 3px; border-radius: 4px; }
.bal-key { display: flex; flex-wrap: wrap; gap: 4px 20px; margin: 8px 0 0 60px; font-size: 14px; }
.bal-key div { display: flex; align-items: center; gap: 7px; }
.bal-key i, .key i.sw { width: 11px; height: 11px; border: 0; border-radius: 3px; flex: none; }
.bal-key dt { color: var(--ink-2); }
.bal-key dd { margin: 0; font-weight: 500; font-variant-numeric: tabular-nums; }
.plots .col-pv { fill: var(--c-pv); }
.plots .col-bat { fill: var(--c-dhw); }
.plots .col-grid { fill: none; stroke: var(--ink-2); stroke-width: 1.5; }
.rank { max-width: 860px; }
.rank-row { display: grid; grid-template-columns: minmax(110px, 200px) minmax(0, 1fr) 84px 48px; align-items: center; gap: 12px; padding: 9px 0; border-top: 1px solid var(--rule); }
.rank-bar { height: 14px; }
.rank-bar i { display: block; height: 100%; min-width: 3px; border-radius: 4px; }
.rank-row b { font-weight: 500; text-align: right; font-variant-numeric: tabular-nums; }
.rank-row small { color: var(--ink-2); text-align: right; font-variant-numeric: tabular-nums; }
.find { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0 40px; }
.find h3 { margin: 0 0 6px; font-size: 14px; font-weight: 400; color: var(--ink-2); }
.fitem { padding: 12px 0; border-top: 1px solid var(--rule); }
.fitem b { font-weight: 500; }
.fitem p { margin: 3px 0 0; font-size: 14px; max-width: 46ch; }
.fitem .none { margin: 0; color: var(--ink-2); }
.foot { margin: 18px 0 0; color: var(--ink-2); font-size: 13px; max-width: 90ch; }
@media (max-width: 900px) {
  .find { grid-template-columns: minmax(0, 1fr); gap: 22px; }
  .rank-row { grid-template-columns: minmax(0, 1fr) auto 44px; }
  .rank-bar { grid-column: 1 / -1; order: 3; }
  .bal-key { margin-left: 0; }
}

/* ---- Logbuch und Regeln ---- */
.lower { display: grid; grid-template-columns: minmax(0, 7fr) minmax(0, 4fr); gap: 48px; align-items: start; }
.day { margin: 22px 0 4px; color: var(--ink-2); font-size: 13px; }
.day:first-child { margin-top: 0; }
.entry { display: grid; grid-template-columns: 52px 18px minmax(0, 1fr); gap: 0 10px; padding: 12px 0; border-top: 1px solid var(--rule); }
.entry time { color: var(--ink-2); font-variant-numeric: tabular-nums; }
.entry svg { margin-top: 4px; fill: var(--ink); }
.entry.k-error svg { fill: var(--c-warn); }
.entry .what { font-weight: 500; }
.entry p { margin: 2px 0 0; max-width: 62ch; }
.entry .meta { color: var(--ink-2); font-size: 13px; margin-top: 4px; }
.more { margin-top: 14px; }
.rules p { margin: 0 0 12px; max-width: 44ch; }
.rules a { color: var(--ink); }
.rules .foot { color: var(--ink-2); font-size: 13px; margin-top: 20px; }

@media (max-width: 900px) {
  main { padding: 20px 16px 48px; }
  .lage, .lower { grid-template-columns: minmax(0, 1fr); gap: 28px; }
  .headline { font-size: 26px; }
  .row { grid-template-columns: minmax(0, 1fr); }
  .facts { gap: 14px 28px; }
  .facts dd { font-size: 21px; }
  .sheet { padding: 14px 12px 10px; }
}
@media (max-width: 520px) {
  .schema text { font-size: 17px; }
  .schema .cap { font-size: 16px; }
  .schema .val { font-size: 22px; }
}
`;

/* ------------------------------------------------------------------ Panel */

class EnergyHubPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._snap = null;
    this._range = RANGES[0];
    this._chart = null;
    this._logShown = 40;
    this._lastLogRev = -1;
    this._duration = 120;
  }

  set hass(hass) {
    this._hass = hass;
    this.toggleAttribute("dark", Boolean(hass?.themes?.darkMode));
    if (!this._built) this._build();
    if (this._menu) this._menu.hass = hass;
    this._subscribe();
    this._queueRender();
  }

  set narrow(value) {
    this._narrow = value;
    if (this._menu) this._menu.narrow = value;
  }

  connectedCallback() {
    this._clock = setInterval(() => this._queueRender(), 30000);
    this._refresh = setInterval(() => {
      this._loadHistory();
      this._loadDraws();
      this._loadEnergy();
      if (this._tab === "overview" && Date.now() - (this._analysisAt || 0) > 30 * 60000) this._loadAnalysis();
    }, 5 * 60000);
    if (this._hass) this._subscribe();
  }

  disconnectedCallback() {
    clearInterval(this._clock);
    clearInterval(this._refresh);
    this._resize?.disconnect();
    this._resize2?.disconnect();
    if (this._unsub) this._unsub.then((unsub) => unsub()).catch(() => {});
    this._unsub = null;
  }

  /* ------------------------------------------------------- Verbindung */

  _subscribe() {
    if (this._unsub || !this._hass?.connection || !this.isConnected) return;
    this._unsub = this._hass.connection.subscribeMessage(
      (event) => {
        const first = !this._snap;
        this._snap = { ...event, log: event.log ?? this._snap?.log ?? [] };
        this._queueRender();
        if (first) {
          this._loadHistory();
          this._loadDraws();
          this._loadEnergy();
          if (this._tab === "overview") this._loadAnalysis();
        }
      },
      { type: `${DOMAIN}/subscribe` }
    );
    this._unsub.catch((err) => {
      this._unsub = null;
      this._fail(`Die Verbindung zur Integration ist fehlgeschlagen: ${err?.message || err}`);
    });
  }

  async _call(type, data = {}) {
    try {
      await this._hass.callWS({ type: `${DOMAIN}/${type}`, ...data });
    } catch (err) {
      this._fail(`Das hat nicht geklappt: ${err?.message || err}`);
    }
  }

  _fail(text) {
    this.$.error.textContent = text;
    this.$.error.hidden = false;
  }

  _navigate(event) {
    event.preventDefault();
    history.pushState(null, "", event.currentTarget.getAttribute("href"));
    window.dispatchEvent(new CustomEvent("location-changed", { bubbles: true, composed: true }));
  }

  /* ------------------------------------------------------------ Aufbau */

  _build() {
    this._built = true;
    const root = this.shadowRoot;
    const settingsHref = `/config/integrations/integration/${DOMAIN}`;
    const nav = (e) => this._navigate(e);
    this.$ = {};
    const $ = this.$;

    this._menu = document.createElement("ha-menu-button");

    $.headline = h("p", { class: "headline", role: "status" }, "Die Regelung wird geladen.");
    $.reason = h("p", { class: "reason" });
    $.dry = h(
      "p",
      { class: "note", hidden: true },
      "Probebetrieb: Die Regelung protokolliert nur, was sie tun würde. An die Wärmepumpe wird nichts gesendet. ",
      h("a", { href: settingsHref, onclick: nav }, "Eingriff einstellen")
    );
    $.nopv = h(
      "p",
      { class: "note", hidden: true },
      "Es ist noch kein Sensor für den PV-Überschuss hinterlegt. Ohne ihn bleibt die Heizung im Normalbetrieb. ",
      h("a", { href: settingsHref, onclick: nav }, "Sensor hinterlegen")
    );
    $.error = h("p", { class: "note error", hidden: true });

    $.auto = h("button", {
      class: "switch", role: "switch", "aria-checked": "false", "aria-label": "Automatik",
      onclick: () => this._call("set_automation", { enabled: !this._snap?.state.automation }),
    });
    $.autoText = h("span", { class: "switch-text" });

    $.modes = {};
    const seg = h("div", { class: "seg", role: "group", "aria-label": "Von Hand" });
    for (const mode of ["normal", "boost", "setback"]) {
      $.modes[mode] = h("button", {
        "aria-pressed": "false",
        onclick: () => this._call("set_override", { mode, minutes: this._duration }),
      }, MODE_NAME[mode]);
      seg.append($.modes[mode]);
    }
    $.duration = h("select", {
      "aria-label": "Dauer des Handbetriebs",
      onchange: (e) => { this._duration = e.target.value === "" ? null : Number(e.target.value); },
    }, DURATIONS.map((d) => h("option", { value: d.minutes ?? "", selected: d.minutes === 120 }, d.label)));
    $.endOverride = h("button", { class: "plain", hidden: true, onclick: () => this._call("clear_override") }, "Handbetrieb beenden");

    $.schema = this._buildSchema();
    $.facts = h("dl", { class: "facts" });

    $.ranges = h("div", { class: "seg", role: "group", "aria-label": "Zeitraum" },
      RANGES.map((r) => h("button", {
        "aria-pressed": String(r === this._range),
        onclick: (e) => {
          this._range = r;
          for (const b of $.ranges.children) b.setAttribute("aria-pressed", String(b === e.currentTarget));
          this._loadHistory();
        },
      }, r.label)));
    $.tableBtn = h("button", { class: "plain", "aria-expanded": "false", onclick: () => this._toggleTable() }, "Werte als Tabelle");
    $.plots = h("div", { class: "plots" });
    $.table = h("div", { class: "tablewrap", hidden: true });

    $.log = h("div", {});
    $.more = h("button", { class: "plain more", hidden: true, onclick: () => { this._logShown += 40; this._renderLog(true); } }, "Ältere Einträge zeigen");
    $.rules = h("div", { class: "rules" });

    $.exportBtn = h("button", { onclick: () => this._openExport() }, "Export");
    $.tabs = {};
    const order = [["overview", "Übersicht"], ["power", "Strom"], ["heat", "Wärme"]];
    for (const [key, label] of order) {
      $.tabs[key] = h("button", { role: "tab", "aria-selected": "false", onclick: () => this._showTab(key) }, label);
    }
    const tablist = h("nav", {
      class: "tabs", role: "tablist", "aria-label": "Bereiche",
      onkeydown: (e) => {
        const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
        if (!step) return;
        const keys = order.map(([key]) => key);
        const next = keys[(keys.indexOf(this._tab) + step + keys.length) % keys.length];
        this._showTab(next);
        $.tabs[next].focus();
      },
    }, Object.values($.tabs));
    $.panes = { overview: this._buildOverview(settingsHref, nav), power: this._buildPower(settingsHref, nav) };

    root.append(
      h("style", {}, STYLE),
      h("header", { class: "bar" }, this._menu, h("h1", {}, "Energie"),
        $.exportBtn, h("a", { href: settingsHref, onclick: nav }, "Einstellungen"), tablist),
      $.panes.overview, $.panes.power,
      ($.panes.heat = h("main", { hidden: true },
        h("section", { class: "lage" },
          h("div", {},
            $.headline, $.reason, $.dry, $.nopv, $.error,
            h("div", { class: "controls" },
              h("div", { class: "row" }, h("span", { class: "label" }, "Automatik"), h("div", { class: "ctl" }, $.auto, $.autoText)),
              h("div", { class: "row" }, h("span", { class: "label" }, "Von Hand"),
                h("div", { class: "ctl" }, seg,
                  h("span", { class: "for" }, h("span", { class: "switch-text" }, "für"), $.duration),
                  $.endOverride)))),
          $.schema),
        h("section", {}, $.facts),
        h("section", { class: "sheet" },
          h("div", { class: "sheet-head" }, h("h2", {}, "Verlauf"), $.ranges, $.tableBtn),
          $.plots, $.table),
        h("section", { class: "lower" },
          h("div", {}, h("h2", {}, "Logbuch"), $.log, $.more),
          h("div", {}, h("h2", {}, "So wird geregelt"), $.rules))))
    );

    root.append(this._buildExportDialog(settingsHref, nav));

    this._resize = new ResizeObserver(() => this._drawPlots());
    this._resize.observe($.plots);
    this._resize2 = new ResizeObserver(() => {
      this._drawPower();
      this._drawHours();
    });
    this._resize2.observe($.pPlots);
    this._resize2.observe($.oHours);
    let tab = "overview";
    try {
      tab = localStorage.getItem("energy-hub-tab") || tab;
    } catch (_err) {
      tab = "overview";
    }
    this._showTab($.panes[tab] ? tab : "overview");
  }

  _buildSchema() {
    const $ = this.$;
    const t = (x, y, cls, anchor = "middle") => s("text", { x, y, class: cls, "text-anchor": anchor });
    $.sOutdoor = t(76, 88, "val");
    $.sCompressor = t(16, 258, "cap", "start");
    $.sStatus = t(16, 278, "cap", "start");
    $.sDhw = t(301, 112, "val");
    $.sDhwTarget = t(301, 134, "cap");
    $.sFlow = t(476, 138, "val");
    $.sReturn = t(476, 246, "val");
    $.sReturnTarget = t(476, 266, "cap");
    const flowPath = "M136 152 H236 M366 152 H416 V168 H536 V184 H416";
    const svg = s("svg", { class: "schema", viewBox: "0 0 560 300", role: "img", "aria-label": "Anlagenschema der Wärmepumpe mit aktuellen Temperaturen" },
      // Außengerät
      s("text", { x: 76, y: 64, class: "cap", "text-anchor": "middle" }, "Außen"),
      $.sOutdoor,
      s("rect", { x: 16, y: 104, width: 120, height: 130, rx: 8, class: "box" }),
      s("g", { class: "fan" },
        s("circle", { cx: 76, cy: 169, r: 38 }),
        s("path", { d: "M76 169 L76 135 M76 169 L105.4 186 M76 169 L46.6 186" }),
        s("circle", { cx: 76, cy: 169, r: 5 })),
      $.sCompressor, $.sStatus,
      // Inneneinheit mit Warmwasserspeicher
      s("rect", { x: 236, y: 36, width: 130, height: 228, rx: 8, class: "box" }),
      s("rect", { x: 250, y: 50, width: 102, height: 100, rx: 20, class: "tank" }),
      s("text", { x: 301, y: 88, class: "cap", "text-anchor": "middle" }, "Warmwasser"),
      $.sDhw, $.sDhwTarget,
      s("text", { x: 301, y: 250, class: "cap", "text-anchor": "middle" }, "Inneneinheit"),
      // Leitungen: Vorlauf oben, Rücklauf unten, Heizkreis rechts
      s("path", { d: flowPath, class: "pipe flow" }),
      s("path", { d: "M416 184 V200 H536 V216 H366 M236 192 H136", class: "pipe return" }),
      s("path", { d: flowPath, class: "pulse" }),
      s("text", { x: 476, y: 114, class: "cap", "text-anchor": "middle" }, "Vorlauf"),
      $.sFlow, $.sReturn, $.sReturnTarget,
      s("text", { x: 476, y: 292, class: "cap", "text-anchor": "middle" }, "Heizkreis")
    );
    // Zweite Reihe: Kamin lädt den Speicher, der Speicher versorgt den Heizkreis
    $.sFire = t(76, 372, "val");
    $.sFireState = t(76, 394, "cap");
    $.sFirePipe = s("path", { d: "M136 376 H250", class: "pipe aux" });
    $.gFire = s("g", { class: "hide" },
      s("text", { x: 76, y: 322, class: "cap", "text-anchor": "middle" }, "Kamin"),
      s("rect", { x: 16, y: 332, width: 120, height: 88, rx: 8, class: "box" }),
      $.sFire, $.sFireState, $.sFirePipe);
    $.sStore = t(301, 378, "val");
    $.sStoreState = t(301, 400, "cap");
    $.sStoreBox = s("rect", { x: 250, y: 320, width: 102, height: 108, rx: 20, class: "store" });
    $.sStorePipe = s("path", { d: "M352 376 H476 V304", class: "pipe aux" });
    $.sStorePulse = s("path", { d: "M352 376 H476 V304", class: "pulse aux-pulse" });
    $.gStore = s("g", { class: "hide" },
      $.sStoreBox,
      s("text", { x: 301, y: 352, class: "cap", "text-anchor": "middle" }, "Speicher"),
      $.sStore, $.sStoreState, $.sStorePipe, $.sStorePulse);
    svg.append($.gFire, $.gStore);
    return svg;
  }

  /* ---------------------------------------------------------- Zustände */

  _state(key) {
    const id = this._snap?.entities?.[key];
    return id ? this._hass?.states?.[id] : undefined;
  }

  _value(key, kind) {
    const st = this._state(key);
    if (!st) return null;
    let value = Number(st.state);
    if (!Number.isFinite(value) || st.state === "") return null;
    const unit = String(st.attributes?.unit_of_measurement || "").toLowerCase();
    if (kind === "power") value *= { kw: 1000, mw: 1e6 }[unit] || 1;
    if (kind === "energy") value *= { wh: 0.001, mwh: 1000 }[unit] || 1;
    return value;
  }

  _queueRender() {
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => {
      this._raf = null;
      this._render();
    });
  }

  _render() {
    const snap = this._snap;
    if (!snap || !this._built) return;
    const $ = this.$;
    const st = snap.state;
    const cfg = snap.entities;

    const headline = this._heatHeadline(st);
    $.headline.textContent = headline;
    $.reason.textContent = st.override ? "" : st.reason;
    $.dry.hidden = !st.dry_run;
    $.nopv.hidden = Boolean(cfg.ent_pv_surplus);
    if (st.last_error) {
      this._fail(`Die Wärmepumpe hat die letzte Vorgabe nicht angenommen: ${st.last_error}`);
    } else if ($.error.textContent.startsWith("Die Wärmepumpe hat")) {
      $.error.hidden = true;
    }

    // Bedienung
    $.auto.setAttribute("aria-checked", String(st.automation));
    $.autoText.textContent = st.automation ? "Die Regeln entscheiden" : "Ausgeschaltet, es wird nichts verstellt";
    for (const [mode, btn] of Object.entries($.modes)) {
      btn.setAttribute("aria-pressed", String(st.override?.mode === mode));
    }
    $.endOverride.hidden = !st.override;

    // Anlagenschema
    const running = this._state("ent_compressor")?.state === "on";
    $.schema.classList.toggle("running", running);
    $.sOutdoor.textContent = cfg.ent_outdoor ? fmtC(this._value("ent_outdoor")) : "";
    $.sCompressor.textContent = cfg.ent_compressor ? (running ? "Verdichter läuft" : "Verdichter steht") : "";
    const status = this._state("ent_status")?.state;
    $.sStatus.textContent = status && !["unknown", "unavailable"].includes(status) ? status : "";
    $.sDhw.textContent = cfg.ent_dhw ? fmtC(this._value("ent_dhw")) : "";
    const dhwT = this._value("ent_dhw_target");
    $.sDhwTarget.textContent = isNum(dhwT) ? `Soll ${fmtC(dhwT)}` : "";
    $.sFlow.textContent = cfg.ent_flow ? fmtC(this._value("ent_flow")) : "";
    $.sReturn.textContent = cfg.ent_return ? fmtC(this._value("ent_return")) : "";
    const retT = this._value("ent_return_target");
    $.sReturnTarget.textContent = isNum(retT) ? `Rücklauf, Soll ${fmtC(retT)}` : "Rücklauf";

    // Kamin und Speicher
    const hasFire = Boolean(cfg.ent_fireplace);
    const hasStore = Boolean(cfg.ent_storage);
    $.schema.setAttribute("viewBox", hasFire || hasStore ? "0 0 560 440" : "0 0 560 300");
    $.gFire.classList.toggle("hide", !hasFire);
    $.gStore.classList.toggle("hide", !hasStore);
    const live = this._liveAux();
    if (hasFire) {
      $.sFire.textContent = fmtC(live.fireTemp);
      $.sFireState.textContent = live.fireStatus || (live.fireOn === null ? "" : live.fireOn ? "brennt" : "aus");
      $.sFirePipe.classList.toggle("hot", Boolean(live.fireOn) && hasStore);
      $.sFirePipe.classList.toggle("hide", !hasStore);
    }
    if (hasStore) {
      $.sStore.textContent = fmtC(live.storeTemp);
      $.sStoreState.textContent = live.drawing ? "liefert" : live.ready === null ? "" : live.ready ? "bereit" : "nicht bereit";
      $.sStoreBox.classList.toggle("ready", Boolean(live.ready));
      $.sStorePipe.classList.toggle("hot", Boolean(live.drawing));
      $.sStorePulse.classList.toggle("on", Boolean(live.drawing));
    }

    this._renderFacts();
    this._renderRules();
    this._renderLog(false);
    this._renderLive();
  }

  /** Kamin und Speicher aus den aktuellen Zuständen: Temperaturen, brennt, bereit, liefert. */
  _liveAux() {
    const set = this._snap.settings;
    const storeTemp = this._value("ent_storage");
    const fireTemp = this._value("ent_fireplace");
    const lock = this._state("ent_lock")?.state;
    const status = this._state("ent_fireplace_status")?.state;
    // Bereit wie im Regler der Wärmepumpe: Rücklaufsoll plus Differenz, sonst die feste Ersatz-Schwelle
    const retTarget = this._value("ent_return_target");
    const readyAt = isNum(retTarget) ? retTarget + Number(set.storage_ready_delta_k) : Number(set.storage_ready_c);
    return {
      storeTemp,
      readyAt,
      relative: isNum(retTarget),
      ready: isNum(storeTemp) ? storeTemp >= readyAt : null,
      fireTemp,
      fireOn: isNum(fireTemp) ? fireTemp >= Number(set.fireplace_on_c) : null,
      fireStatus: status && !isGap(status) ? status : "",
      drawing: lock === undefined || isGap(lock) ? null : matcher(set.lock_regen_value)(lock),
    };
  }

  _renderFacts() {
    const { state: st, entities: cfg, settings: set } = this._snap;
    const items = [];
    if (cfg.ent_pv_surplus) {
      const above = minutesSince(st.above_since);
      const below = minutesSince(st.below_since);
      let hint = "";
      if (above !== null) hint = `seit ${above} min über ${fmtW(set.boost_on_w)}`;
      else if (below !== null && st.mode === "boost") hint = `seit ${below} min unter ${fmtW(set.boost_off_w)}`;
      items.push(["PV-Überschuss", fmtW(st.inputs.surplus_w), hint]);
    }
    if (cfg.ent_forecast_today) items.push(["Prognose Rest heute", fmtKwh(st.inputs.forecast_kwh)]);
    if (cfg.ent_forecast_tomorrow) items.push(["Prognose morgen", fmtKwh(st.inputs.forecast_tomorrow_kwh)]);
    const el = this._value("ent_power_el", "power");
    const heat = this._value("ent_power_heat", "power");
    if (cfg.ent_power_el) items.push(["Strom Wärmepumpe", fmtKw(el)]);
    if (cfg.ent_power_heat) items.push(["Heizleistung", fmtKw(heat)]);
    if (isNum(el) && isNum(heat) && el >= 200 && heat > 0) {
      items.push(["Leistungszahl", nf1.format(heat / el), "Wärme je Strom, Momentanwert"]);
    }
    const live = this._liveAux();
    if (cfg.ent_storage) {
      const hint = live.drawing ? "liefert gerade Wärme"
        : live.ready === null ? ""
        : `${live.ready ? "bereit" : "noch nicht bereit"}, ab ${fmtC(live.readyAt)}${live.relative ? ` (Rücklaufsoll + ${nf0.format(set.storage_ready_delta_k)} K)` : ""}`;
      items.push(["Speicher", fmtC(live.storeTemp), hint]);
    }
    if (cfg.ent_fireplace) {
      items.push(["Kamin", fmtC(live.fireTemp), live.fireStatus || (live.fireOn === null ? "" : live.fireOn ? "brennt" : "aus")]);
    }
    if (cfg.ent_lock && this._draws) {
      const d = this._draws;
      const dur = d.todayMs >= 3600e3
        ? `${Math.floor(d.todayMs / 3600e3)} h ${Math.round((d.todayMs % 3600e3) / 60e3)} min`
        : `${Math.round(d.todayMs / 60e3)} min`;
      items.push(["Wärme aus dem Speicher heute", `${d.today}-mal`, `${dur}, in 7 Tagen ${d.week}-mal`]);
    }
    this.$.facts.replaceChildren(
      ...items.map(([label, value, hint]) =>
        h("div", {}, h("dt", {}, label), h("dd", {}, value, hint ? h("small", {}, hint) : null)))
    );
    this.$.facts.parentElement.hidden = items.length === 0;
  }

  _renderRules() {
    const set = this._snap.settings;
    const settingsHref = `/config/integrations/integration/${DOMAIN}`;
    const parts = [
      `Angehoben wird, wenn der PV-Überschuss ${nf0.format(set.boost_on_min)} min lang über ${fmtW(set.boost_on_w)} liegt.`,
      `Das Anheben endet, wenn er ${nf0.format(set.boost_off_min)} min lang unter ${fmtW(set.boost_off_w)} liegt.`,
    ];
    if (set.setback_enabled) {
      const conds = [`für den Rest des Tages mindestens ${fmtKwh(set.setback_min_forecast_kwh)} vorhergesagt sind`];
      if (isNum(set.setback_min_outdoor_c)) conds.push(`es draußen mindestens ${fmtC(set.setback_min_outdoor_c)} hat`);
      if (isNum(set.setback_min_dhw_c)) conds.push(`das Warmwasser mindestens ${fmtC(set.setback_min_dhw_c)} hat`);
      const list = conds.length > 1 ? `${conds.slice(0, -1).join(", ")} und ${conds.at(-1)}` : conds[0];
      parts.push(`Abgesenkt wird zwischen ${hhmm(set.setback_start)} und ${hhmm(set.setback_end)} Uhr, wenn ${list}.`);
    } else {
      parts.push("Abgesenkt wird nicht.");
    }
    if (this._snap.entities.ent_storage && set.storage_blocks_boost) {
      parts.push(this._snap.entities.ent_return_target
        ? `Der Speicher gilt als bereit, wenn er mindestens ${nf0.format(set.storage_ready_delta_k)} K über der Rücklauf-Solltemperatur liegt. So rechnet auch der Regler der Wärmepumpe. Solange er bereit ist, wird nicht angehoben.`
        : `Solange der Speicher mindestens ${fmtC(Number(set.storage_ready_c))} hat, wird nicht angehoben. Dann kann der Kamin die Heizung versorgen.`);
    }
    parts.push(`Jeder Zustand wird mindestens ${nf0.format(set.min_hold_min)} min gehalten. Handbetrieb wirkt sofort.`);
    parts.push({
      dry_run: "Eingriff: keiner, die Regelung läuft im Probebetrieb.",
      smart_grid: "Eingriff: Smart-Grid-Zustand der Wärmepumpe.",
      parallel_shift: `Eingriff: Parallelverschiebung der Heizkurve, +${nf0.format(set.shift_boost_k)} K beim Anheben und −${nf0.format(set.shift_setback_k)} K beim Absenken.`,
    }[set.actuator]);
    const key = parts.join("|");
    if (key === this._rulesKey) return;
    this._rulesKey = key;
    this.$.rules.replaceChildren(
      ...parts.map((p) => h("p", {}, p)),
      h("p", {}, h("a", { href: settingsHref, onclick: (e) => this._navigate(e) }, "Regeln ändern")),
      h("p", { class: "foot" }, `Energy Hub ${this._snap.version}`)
    );
  }

  /* ------------------------------------------------------------ Logbuch */

  _entryTitle(e) {
    return entryTitle(e);
  }

  _entryGlyph(e) {
    const d = e.kind === "error" ? "M7 1 L13 13 H1 Z M6.2 5.5 h1.6 v3.6 h-1.6 Z M6.2 10 h1.6 v1.6 h-1.6 Z"
      : e.kind === "switch" && e.to === "boost" ? "M7 2 L12.5 11 H1.5 Z"
      : e.kind === "switch" && e.to === "setback" ? "M7 12 L1.5 3 H12.5 Z"
      : e.kind === "switch" ? "M2 6 H12 V8 H2 Z"
      : "M7 4.5 a2.5 2.5 0 1 0 0.01 0 Z";
    return s("svg", { width: 14, height: 14, viewBox: "0 0 14 14", "aria-hidden": "true" },
      s("path", { d, "fill-rule": "evenodd" }));
  }

  _entryMeta(e) {
    const v = e.values || {};
    const bits = [];
    if (isNum(v.surplus_w)) bits.push(`Überschuss ${fmtW(v.surplus_w)}`);
    if (isNum(v.forecast_kwh)) bits.push(`Prognose ${fmtKwh(v.forecast_kwh)}`);
    if (isNum(v.outdoor_c)) bits.push(`außen ${fmtC(v.outdoor_c)}`);
    if (isNum(v.dhw_c)) bits.push(`Warmwasser ${fmtC(v.dhw_c)}`);
    if (isNum(v.storage_c)) bits.push(`Speicher ${fmtC(v.storage_c)}`);
    let result = "";
    if (e.result === "sent") result = `Gesendet: ${e.detail || "Vorgabe gesetzt"}`;
    else if (e.result === "simulated") result = "Nur protokolliert (Probebetrieb)";
    else if (e.result === "failed") result = `Fehlgeschlagen: ${e.detail || "unbekannter Grund"}`;
    return [bits.join(", "), result].filter(Boolean);
  }

  _renderLog(force) {
    const snap = this._snap;
    if (!force && snap.log_rev === this._lastLogRev) return;
    this._lastLogRev = snap.log_rev;
    const log = snap.log || [];
    const $ = this.$;
    if (!log.length) {
      $.log.replaceChildren(h("p", { class: "empty" },
        "Noch keine Einträge. Sobald die Regelung etwas ändert, steht es hier mit Uhrzeit und Begründung."));
      $.more.hidden = true;
      return;
    }
    const nodes = [];
    let lastDay = "";
    for (const e of log.slice(0, this._logShown)) {
      const when = new Date(e.ts);
      const day = tfDay.format(when);
      if (day !== lastDay) {
        nodes.push(h("div", { class: "day" }, day));
        lastDay = day;
      }
      nodes.push(h("div", { class: `entry k-${e.kind}` },
        h("time", { datetime: e.ts }, tfTime.format(when)),
        this._entryGlyph(e),
        h("div", {},
          h("div", { class: "what" }, this._entryTitle(e)),
          h("p", {}, e.text),
          this._entryMeta(e).map((line) => h("p", { class: "meta" }, line)))));
    }
    $.log.replaceChildren(...nodes);
    $.more.hidden = log.length <= this._logShown;
  }

  /* ---------------------------------------------------------- Bereiche */

  _showTab(name) {
    const $ = this.$;
    this._tab = name;
    try {
      localStorage.setItem("energy-hub-tab", name);
    } catch (_err) {
      // ohne Speicher merkt sich das Panel den Bereich nur bis zum Neuladen
    }
    for (const [key, pane] of Object.entries($.panes)) pane.hidden = key !== name;
    for (const [key, btn] of Object.entries($.tabs)) {
      btn.setAttribute("aria-selected", String(key === name));
      btn.tabIndex = key === name ? 0 : -1;
    }
    $.exportBtn.hidden = name !== "heat";
    if (name === "heat") this._drawPlots();
    if (name === "power") this._drawPower();
    if (name === "overview") {
      this._drawHours();
      if (!this._analysisAt && this._snap) this._loadAnalysis();
    }
  }

  _buildOverview(settingsHref, nav) {
    const $ = this.$;
    $.oHeadline = h("p", { class: "headline", role: "status" }, "Die Übersicht wird geladen.");
    $.oSub = h("p", { class: "reason" });
    $.oNow = h("p", { class: "reason" });
    $.oNote = h("p", { class: "note", hidden: true },
      "Für Strom und Übersicht sind noch keine Sensoren hinterlegt. Gebraucht werden Netzanschluss und PV-Anlage, dazu nach Wunsch Batterie, Wallbox und einzelne Verbraucher. ",
      h("a", { href: settingsHref, onclick: nav }, "Strom-Sensoren hinterlegen"));
    $.oBalance = h("div", { class: "bal" });
    $.oFacts = h("dl", { class: "facts" });
    $.oHours = h("div", { class: "plots" });
    $.oFind = h("div", {});
    return h("main", { hidden: true },
      h("section", { class: "lage" },
        h("div", {}, $.oHeadline, $.oNow, $.oSub, $.oNote),
        ($.oBalWrap = h("div", {}, h("h2", {}, "Strom heute: woher er kam, wohin er ging"), $.oBalance))),
      ($.oFactsSec = h("section", {}, $.oFacts)),
      ($.oHoursSec = h("section", { class: "sheet" },
        h("div", { class: "sheet-head" }, h("h2", {}, "Heute, Stunde für Stunde")), $.oHours)),
      h("section", {}, h("h2", {}, "Die letzten 7 Tage"), $.oFind));
  }

  _buildPower(settingsHref, nav) {
    const $ = this.$;
    this._pRange = 24;
    $.pHeadline = h("p", { class: "headline", role: "status" }, "Die Stromdaten werden geladen.");
    $.pSub = h("p", { class: "reason" });
    $.pNote = h("p", { class: "note", hidden: true },
      "Für den Bereich Strom sind noch keine Sensoren hinterlegt. ",
      h("a", { href: settingsHref, onclick: nav }, "Strom-Sensoren hinterlegen"));
    $.pBalance = h("div", { class: "bal" });
    $.pFacts = h("dl", { class: "facts" });
    $.pRanges = h("div", { class: "seg", role: "group", "aria-label": "Zeitraum" },
      [[24, "24 Stunden"], [48, "48 Stunden"], [168, "7 Tage"]].map(([hours, label]) => h("button", {
        "aria-pressed": String(hours === this._pRange),
        onclick: (e) => {
          this._pRange = hours;
          for (const b of $.pRanges.children) b.setAttribute("aria-pressed", String(b === e.currentTarget));
          if (hours === 168 && !this._enWeek) this._loadEnergyWeek();
          else this._drawPower();
        },
      }, label)));
    $.pPlots = h("div", { class: "plots" });
    $.pRank = h("div", { class: "rank" });
    return h("main", { hidden: true },
      h("section", { class: "lage" },
        h("div", {}, $.pHeadline, $.pSub, $.pNote),
        ($.pBalWrap = h("div", {}, h("h2", {}, "Strom jetzt: woher er kommt, wohin er geht"), $.pBalance))),
      ($.pFactsSec = h("section", {}, $.pFacts)),
      ($.pSheet = h("section", { class: "sheet" },
        h("div", { class: "sheet-head" }, h("h2", {}, "Verlauf"), $.pRanges), $.pPlots)),
      ($.pRankSec = h("section", {}, h("h2", {}, "Verbraucher heute"), $.pRank)));
  }

  /* ------------------------------------------------------------- Strom */

  _hasPower() {
    const cfg = this._snap?.entities;
    return Boolean(cfg && (cfg.ent_grid_power || cfg.ent_pv_power || cfg.ent_house_power));
  }

  _powerFactor(id) {
    const unit = String(this._hass?.states?.[id]?.attributes?.unit_of_measurement || "").toLowerCase();
    return { kw: 1000, mw: 1e6 }[unit] || 1;
  }

  _name(id) {
    const name = this._hass?.states?.[id]?.attributes?.friendly_name || id.split(".").pop().replaceAll("_", " ");
    return name.replace(/\s+(Leistung|Power|Wirkleistung|power)$/i, "");
  }

  _heatHeadline(st) {
    const since = fmtClock(st.since);
    if (st.override) {
      const until = st.override.until ? `bis ${fmtClock(st.override.until)}` : "bis du ihn beendest";
      return `Handbetrieb: ${MODE_NAME[st.override.mode]}, ${until}.`;
    }
    if (!st.automation) return "Die Automatik ist aus. Die Heizung läuft normal.";
    if (st.mode === "boost") return `Die Heizung ist seit ${since} angehoben.`;
    if (st.mode === "setback") return `Die Heizung ist seit ${since} abgesenkt.`;
    return "Die Heizung läuft im Normalbetrieb.";
  }

  /** Strombilanz aus den aktuellen Zuständen (Watt). */
  _liveBalance() {
    const cfg = this._snap.entities;
    const set = this._snap.settings;
    const consumers = this._snap.consumers || [];
    const one = (id) => {
      if (!id) return null;
      const st = this._hass?.states?.[id];
      const v = st && !isGap(st.state) ? Number(st.state) : NaN;
      return [Number.isFinite(v) ? v * this._powerFactor(id) : null];
    };
    const bal = energyBalance({
      grid: one(cfg.ent_grid_power), pv: one(cfg.ent_pv_power), battery: one(cfg.ent_battery_power),
      house: one(cfg.ent_house_power), wp: one(cfg.ent_power_el), wallbox: one(cfg.ent_wallbox_power),
      consumers: consumers.map((id) => one(id) || [null]),
    }, { gridSign: set.grid_sign, batterySign: set.battery_sign });
    const live = {};
    for (const [key, arr] of Object.entries(bal)) if (key !== "consumers") live[key] = arr[0] ?? null;
    const socState = cfg.ent_battery_soc ? this._hass?.states?.[cfg.ent_battery_soc] : null;
    live.soc = socState && !isGap(socState.state) && Number.isFinite(Number(socState.state)) ? Number(socState.state) : null;
    return live;
  }

  /** Zwei Balken auf gleicher Skala: woher der Strom kommt und wohin er geht. */
  _renderBalance(host, v, fmt) {
    const sources = [["k-pv", "Dach", v.pv], ["k-bat", "Batterie", v.dis], ["k-grid", "Netz", v.imp]];
    const sinks = [
      ["k-wp", "Wärmepumpe", v.wp], ["k-wb", "Wallbox", v.wallbox], ["k-small", "Weitere Verbraucher", v.small],
      ["k-rest", "Übriges Haus", v.rest], ["k-bat", "Batterie laden", v.chg], ["k-grid", "Einspeisung", v.exp],
    ];
    const total = (list) => list.reduce((sum, [, , value]) => sum + (isNum(value) ? value : 0), 0);
    const max = Math.max(total(sources), total(sinks));
    if (!(max > 0)) {
      host.replaceChildren(h("p", { class: "empty" }, "Noch keine Werte."));
      return;
    }
    const row = (label, list) => {
      const shown = list.filter(([, , value]) => isNum(value) && value / max >= 0.004);
      return [
        h("div", { class: "bal-row" },
          h("span", {}, label),
          h("div", { class: "bal-bar", style: `width:${((total(list) / max) * 100).toFixed(2)}%`, role: "img",
            "aria-label": `${label}: ${shown.map(([, name, value]) => `${name} ${fmt(value)}`).join(", ")}` },
            shown.map(([cls, , value]) => h("i", { class: cls, style: `flex:${value} 1 0` })))),
        h("dl", { class: "bal-key" }, shown.map(([cls, name, value]) =>
          h("div", {}, h("i", { class: cls }), h("dt", {}, name), h("dd", {}, fmt(value))))),
      ];
    };
    host.replaceChildren(...row("Woher", sources), ...row("Wohin", sinks));
  }

  _renderLive() {
    const snap = this._snap;
    const $ = this.$;
    const has = this._hasPower();
    $.pNote.hidden = has;
    $.oNote.hidden = has;
    for (const el of [$.oBalWrap, $.oFactsSec, $.oHoursSec, $.pBalWrap, $.pFactsSec, $.pSheet, $.pRankSec]) el.hidden = !has;
    const heat = this._heatHeadline(snap.state);
    const aux = this._liveAux();
    const heatBits = [heat];
    if (aux.fireOn) heatBits.push("Der Kamin brennt.");
    if (aux.drawing) heatBits.push("Der Speicher liefert Wärme.");
    else if (aux.ready) heatBits.push("Der Speicher ist bereit.");

    if (!has) {
      $.pHeadline.textContent = "Noch keine Stromdaten.";
      $.pSub.textContent = "";
      $.oHeadline.textContent = heat;
      $.oNow.textContent = "";
      $.oSub.textContent = heatBits.slice(1).join(" ");
      return;
    }
    const v = this._liveBalance();
    $.pHeadline.textContent = isNum(v.cons) ? `Das Haus verbraucht gerade ${fmtKw(v.cons)}.` : "Der Verbrauch ist gerade nicht bekannt.";
    const bits = [];
    if (v.pv > 30) bits.push(`Das Dach liefert ${fmtKw(v.pv)}.`);
    else if (v.pv !== null) bits.push("Das Dach liefert nichts.");
    if (v.dis > 30) bits.push(`Die Batterie gibt ${fmtKw(v.dis)} ab.`);
    if (v.chg > 30) bits.push(`Die Batterie lädt mit ${fmtKw(v.chg)}.`);
    if (v.imp > 30) bits.push(`Aus dem Netz kommen ${fmtKw(v.imp)}.`);
    if (v.exp > 30) bits.push(`Ins Netz gehen ${fmtKw(v.exp)}.`);
    if (isNum(v.soc)) bits.push(`Ladestand ${nf0.format(v.soc)} %.`);
    $.pSub.textContent = bits.join(" ");
    if (this._tab === "power") this._renderBalance($.pBalance, v, fmtKw);

    const today = this._today;
    $.oHeadline.textContent = today && today.autarky !== null
      ? `Heute hat sich das Haus zu ${fmtPct(today.autarky)} selbst mit Strom versorgt.`
      : "Die Stromdaten von heute werden geladen.";
    $.oNow.textContent = [$.pHeadline.textContent, ...bits].join(" ");
    $.oSub.textContent = heatBits.join(" ");
  }

  /** Kennwerte des heutigen Tages, gemeinsam für Übersicht und Strom. */
  _renderToday() {
    const $ = this.$;
    const t = this._today;
    if (!t) return;
    const kwh = (v) => (isNum(v) ? `${nf1.format(v)} kWh` : "–");
    const cfg = this._snap.entities;
    const live = this._liveBalance();
    const items = [["Verbrauch heute", kwh(t.cons)]];
    if (cfg.ent_pv_power) items.push(["Vom Dach", kwh(t.pv), t.selfUse !== null ? `${fmtPct(t.selfUse)} selbst genutzt` : ""]);
    if (t.autarky !== null) items.push(["Autarkie", fmtPct(t.autarky), "Anteil ohne Netz"]);
    if (cfg.ent_grid_power) {
      items.push(["Netzbezug", kwh(t.imp)]);
      items.push(["Einspeisung", kwh(t.exp)]);
    }
    if (cfg.ent_battery_power || cfg.ent_battery_soc) {
      const hint = t.chg !== null ? `heute ${kwh(t.chg)} geladen, ${kwh(t.dis)} entladen` : "";
      items.push(["Batterie", isNum(live.soc) ? `${nf0.format(live.soc)} %` : kwh(t.dis), hint]);
    }
    if (cfg.ent_power_el) items.push(["Wärmepumpe", kwh(t.wp), t.cons > 0 && isNum(t.wp) ? `${fmtPct(t.wp / t.cons)} des Verbrauchs` : ""]);
    if (cfg.ent_wallbox_power) items.push(["Wallbox", kwh(t.wallbox)]);
    const nodes = () => items.map(([label, value, hint]) =>
      h("div", {}, h("dt", {}, label), h("dd", {}, value, hint ? h("small", {}, hint) : null)));
    $.oFacts.replaceChildren(...nodes());
    $.pFacts.replaceChildren(...nodes());
    this._renderBalance($.oBalance, t, kwh);

    // Rangliste der Verbraucher
    const rows = [];
    if (isNum(t.wp)) rows.push(["Wärmepumpe", t.wp, "k-wp"]);
    if (isNum(t.wallbox)) rows.push(["Wallbox", t.wallbox, "k-wb"]);
    (this._en?.names || []).forEach((name, i) => {
      if (isNum(t.consumers[i])) rows.push([name, t.consumers[i], "k-small"]);
    });
    rows.sort((a, b) => b[1] - a[1]);
    if (isNum(t.rest)) rows.push(["Übriges Haus", t.rest, "k-rest"]);
    const max = Math.max(...rows.map((r) => r[1]), 0.001);
    $.pRank.replaceChildren(...(rows.length ? rows.map(([name, value, cls]) => h("div", { class: "rank-row" },
      h("span", {}, name),
      h("div", { class: "rank-bar" }, h("i", { class: cls, style: `width:${Math.max(0.5, (value / max) * 100).toFixed(1)}%` })),
      h("b", {}, kwh(value)),
      h("small", {}, t.cons > 0 ? fmtPct(value / t.cons) : "")))
      : [h("p", { class: "empty" }, "Noch keine Verbraucher hinterlegt oder heute noch keine Werte.")]));
    this._renderLive();
  }

  /* ---------------------------------------------------- Daten für Strom */

  /** Zahlenreihen aus der Statistik von Home Assistant, ersatzweise aus dem Verlauf. */
  async _grids(ids, t0, t1, step, n, period) {
    const out = {};
    if (!ids.length) return out;
    let stats = {};
    try {
      stats = await this._hass.callWS({
        type: "recorder/statistics_during_period", start_time: new Date(t0).toISOString(),
        end_time: new Date(t1).toISOString(), statistic_ids: ids, period, types: ["mean"],
      }) || {};
    } catch (_err) {
      stats = {};
    }
    for (const id of ids) {
      const rows = (stats[id] || []).filter((r) => isNum(r.mean)).map((r) => [new Date(r.start).getTime(), r.mean]);
      out[id] = rows.length
        ? rowsToGrid(rows, t0, step, n)
        : stepSeries(await this._history(id, t0, t1), t0, step, n, Math.min(t1, Date.now()));
    }
    return out;
  }

  async _energySet(hours, step, period) {
    const snap = this._snap;
    const cfg = snap.entities;
    const consumers = snap.consumers || [];
    const t1 = Math.ceil(Date.now() / step) * step;
    const t0 = t1 - hours * 3600e3;
    const n = Math.round((t1 - t0) / step);
    const src = {
      grid: cfg.ent_grid_power, pv: cfg.ent_pv_power, battery: cfg.ent_battery_power, soc: cfg.ent_battery_soc,
      house: cfg.ent_house_power, wp: cfg.ent_power_el, wallbox: cfg.ent_wallbox_power,
    };
    const ids = [...new Set([...Object.values(src), ...consumers].filter(Boolean))];
    const grids = await this._grids(ids, t0, t1, step, n, period);
    const pick = (id, power = true) => (id && grids[id]
      ? grids[id].map((v) => (v === null ? null : v * (power ? this._powerFactor(id) : 1))) : null);
    const bal = energyBalance({
      grid: pick(src.grid), pv: pick(src.pv), battery: pick(src.battery), house: pick(src.house),
      wp: pick(src.wp), wallbox: pick(src.wallbox),
      consumers: consumers.map((id) => pick(id) || new Array(n).fill(null)),
    }, { gridSign: snap.settings.grid_sign, batterySign: snap.settings.battery_sign });
    return { t0, t1, n, step, bal, soc: pick(src.soc, false), names: consumers.map((id) => this._name(id)) };
  }

  async _loadEnergy() {
    if (!this._snap || !this._hass?.callWS || !this._hasPower()) {
      if (this._snap) this._renderLive();
      return;
    }
    try {
      const en = await this._energySet(48, 300e3, "5minute");
      const midnight = new Date();
      midnight.setHours(0, 0, 0, 0);
      const i0 = Math.max(0, Math.round((midnight.getTime() - en.t0) / en.step));
      this._en = en;
      this._today = energyTotals(en.bal, en.step, i0, en.n);
      this._hours = hourlyMix(en.bal, en.t0, en.step, midnight.getTime());
      this._renderToday();
      this._drawHours();
      this._drawPower();
    } catch (err) {
      this.$.pSub.textContent = `Die Stromdaten konnten nicht geladen werden: ${err?.message || err}`;
    }
  }

  async _loadEnergyWeek() {
    this.$.pPlots.classList.add("loading");
    try {
      this._enWeek = await this._energySet(168, 3600e3, "hour");
    } catch (_err) {
      this._enWeek = null;
    }
    this.$.pPlots.classList.remove("loading");
    this._drawPower();
  }

  /** Auswertung der letzten 7 Tage für die Übersicht. */
  async _loadAnalysis() {
    const snap = this._snap;
    if (!snap || !this._hass?.callWS) return;
    this._analysisAt = Date.now();
    const findings = [];
    try {
      if (this._hasPower()) {
        const week = await this._energySet(168, 300e3, "5minute");
        findings.push(...powerFindings(week.bal, week.soc, { consumers: week.names, wallbox: "Wallbox" }, week.step, week.t0));
      }
    } catch (_err) {
      // Strom-Auswertung entfällt, die Wärme-Auswertung läuft trotzdem
    }
    try {
      findings.push(...heatFindings(await this._heatWeek()));
    } catch (_err) {
      // ohne Verlauf der Wärmepumpe gibt es keine Wärme-Auswertung
    }
    this._findings = findings;
    this._renderFindings();
  }

  /** Summen der Wärmepumpe über 7 Tage, berechnet wie im Effizienz-Export. */
  async _heatWeek() {
    const snap = this._snap;
    const cfg = snap.entities;
    const now = Date.now();
    const t0 = Math.floor(now / 3600e3) * 3600e3 + 3600e3 - 168 * 3600e3;
    const data = {};
    const textual = { comp: cfg.ent_compressor, heater: cfg.ent_heater, lock: cfg.ent_lock, mode: snap.state.state_entity_id };
    for (const [key, id] of Object.entries(textual)) {
      if (id) data[key] = await this._history(id, t0, now);
    }
    const numeric = { pEl: cfg.ent_power_el, pHeat: cfg.ent_power_heat };
    const ids = Object.values(numeric).filter(Boolean);
    const n = Math.round((Math.ceil(now / 300e3) * 300e3 - t0) / 300e3);
    const grids = await this._grids(ids, t0, t0 + n * 300e3, 300e3, n, "5minute");
    for (const [key, id] of Object.entries(numeric)) {
      if (id && grids[id]) data[key] = grids[id].map((v, b) => [t0 + b * 300e3, v === null ? "unknown" : v]);
    }
    const a = analyseEfficiency(data, { pEl: this._powerFactor(numeric.pEl), pHeat: this._powerFactor(numeric.pHeat) },
      t0, now, 3600e3, { regen: matcher(snap.settings.lock_regen_value) });
    const col = (name) => HOUR_HEADER.indexOf(name);
    const sum = (name) => a.hourRows.reduce((total, row) => total + (isNum(row[col(name)]) ? row[col(name)] : 0), 0);
    const known = (name) => a.hourRows.some((row) => isNum(row[col(name)]));
    const whole = a.cycleRows.filter((row) => !row[CYCLE_HEADER.indexOf("hinweis")]);
    const runs = whole.map((row) => row[CYCLE_HEADER.indexOf("dauer_min")]);
    const hoursKnown = a.hourRows.filter((row) => isNum(row[col("verdichter_min")])).length;
    return {
      days: hoursKnown / 24,
      starts: sum("verdichter_starts"),
      cycles: whole.length,
      meanRunMin: runs.length ? runs.reduce((x, y) => x + y, 0) / runs.length : null,
      elKwh: sum("strom_aus_leistung_kwh"),
      heatKwh: sum("waerme_aus_leistung_kwh"),
      heaterMin: known("heizstab_min") ? sum("heizstab_min") : null,
      draws: a.drawRows.length,
      drawMin: a.drawRows.reduce((total, row) => total + row[DRAW_HEADER.indexOf("dauer_min")], 0),
      boostMin: sum("angehoben_min"),
      dryRun: snap.state.dry_run,
    };
  }

  _renderFindings() {
    const host = this.$.oFind;
    const list = this._findings;
    if (!list) {
      host.replaceChildren(h("p", { class: "empty" }, "Die Auswertung wird geladen."));
      return;
    }
    if (!list.length) {
      host.replaceChildren(h("p", { class: "empty" },
        "Für eine Auswertung liegen noch zu wenige Daten vor. Sie füllt sich, sobald die Sensoren ein paar Tage aufgezeichnet haben."));
      return;
    }
    const groups = [["warn", "Fällt auf"], ["good", "Läuft gut"], ["info", "Zur Einordnung"]];
    host.replaceChildren(
      h("div", { class: "find" }, groups.map(([tone, title]) => {
        const items = list.filter((f) => f.tone === tone);
        return h("div", {},
          h("h3", {}, title),
          items.length
            ? items.map((f) => h("div", { class: "fitem" }, h("b", {}, f.title), h("p", {}, f.text)))
            : h("div", { class: "fitem" }, h("p", { class: "none" }, tone === "warn" ? "Nichts Auffälliges." : "Noch nichts.")));
      })),
      h("p", { class: "foot" },
        "Grundlage: die letzten 7 Tage, berechnet aus den Leistungs-Sensoren und dem Verlauf von Home Assistant. „Bis zu“ heißt: zeitgleich gemessen, nicht einzeln zugeordnet. Die Schwellen der Bewertungen stehen in der Anleitung."));
  }

  /* -------------------------------------------------- Zeichnen für Strom */

  /** Heute, Stunde für Stunde: woher der Verbrauch kam, dazu die PV-Erzeugung als Linie. */
  _drawHours() {
    const host = this.$?.oHours;
    const hours = this._hours;
    if (!host || !hours) return;
    const W = Math.floor(host.clientWidth);
    if (W < 120) return;
    if (!hours.some((x) => x.known)) {
      host.replaceChildren(h("p", { class: "empty" }, "Für heute liegen noch keine Stromdaten vor."));
      return;
    }
    const narrow = W < 520;
    const M = { l: narrow ? 34 : 44, r: 8 };
    const H = 220;
    const top = 10;
    const ih = H - top - 24;
    const iw = W - M.l - M.r;
    const slot = iw / 24;
    const max = Math.max(0.2, ...hours.map((x) => Math.max(x.fromPv + x.fromBat + x.fromGrid, x.pv)));
    const hi = niceTicks(0, max * 1.05, 3).at(-1) >= max ? niceTicks(0, max * 1.05, 3).at(-1) : max * 1.1;
    const y = (v) => top + ih - (v / hi) * ih;
    const svg = s("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, "aria-hidden": "true" });
    for (const tick of niceTicks(0, hi, 3)) {
      svg.append(
        s("line", { x1: M.l, x2: W - M.r, y1: y(tick), y2: y(tick), class: tick === 0 ? "axis" : "grid" }),
        s("text", { x: M.l - 8, y: y(tick) + 4, class: "tick", "text-anchor": "end" }, nf1.format(tick)));
    }
    const gap = Math.min(4, slot * 0.18);
    let line = "";
    hours.forEach((x, i) => {
      const x0 = M.l + i * slot + gap / 2;
      const w = slot - gap;
      if (x.known) {
        let base = 0;
        for (const [key, cls] of [["fromPv", "col-pv"], ["fromBat", "col-bat"], ["fromGrid", "col-grid"]]) {
          const v = x[key];
          if (v > hi * 0.004) {
            const inset = cls === "col-grid" ? 0.75 : 0;
            svg.append(s("rect", {
              x: x0 + inset, y: y(base + v) + inset, width: Math.max(1, w - 2 * inset),
              height: Math.max(1, y(base) - y(base + v) - 1.5 - 2 * inset), rx: 2, class: cls,
            }));
          }
          base += v;
        }
        line += `${line ? "L" : "M"}${(x0 - gap / 2).toFixed(1)} ${y(x.pv).toFixed(1)}H${(x0 + w + gap / 2).toFixed(1)}`;
      }
      if (i % (narrow ? 6 : 3) === 0) {
        svg.append(s("text", { x: M.l + i * slot + slot / 2, y: H - 6, class: "tick", "text-anchor": "middle" }, `${i} Uhr`));
      }
    });
    if (line) svg.append(s("path", { d: line, class: "line thin s-ink" }));
    const tip = h("div", { class: "tip" });
    const key = (cls, name) => h("span", { class: "key" }, h("i", { class: `sw ${cls}` }), h("span", {}, name));
    host.replaceChildren(
      h("div", { class: "plot-title" }, h("b", {}, "Verbrauch in kWh je Stunde, nach Herkunft"),
        key("k-pv", "Dach"), key("k-bat", "Batterie"), key("k-grid", "Netz"),
        h("span", { class: "key s-ink" }, h("i", {}), h("span", {}, "Erzeugung vom Dach"))),
      svg, tip);
    const kwh = (v) => `${nf1.format(v)} kWh`;
    host.onpointermove = (ev) => {
      const px = ev.clientX - host.getBoundingClientRect().left;
      const i = Math.floor((px - M.l) / slot);
      const x = hours[i];
      if (!x || !x.known) { tip.style.display = "none"; return; }
      tip.replaceChildren(
        h("div", { class: "when" }, `${i} bis ${i + 1} Uhr`),
        ...[["Verbrauch", x.fromPv + x.fromBat + x.fromGrid], ["vom Dach", x.fromPv], ["aus der Batterie", x.fromBat],
          ["aus dem Netz", x.fromGrid], ["Erzeugung vom Dach", x.pv]]
          .map(([name, value]) => h("div", { class: "line" }, h("span", {}, name), h("b", {}, kwh(value)))));
      tip.style.display = "block";
      const cx = M.l + (i + 0.5) * slot;
      tip.style.left = `${cx + 14 + tip.offsetWidth > W ? Math.max(0, cx - 14 - tip.offsetWidth) : cx + 14}px`;
    };
    host.onpointerdown = host.onpointermove;
    host.onpointerleave = () => { tip.style.display = "none"; };
  }

  _drawPower() {
    const host = this.$?.pPlots;
    const full = this._pRange === 168 ? this._enWeek : this._en;
    if (!host || !full) return;
    const keep = this._pRange === 24 ? Math.round(86400e3 / full.step) : full.n;
    const from = full.n - keep;
    const cut = (arr) => (arr ? arr.slice(from) : null);
    const bal = full.bal;
    const g = { t0: full.t0 + from * full.step, t1: full.t1, n: keep, step: full.step };
    const signed = (up, down) => up.map((v, b) => (v === null && down[b] === null ? null : (v ?? 0) - (down[b] ?? 0)));
    const d = {
      pv: cut(bal.pv), cons: cut(bal.cons), grid: cut(signed(bal.imp, bal.exp)), bat: cut(signed(bal.dis, bal.chg)),
      soc: cut(full.soc), wp: cut(bal.wp), wallbox: cut(bal.wallbox), small: cut(bal.small),
    };
    const any = (arr) => Boolean(arr && arr.some((v) => v !== null));
    const last = (arr) => arr.findLast((v) => v !== null) ?? null;
    const plots = [];
    if (any(d.pv) || any(d.cons)) {
      plots.push({
        title: "Erzeugung und Verbrauch in Watt", height: 170, zero: true,
        series: [
          any(d.pv) && { vals: d.pv, cls: "s-pv", kind: "area", name: "Dach", value: fmtW(last(d.pv)) },
          any(d.cons) && { vals: d.cons, cls: "s-ink", kind: "line", name: "Verbrauch", value: fmtW(last(d.cons)) },
        ].filter(Boolean),
      });
    }
    if (any(d.grid)) {
      plots.push({ title: "Netz in Watt", note: "Nach oben: Bezug. Nach unten: Einspeisung.", height: 120, zero: true,
        series: [{ vals: d.grid, cls: "s-grid", kind: "area" }] });
    }
    if (any(d.bat)) {
      plots.push({ title: "Batterie in Watt", note: "Nach oben: Entladen. Nach unten: Laden.", height: 110, zero: true,
        series: [{ vals: d.bat, cls: "s-bat", kind: "area" }] });
    }
    if (any(d.soc)) {
      plots.push({ title: "Ladestand in Prozent", height: 90, lo: 0, hi: 100,
        series: [{ vals: d.soc, cls: "s-bat", kind: "line", name: "Ladestand", value: `${nf0.format(last(d.soc))} %` }] });
    }
    if (any(d.wp) || any(d.wallbox) || any(d.small)) {
      plots.push({
        title: "Verbraucher in Watt", height: 150, zero: true,
        series: [
          any(d.small) && { vals: d.small, cls: "s-outdoor", kind: "line", thin: true, name: "Weitere Verbraucher", value: fmtW(last(d.small)) },
          any(d.wallbox) && { vals: d.wallbox, cls: "s-return", kind: "line", name: "Wallbox", value: fmtW(last(d.wallbox)) },
          any(d.wp) && { vals: d.wp, cls: "s-flow", kind: "line", name: "Wärmepumpe", value: fmtW(last(d.wp)) },
        ].filter(Boolean),
      });
    }
    if (!plots.length) {
      host.replaceChildren(h("p", { class: "empty" }, "Für diesen Zeitraum liegen noch keine Stromdaten vor."));
      return;
    }
    this._stack(host, g, plots, (i) => {
      const lines = [];
      if (any(d.pv)) lines.push(["s-pv", "Dach", fmtW(d.pv[i])]);
      if (any(d.cons)) lines.push(["s-ink", "Verbrauch", fmtW(d.cons[i])]);
      if (any(d.grid)) lines.push(["s-grid", d.grid[i] < 0 ? "Einspeisung" : "Netzbezug", fmtW(Math.abs(d.grid[i] ?? NaN))]);
      if (any(d.bat)) lines.push(["s-bat", d.bat[i] < 0 ? "Batterie lädt" : "Batterie gibt ab", fmtW(Math.abs(d.bat[i] ?? NaN))]);
      if (any(d.soc)) lines.push(["s-bat", "Ladestand", isNum(d.soc[i]) ? `${nf0.format(d.soc[i])} %` : "–"]);
      if (any(d.wp)) lines.push(["s-flow", "Wärmepumpe", fmtW(d.wp[i])]);
      if (any(d.wallbox)) lines.push(["s-return", "Wallbox", fmtW(d.wallbox[i])]);
      if (any(d.small)) lines.push(["s-outdoor", "Weitere Verbraucher", fmtW(d.small[i])]);
      return lines;
    });
  }

  /**
   * Mehrere Diagramme untereinander auf gemeinsamer Zeitachse, mit Fadenkreuz.
   * g: { t0, t1, n, step }; plots: [{ title, note, height, zero, lo, hi, series: [{ vals, cls, kind, thin, name, value }] }]
   * tipLines(i) liefert die Zeilen der Ablesung für Raster i.
   */
  _stack(host, g, plots, tipLines) {
    const W = Math.floor(host.clientWidth);
    if (W < 120) return;
    const narrow = W < 520;
    const M = { l: narrow ? 40 : 52, r: 12 };
    const iw = W - M.l - M.r;
    const x = (i) => M.l + ((i + 0.5) / g.n) * iw;
    const xt = (t) => M.l + ((t - g.t0) / (g.n * g.step)) * iw;
    const hours = (g.n * g.step) / 3600e3;
    const every = hours <= 24 ? (narrow ? 6 : 3) : hours <= 48 ? (narrow ? 12 : 6) : 24;
    const xticks = [];
    const d = new Date(g.t0);
    d.setMinutes(0, 0, 0);
    while (d.getTime() <= g.t0 + g.n * g.step) {
      if (d.getTime() >= g.t0 && d.getHours() % every === 0) xticks.push(d.getTime());
      d.setHours(d.getHours() + 1);
    }
    const nodes = [];
    plots.forEach((plot, index) => {
      const lastPlot = index === plots.length - 1;
      const all = plot.series.flatMap((sr) => sr.vals.filter((v) => v !== null));
      let lo = plot.lo ?? Math.min(...all, plot.zero ? 0 : Infinity);
      let hi = plot.hi ?? Math.max(...all, plot.zero ? 0 : -Infinity);
      if (!(hi > lo)) hi = lo + 1;
      if (plot.lo === undefined && plot.hi === undefined) {
        const pad = (hi - lo) * 0.06;
        hi += pad;
        if (lo < 0) lo -= pad;
      }
      const top = 8;
      const ih = plot.height - top - 4;
      const height = plot.height + (lastPlot ? 20 : 0);
      const y = (v) => top + ih - ((v - lo) / (hi - lo)) * ih;
      const svg = s("svg", { width: W, height, viewBox: `0 0 ${W} ${height}`, "aria-hidden": "true" });
      for (const t of xticks) svg.append(s("line", { x1: xt(t), x2: xt(t), y1: top, y2: top + ih, class: "grid" }));
      for (const tick of niceTicks(lo, hi, 3)) {
        svg.append(
          s("line", { x1: M.l, x2: W - M.r, y1: y(tick), y2: y(tick), class: tick === 0 ? "axis" : "grid" }),
          s("text", { x: M.l - 8, y: y(tick) + 4, class: "tick", "text-anchor": "end" }, nf0.format(tick + 0)));
      }
      for (const sr of plot.series) {
        let dstr = "";
        let pen = false;
        let area = "";
        let start = null;
        sr.vals.forEach((v, i) => {
          if (v === null) {
            if (pen && sr.kind === "area") area += `L${x(i - 1).toFixed(1)} ${y(0).toFixed(1)}L${x(start).toFixed(1)} ${y(0).toFixed(1)}Z`;
            pen = false;
            return;
          }
          if (!pen) start = i;
          const point = `${x(i).toFixed(1)} ${y(v).toFixed(1)}`;
          dstr += `${pen ? "L" : "M"}${point}`;
          if (sr.kind === "area") area += `${pen ? "L" : "M"}${point}`;
          pen = true;
        });
        if (pen && sr.kind === "area") area += `L${x(sr.vals.length - 1).toFixed(1)} ${y(0).toFixed(1)}L${x(start).toFixed(1)} ${y(0).toFixed(1)}Z`;
        if (area) svg.append(s("path", { d: area, class: `fillarea ${sr.cls}` }));
        svg.append(s("path", { d: dstr, class: `line ${sr.cls}${sr.thin ? " thin" : ""}` }));
      }
      if (lastPlot) {
        for (const t of xticks) {
          const date = new Date(t);
          const label = hours > 48 || date.getHours() === 0 ? tfShortDay.format(date) : tfTime.format(date);
          svg.append(s("text", { x: xt(t), y: height - 6, class: "tick", "text-anchor": "middle" }, label));
        }
      }
      nodes.push(h("div", { class: "plot-title" }, h("b", {}, plot.title),
        plot.series.filter((sr) => sr.name).map((sr) => h("span", { class: `key ${sr.cls}` }, h("i", {}),
          h("span", {}, `${sr.name} ${sr.value ?? ""}`))),
        plot.note ? h("span", {}, plot.note) : null), svg);
    });
    const cross = h("div", { class: "cross" });
    const tip = h("div", { class: "tip" });
    host.replaceChildren(...nodes, cross, tip);
    const leave = () => { cross.style.display = "none"; tip.style.display = "none"; };
    const move = (ev) => {
      const px = ev.clientX - host.getBoundingClientRect().left;
      if (px < M.l || px > W - M.r) { leave(); return; }
      const i = Math.min(g.n - 1, Math.max(0, Math.floor(((px - M.l) / iw) * g.n)));
      const when = new Date(g.t0 + (i + 0.5) * g.step);
      cross.style.display = "block";
      cross.style.left = `${x(i)}px`;
      tip.replaceChildren(
        h("div", { class: "when" }, `${tfShortDay.format(when)}, ${tfTime.format(when)} Uhr`),
        ...tipLines(i).map(([cls, name, value]) => h("div", { class: `line ${cls}` }, h("i", {}), h("span", {}, name), h("b", {}, value))));
      tip.style.display = "block";
      const tw = tip.offsetWidth;
      tip.style.left = `${x(i) + 14 + tw > W ? Math.max(0, x(i) - 14 - tw) : x(i) + 14}px`;
    };
    host.onpointermove = move;
    host.onpointerdown = move;
    host.onpointerleave = leave;
  }

  /* ------------------------------------------------------------- Export */

  _buildExportDialog(settingsHref, nav) {
    const $ = this.$;
    this._exportRange = EXPORT_RANGES[1];
    this._exportKind = "verlauf";
    $.expStatus = h("p", { class: "dlg-status", role: "status" });
    $.expMake = h("button", { class: "solid", onclick: () => this._runExport() }, "Export erstellen");
    $.expSave = h("button", { class: "solid", hidden: true, onclick: () => this._saveExport() }, "Herunterladen");
    $.expShare = h("button", { class: "plain", hidden: true, onclick: () => this._shareExport() }, "Teilen");
    $.expExtra = h("p", {});
    $.expDetails = [];
    const kinds = [
      ["verlauf", "Verlauf und Entscheidungen", "Messwerte im Zeitraster, Regelzustand, Logbuch"],
      ["effizienz", "Effizienz", "Stundenwerte, Verdichterläufe und Speicherentnahmen"],
    ];
    $.expDialog = h("dialog", { "aria-labelledby": "exp-title" },
      h("h2", { id: "exp-title" }, "Daten exportieren"),
      h("p", {}, "Eine CSV-Datei zum Auswerten. Die Regeln und die Zuordnung der Sensoren stehen im Kopf der Datei."),
      h("fieldset", {},
        h("legend", {}, "Inhalt"),
        kinds.map(([kind, label, detail]) => h("label", {},
          h("input", {
            type: "radio", name: "exp-kind", checked: kind === this._exportKind,
            onchange: () => {
              this._exportKind = kind;
              for (const el of $.expDetails) el.hidden = kind !== "verlauf";
              this._resetExport();
            },
          }),
          h("span", { class: "opt stack" }, label, h("span", { class: "sub" }, detail))))),
      h("fieldset", {},
        h("legend", {}, "Zeitraum"),
        EXPORT_RANGES.map((r) => {
          const detail = h("span", { class: "sub" }, r.detail);
          $.expDetails.push(detail);
          return h("label", {},
            h("input", {
              type: "radio", name: "exp-range", checked: r === this._exportRange,
              onchange: () => { this._exportRange = r; this._resetExport(); },
            }),
            h("span", { class: "opt" }, r.label, detail));
        })),
      $.expExtra,
      $.expStatus,
      h("div", { class: "dlg-actions" },
        h("button", { class: "plain", onclick: () => $.expDialog.close() }, "Schließen"),
        $.expShare, $.expSave, $.expMake));
    $.expExtraLink = h("a", { href: settingsHref, onclick: (e) => { $.expDialog.close(); nav(e); } }, "Sensoren für den Export wählen");
    return $.expDialog;
  }

  _openExport() {
    if (!this._snap) return;
    const count = (this._snap.export_extra || []).length;
    this.$.expExtra.replaceChildren(
      count
        ? `Im Verlauf werden zusätzlich ${count} weitere Sensoren exportiert. `
        : "Zähler, Heizstab und weitere Sensoren lassen sich in den Einstellungen hinzufügen. ",
      this.$.expExtraLink);
    this._resetExport();
    this.$.expDialog.showModal();
  }

  _resetExport() {
    const $ = this.$;
    this._export = null;
    this._exportToken = (this._exportToken || 0) + 1;
    $.expStatus.textContent = "";
    $.expStatus.classList.remove("error");
    $.expMake.hidden = false;
    $.expMake.disabled = false;
    $.expSave.hidden = true;
    $.expShare.hidden = true;
  }

  /** Welche Spalten exportiert werden. Das Schema ist fest; nicht hinterlegte Spalten bleiben leer. */
  _exportPlan() {
    const snap = this._snap;
    const cfg = snap.entities;
    const unitOf = (id) => String(this._hass.states?.[id]?.attributes?.unit_of_measurement || "");
    const power = (id) => ({ kw: 1000, mw: 1e6 }[unitOf(id).toLowerCase()] || 1);
    const energy = (id) => ({ wh: 0.001, mwh: 1000 }[unitOf(id).toLowerCase()] || 1);
    const plan = [];
    const num = (name, id, factor = 1, unit = "") => plan.push({ name, id, type: "num", factor, unit });
    const surplusFactor = power(cfg.ent_pv_surplus) * (snap.settings.surplus_sign === "export_negative" ? -1 : 1);
    num("pv_ueberschuss_w", cfg.ent_pv_surplus, surplusFactor, "W");
    num("pv_prognose_rest_heute_kwh", cfg.ent_forecast_today, energy(cfg.ent_forecast_today), "kWh");
    num("pv_prognose_morgen_kwh", cfg.ent_forecast_tomorrow, energy(cfg.ent_forecast_tomorrow), "kWh");
    num("aussen_c", cfg.ent_outdoor, 1, "°C");
    num("vorlauf_c", cfg.ent_flow, 1, "°C");
    num("ruecklauf_c", cfg.ent_return, 1, "°C");
    num("ruecklauf_soll_c", cfg.ent_return_target, 1, "°C");
    num("warmwasser_c", cfg.ent_dhw, 1, "°C");
    num("warmwasser_soll_c", cfg.ent_dhw_target, 1, "°C");
    num("strom_wp_w", cfg.ent_power_el, power(cfg.ent_power_el), "W");
    num("heizleistung_w", cfg.ent_power_heat, power(cfg.ent_power_heat), "W");
    plan.push({ name: "verdichter", id: cfg.ent_compressor, type: "binary", starts: true });
    plan.push({ name: "wp_status", id: cfg.ent_status, type: "text" });
    plan.push({ name: "regelzustand", id: snap.state.state_entity_id, type: "text" });
    plan.push({ name: "smart_grid", id: cfg.ent_smart_grid, type: "text" });
    num("parallelverschiebung_k", cfg.ent_shift, 1, "K");
    plan.push({ name: "heizstab", id: cfg.ent_heater, type: "binary" });
    plan.push({ name: "zweiter_waermeerzeuger", id: cfg.ent_second_heat, type: "binary" });
    num("strom_zaehler_kwh", cfg.ent_energy_el, energy(cfg.ent_energy_el), "kWh");
    num("waerme_heizen_zaehler_kwh", cfg.ent_energy_heat, energy(cfg.ent_energy_heat), "kWh");
    num("waerme_warmwasser_zaehler_kwh", cfg.ent_energy_dhw, energy(cfg.ent_energy_dhw), "kWh");
    num("umweltenergie_zaehler_kwh", cfg.ent_energy_env, energy(cfg.ent_energy_env), "kWh");
    num("speicher_c", cfg.ent_storage, 1, "°C");
    num("kamin_c", cfg.ent_fireplace, 1, "°C");
    plan.push({ name: "kamin_status", id: cfg.ent_fireplace_status, type: "text" });
    plan.push({ name: "sperre", id: cfg.ent_lock, type: "text" });

    const used = new Set(plan.map((col) => col.id).filter(Boolean));
    for (const id of snap.export_extra || []) {
      if (used.has(id)) continue;
      used.add(id);
      const st = this._hass.states?.[id];
      if (id.startsWith("binary_sensor.")) plan.push({ name: id, id, type: "binary" });
      else if (unitOf(id) || (st && !isGap(st.state) && Number.isFinite(Number(st.state)))) num(id, id, 1, unitOf(id));
      else plan.push({ name: id, id, type: "text" });
    }
    return plan;
  }

  async _history(id, t0, t1) {
    const hist = await this._hass.callWS({
      type: "history/history_during_period",
      start_time: new Date(t0).toISOString(), end_time: new Date(t1).toISOString(),
      entity_ids: [id], minimal_response: true, no_attributes: true, significant_changes_only: false,
    });
    return (hist?.[id] || []).map((r) => [((r.lu ?? r.lc) || 0) * 1000, r.s]);
  }

  async _runExport() {
    const $ = this.$;
    const range = this._exportRange;
    const kind = this._exportKind;
    const token = this._exportToken;
    const say = (text, error = false) => {
      if (token !== this._exportToken) return;
      $.expStatus.textContent = text;
      $.expStatus.classList.toggle("error", error);
    };
    $.expMake.disabled = true;
    const created = Date.now();
    let built;
    let summary;
    try {
      built = kind === "effizienz"
        ? await this._buildEfficiency(range, created, say, token)
        : await this._buildHistory(range, created, say, token);
    } catch (err) {
      say(`Der Export ist fehlgeschlagen: ${err?.message || err}`, true);
      $.expMake.disabled = false;
      return;
    }
    if (!built || token !== this._exportToken) return;
    if (!built.rows) {
      say("Für diesen Zeitraum ist noch nichts aufgezeichnet. Es gibt nichts zu exportieren.", true);
      $.expMake.disabled = false;
      return;
    }
    const stamp = isoLocal(created);
    const filename = `energy-hub_${kind}_${stamp.slice(0, 10)}_${stamp.slice(11, 16).replace(":", "")}_${range.hours}h.csv`;
    const bytes = new Blob([built.csv]).size;
    const size = bytes > 1e6 ? `${nf1.format(bytes / 1e6)} MB` : `${nf0.format(Math.max(1, bytes / 1000))} kB`;
    this._export = { csv: built.csv, filename };
    summary = kind === "effizienz"
      ? `Fertig: ${nf0.format(built.rows)} Stunden, ${nf0.format(built.cycles)} Verdichterläufe, ${nf0.format(built.draws)} Speicherentnahmen, ${size}.`
      : `Fertig: ${nf0.format(built.rows)} Zeilen, ${built.columns} Spalten, ${size}.`;
    say(built.note ? `${summary} ${built.note}` : summary);
    $.expMake.hidden = true;
    $.expSave.hidden = false;
    let canShare = false;
    try {
      canShare = Boolean(navigator.canShare?.({ files: [new File([""], filename, { type: "text/csv" })] }));
    } catch (_err) {
      canShare = false;
    }
    $.expShare.hidden = !canShare;
  }

  async _buildHistory(range, created, say, token) {
    const snap = this._snap;
    const step = range.step;
    const t1 = Math.ceil(created / step) * step;
    const t0 = t1 - range.hours * 3600e3;
    const n = Math.round((t1 - t0) / step);
    const plan = this._exportPlan();
    const total = plan.filter((col) => col.id).length;
    const columns = [];
    let done = 0;
    for (const col of plan) {
      let rows = [];
      if (col.id) {
        say(`Lade ${++done} von ${total}: ${col.name}`);
        rows = await this._history(col.id, t0, created);
        if (token !== this._exportToken) return null;
      }
      if (col.type === "num") {
        const values = stepSeries(rows, t0, step, n, created).map((v) => (v === null ? null : v * col.factor));
        columns.push({ name: col.name, entity: col.id, unit: col.unit, values });
      } else if (col.type === "binary") {
        const { share, starts } = stepBinary(rows, t0, step, n, created);
        columns.push({ name: `${col.name}_anteil`, entity: col.id, values: share });
        if (col.starts) columns.push({ name: `${col.name}_starts`, entity: col.id, values: starts });
      } else {
        columns.push({ name: col.name, entity: col.id, values: stepText(rows, t0, step, n, created) });
      }
    }
    return buildExport({ version: snap.version, created, t0, step, n, columns, log: snap.log, settings: snap.settings });
  }

  async _buildEfficiency(range, created, say, token) {
    const snap = this._snap;
    const cfg = snap.entities;
    const step = 3600e3;
    const top = new Date(created);
    top.setMinutes(0, 0, 0);
    const t0 = top.getTime() + step - range.hours * 3600e3;
    const unitOf = (id) => String(this._hass.states?.[id]?.attributes?.unit_of_measurement || "").toLowerCase();
    const power = (id) => ({ kw: 1000, mw: 1e6 }[unitOf(id)] || 1);
    const energy = (id) => ({ wh: 0.001, mwh: 1000 }[unitOf(id)] || 1);
    const source = {
      comp: cfg.ent_compressor, status: cfg.ent_status, mode: snap.state.state_entity_id,
      outdoor: cfg.ent_outdoor, flow: cfg.ent_flow, ret: cfg.ent_return, retTarget: cfg.ent_return_target,
      dhw: cfg.ent_dhw, dhwTarget: cfg.ent_dhw_target, pEl: cfg.ent_power_el, pHeat: cfg.ent_power_heat,
      surplus: cfg.ent_pv_surplus, heater: cfg.ent_heater, second: cfg.ent_second_heat,
      eEl: cfg.ent_energy_el, eHeat: cfg.ent_energy_heat, eDhw: cfg.ent_energy_dhw, eEnv: cfg.ent_energy_env,
      storage: cfg.ent_storage, fireplace: cfg.ent_fireplace, lock: cfg.ent_lock,
    };
    const factors = {
      pEl: power(source.pEl), pHeat: power(source.pHeat),
      surplus: power(source.surplus) * (snap.settings.surplus_sign === "export_negative" ? -1 : 1),
      eEl: energy(source.eEl), eHeat: energy(source.eHeat), eDhw: energy(source.eDhw), eEnv: energy(source.eEnv),
    };
    const wanted = EFF_KEYS.filter((key) => source[key]);
    const data = {};
    let done = 0;
    for (const key of wanted) {
      say(`Lade ${++done} von ${wanted.length}: ${source[key]}`);
      data[key] = await this._history(source[key], t0, created);
      if (token !== this._exportToken) return null;
    }
    say("Werte aus …");
    const analysis = analyseEfficiency(data, factors, t0, created, step, {
      regen: matcher(snap.settings.lock_regen_value),
      fireplaceOnC: source.fireplace ? Number(snap.settings.fireplace_on_c) : null,
      storageReadyC: source.storage ? Number(snap.settings.storage_ready_c) : null,
      storageReadyDeltaK: source.storage ? Number(snap.settings.storage_ready_delta_k) : null,
    });
    const built = buildEfficiencyExport({
      version: snap.version, created, t0, step, analysis, settings: snap.settings, entities: source,
    });
    const missing = [];
    if (!source.comp) missing.push("Verdichter");
    if (!source.pEl && !source.eEl) missing.push("Strom der Wärmepumpe");
    if (!source.pHeat && !source.eHeat) missing.push("Wärme");
    if (missing.length) built.note = `Nicht hinterlegt und deshalb leer: ${missing.join(", ")}.`;
    return built;
  }

  _saveExport() {
    if (!this._export) return;
    const { csv, filename } = this._export;
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = h("a", { href: url, download: filename, hidden: true });
    this.shadowRoot.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
    this.$.expStatus.textContent = `Gespeichert als ${filename}.`;
  }

  async _shareExport() {
    if (!this._export) return;
    const { csv, filename } = this._export;
    try {
      await navigator.share({ files: [new File([csv], filename, { type: "text/csv" })], title: "Energy Hub Export" });
    } catch (err) {
      if (err?.name === "AbortError") return;
      this.$.expStatus.textContent = `Teilen hat nicht geklappt (${err?.message || err}). Nimm „Herunterladen“.`;
      this.$.expStatus.classList.add("error");
    }
  }

  /* ------------------------------------------------------------ Verlauf */

  /** Wie oft und wie lange heute und in den letzten 7 Tagen Wärme aus dem Speicher kam. */
  async _loadDraws() {
    const snap = this._snap;
    const id = snap?.entities?.ent_lock;
    if (!id || !this._hass?.callWS) return;
    const now = Date.now();
    const t0 = now - 7 * 86400e3;
    try {
      const rows = await this._history(id, t0, now);
      const active = matcher(snap.settings.lock_regen_value);
      const midnight = new Date(now);
      midnight.setHours(0, 0, 0, 0);
      const day = episodes(rows, active, midnight.getTime(), now);
      this._draws = {
        week: episodes(rows, active, t0, now).length,
        today: day.length,
        todayMs: day.reduce((sum, e) => sum + (e.end - e.start), 0),
      };
      this._queueRender();
    } catch (_err) {
      this._draws = null;
    }
  }

  async _loadHistory() {
    const snap = this._snap;
    if (!snap || !this._hass?.callWS) return;
    const range = this._range;
    const t1 = Date.now();
    const t0 = t1 - range.hours * 3600e3;
    const cfg = snap.entities;
    const numeric = [
      { key: "surplus", id: cfg.ent_pv_surplus }, ...SERIES.map((x) => ({ key: x.key, id: cfg[x.ent] })),
      { key: "storage", id: cfg.ent_storage }, { key: "fireplace", id: cfg.ent_fireplace },
      { key: "retTarget", id: cfg.ent_storage ? cfg.ent_return_target : null },
    ].filter((x) => x.id);
    const lockId = cfg.ent_lock;
    const modeId = snap.state.state_entity_id;
    this.$.plots.classList.add("loading");
    const token = (this._loadToken = (this._loadToken || 0) + 1);
    const start = new Date(t0).toISOString();
    const end = new Date(t1).toISOString();
    const raw = {};

    try {
      let pending = numeric.map((x) => x.id);
      if (range.hours > 48 && pending.length) {
        // Lange Zeiträume aus der Langzeitstatistik, das spart viel Datenverkehr
        const stats = await this._hass.callWS({
          type: "recorder/statistics_during_period", start_time: start, end_time: end,
          statistic_ids: pending, period: "hour", types: ["mean"],
        });
        for (const id of pending) {
          const rows = (stats?.[id] || []).filter((r) => isNum(r.mean));
          if (rows.length) raw[id] = rows.map((r) => [new Date(r.start).getTime() + 1800e3, r.mean]);
        }
        pending = pending.filter((id) => !raw[id]);
      }
      const ids = [...pending, ...(modeId ? [modeId] : []), ...(lockId ? [lockId] : [])];
      if (ids.length) {
        const hist = await this._hass.callWS({
          type: "history/history_during_period", start_time: start, end_time: end,
          entity_ids: ids, minimal_response: true, no_attributes: true, significant_changes_only: false,
        });
        for (const id of ids) {
          raw[id] = (hist?.[id] || []).map((r) => [((r.lu ?? r.lc) || 0) * 1000, r.s]);
        }
      }
    } catch (err) {
      if (token === this._loadToken) {
        this.$.plots.classList.remove("loading");
        this.$.plots.replaceChildren(h("p", { class: "empty" },
          `Der Verlauf konnte nicht geladen werden: ${err?.message || err}`));
      }
      return;
    }
    if (token !== this._loadToken) return;

    const n = range.buckets;
    const step = (t1 - t0) / n;
    const chart = { t0, t1, n, step, series: {}, modes: new Array(n).fill(null) };
    for (const { key, id } of numeric) {
      const st = this._hass.states?.[id];
      const unit = String(st?.attributes?.unit_of_measurement || "").toLowerCase();
      let factor = 1;
      if (key === "surplus") {
        factor = { kw: 1000, mw: 1e6 }[unit] || 1;
        if (snap.settings.surplus_sign === "export_negative") factor = -factor;
      }
      chart.series[key] = this._bucket(raw[id] || [], t0, step, n, factor);
    }
    if (modeId) {
      let i = 0;
      let current = null;
      const rows = raw[modeId] || [];
      for (let b = 0; b < n; b++) {
        const edge = t0 + (b + 1) * step;
        while (i < rows.length && rows[i][0] <= edge) current = rows[i++][1];
        chart.modes[b] = ["normal", "boost", "setback"].includes(current) ? current : null;
      }
    }
    if (lockId) {
      const active = matcher(snap.settings.lock_regen_value);
      chart.draw = stepText(raw[lockId] || [], t0, step, n, t1).map((v) => (v === null ? null : active(v)));
      chart.drawCount = episodes(raw[lockId] || [], active, t0, t1).length;
    }
    const onC = Number(snap.settings.fireplace_on_c);
    if (chart.series.fireplace) chart.fire = chart.series.fireplace.map((v) => (v === null ? null : v >= onC));
    if (chart.series.storage) {
      const target = chart.series.retTarget;
      const delta = Number(snap.settings.storage_ready_delta_k);
      const fixedC = Number(snap.settings.storage_ready_c);
      chart.readyAt = chart.series.storage.map((_v, b) => (target && target[b] !== null ? target[b] + delta : fixedC));
      chart.readyRelative = Boolean(target && target.some((v) => v !== null));
      chart.ready = chart.series.storage.map((v, b) => (v === null ? null : v >= chart.readyAt[b]));
    }
    this._chart = chart;
    this.$.plots.classList.remove("loading");
    this._drawPlots();
    if (!this.$.table.hidden) this._drawTable();
  }

  /** Mittelwert je Zeitabschnitt; ohne neue Messung gilt der letzte Wert weiter. */
  _bucket(rows, t0, step, n, factor) {
    const sum = new Array(n).fill(0);
    const cnt = new Array(n).fill(0);
    let before = null;
    for (const [t, sv] of rows) {
      const v = Number(sv);
      if (sv === "" || sv === null || !Number.isFinite(v)) continue;
      const b = Math.floor((t - t0) / step);
      if (b < 0) { before = v * factor; continue; }
      if (b >= n) continue;
      sum[b] += v * factor;
      cnt[b] += 1;
    }
    const out = new Array(n).fill(null);
    let last = before;
    for (let b = 0; b < n; b++) {
      if (cnt[b]) last = sum[b] / cnt[b];
      out[b] = last;
    }
    return out;
  }

  _drawPlots() {
    const chart = this._chart;
    const host = this.$?.plots;
    if (!chart || !host) return;
    const W = Math.floor(host.clientWidth);
    if (W < 120) return;
    const narrow = W < 520;
    const M = { l: narrow ? 38 : 48, r: 12 };
    const iw = W - M.l - M.r;
    const x = (i) => M.l + ((i + 0.5) / chart.n) * iw;
    const xt = (t) => M.l + ((t - chart.t0) / (chart.t1 - chart.t0)) * iw;
    const snap = this._snap;
    const set = snap.settings;
    const nodes = [];

    // Senkrechte Hilfslinien und Beschriftung der Zeitachse
    const hours = (chart.t1 - chart.t0) / 3600e3;
    const every = hours <= 24 ? (narrow ? 6 : 3) : hours <= 48 ? (narrow ? 12 : 6) : 24;
    const xticks = [];
    const d = new Date(chart.t0);
    d.setMinutes(0, 0, 0);
    while (d.getTime() <= chart.t1) {
      if (d.getTime() >= chart.t0 && d.getHours() % every === 0) xticks.push(d.getTime());
      d.setHours(d.getHours() + 1);
    }
    const vgrid = (h0, h1) => xticks.map((t) => s("line", { x1: xt(t), x2: xt(t), y1: h0, y2: h1, class: "grid" }));

    const path = (vals, y) => {
      let dstr = "";
      let pen = false;
      vals.forEach((v, i) => {
        if (v === null) { pen = false; return; }
        dstr += `${pen ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`;
        pen = true;
      });
      return dstr;
    };

    const plot = (height, lo, hi, count, draw) => {
      const top = 8;
      const ih = height - top - 4;
      const y = (v) => top + ih - ((v - lo) / (hi - lo)) * ih;
      const svg = s("svg", { width: W, height, viewBox: `0 0 ${W} ${height}`, "aria-hidden": "true" });
      svg.append(...vgrid(top, top + ih));
      for (const tick of niceTicks(lo, hi, count)) {
        svg.append(
          s("line", { x1: M.l, x2: W - M.r, y1: y(tick), y2: y(tick), class: tick === 0 ? "axis" : "grid" }),
          s("text", { x: M.l - 8, y: y(tick) + 4, class: "tick", "text-anchor": "end" }, nf0.format(tick + 0)));
      }
      draw(svg, y, top, ih);
      return svg;
    };

    // 1. PV-Überschuss
    const surplus = chart.series.surplus;
    if (surplus && surplus.some((v) => v !== null)) {
      const vals = surplus.filter((v) => v !== null);
      const lo = Math.min(0, ...vals);
      const hi = Math.max(...vals, Number(set.boost_on_w) * 1.25, 500);
      nodes.push(h("div", { class: "plot-title" }, h("b", {}, "PV-Überschuss in Watt")));
      nodes.push(plot(150, lo, hi, 4, (svg, y) => {
        const line = path(surplus, y);
        const first = surplus.findIndex((v) => v !== null);
        if (line) {
          svg.append(
            s("path", { d: `${line}L${x(chart.n - 1).toFixed(1)} ${y(0)}L${x(first).toFixed(1)} ${y(0)}Z`, class: "area" }),
            s("path", { d: line, class: "line s-pv" }));
        }
        for (const [value, label] of [[set.boost_on_w, "Anheben ab"], [set.boost_off_w, "Ende unter"]]) {
          if (!isNum(Number(value)) || value < lo || value > hi) continue;
          svg.append(
            s("line", { x1: M.l, x2: W - M.r, y1: y(value), y2: y(value), class: "ref" }),
            s("text", { x: W - M.r, y: y(value) - 5, class: "ref-label", "text-anchor": "end" }, `${label} ${fmtW(Number(value))}`));
        }
      }));
    }

    // 2. Temperaturen
    const temps = SERIES.filter((x) => chart.series[x.key]?.some((v) => v !== null));
    if (temps.length) {
      const all = temps.flatMap((x) => chart.series[x.key].filter((v) => v !== null));
      const lo = Math.floor((Math.min(...all) - 2) / 5) * 5;
      const hi = Math.ceil((Math.max(...all) + 2) / 5) * 5;
      nodes.push(h("div", { class: "plot-title" }, h("b", {}, "Temperaturen in °C"),
        temps.map((x) => h("span", { class: `key ${x.cls}` }, h("i", {}),
          h("span", {}, `${x.name} ${fmtC(chart.series[x.key].at(-1))}`)))));
      nodes.push(plot(200, lo, hi, 3, (svg, y) => {
        // Außen zuerst, damit die Anlagentemperaturen darüber liegen
        for (const x of [...temps].reverse()) {
          svg.append(s("path", { d: path(chart.series[x.key], y), class: `line ${x.cls}${x.key === "outdoor" ? " thin" : ""}` }));
        }
      }));
    }

    // 3. Speicher: Temperatur und die Schwelle, ab der er als bereit gilt
    const store = chart.series.storage;
    if (store && store.some((v) => v !== null)) {
      const all = [...store.filter((v) => v !== null), ...chart.readyAt];
      const lo = Math.floor((Math.min(...all) - 2) / 5) * 5;
      const hi = Math.ceil((Math.max(...all) + 2) / 5) * 5;
      const label = chart.readyRelative
        ? `bereit ab Rücklaufsoll + ${nf0.format(set.storage_ready_delta_k)} K`
        : `bereit ab ${fmtC(Number(set.storage_ready_c))}`;
      nodes.push(h("div", { class: "plot-title" }, h("b", {}, "Speicher in °C"),
        h("span", { class: "key s-store" }, h("i", {}), h("span", {}, `Speicher ${fmtC(store.at(-1))}`)),
        h("span", {}, `Gestrichelt: ${label}, zuletzt ${fmtC(chart.readyAt.at(-1))}`)));
      nodes.push(plot(130, lo, hi, 3, (svg, y) => {
        svg.append(
          s("path", { d: path(chart.readyAt, y), class: "ref" }),
          s("path", { d: path(store, y), class: "line s-store" }));
      }));
    }

    // 4. Kamin und Speicher als Zustände: je Zeile ein Balken, solange der Zustand gilt
    const lanes = [
      ["Kamin", chart.fire], ["bereit", chart.ready], ["liefert", chart.draw],
    ].filter(([, arr]) => arr);
    if (lanes.length) {
      const laneH = 18;
      const height = lanes.length * laneH + 6;
      const svg = s("svg", { width: W, height, viewBox: `0 0 ${W} ${height}`, "aria-hidden": "true" });
      svg.append(...vgrid(2, height - 4));
      lanes.forEach(([label, arr], row) => {
        const top = 3 + row * laneH;
        svg.append(
          s("line", { x1: M.l, x2: W - M.r, y1: top + 12.5, y2: top + 12.5, class: "lane" }),
          s("text", { x: M.l - 8, y: top + 11, class: "tick", "text-anchor": "end" }, label));
        let i = 0;
        while (i < chart.n) {
          let e = i;
          while (e + 1 < chart.n && arr[e + 1] === arr[i]) e++;
          if (arr[i] === true) {
            const x0 = M.l + (i / chart.n) * iw;
            const x1 = M.l + ((e + 1) / chart.n) * iw;
            svg.append(s("rect", { x: x0, y: top, width: Math.max(1.5, x1 - x0), height: 12, class: "block" }));
          }
          i = e + 1;
        }
      });
      const count = isNum(chart.drawCount)
        ? ` Wärme aus dem Speicher geholt: ${chart.drawCount}-mal im gezeigten Zeitraum.` : "";
      nodes.push(h("div", { class: "plot-title" }, h("b", {}, "Kamin und Speicher"),
        h("span", {}, `Balken: Kamin brennt, Speicher ist bereit, Speicher liefert Wärme.${count}`)));
      nodes.push(svg);
    }

    // 5. Eingriffe: nach oben = angehoben, nach unten = abgesenkt
    const stripH = 74;
    const mid = 26;
    const strip = s("svg", { width: W, height: stripH, viewBox: `0 0 ${W} ${stripH}`, "aria-hidden": "true" });
    strip.append(...vgrid(4, 48));
    let b = 0;
    while (b < chart.n) {
      const mode = chart.modes[b];
      let e = b;
      while (e + 1 < chart.n && chart.modes[e + 1] === mode) e++;
      if (mode === "boost" || mode === "setback") {
        const x0 = M.l + (b / chart.n) * iw;
        const x1 = M.l + ((e + 1) / chart.n) * iw;
        strip.append(s("rect", { x: x0, y: mode === "boost" ? mid - 18 : mid + 1, width: Math.max(1.5, x1 - x0), height: 17, class: "block" }));
      }
      b = e + 1;
    }
    strip.append(
      s("line", { x1: M.l, x2: W - M.r, y1: mid, y2: mid, class: "axis" }),
      s("text", { x: M.l - 8, y: mid - 6, class: "tick", "text-anchor": "end" }, narrow ? "auf" : "hoch"),
      s("text", { x: M.l - 8, y: mid + 14, class: "tick", "text-anchor": "end" }, narrow ? "ab" : "runter"));
    for (const t of xticks) {
      const date = new Date(t);
      const label = hours > 48 ? tfShortDay.format(date) : date.getHours() === 0 ? tfShortDay.format(date) : tfTime.format(date);
      strip.append(s("text", { x: xt(t), y: stripH - 6, class: "tick", "text-anchor": "middle" }, label));
    }
    nodes.push(h("div", { class: "plot-title" }, h("b", {}, "Eingriffe"),
      h("span", {}, "Balken nach oben: angehoben. Balken nach unten: abgesenkt.")));
    nodes.push(strip);

    if (nodes.length <= 2 && !chart.modes.some(Boolean)) {
      nodes.unshift(h("p", { class: "empty" },
        "Für diesen Zeitraum liegen noch keine aufgezeichneten Werte vor. Der Verlauf füllt sich, sobald die Sensoren Daten liefern."));
    }

    // Fadenkreuz mit Ablesung aller Reihen
    const cross = h("div", { class: "cross" });
    const tip = h("div", { class: "tip" });
    const host2 = this.$.plots;
    host2.replaceChildren(...nodes, cross, tip);
    const move = (ev) => {
      const rect = host2.getBoundingClientRect();
      const px = ev.clientX - rect.left;
      if (px < M.l || px > W - M.r) { leave(); return; }
      const i = Math.min(chart.n - 1, Math.max(0, Math.floor(((px - M.l) / iw) * chart.n)));
      cross.style.display = "block";
      cross.style.left = `${x(i)}px`;
      const when = new Date(chart.t0 + (i + 0.5) * chart.step);
      const lines = [];
      if (chart.series.surplus) lines.push(["s-pv", "PV-Überschuss", fmtW(chart.series.surplus[i])]);
      for (const sr of SERIES) {
        if (chart.series[sr.key]) lines.push([sr.cls, sr.name, fmtC(chart.series[sr.key][i])]);
      }
      if (chart.series.storage) lines.push(["s-store", "Speicher", fmtC(chart.series.storage[i])]);
      const states = [];
      if (chart.series.fireplace) {
        states.push(["Kamin", `${fmtC(chart.series.fireplace[i])}${chart.fire?.[i] ? ", brennt" : ""}`]);
      }
      if (chart.draw || chart.ready) {
        states.push(["Speicher", chart.draw?.[i] ? "liefert Wärme" : chart.ready?.[i] ? "bereit" : chart.ready?.[i] === false ? "nicht bereit" : "–"]);
      }
      const mode = chart.modes[i];
      tip.replaceChildren(
        h("div", { class: "when" }, `${tfShortDay.format(when)}, ${tfTime.format(when)} Uhr`),
        ...lines.map(([cls, name, value]) => h("div", { class: `line ${cls}` }, h("i", {}), h("span", {}, name), h("b", {}, value))),
        ...states.map(([name, value]) => h("div", { class: "line" }, h("span", {}, name), h("b", {}, value))),
        h("div", { class: "line" }, h("span", {}, "Eingriff"), h("b", {}, mode ? { normal: "keiner", boost: "angehoben", setback: "abgesenkt" }[mode] : "–")));
      tip.style.display = "block";
      const tw = tip.offsetWidth;
      tip.style.left = `${x(i) + 14 + tw > W ? Math.max(0, x(i) - 14 - tw) : x(i) + 14}px`;
    };
    const leave = () => { cross.style.display = "none"; tip.style.display = "none"; };
    host2.onpointermove = move;
    host2.onpointerdown = move;
    host2.onpointerleave = leave;
  }

  _toggleTable() {
    const $ = this.$;
    $.table.hidden = !$.table.hidden;
    $.tableBtn.setAttribute("aria-expanded", String(!$.table.hidden));
    $.tableBtn.textContent = $.table.hidden ? "Werte als Tabelle" : "Tabelle ausblenden";
    if (!$.table.hidden) this._drawTable();
  }

  _drawTable() {
    const chart = this._chart;
    if (!chart) return;
    const per = Math.max(1, Math.round(3600e3 / chart.step));
    const cols = [];
    if (chart.series.surplus) cols.push(["PV-Überschuss", (i) => fmtW(chart.series.surplus[i])]);
    for (const sr of SERIES) {
      if (chart.series[sr.key]) cols.push([sr.name, (i) => fmtC(chart.series[sr.key][i])]);
    }
    if (chart.series.storage) cols.push(["Speicher", (i) => fmtC(chart.series.storage[i])]);
    if (chart.series.fireplace) cols.push(["Kamin", (i) => fmtC(chart.series.fireplace[i])]);
    if (chart.draw) cols.push(["Speicher liefert", (i) => (chart.draw[i] ? "ja" : chart.draw[i] === false ? "nein" : "")]);
    const rows = [];
    for (let i = chart.n - 1; i >= 0; i -= per) {
      const when = new Date(chart.t0 + (i + 0.5) * chart.step);
      const mode = chart.modes[i];
      rows.push(h("tr", {},
        h("td", {}, `${tfShortDay.format(when)} ${tfTime.format(when)}`),
        cols.map(([, get]) => h("td", {}, get(i))),
        h("td", {}, mode ? { normal: "–", boost: "angehoben", setback: "abgesenkt" }[mode] : "")));
    }
    this.$.table.replaceChildren(h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Zeit"), cols.map(([name]) => h("th", {}, name)), h("th", {}, "Eingriff"))),
      h("tbody", {}, rows)));
  }
}

if (!customElements.get("energy-hub-panel")) {
  customElements.define("energy-hub-panel", EnergyHubPanel);
}
