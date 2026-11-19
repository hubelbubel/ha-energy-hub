# CLAUDE.md

Home-Assistant-Integration „Energy Hub“ (Domain `energy_hub`, per HACS installierbar). Sie führt Strom, PV und Wärme in einem Seitenleisten-Panel zusammen und regelt die Wärmepumpe nach PV-Überschuss und Prognose. Die ausführliche Beschreibung für Nutzer steht in `README.md`.

## Sprache und Stil

- Alles ist deutsch: Panel-Texte, Logbuch, README, Code-Kommentare, Docstrings, Testnamen und Commit-Messages. Nur die Bezeichner im Code sind englisch.
- Die Commit-Messages sind kurz und beschreiben das Ergebnis, zum Beispiel „Bereich PV: Wechselrichter und Tigo-Optimierer“.
- Die README ist sachlich und konkret. Schwellen und Bedingungen stehen als Tabellen mit echten Zahlen da. Wenn du ein Verhalten oder eine Schwelle änderst, passe die README im selben Commit an, auch die Testanzahl im Abschnitt „Stand“.

## Aufbau

```
custom_components/energy_hub/
  logic.py          Entscheidung aus Messwerten + Einstellungen – rein, ohne HA-Importe
  tigo.py           Optimierer/Strings aus dem Entitätsregister von tigo_rs485 – rein, ohne HA-Importe
  controller.py     liest Messwerte, ruft logic auf, stellt die Wärmepumpe, führt nach, schreibt das Logbuch
  config_flow.py    Einrichtung in 8 Schritten; Optionen zeigen dieselben Formulare
  websocket_api.py  Schnittstelle Panel ↔ Regler
  const.py          Konstanten, Standardwerte, VERSION, STORAGE_VERSION
  sensor.py, switch.py, services.yaml
  frontend/energy-hub-panel.js   das ganze Panel (~4400 Zeilen), ES-Modul ohne Build-Schritt und ohne Abhängigkeiten
  translations/de.json, en.json  GENERIERT – nicht von Hand ändern
packages/dimplex_wpm.yaml   Modbus-Package für die Dimplex-Wärmepumpe; die Vorschläge im config_flow passen zu dessen Entitätsnamen
dev/                        preview.html (Panel mit Beispieldaten), screenshot.py, build_translations.py
tests/                      pytest (fake_ha.py ersetzt Home Assistant) und node --test
docs/                       Screenshots für die README
```

## Regeln für Änderungen

- **`logic.py` und `tigo.py` bleiben frei von Home-Assistant-Importen**, damit sie ohne HA testbar sind. Der Kontakt zu HA gehört in `controller.py` und `websocket_api.py`.
- **Die Texte für Einrichtung und Optionen stehen in `dev/build_translations.py`.** Nach jeder Änderung dort `python3 dev/build_translations.py` ausführen und beide erzeugten JSON-Dateien mit committen.
- **Panel:** Rechenfunktionen werden als `export function …` aus `energy-hub-panel.js` exportiert und in `tests/*.mjs` direkt getestet. Neue Rechnungen gehören in solche reinen Funktionen, nicht in die Darstellung. Die Schwellen für die PV-Auswertung stehen in `PV_LIMITS`. Keine externen Bibliotheken und kein Bundler.
- **Die Version steht an vier Stellen:** `const.py` (`VERSION`), `manifest.json`, `dev/preview.html` und README („Stand“). Bei einer neuen Version alle vier ändern. `VERSION` dient auch als Cache-Buster für die Panel-URL.
- Ändert sich das Format der gespeicherten Daten (`Store` im Controller), `STORAGE_VERSION` erhöhen und die Migration bedenken.
- Die Integration bleibt **herstellerneutral**. Sie arbeitet nur mit Entitäten, die bei der Einrichtung ausgewählt werden, und spricht nicht selbst Modbus. Dimplex, ZCS Azzurro und Tigo sind nur die Vorschläge und Beispiele.
- **Sicherheit der Anlage:** Standard ist der Probebetrieb, in dem nichts an die Wärmepumpe gesendet wird. Das bleibt so. Die Mindesthaltezeit gegen Takten des Verdichters darf nicht umgangen werden. Jede Schaltung braucht eine Begründung im Logbuch.
- Unterstützt wird Home Assistant ab 2025.1 (`hacs.json`). Keine neueren HA-APIs ohne Rückfall verwenden.

## Prüfen

```bash
pytest tests -q
node --test tests/test_export.mjs tests/test_energy.mjs tests/test_pv.mjs
python3 dev/screenshot.py /tmp/shots   # Panel mit Beispieldaten rendern, meldet Konsolenfehler (Playwright + Chromium)
```

Die CI (`.github/workflows/pruefen.yml`) führt beide Testläufe aus (Python 3.13, Node 22) und dazu `hassfest`. Neue `.mjs`-Testdateien müssen dort und in der README im Befehl ergänzt werden.

Die Integration ist noch nie in einem laufenden Home Assistant oder an der echten Wärmepumpe gelaufen. Die Tests und `fake_ha.py` ersetzen das nicht. Behaupte also nicht, dass etwas „in HA funktioniert“, nur weil die Tests grün sind. Sag stattdessen, was der Nutzer an der echten Anlage prüfen sollte.

## Anlage des Nutzers (Bezug für Beispiele und Vorschläge)

Dimplex-Wärmepumpe (WPM, Modbus RTU), wasserführender Kamin (Spartherm S-Thermatik NEO) mit Speicher (Bivalent-Regenerativ), PV mit ZCS-Azzurro-HYD-Wechselrichter und 16 Tigo-Optimierern an einem MPPT (tigo_rs485), Batterie und go-e-Wallbox.
