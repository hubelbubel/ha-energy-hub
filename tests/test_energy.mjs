// Tests der Rechenfunktionen für Strom und Übersicht. Aufruf:  node --test tests/test_energy.mjs
process.env.TZ = "Europe/Berlin";
globalThis.HTMLElement = class {};
globalThis.customElements = { get: () => undefined, define: () => {} };

import assert from "node:assert/strict";
import { test } from "node:test";

const m = await import("../custom_components/energy_hub/frontend/energy-hub-panel.js");

const near = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);
const HOUR = 3600e3;
const T0 = new Date("2026-11-16T00:00:00+01:00").getTime();

test("rowsToGrid legt Statistik-Zeilen ins Raster", () => {
  const rows = [[T0, 100], [T0 + HOUR, 200], [T0 + HOUR + 1000, 400], [T0 + 5 * HOUR, 1], [T0 - HOUR, 9], [T0 + 2 * HOUR, null]];
  assert.deepEqual(m.rowsToGrid(rows, T0, HOUR, 4), [100, 300, null, null]);
});

test("energyBalance: Sonne mittags, Batterie lädt, Rest wird eingespeist", () => {
  const bal = m.energyBalance({ grid: [-1500], pv: [5000], battery: [-2000], wp: [800], wallbox: [0], consumers: [[300], [null]] });
  assert.equal(bal.imp[0], 0);
  assert.equal(bal.exp[0], 1500);
  assert.equal(bal.chg[0], 2000);
  assert.equal(bal.dis[0], 0);
  assert.equal(bal.cons[0], 1500); // 5000 - 1500 - 2000
  assert.deepEqual([bal.fromPv[0], bal.fromBat[0], bal.fromGrid[0]], [1500, 0, 0]);
  assert.equal(bal.small[0], 300);
  assert.equal(bal.rest[0], 400); // 1500 - 800 - 300
  assert.deepEqual(bal.consumers.map((c) => c[0]), [300, null]);
});

test("counterPower: Zunahme je Raster als mittlere Leistung, Wh werden umgerechnet", () => {
  const t0 = 0;
  const step = 300e3; // 5 Minuten
  // 0,1 kWh in 5 Minuten sind im Mittel 1200 W; zwei Zeilen im selben Raster werden addiert
  const w = m.counterPower([[0, 0.1], [300e3, 0.05], [300e3, 0.05], [900e3, -3]], t0, step, 4);
  assert.deepEqual(w, [1200, 1200, null, 0]);
  assert.deepEqual(m.counterPower([[0, 250]], t0, 3600e3, 1, 0.001), [250]); // 250 Wh in einer Stunde
});

test("energyBalance: Zähler gelten statt der Leistung, wo sie einen Wert haben", () => {
  // Netz-Leistung fehlt ganz (etwa ohne Aufzeichnung), die Zähler liefern Bezug und Einspeisung
  const bal = m.energyBalance({
    grid: [null, null], pv: [0, 3000], battery: [0, 0], impE: [600, 0], expE: [0, 1000],
  });
  assert.deepEqual(bal.imp, [600, 0]);
  assert.deepEqual(bal.exp, [0, 1000]);
  assert.deepEqual(bal.cons, [600, 2000]);
  assert.deepEqual(bal.fromGrid, [600, 0]);
  // Ohne Zählerwert im Raster gilt die Leistung
  const mixed = m.energyBalance({ grid: [400, 400], impE: [null, 900] });
  assert.deepEqual(mixed.imp, [400, 900]);
  const t = m.energyTotals(m.energyBalance({ grid: [null], impE: [1200], expE: [0], pv: [0] }), 3600e3);
  assert.equal(t.imp, 1.2);
});

test("energyBalance: abends aus Batterie und Netz", () => {
  const bal = m.energyBalance({ grid: [1200], pv: [0], battery: [2500], wp: [2000], wallbox: [null] });
  assert.equal(bal.cons[0], 3700);
  assert.deepEqual([bal.fromPv[0], bal.fromBat[0], bal.fromGrid[0]], [0, 2500, 1200]);
  assert.equal(bal.rest[0], 1700);
  assert.equal(bal.small[0], null);
});

