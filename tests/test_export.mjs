// Tests der Export-Funktionen des Panels. Aufruf:  node --test tests/
// Die Funktionen sind reine Rechenfunktionen; der Browser wird nur für den Import nachgebildet.
process.env.TZ = "Europe/Berlin";
globalThis.HTMLElement = class {};
globalThis.customElements = { get: () => undefined, define: () => {} };

import assert from "node:assert/strict";
import { test } from "node:test";

const m = await import("../custom_components/energy_hub/frontend/energy-hub-panel.js");

const T0 = new Date("2026-11-16T10:00:00+01:00").getTime();
const MIN = 60e3;
const at = (minutes) => T0 + minutes * MIN;
const near = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);

/** Zerlegt eine CSV-Zeile nach RFC 4180. */
function parseLine(line) {
  const cells = [];
  let cur = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (quoted) {
      if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; } else if (ch === '"') quoted = false; else cur += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") { cells.push(cur); cur = ""; } else cur += ch;
  }
  cells.push(cur);
  return cells;
}

test("stepSeries bildet zeitgewichtete Mittelwerte", () => {
  const rows = [[at(-5), "10"], [at(0.5), "20"]];
  const out = m.stepSeries(rows, T0, MIN, 3, at(3));
  near(out[0], 15); // 30 s lang 10, 30 s lang 20
  near(out[1], 20);
  near(out[2], 20); // ohne neue Meldung gilt der letzte Wert weiter
});

test("stepSeries lässt Lücken und die Zukunft aus", () => {
  const rows = [[at(0), "10"], [at(0.5), "unavailable"], [at(1.5), "30"]];
  const out = m.stepSeries(rows, T0, MIN, 4, at(2.5));
  near(out[0], 10); // nur die ersten 30 s sind bekannt
  near(out[1], 30);
  near(out[2], 30); // angebrochenes Raster bis tEnd
  assert.equal(out[3], null); // liegt nach tEnd
  assert.deepEqual(m.stepSeries([], T0, MIN, 2, at(2)), [null, null]);
  assert.deepEqual(m.stepSeries([[at(0.2), "abc"]], T0, MIN, 1, at(1)), [null]);
});

test("stepText liefert den Zustand am Rasterende", () => {
  const rows = [[at(-1), "Aus"], [at(0.4), "Heizen"], [at(1.2), "unknown"], [at(2.5), "Abtauen"]];
  assert.deepEqual(m.stepText(rows, T0, MIN, 4, at(3.5)), ["Heizen", null, "Abtauen", "Abtauen"]);
});

test("stepBinary zählt Laufanteil und Einschaltvorgänge", () => {
  const rows = [[at(-1), "off"], [at(0.25), "on"], [at(0.75), "off"], [at(1.5), "on"], [at(1.6), "unavailable"], [at(1.7), "on"]];
  const { share, starts } = m.stepBinary(rows, T0, MIN, 3, at(3));
  near(share[0], 0.5);
  near(share[1], 0.4 / 0.9); // 0,1 min Lücke zählt nicht mit
  near(share[2], 1);
  assert.deepEqual(starts, [1, 1, 0]); // "nicht verfügbar" und zurück ist kein neuer Start
});

test("csvCell maskiert nur, wo es nötig ist", () => {
  assert.equal(m.csvCell(null), "");
  assert.equal(m.csvCell(12.34567), "12.346");
  assert.equal(m.csvCell(-0.0001), "0");
  assert.equal(m.csvCell("Heizen"), "Heizen");
  assert.equal(m.csvCell('a "b", c'), '"a ""b"", c"');
  assert.equal(m.csvCell("zwei\nZeilen"), '"zwei\nZeilen"');
});

test("isoLocal schreibt Ortszeit mit Versatz", () => {
  assert.equal(m.isoLocal(T0), "2026-11-16T10:00:00+01:00");
  assert.equal(m.isoLocal(new Date("2026-07-01T12:00:00Z").getTime()), "2026-07-01T14:00:00+02:00");
});

