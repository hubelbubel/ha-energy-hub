/*
 * WP Leitstand – Panel für die Seitenleiste von Home Assistant.
 * Reines JavaScript ohne Build-Schritt und ohne externe Abhängigkeiten.
 *
 * Aufbau der Seite:
 *   Lage      – ein Satz, was die Heizung gerade tut und warum; daneben das Anlagenschema
 *   Kennwerte – PV-Überschuss, Prognose, Leistung
 *   Verlauf   – Überschuss, Temperaturen und Eingriffe auf einer gemeinsamen Zeitachse
 *   Logbuch   – was wann und warum geschaltet wurde; daneben die Regeln in Klartext
 */

const DOMAIN = "wp_leitstand";
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
  --c-warn: #e66767;
}
* { box-sizing: border-box; }
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
.bar a { color: inherit; font-size: 14px; text-decoration: none; padding: 8px; border-radius: 6px; }
.bar a:hover { background: color-mix(in srgb, currentColor 10%, transparent); }

main { max-width: 1240px; margin: 0 auto; padding: 28px 24px 64px; }
section + section { margin-top: 36px; }
h2 { margin: 0 0 14px; font-size: 16px; font-weight: 500; }

/* ---- Lage ---- */
.lage { display: grid; grid-template-columns: minmax(0, 5fr) minmax(0, 6fr); gap: 40px; align-items: start; }
.headline { margin: 4px 0 12px; font-size: 32px; line-height: 1.18; font-weight: 400; letter-spacing: -0.012em; max-width: 18em; text-wrap: balance; }
.reason { margin: 0; color: var(--ink-2); font-size: 16px; max-width: 34em; }
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
.schema.running .pulse { opacity: 0.75; animation: flow 1.6s linear infinite; }
.schema.running .fan { animation: spin 2.4s linear infinite; }
.schema text { fill: var(--ink); font-size: 13px; }
.schema .cap { fill: var(--ink-2); font-size: 12px; }
.schema .val { font-size: 17px; font-weight: 500; }
@keyframes flow { to { stroke-dashoffset: -24; } }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .schema.running .pulse, .schema.running .fan { animation: none; }
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
.plots .ref-label { fill: var(--ink-2); font-size: 11px; paint-order: stroke; stroke: var(--surface); stroke-width: 4px; stroke-linejoin: round; }
.plots .block { fill: var(--ink); opacity: 0.72; }
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

class WpLeitstandPanel extends HTMLElement {
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
    this._refresh = setInterval(() => this._loadHistory(), 5 * 60000);
    if (this._hass) this._subscribe();
  }

  disconnectedCallback() {
    clearInterval(this._clock);
    clearInterval(this._refresh);
    this._resize?.disconnect();
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
        if (first) this._loadHistory();
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

    root.append(
      h("style", {}, STYLE),
      h("header", { class: "bar" }, this._menu, h("h1", {}, "Wärmepumpe"),
        h("a", { href: settingsHref, onclick: nav }, "Einstellungen")),
      h("main", {},
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
          h("div", {}, h("h2", {}, "So wird geregelt"), $.rules)))
    );

    this._resize = new ResizeObserver(() => this._drawPlots());
    this._resize.observe($.plots);
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
    return s("svg", { class: "schema", viewBox: "0 0 560 300", role: "img", "aria-label": "Anlagenschema der Wärmepumpe mit aktuellen Temperaturen" },
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

    // Lage: ein Satz, was gerade passiert
    const since = fmtClock(st.since);
    let headline;
    if (st.override) {
      const until = st.override.until ? `bis ${fmtClock(st.override.until)}` : "bis du ihn beendest";
      headline = `Handbetrieb: ${MODE_NAME[st.override.mode]}, ${until}.`;
    } else if (!st.automation) {
      headline = "Die Automatik ist aus. Die Heizung läuft normal.";
    } else if (st.mode === "boost") {
      headline = `Die Heizung ist seit ${since} angehoben.`;
    } else if (st.mode === "setback") {
      headline = `Die Heizung ist seit ${since} abgesenkt.`;
    } else {
      headline = "Die Heizung läuft im Normalbetrieb.";
    }
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

    this._renderFacts();
    this._renderRules();
    this._renderLog(false);
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
      h("p", { class: "foot" }, `WP Leitstand ${this._snap.version}`)
    );
  }

  /* ------------------------------------------------------------ Logbuch */

  _entryTitle(e) {
    if (e.kind === "switch") {
      if (e.to === "boost") return "Angehoben";
      if (e.to === "setback") return "Abgesenkt";
      if (e.from === "boost") return "Anheben beendet";
      if (e.from === "setback") return "Absenken beendet";
      return "Normalbetrieb";
    }
    return { override: "Handbetrieb", automation: "Automatik", error: "Fehler", reapply: "Erneut gesetzt" }[e.kind] || "Hinweis";
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

  /* ------------------------------------------------------------ Verlauf */

  async _loadHistory() {
    const snap = this._snap;
    if (!snap || !this._hass?.callWS) return;
    const range = this._range;
    const t1 = Date.now();
    const t0 = t1 - range.hours * 3600e3;
    const cfg = snap.entities;
    const numeric = [{ key: "surplus", id: cfg.ent_pv_surplus }, ...SERIES.map((x) => ({ key: x.key, id: cfg[x.ent] }))]
      .filter((x) => x.id);
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
      const ids = [...pending, ...(modeId ? [modeId] : [])];
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

    // 3. Eingriffe: nach oben = angehoben, nach unten = abgesenkt
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
      const mode = chart.modes[i];
      tip.replaceChildren(
        h("div", { class: "when" }, `${tfShortDay.format(when)}, ${tfTime.format(when)} Uhr`),
        ...lines.map(([cls, name, value]) => h("div", { class: `line ${cls}` }, h("i", {}), h("span", {}, name), h("b", {}, value))),
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

if (!customElements.get("wp-leitstand-panel")) {
  customElements.define("wp-leitstand-panel", WpLeitstandPanel);
}