test("energyBalance: Vorzeichen umstellbar, eigener Verbrauchs-Sensor hat Vorrang, Lücken bleiben Lücken", () => {
  const bal = m.energyBalance(
    { grid: [1500, null], pv: [5000, null], battery: [2000, null], house: [1400, null] },
    { gridSign: "export_positive", batterySign: "charge_positive" });
  assert.equal(bal.exp[0], 1500);
  assert.equal(bal.chg[0], 2000);
  assert.equal(bal.cons[0], 1400);
  assert.equal(bal.cons[1], null);
  assert.equal(bal.fromPv[1], null);
  assert.equal(bal.rest[1], null);
});

test("energyTotals: Energie, Eigenverbrauch und Autarkie", () => {
  // drei Stunden: Nacht (Netz), Mittag (PV-Überschuss), Abend (Batterie)
  const bal = m.energyBalance({ grid: [1000, -2000, 0], pv: [0, 6000, 0], battery: [0, -1000, 1500], wp: [500, 1000, 500] });
  const t = m.energyTotals(bal, HOUR);
  near(t.cons, 5.5); // 1 + 3 + 1,5 kWh
  near(t.pv, 6);
  near(t.imp, 1);
  near(t.exp, 2);
  near(t.chg, 1);
  near(t.dis, 1.5);
  near(t.wp, 2);
  near(t.selfUse, 4 / 6);
  near(t.autarky, 1 - 1 / 5.5);
  near(m.energyTotals(bal, HOUR, 1, 2).cons, 3);

  const noGrid = m.energyTotals(m.energyBalance({ pv: [1000], house: [500] }), HOUR);
  assert.equal(noGrid.autarky, null); // ohne Netz-Sensor keine Aussage
  assert.equal(noGrid.selfUse, null);
  assert.equal(noGrid.wp, null);
});

test("hourlyMix: Herkunft je Stunde für einen Tag", () => {
  const step = 1800e3; // halbe Stunden, beginnend eine Stunde vor Mitternacht
  const t0 = T0 - HOUR;
  const bal = m.energyBalance({
    grid: [500, 500, 1000, 1000, 0, 0], pv: [0, 0, 0, 0, 3000, 3000], battery: [0, 0, 0, 0, -1000, -1000],
  });
  const hours = m.hourlyMix(bal, t0, step, T0);
  assert.equal(hours.length, 24);
  near(hours[0].fromGrid, 1); // 2 x 0,5 h x 1 kW
  near(hours[1].fromPv, 2);
  near(hours[1].pv, 3);
  assert.equal(hours[1].fromGrid, 0);
  assert.equal(hours[2].known, false);
});

function week() {
  // 7 Tage in Stunden. Mittags viel Sonne und Einspeisung, die Batterie ist erst um 13 Uhr voll.
  // Abends läuft die Spülmaschine mit Netzstrom, während die Batterie noch geladen ist.
  const grid = [];
  const pv = [];
  const battery = [];
  const soc = [];
  const wp = [];
  const dish = [];
  for (let d = 0; d < 7; d++) {
    for (let h = 0; h < 24; h++) {
      const sun = h >= 10 && h < 15;
      pv.push(sun ? 6000 : 0);
      wp.push(sun ? 2000 : h >= 20 ? 1500 : 0);
      dish.push(h === 21 ? 1000 : 0);
      battery.push(sun && h < 13 ? -1000 : h >= 20 && h < 22 ? 500 : 0);
      soc.push(h < 10 ? 15 : h < 13 ? 60 : h < 20 ? 100 : 70);
      const load = 300 + wp.at(-1) + dish.at(-1);
      grid.push(load - pv.at(-1) - battery.at(-1));
    }
  }
  return { bal: m.energyBalance({ grid, pv, battery, wp, consumers: [dish] }), soc };
}

