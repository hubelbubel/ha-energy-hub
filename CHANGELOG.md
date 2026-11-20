# Änderungen

Jede Version hat hier einen Abschnitt. Die CI übernimmt ihn als Text des Releases; den zeigt Home Assistant beim Update an. Ältere Versionen stehen nur im Verlauf auf GitHub.

## 0.5.4 – 2026-11-20

- Optimierer anordnen: Im Bereich PV lassen sich die Kacheln unter „Paneele jetzt“ mit „Anordnen“ in ein Raster ziehen, so wie die Module auf dem Dach liegen. Sie rasten in den Feldern ein, auf einem belegten Feld tauschen zwei Kacheln die Plätze. Mit der Tastatur geht es über die Pfeiltasten.
- Die Anordnung wird in Home Assistant gespeichert und gilt für alle Benutzer und Geräte. Anordnen dürfen Administratoren. „Zurücksetzen“ stellt die Sortierung nach String wieder her.
- Neue Optimierer erscheinen unter der Anordnung. Bei mehreren Strings zeigt ein farbiger Streifen, zu welchem String eine Kachel gehört.

## 0.5.3 – 2026-11-19

- Tageswerte im Bereich Strom und in der Übersicht kommen aus Zählern in kWh, sobald welche da sind: Netzbezug, Einspeisung, Erzeugung, Batterie, „woher und wohin“ und Stunde für Stunde. Das ist genauer als die aufsummierte Leistung, weil sich schnelle Wechsel zwischen Bezug und Einspeisung nicht gegenseitig aufheben.
- Neu im Schritt Strom: Zähler für Netzbezug, Einspeisung, PV-Erzeugung, Batterie geladen und Batterie entladen. Ohne sie nimmt Energy Hub die Zähler aus dem Schritt „Wechselrichter“.
- Unter den Werten steht „laut Zähler“, wenn ein Zähler die Quelle ist.
- Hinweis im Bereich Strom, wenn ein Leistungs-Sensor einen Wert, aber keinen Verlauf hat, etwa weil er vom Recorder ausgeschlossen ist.

## 0.5.2 – 2026-11-19

- Zeichen für Energy Hub, ein „E“ aus den Bilanzbalken des Panels. Es erscheint nach der Installation auf der Integrationsseite und im Marketplace, ab Home Assistant 2026.3.
- Releases tragen die Versionsnummer; der Marketplace zeigt sie statt der Commit-Kennung.

## 0.5.1 – 2026-11-19

- Die Einrichtung schlägt nur Entitäten vor, die es in deinem Home Assistant gibt.
- Bereich Wärme ohne Wärmepumpe: ein Hinweis statt eines leeren Anlagenschemas. Mit Sensor für den PV-Überschuss läuft die Regelung im Probebetrieb mit und schreibt ins Logbuch, was sie getan hätte.
- Ist die Wärmepumpe hinterlegt, meldet aber keine Werte (etwa ohne Modbus-Karte), zeigt der Bereich Wärme das an.
- Die Übersicht erwähnt die Heizung nur, wenn es eine Wärmepumpe gibt. Im Probebetrieb heißt es „hätte angehoben“ statt „PV-Überschuss floss in die Heizung“.
- Für den Bereich PV reicht schon die Leistung der PV-Anlage aus dem Schritt Strom.

## 0.5.0 – 2026-11-19

- Neuer Bereich PV: Wechselrichter und Tigo-Optimierer (Integration tigo_rs485) zusammen.
  - Paneele jetzt als Kacheln, Verlauf je Paneel einzeln oder mehrere übereinander
  - Abgleich von Optimierern und Wechselrichter, Ertrag je Paneel im Vergleich zum Median
  - Auswertung der letzten 7 Tage: schwache Paneele, Schatten zu bestimmten Uhrzeiten, Aussetzer, Fehler am Wechselrichter
  - PV-Export als CSV
- Neuer Einrichtungsschritt „Wechselrichter“.
