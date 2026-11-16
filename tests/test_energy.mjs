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
  assert.equal(tones["PV-Überschuss floss in die Heizung"], "good");

  assert.deepEqual(m.heatFindings({ days: 0, starts: 0, cycles: 0, meanRunMin: null, elKwh: 0, heatKwh: 0, heaterMin: null, draws: 0, drawMin: 0, boostMin: 0, dryRun: false }), []);
});