test("powerFindings: nennt Auffälligkeiten mit Zahlen", () => {
  const { bal, soc } = week();
  const found = m.powerFindings(bal, soc, { consumers: ["Spülmaschine"] }, HOUR, T0);
  const titles = found.map((f) => f.title);
  const get = (part) => found.find((f) => f.title.includes(part));

  assert.ok(get("Eingespeist, obwohl die Batterie nicht voll war"), titles.join(" | "));
  // je Tag 3 Stunden mit 2,7 kW Einspeisung bei 60 % Ladestand
  assert.ok(get("Eingespeist").text.includes("56,7 kWh"), get("Eingespeist").text);
  assert.equal(get("Eingespeist").tone, "warn");

  assert.ok(get("Netzbezug, obwohl die Batterie geladen war"), titles.join(" | "));
  assert.ok(get("Spülmaschine läuft meist mit Netzstrom"), titles.join(" | "));
  assert.ok(get("Spülmaschine").text.startsWith("7,0 kWh, davon bis zu 100 %"), get("Spülmaschine").text);

  assert.equal(get("Grundlast").tone, "info");
  assert.ok(get("Grundlast").title.includes("300 W"));
  assert.ok(get("Viel Solarstrom geht ins Netz") || get("Fast aller Solarstrom"), titles.join(" | "));
  assert.ok(found.every((f) => f.area === "Strom" && f.text.length > 20));
});

test("powerFindings: ohne Verbrauch keine Aussagen, ohne Batterie keine Batterie-Aussagen", () => {
  assert.deepEqual(m.powerFindings(m.energyBalance({ grid: [0, 0] }), null, {}, HOUR, T0), []);
  const { bal } = week();
  const found = m.powerFindings(bal, null, { consumers: ["Spülmaschine"] }, HOUR, T0);
  assert.ok(!found.some((f) => f.title.includes("Batterie")));
});

test("heatFindings: Taktung, Arbeitszahl, Heizstab, Probebetrieb", () => {
  const base = { days: 7, starts: 35, cycles: 34, meanRunMin: 95, elKwh: 60, heatKwh: 222, heaterMin: 0, draws: 0, drawMin: 0, boostMin: 0, dryRun: false };
  const good = m.heatFindings(base);
  assert.deepEqual(good.map((f) => [f.tone, f.title]), [
    ["good", "Die Wärmepumpe läuft in langen Zügen"],
    ["good", "Arbeitszahl 3,7"],
  ]);
  assert.ok(good[0].text.includes("5 Starts am Tag") && good[0].text.includes("1 h 35 min"));

  const bad = m.heatFindings({ ...base, starts: 300, cycles: 290, meanRunMin: 6, heatKwh: 130, heaterMin: 75, dryRun: true, draws: 4, drawMin: 200, boostMin: 90 });
  const tones = Object.fromEntries(bad.map((f) => [f.title, f.tone]));
  assert.equal(tones["Die Regelung läuft im Probebetrieb"], "warn");
  assert.equal(tones["Die Wärmepumpe taktet"], "warn");
  assert.equal(tones["Arbeitszahl 2,2"], "warn");
  assert.equal(tones["Der Heizstab lief 1 h 15 min"], "warn");
  assert.equal(tones["Der Kamin-Speicher hat mitgeheizt"], "good");
  // Im Probebetrieb wurde nichts angehoben, nur protokolliert
  assert.equal(tones["Im Probebetrieb hätte die Regelung angehoben"], "info");
  assert.equal(tones["PV-Überschuss floss in die Heizung"], undefined);
  const real = m.heatFindings({ ...base, boostMin: 90 });
  assert.equal(real.find((f) => f.title === "PV-Überschuss floss in die Heizung")?.tone, "good");

  assert.deepEqual(m.heatFindings({ days: 0, starts: 0, cycles: 0, meanRunMin: null, elKwh: 0, heatKwh: 0, heaterMin: null, draws: 0, drawMin: 0, boostMin: 0, dryRun: false }), []);
});

