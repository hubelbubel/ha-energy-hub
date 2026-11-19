// Tests der Rechenfunktionen für den Bereich PV. Aufruf:  node --test tests/test_pv.mjs
process.env.TZ = "Europe/Berlin";
globalThis.HTMLElement = class {};
globalThis.customElements = { get: () => undefined, define: () => {} };

import assert from "node:assert/strict";
import { test } from "node:test";

const m = await import("../custom_components/energy_hub/frontend/energy-hub-panel.js");

const near = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);
const HOUR = 3600e3;
const T0 = new Date("2026-11-16T00:00:00+01:00").getTime();

test("inverterStatus übersetzt die Codes von ZCS Azzurro und Sofar", () => {
  assert.deepEqual(m.inverterStatus("2"), { code: 2, text: "Am Netz", fault: false, ok: true });
  assert.equal(m.inverterStatus("0").text, "Wartet");
  assert.equal(m.inverterStatus("4.0").fault, true);
  assert.equal(m.inverterStatus("5").text, "Dauerhafter Fehler");
  assert.equal(m.inverterStatus("9").text, "Code 9");
  assert.equal(m.inverterStatus("Normalbetrieb").ok, true);
  assert.equal(m.inverterStatus("Störung").fault, true);
  assert.equal(m.inverterStatus("unavailable"), null);
});

test("median", () => {
  assert.equal(m.median([3, 1, 2]), 2);
  assert.equal(m.median([4, null, 1, 3, 2]), 2.5);
  assert.equal(m.median([null]), null);
});

const layout = (strings) => ({
  panels: Object.entries(strings).flatMap(([s, labels]) => labels.map((label) => ({ label, string: s === "-" ? null : s, entities: {} }))),
  strings: Object.keys(strings).filter((s) => s !== "-").map((name) => ({ name, entities: {} })),
});

test("pvStrings: ein String gehört zu MPPT 1, sobald es MPPT 1 gibt", () => {
  const one = layout({ A: ["A1", "A2"] });
  assert.deepEqual(m.pvStrings(one, {}, { ent_mppt1_power: "sensor.pv_power" }), [{ name: "A", panels: ["A1", "A2"], mppt: 1 }]);
  assert.equal(m.pvStrings(one, {}, {})[0].mppt, null);
  // Spannung und Strom reichen auch
  assert.equal(m.pvStrings(one, {}, { ent_mppt1_voltage: "v", ent_mppt1_current: "i" })[0].mppt, 1);
});

test("pvStrings: Zuordnung aus den Einstellungen, sonst zwei Strings auf zwei MPPTs", () => {
  const two = layout({ A: ["A1"], B: ["B1"], "-": ["X"] });
  const ent = { ent_mppt1_power: "p1", ent_mppt2_power: "p2" };
  const set = m.pvStrings(two, { tigo_string_mppt1: "b", tigo_string_mppt2: "A" }, ent);
  assert.deepEqual(set.map((s) => [s.name, s.mppt]), [["A", 2], ["B", 1], [null, null]]);
  // Ohne Einstellung und mit Paneelen ohne String: keine Annahme
  assert.deepEqual(m.pvStrings(two, {}, ent).map((s) => s.mppt), [null, null, null]);
  const clean = layout({ A: ["A1"], B: ["B1"] });
  assert.deepEqual(m.pvStrings(clean, {}, ent).map((s) => s.mppt), [1, 2]);
});

/** Drei Tage mit Stundenwerten. Sonne von 8 bis 16 Uhr, 300 W je Paneel zur Mittagszeit. */
function scenario() {
  const n = 72;
  const sun = (b) => {
    const hr = b % 24;
    return hr >= 8 && hr < 16 ? Math.sin(((hr - 8 + 0.5) / 8) * Math.PI) : 0;
  };
  const base = Array.from({ length: n }, (_x, b) => 300 * sun(b));
  const mk = (label, f = () => 1, minF = null) => ({
    label, string: "A",
    power: base.map((v, b) => v * f(b)),
    powerMin: base.map((v, b) => (minF ? minF(b, v) : v * 0.9 * f(b))),
    tempMax: base.map((v) => (v > 0 ? 20 + v / 30 : null)),
  });
  const panels = [
    mk("A1"),
    mk("A2", () => 1, (b, v) => ([10, 11, 35].includes(b) ? 0 : v * 0.9)), // Aussetzer in drei Stunden
    mk("A3", (b) => (b % 24 >= 13 && b % 24 < 16 ? 0.5 : 1)), // nachmittags Schatten
    mk("A4", () => 0.8), // dauerhaft schwächer
    mk("A5"),
  ];
  const sumAt = (b) => panels.reduce((s, p) => s + p.power[b], 0);
  const inv = Array.from({ length: n }, (_x, b) => sumAt(b) * 0.97);
  return { t0: T0, step: HOUR, n, panels, strings: [{ name: "A", mppt: 1, panels: panels.map((p) => p.label), inv }], total: inv };
}

test("pvAnalysis: Energie je Tag, Verhältnis zum Median, Schatten, Aussetzer, Abgleich", () => {
  const a = m.pvAnalysis(scenario());
  assert.equal(a.days.length, 3);
  const by = Object.fromEntries(a.panels.map((p) => [p.label, p]));
  near(by.A4.ratio, 0.8);
  assert.equal(by.A4.below, 3);
  assert.equal(by.A4.validDays, 3);
  near(by.A1.ratio, 1);
  assert.deepEqual([by.A3.shade.from, by.A3.shade.to], [13, 16]);
  near(by.A3.shade.ratio, 0.5);
  assert.equal(by.A1.shade, null);
  assert.equal(by.A2.dropouts, 3);
  assert.equal(by.A1.dropouts, 0);
  near(by.A1.tempMax, 20 + (300 * Math.sin((3.5 / 8) * Math.PI)) / 30);
  const s = a.strings[0];
  near(s.dev, 1 / 0.97 - 1);
  near(a.tigoDays[0] * 0.97, a.invDays[0]);
});