test("buildExport: Kopf, Spalten, Ereignisse, leere Ränder", () => {
  const n = 6;
  const columns = [
    { name: "pv_ueberschuss_w", entity: "sensor.pv", unit: "W", values: [null, null, 1200.5, 1800, null, null] },
    { name: "wp_status", entity: "sensor.wp_status", values: [null, null, "Heizen", "Heizen", null, null] },
    { name: "aussen_c", entity: null, values: new Array(n).fill(null) },
  ];
  const log = [
    { ts: new Date(at(3.2)).toISOString(), kind: "switch", from: "normal", to: "boost", result: "sent",
      detail: "select.x → grün", text: 'Überschuss über 1.500 W, "sonnig"' },
    { ts: new Date(at(3.6)).toISOString(), kind: "override", text: "Handbetrieb gestartet." },
    { ts: new Date(at(4.5)).toISOString(), kind: "error", result: "failed", text: "Schreiben fehlgeschlagen.", detail: null },
    { ts: new Date(at(-30)).toISOString(), kind: "automation", text: "liegt vor dem Zeitraum" },
  ];
  const out = m.buildExport({
    version: "9.9.9", created: at(6), t0: T0, step: MIN, n, columns, log, settings: { boost_on_w: 1500, setback_min_dhw_c: null },
  });
  assert.equal(out.rows, 3); // Raster 2 bis 4: zwei mit Werten, eins nur mit Ereignis
  assert.equal(out.columns, 5);
  assert.ok(out.csv.startsWith("﻿# Energy Hub Export\r\n"));
  const lines = out.csv.slice(1).trimEnd().split("\r\n");
  const meta = lines.filter((l) => l.startsWith("#"));
  assert.ok(meta.includes("# version: 9.9.9"));
  assert.ok(meta.includes("# von: 2026-11-16T10:02:00+01:00"));
  assert.ok(meta.includes("# bis: 2026-11-16T10:05:00+01:00"));
  assert.ok(meta.includes("# raster_sekunden: 60"));
  assert.ok(meta.includes("# einstellung.boost_on_w: 1500"));
  assert.ok(meta.includes("# einstellung.setback_min_dhw_c: "));
  assert.ok(meta.includes("# spalte.pv_ueberschuss_w: sensor.pv [W]"));
  assert.ok(meta.includes("# spalte.aussen_c: nicht hinterlegt"));

  const table = lines.filter((l) => !l.startsWith("#")).map(parseLine);
  assert.deepEqual(table[0], ["zeit", "pv_ueberschuss_w", "wp_status", "aussen_c", "ereignisse"]);
  assert.deepEqual(table[1], ["2026-11-16T10:02:00+01:00", "1200.5", "Heizen", "", ""]);
  assert.equal(table[2][4],
    '10:03:12 Angehoben [gesendet]: Überschuss über 1.500 W, "sonnig" (select.x → grün) | 10:03:36 Handbetrieb: Handbetrieb gestartet.');
  assert.deepEqual(table[3], ["2026-11-16T10:04:00+01:00", "", "", "", "10:04:30 Fehler [fehlgeschlagen]: Schreiben fehlgeschlagen."]);
  assert.ok(table.every((row) => row.length === 5));
});

test("buildExport ohne Daten", () => {
  const out = m.buildExport({ version: "1", created: at(2), t0: T0, step: MIN, n: 2, columns: [{ name: "a", values: [null, null] }], log: [] });
  assert.equal(out.rows, 0);
});

test("sweep schneidet an Änderungen und Rastergrenzen", () => {
  const segments = [];
  m.sweep([[[at(-1), "a"], [at(20), "b"]], [[at(70), "x"]]], T0, at(90), 60 * MIN,
    (b, a, e, values) => segments.push([b, (a - T0) / MIN, (e - T0) / MIN, ...values]));
  assert.deepEqual(segments, [
    [0, 0, 20, "a", null],
    [0, 20, 60, "b", null],
    [1, 60, 70, "b", null],
    [1, 70, 90, "b", "x"],
  ]);
});