/* ---- Tage: Tagesleiste und Zeitfenster ---- */

const at = (text) => new Date(text).getTime();

test("shiftDay: ganze Kalendertage, auch über die Zeitumstellung", () => {
  const day = at("2026-11-20T00:00:00+01:00");
  assert.equal(m.midnightOf(at("2026-11-20T17:40:00+01:00")), day);
  assert.equal(m.shiftDay(day, -1), at("2026-11-19T00:00:00+01:00"));
  assert.equal(m.shiftDay(at("2026-11-20T09:15:00+01:00"), 3), at("2026-11-23T00:00:00+01:00"));
  // 29. März 2026 hat 23 Stunden, 25. Oktober 2026 hat 25
  const spring = at("2026-03-29T00:00:00+01:00");
  assert.equal(m.shiftDay(spring, 1) - spring, 23 * HOUR);
  const autumn = at("2026-10-25T00:00:00+02:00");
  assert.equal(m.shiftDay(autumn, 1) - autumn, 25 * HOUR);
  assert.equal(m.shiftDay(m.shiftDay(autumn, 1), -1), autumn);
});

test("dayWindow: heute rückwärts ab jetzt, frühere Tage als ganze Kalendertage", () => {
  const now = at("2026-11-20T10:31:00+01:00");
  const today = m.dayWindow(null, 48, 300e3, now);
  assert.equal(today.t1, at("2026-11-20T10:35:00+01:00"));
  assert.equal(today.t1 - today.t0, 48 * HOUR);
  assert.equal(today.n, 576);
  const day = at("2026-11-17T00:00:00+01:00");
  assert.deepEqual(m.dayWindow(day, 24, 300e3, now), { t0: day, t1: at("2026-11-18T00:00:00+01:00"), n: 288 });
  assert.deepEqual(m.dayWindow(day, 48, HOUR, now), { t0: at("2026-11-16T00:00:00+01:00"), t1: at("2026-11-18T00:00:00+01:00"), n: 48 });
  assert.equal(m.dayWindow(day, 168, HOUR, now).t0, at("2026-11-11T00:00:00+01:00"));
  // der Tag der Zeitumstellung im Herbst hat 25 Raster zu einer Stunde
  assert.equal(m.dayWindow(at("2026-10-25T00:00:00+02:00"), 24, HOUR, now).n, 25);
});

test("dayWord: heute, gestern, sonst das Datum, im Vorjahr mit Jahreszahl", () => {
  const now = at("2026-11-20T08:00:00+01:00");
  assert.equal(m.dayWord(at("2026-11-20T00:00:00+01:00"), now), "heute");
  assert.equal(m.dayWord(at("2026-11-19T00:00:00+01:00"), now), "gestern");
  assert.equal(m.dayWord(at("2026-11-03T00:00:00+01:00"), now), "am 3. November");
  assert.equal(m.dayWord(at("2026-11-03T00:00:00+01:00"), now, true), "am 3.11.");
  assert.equal(m.dayWord(at("2025-12-31T00:00:00+01:00"), now), "am 31. Dezember 2025");
  assert.equal(m.dayWord(at("2025-12-31T00:00:00+01:00"), now, true), "am 31.12.2025");
});

test("dayNav: zurück bis zum ersten Tag mit Daten, vor bis heute", () => {
  const now = at("2026-11-20T08:00:00+01:00");
  const first = at("2026-11-02T00:00:00+01:00");
  assert.deepEqual(m.dayNav(null, null, now),
    { label: "Freitag, 20. November", rel: "Heute", today: true, prev: true, next: false });
  assert.deepEqual(m.dayNav(at("2026-11-19T00:00:00+01:00"), first, now),
    { label: "Donnerstag, 19. November", rel: "Gestern", today: false, prev: true, next: true });
  const atFirst = m.dayNav(first, first, now);
  assert.deepEqual([atFirst.rel, atFirst.prev, atFirst.next], ["vor 18 Tagen", false, true]);
  assert.equal(m.dayNav(at("2025-11-20T00:00:00+01:00"), null, now).label, "Donnerstag, 20. November 2025");
  // ein Tag in der Zukunft wird zu heute
  assert.equal(m.dayNav(at("2026-11-22T00:00:00+01:00"), first, now).today, true);
});