test("pvFindings: dauerhaft schwächer, Schatten, Aussetzer, Abgleich, Ertrag", () => {
  const a = m.pvAnalysis(scenario());
  const f = m.pvFindings(a, { count: 2, minutes: 25 });
  const titles = f.map((x) => x.title);
  assert.ok(titles.includes("Der Wechselrichter meldete einen Fehler"));
  assert.ok(titles.includes("Paneel A4 liefert dauerhaft weniger"));
  assert.ok(titles.includes("Paneel A3 fällt zwischen 13 und 16 Uhr ab"));
  assert.ok(titles.includes("Optimierer A2 meldet sich zeitweise nicht"));
  assert.ok(titles.includes("Optimierer und Wechselrichter stimmen überein"));
  assert.ok(titles.some((t) => t.startsWith("PV-Ertrag")));
  assert.ok(!titles.includes("Alle Paneele liefern gleichmäßig"));
  assert.ok(f.every((x) => ["warn", "good", "info"].includes(x.tone) && x.area === "PV"));
  // A4 wird nicht zusätzlich als zeitweise verschattet gemeldet
  assert.ok(!titles.some((t) => t.startsWith("Paneel A4 fällt")));
});

test("pvFindings: gleichmäßige Anlage, Verlust am Wechselrichter", () => {
  const sc = scenario();
  sc.panels = sc.panels.map((p) => ({ ...p, power: sc.panels[0].power, powerMin: sc.panels[0].powerMin }));
  sc.strings[0].inv = sc.strings[0].inv.map((v) => v * 0.8);
  const titles = m.pvFindings(m.pvAnalysis(sc)).map((x) => x.title);
  assert.ok(titles.includes("Alle Paneele liefern gleichmäßig"));
  assert.ok(titles.some((t) => t.startsWith("Am Wechselrichter kommt")));
  assert.ok(!titles.some((t) => t.includes("Fehler")));
});

test("buildPvExport: vier Tabellen, Nachtzeilen entfallen, erster Teiltag ohne Zähler", () => {
  const sc = scenario();
  const t0 = T0 + 6 * HOUR; // der erste Tag liegt nur zum Teil im Zeitraum
  const n = sc.n - 6;
  const cut = (arr) => arr.slice(6);
  const panels = sc.panels.map((p) => ({ label: p.label, string: "A", entities: { power: `sensor.panel_${p.label}_power` },
    values: { power: cut(p.power), temperature: cut(p.tempMax) } }));
  const analysis = m.pvAnalysis({ t0, step: HOUR, n, panels: panels.map((p) => ({ label: p.label, string: "A", power: p.values.power })),
    strings: [{ name: "A", mppt: 1, panels: panels.map((p) => p.label), inv: cut(sc.total) }], total: cut(sc.total) });
  const day = (i) => T0 + i * 24 * HOUR;
  const built = m.buildPvExport({
    version: "test", created: t0 + n * HOUR, t0, step: HOUR, n,
    system: [{ name: "wr_pv_leistung_w", entity: "sensor.pv", unit: "W", values: cut(sc.total) }],
    panels, analysis,
    counters: { pv: { [day(0)]: 99, [day(1)]: 10.5 }, load: { [day(0)]: 50, [day(1)]: 20 } },
    faultsByDay: { [day(1)]: 12 }, settings: { zuordnung: "A=MPPT 1" }, entities: { ent_pv_power: "sensor.pv" },
  });
  const lines = built.csv.replace(/^﻿/, "").trim().split("\r\n");
  const tables = lines.filter((l) => l.startsWith("# tabelle:")).map((l) => l.slice(11));
  assert.deepEqual(tables, ["anlage", "paneele", "tage_paneele", "tage_anlage"]);
  const section = (name) => {
    const i = lines.indexOf(`# tabelle: ${name}`);
    const rest = lines.slice(i + 1);
    const end = rest.findIndex((l) => l.startsWith("# tabelle:"));
    return end < 0 ? rest : rest.slice(0, end);
  };
  // je Tag 8 Sonnenstunden x 5 Paneele; Nachtzeilen ohne Leistung und Temperatur fehlen
  assert.equal(section("paneele").length - 1, 3 * 8 * 5);
  assert.equal(built.panelRows, 120);
  const days = section("tage_anlage");
  assert.equal(days[0], "datum,wr_erzeugung_kwh,tigo_kwh,abweichung,wr_hausverbrauch_kwh,wr_netzbezug_kwh,wr_einspeisung_kwh,wr_fehler_min");
  const first = days[1].split(",");
  assert.equal(first[0], "2026-11-16");
  assert.notEqual(first[1], "99"); // Zähler des Teiltags werden nicht benutzt
  assert.equal(first[4], "");
  const second = days[2].split(",");
  assert.deepEqual([second[1], second[4], second[7]], ["10.5", "20", "12"]);
  assert.equal(section("tage_paneele").length - 1, 3 * 5);
  assert.ok(lines.some((l) => l === "# einstellung.zuordnung: A=MPPT 1"));
});