// Zwei Stunden: Lauf 1 von 10 bis 40 min (Heizen, angehoben), Lauf 2 ab 70 min (Warmwasser), läuft bei Ende noch.
function scenario() {
  return {
    data: {
      comp: [[at(-60), "off"], [at(10), "on"], [at(40), "off"], [at(70), "on"]],
      status: [[at(-60), "Aus"], [at(10), "Heizen"], [at(40), "Aus"], [at(70), "Warmwasser"]],
      mode: [[at(-60), "normal"], [at(5), "boost"], [at(60), "normal"]],
      outdoor: [[at(-60), "5"]],
      flow: [[at(-60), "28"], [at(10), "35"], [at(40), "28"], [at(70), "50"], [at(100), "54"]],
      ret: [[at(-60), "27"], [at(10), "30"], [at(40), "27"], [at(70), "45"]],
      dhw: [[at(-60), "44"], [at(90), "48"], [at(115), "51"]],
      pEl: [[at(-60), "0.04"], [at(10), "2"], [at(40), "0.04"], [at(70), "2"]], // in kW
      pHeat: [[at(-60), "0"], [at(10), "8"], [at(40), "0"], [at(70), "6"]],
      surplus: [[at(-60), "1000"], [at(60), "-500"]],
      heater: [[at(-60), "off"], [at(100), "on"], [at(110), "off"]],
      eHeat: [[at(-60), "100"], [at(40), "104"], [at(60), "105"], [at(115), "109"]],
      // Kamin brennt von 20 bis 80 min; der Speicher liefert von 45 bis 65 min und wieder ab 100 min
      storage: [[at(-60), "55"], [at(30), "50"], [at(90), "38"]],
      fireplace: [[at(-60), "30"], [at(20), "250"], [at(80), "40"]],
      lock: [[at(-60), "Keine"], [at(45), "Regenerativ"], [at(65), "Keine"], [at(100), "regenerativ"]],
    },
    factors: { pEl: 1000, pHeat: 1000 },
  };
}

test("analyseEfficiency: Stundenwerte", () => {
  const { data, factors } = scenario();
  const { hourRows } = m.analyseEfficiency(data, factors, T0, at(120));
  const col = (row, name) => row[m.HOUR_HEADER.indexOf(name)];
  const [h0, h1] = hourRows;
  assert.equal(hourRows.length, 2);
  assert.equal(col(h0, "zeit"), "2026-11-16T10:00:00+01:00");
  near(col(h0, "aussen_c"), 5);
  near(col(h0, "vorlauf_lauf_c"), 35); // nur während des Laufs
  near(col(h0, "ruecklauf_lauf_c"), 30);
  assert.equal(col(h0, "verdichter_min"), 30);
  assert.equal(col(h0, "verdichter_starts"), 1);
  assert.equal(col(h0, "status_min"), "Aus=30;Heizen=30");
  near(col(h0, "strom_aus_leistung_kwh"), (2000 * 0.5 + 40 * 0.5) / 1000);
  near(col(h0, "waerme_aus_leistung_kwh"), 4);
  assert.equal(col(h0, "waerme_heizen_zaehler_kwh"), 4); // 100 -> 104; der Sprung genau zur vollen Stunde zählt zur nächsten
  assert.equal(col(h0, "strom_zaehler_kwh"), null); // kein Zähler hinterlegt
  near(col(h0, "pv_ueberschuss_kwh"), 1);
  near(col(h0, "netzbezug_kwh"), 0);
  assert.equal(col(h0, "angehoben_min"), 55);
  assert.equal(col(h0, "abgesenkt_min"), 0);
  assert.equal(col(h0, "heizstab_min"), 0);
  assert.equal(col(h0, "zweiter_waermeerzeuger_min"), null);

  assert.equal(col(h1, "verdichter_min"), 50);
  assert.equal(col(h1, "verdichter_starts"), 1);
  near(col(h1, "vorlauf_lauf_c"), (50 * 30 + 54 * 20) / 50);
  assert.equal(col(h1, "vorlauf_max_c"), 54);
  assert.equal(col(h1, "waerme_heizen_zaehler_kwh"), 5); // 104 -> 109
  near(col(h1, "netzbezug_kwh"), 0.5);
  near(col(h1, "pv_ueberschuss_kwh"), 0);
  assert.equal(col(h1, "heizstab_min"), 10);
  near(col(h1, "warmwasser_c"), (44 * 30 + 48 * 25 + 51 * 5) / 60);
});

test("analyseEfficiency: Verdichterläufe", () => {
  const { data, factors } = scenario();
  const { cycleRows } = m.analyseEfficiency(data, factors, T0, at(120));
  const col = (row, name) => row[m.CYCLE_HEADER.indexOf(name)];
  assert.equal(cycleRows.length, 2);
  const [c1, c2] = cycleRows;
  assert.equal(col(c1, "start"), "2026-11-16T10:10:00+01:00");
  assert.equal(col(c1, "ende"), "2026-11-16T10:40:00+01:00");
  assert.equal(col(c1, "dauer_min"), 30);
  assert.equal(col(c1, "pause_davor_min"), null);
  assert.equal(col(c1, "betriebsart"), "Heizen");
  assert.equal(col(c1, "regelzustand"), "boost");
  near(col(c1, "strom_kwh"), 1);
  near(col(c1, "waerme_kwh"), 4); // Leistungszahl 4,0
  near(col(c1, "vorlauf_c"), 35);
  assert.equal(col(c1, "hinweis"), null);

  assert.equal(col(c2, "dauer_min"), 50);
  assert.equal(col(c2, "pause_davor_min"), 30);
  assert.equal(col(c2, "betriebsart"), "Warmwasser");
  assert.equal(col(c2, "regelzustand"), "normal");
  assert.equal(col(c2, "warmwasser_start_c"), 44);
  assert.equal(col(c2, "warmwasser_ende_c"), 51);
  near(col(c2, "waerme_kwh"), 5);
  assert.equal(col(c2, "heizstab_min"), 10);
  assert.equal(col(c2, "hinweis"), "läuft bei Exportende noch");
});