test("Stundenwerte füllen im 5-Minuten-Raster die ganze Stunde", () => {
  const step = 300e3;
  const grid = m.rowsToGrid([[T0, 600, HOUR], [T0 + HOUR, 900, step], [T0 + HOUR + step, 300, step]], T0, step, 14);
  assert.deepEqual(grid, [...new Array(12).fill(600), 900, 300]);
  // 1,2 kWh in einer Stunde sind 1.200 W in jedem der zwölf Raster; Wh werden umgerechnet
  const w = m.counterPower([[T0, 1.2, HOUR]], T0, step, 12);
  assert.equal(w.length, 12);
  w.forEach((x) => near(x, 1200));
  m.counterPower([[T0, 600, HOUR]], T0, step, 12, 0.001).forEach((w) => near(w, 600));
  // ragt die Stunde über das Raster hinaus, zählt nur ihr Anteil darin
  m.counterPower([[T0 - 0.5 * HOUR, 1.2, HOUR]], T0, step, 12).forEach((x, b) => (b < 6 ? near(x, 1200) : assert.equal(x, null)));
});

test("usesBalance: nur mit Schalter und hinterlegtem Akku", () => {
  assert.equal(m.usesBalance({ off_without_battery: true }, { ent_battery_power: "sensor.akku" }), true);
  assert.equal(m.usesBalance({ off_without_battery: false }, { ent_battery_power: "sensor.akku" }), false);
  assert.equal(m.usesBalance({ off_without_battery: true }, { ent_battery_power: null }), false);
  assert.equal(m.usesBalance(undefined, undefined), false);
});

test("balanceSeries: Überschuss plus Ladeleistung, ohne Akku-Wert zählt der Überschuss", () => {
  // Einspeisung 0, Akku entlädt 800 W  →  -800 W; Akku lädt 200 W → 200 W; Lücke im Akku → Überschuss
  assert.deepEqual(m.balanceSeries([0, 0, 1500, null], [-800, 200, null, 100]), [-800, 200, 1500, null]);
  assert.deepEqual(m.balanceSeries([300], undefined), [300]);
});

test("shownSurplus: PV-Überschuss nie unter 0, Lücken bleiben Lücken", () => {
  assert.equal(m.shownSurplus(-380), 0);
  assert.equal(m.shownSurplus(2140), 2140);
  assert.equal(m.shownSurplus(null), null);
  assert.equal(m.shownSurplus(undefined), null);
});

/* ---- Wärmepumpe: für sie übrig, Herkunft ihres Stroms ---- */

test("availableSeries: Überschuss plus Wärmepumpe, Entladen zählt nicht als übrig", () => {
  assert.deepEqual(
    m.availableSeries([400, 400, -300, null], [1600, null, 2000, 1000], [500, 0, -900, 0]),
    [2000, 400, 800, null]); // Laden bleibt beim Akku, Entladen wird abgezogen, fehlende Wärmepumpe zählt 0
  assert.deepEqual(m.availableSeries([100], null, null), [100]);
});

test("heatPumpSupply: Netz und Akku zählen zuerst bei der Wärmepumpe", () => {
  const bal = m.energyBalance({
    // 1. Sonne: alles vom Dach  2. Wolke: Akku hilft  3. Abend: Netz und Akku  4. ohne Netzwert
    grid: [-1000, 0, 800, null], pv: [5000, 1500, 0, 0], battery: [-1500, 700, 1500, 0], wp: [2000, 2000, 2000, 2000],
  });
  const r3 = (list) => list.map((v) => (v === null ? null : Math.round(v * 1000) / 1000));
  const all = m.heatPumpSupply(bal, HOUR);
  assert.deepEqual(r3([all.wp, all.pv, all.bat, all.grid]), [6, 3.3, 1.9, 0.8]);
  assert.equal(all.raised.min, null);

  const raised = m.heatPumpSupply(bal, HOUR, 0, 4, ["boost", "strong", "normal", "boost"]).raised;
  assert.deepEqual(r3([raised.wp, raised.pv, raised.bat, raised.grid, raised.min]), [4, 3.3, 0.7, 0, 180]);
  // ab Raster 2: nur der Abend
  const evening = m.heatPumpSupply(bal, HOUR, 2);
  assert.deepEqual(r3([evening.wp, evening.pv, evening.grid]), [2, 0, 0.8]);

  assert.equal(m.supplyText(all), "3,3 kWh vom Dach, 1,9 aus dem Akku, 0,8 aus dem Netz");
  assert.equal(m.supplyText(evening, false), "0,0 kWh vom Dach, 0,8 aus dem Netz");
  assert.equal(m.supplyText(m.heatPumpSupply(m.energyBalance({ grid: [null], wp: [1000] }), HOUR)), "");
});

test("heatFindings: woher der Strom beim Anheben kam", () => {
  const base = { days: 7, starts: 0, cycles: 0, meanRunMin: null, elKwh: 0, heatKwh: 0, heaterMin: null, draws: 0, drawMin: 0, boostMin: 300, dryRun: false };
  const sunny = m.heatFindings({ ...base, raised: { wp: 10, pv: 8.5, bat: 1, grid: 0.5, min: 300 } });
  assert.deepEqual(sunny.map((f) => [f.tone, f.title]), [["good", "Beim Anheben 85 % Solarstrom"]]);
  assert.equal(sunny[0].text, "Die Heizung war 5 h 0 min angehoben. Die Wärmepumpe brauchte dabei 10,0 kWh: 8,5 kWh vom Dach, 1,0 aus dem Akku, 0,5 aus dem Netz.");
  const grey = m.heatFindings({ ...base, raised: { wp: 10, pv: 3, bat: 2, grid: 5, min: 300 }, battery: true });
  assert.equal(grey[0].tone, "warn");
  assert.ok(grey[0].text.endsWith("ist die Schwelle zum Anheben zu niedrig."), grey[0].text);
  // ohne Strombilanz bleibt es bei der Dauer
  assert.equal(m.heatFindings({ ...base, raised: null })[0].title, "PV-Überschuss floss in die Heizung");
});

test("powerFindings: Herkunft des Stroms der Wärmepumpe", () => {
  const { bal, soc } = week();
  const found = m.powerFindings(bal, soc, { consumers: ["Spülmaschine"] }, HOUR, T0);
  const wp = found.find((f) => f.title.includes("Wärmepumpe"));
  // je Tag 5 h mit 2 kW vom Dach, abends 4 h mit 1,5 kW aus Akku und Netz
  assert.equal(wp.title, "Die Wärmepumpe läuft überwiegend mit Solarstrom");
  assert.ok(wp.text.startsWith("Die Wärmepumpe brauchte 112,0 kWh"), wp.text);
  assert.ok(wp.text.includes("70,0 kWh vom Dach"), wp.text);
});

test("entryTitle: Stufen beim Anheben", () => {
  assert.equal(m.entryTitle({ kind: "switch", from: "boost", to: "strong" }), "Stark angehoben");
  assert.equal(m.entryTitle({ kind: "switch", from: "strong", to: "boost" }), "Zurück auf Anheben");
  assert.equal(m.entryTitle({ kind: "switch", from: "normal", to: "boost" }), "Angehoben");
  assert.equal(m.entryTitle({ kind: "switch", from: "strong", to: "normal" }), "Anheben beendet");
});