test("analyseEfficiency: Lauf, der vor dem Zeitraum begann, und fehlender Verdichter", () => {
  const running = m.analyseEfficiency({ comp: [[at(-30), "on"], [at(20), "off"]] }, {}, T0, at(60));
  assert.equal(running.cycleRows.length, 1);
  assert.equal(running.cycleRows[0][m.CYCLE_HEADER.indexOf("hinweis")], "Beginn vor dem Exportzeitraum");
  assert.equal(running.hourRows[0][m.HOUR_HEADER.indexOf("verdichter_starts")], 0);
  assert.equal(running.hourRows[0][m.HOUR_HEADER.indexOf("verdichter_min")], 20);

  const none = m.analyseEfficiency({ outdoor: [[at(-1), "3"]] }, {}, T0, at(60));
  assert.equal(none.cycleRows.length, 0);
  assert.equal(none.hourRows[0][m.HOUR_HEADER.indexOf("verdichter_min")], null);
});

test("episodes und matcher", () => {
  const active = m.matcher("Regenerativ, 14");
  assert.ok(active("Regenerativ") && active(" regenerativ ") && active(14) && !active("Keine") && !active("1"));
  const rows = [[at(-30), "Regenerativ"], [at(10), "Keine"], [at(20), "Regenerativ"], [at(25), "unavailable"],
    [at(26), "Regenerativ"], [at(40), "Keine"], [at(50), "Regenerativ"]];
  const found = m.episodes(rows, active, T0, at(60)).map((e) => [(e.start - T0) / MIN, (e.end - T0) / MIN, e.began, e.open]);
  assert.deepEqual(found, [
    [0, 10, false, false], // lief schon vor dem Zeitraum
    [20, 40, true, false], // der Ausfall des Sensors trennt den Abschnitt nicht
    [50, 60, true, true], // läuft am Ende noch
  ]);
  assert.deepEqual(m.episodes([], active, T0, at(60)), []);
  assert.deepEqual(m.episodes([[at(70), "Regenerativ"]], active, T0, at(60)), []);
});

test("analyseEfficiency: Kamin, Speicher und Entnahmen", () => {
  const { data, factors } = scenario();
  const opts = { regen: m.matcher("Regenerativ"), fireplaceOnC: 80, storageReadyC: 40 };
  const { hourRows, drawRows } = m.analyseEfficiency(data, factors, T0, at(120), 3600e3, opts);
  const col = (row, name) => row[m.HOUR_HEADER.indexOf(name)];
  const [h0, h1] = hourRows;
  near(col(h0, "speicher_c"), 52.5);
  near(col(h0, "kamin_c"), (30 * 20 + 250 * 40) / 60);
  assert.equal(col(h0, "kamin_min"), 40);
  assert.equal(col(h0, "speicher_bereit_min"), 60);
  assert.equal(col(h0, "sperre_regenerativ_min"), 15);
  assert.equal(col(h0, "speicher_entnahmen"), 1);
  assert.equal(col(h1, "kamin_min"), 20);
  assert.equal(col(h1, "speicher_bereit_min"), 30);
  assert.equal(col(h1, "sperre_regenerativ_min"), 25);
  assert.equal(col(h1, "speicher_entnahmen"), 1); // die erste Entnahme begann in der Stunde davor

  const d = (row, name) => row[m.DRAW_HEADER.indexOf(name)];
  assert.equal(drawRows.length, 2);
  assert.equal(d(drawRows[0], "start"), "2026-11-16T10:45:00+01:00");
  assert.equal(d(drawRows[0], "dauer_min"), 20);
  assert.equal(d(drawRows[0], "speicher_start_c"), 50);
  near(d(drawRows[0], "aussen_c"), 5);
  assert.equal(d(drawRows[0], "hinweis"), null);
  assert.equal(d(drawRows[1], "speicher_start_c"), 38);
  assert.equal(d(drawRows[1], "hinweis"), "läuft bei Exportende noch");

  // Bereit wie im Regler: Speicher mindestens Rücklaufsoll + Differenz
  const rel = m.analyseEfficiency(
    { storage: [[at(-5), "38"]], retTarget: [[at(-5), "30"], [at(20), "36"], [at(50), "unavailable"]] },
    {}, T0, at(60), 3600e3, { storageReadyC: 40, storageReadyDeltaK: 5 });
  // 0-20 min: 38 >= 30 + 5 bereit; 20-50 min: 38 < 36 + 5 nicht; 50-60 min: ohne Sollwert gilt 40, nicht bereit
  assert.equal(col(rel.hourRows[0], "speicher_bereit_min"), 20);
  const fixed = m.analyseEfficiency({ storage: [[at(-5), "41"]], retTarget: [[at(-5), "39"]] }, {}, T0, at(60), 3600e3, { storageReadyC: 40 });
  assert.equal(col(fixed.hourRows[0], "speicher_bereit_min"), 60);

  // Ohne hinterlegten Kamin und Speicher bleiben die Spalten leer
  const bare = m.analyseEfficiency({ comp: data.comp }, {}, T0, at(120));
  assert.equal(col(bare.hourRows[0], "kamin_min"), null);
  assert.equal(col(bare.hourRows[0], "sperre_regenerativ_min"), null);
  assert.equal(col(bare.hourRows[0], "speicher_entnahmen"), null);
  assert.equal(bare.drawRows.length, 0);
});

test("buildEfficiencyExport: drei Tabellen mit festen Spalten", () => {
  const { data, factors } = scenario();
  const t0 = at(-120); // zwei leere Stunden davor werden abgeschnitten
  const analysis = m.analyseEfficiency({ ...data, outdoor: [[at(0), "5"]], comp: data.comp.slice(1), status: [], mode: [], flow: [], ret: [], dhw: [], pEl: [[at(0), "0.04"], ...data.pEl.slice(1)], pHeat: [], surplus: [], heater: [], eHeat: [], storage: [], fireplace: [], lock: data.lock.slice(1) }, factors, t0, at(120), 3600e3, { regen: m.matcher("Regenerativ") });
  const out = m.buildEfficiencyExport({
    version: "9.9.9", created: at(120), t0, step: 3600e3, analysis,
    settings: { boost_on_w: 1500 }, entities: { comp: "binary_sensor.v", eEl: undefined },
  });
  assert.equal(out.rows, 2);
  const lines = out.csv.slice(1).trimEnd().split("\r\n");
  assert.ok(lines.includes("# von: 2026-11-16T10:00:00+01:00"));
  assert.ok(lines.includes("# entitaet.comp: binary_sensor.v"));
  assert.ok(lines.includes("# entitaet.eEl: nicht hinterlegt"));
  const iHours = lines.indexOf("# tabelle: stundenwerte");
  const iCycles = lines.indexOf("# tabelle: verdichterlaeufe");
  assert.ok(iHours > 0 && iCycles > iHours);
  assert.deepEqual(parseLine(lines[iHours + 1]), m.HOUR_HEADER);
  assert.deepEqual(parseLine(lines[iCycles + 1]), m.CYCLE_HEADER);
  assert.equal(iCycles - iHours, 2 + out.rows + 1); // Kopf, Stunden, Leerzeile
  for (const line of lines.slice(iHours + 2, iHours + 2 + out.rows)) assert.equal(parseLine(line).length, m.HOUR_HEADER.length);
  const iDraws = lines.indexOf("# tabelle: speicherentnahmen");
  assert.ok(iDraws > iCycles);
  assert.deepEqual(parseLine(lines[iDraws + 1]), m.DRAW_HEADER);
  assert.equal(out.cycles, iDraws - iCycles - 3); // Kopf, Läufe, Leerzeile
  assert.equal(out.draws, 2);
  for (const line of lines.slice(iCycles + 2, iDraws - 1)) assert.equal(parseLine(line).length, m.CYCLE_HEADER.length);
  for (const line of lines.slice(iDraws + 2)) assert.equal(parseLine(line).length, m.DRAW_HEADER.length);
  assert.equal(lines.length - iDraws - 2, out.draws);
});
