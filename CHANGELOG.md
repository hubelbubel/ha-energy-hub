# Änderungen

Jede Version hat hier einen Abschnitt. Die CI übernimmt ihn als Text des Releases; den zeigt Home Assistant beim Update an. Ältere Versionen stehen nur im Verlauf auf GitHub.

## 0.7.0 – 2026-11-20

- Stark anheben: eine zweite Stufe. Bleiben beim Anheben 10 min lang noch mehr als 2.000 W übrig, stellt Energy Hub auf „Verstärkt Stufe 3 (dunkelgrün)“ bzw. hebt die Heizkurve um 4 K statt 2 K an. Trägt die PV das nicht mehr, geht es zurück auf einfaches Anheben. Kennt die Smart-Grid-Auswahl keine zweite Stufe, bleibt es bei Grün. Neu im Schritt Regeln: „Stark anheben (zweite Stufe)“ (an) und die Schwelle; im Schritt Eingriff die Option bzw. der Betrag. Auch von Hand und im Dienst `set_override` als `strong`.
- Angehoben wird jetzt nach dem, was für die Wärmepumpe übrig ist: Überschuss plus das, was sie gerade selbst zieht. Läuft sie im Normalbetrieb schon mit Solarstrom, hebt Energy Hub sie trotzdem an. Strom aus dem Akku zählt dabei nicht als übrig. Dafür braucht es die elektrische Leistung der Wärmepumpe.
- Die Schwelle zum Anheben passt sich an: Energy Hub lernt, wie viel die Wärmepumpe im Lauf zieht, und hebt an, sobald so viel übrig ist. Der Wert folgt langsam der Jahreszeit. Abschaltbar mit „Schwelle an die Wärmepumpe anpassen“; dann gilt wieder die feste Schwelle.
- Wird der Akku laut Prognose heute ohnehin voll, zählt seine Ladeleistung beim Anheben mit. Die Wärmepumpe muss dann nicht warten, bis der Akku voll ist. Die Kapazität des Akkus lernt Energy Hub aus Ladung und Ladestand; dafür braucht es den Ladestand der Batterie.
- Bereich Wärme: neuer Kennwert „Für die Wärmepumpe übrig“, im Verlauf gepunktet, dazu die Schwelle für die zweite Stufe. Für den gezeigten Tag steht da, woher der Strom der Wärmepumpe kam (vom Dach, aus dem Akku, aus dem Netz) und wie viel beim Anheben vom Dach kam.
- Auswertung der letzten 7 Tage: „Beim Anheben … % Solarstrom“ statt nur der Dauer. Die Aussage zur Wärmepumpe rechnet jetzt vorsichtig: Netzbezug und Akku zählen zuerst bei der Wärmepumpe.
- Neuer Problem-Sensor: an, wenn die Wärmepumpe eine Vorgabe nicht annimmt, der Überschuss oder die Prognose keinen Wert liefert, die Stellgröße fehlt oder die Wärmepumpe nichts meldet. Die Gründe stehen im Attribut `problems`. Damit lässt sich eine Benachrichtigung als normale Automation bauen.
- Effizienz-Export: neue Spalte `stark_angehoben_min`; `angehoben_min` zählt beide Stufen.

## 0.6.0 – 2026-11-20

- Die Regelung rechnet mit dem Mittel des PV-Überschusses über die letzten 5 Minuten (einstellbar, 0 = aus). Kurze Wolken setzen die Wartezeit bis zum Anheben nicht mehr zurück.
- Fällt der Überschuss-Sensor kurz aus, gilt sein letzter Wert noch 3 Minuten. Erst danach geht die Heizung zur Sicherheit in den Normalbetrieb.
- Das Anheben endet nach dem Überschuss ohne Akku, also dem Überschuss plus der Ladeleistung des Akkus. So läuft es weiter, solange die PV die Wärmepumpe trägt, und endet, wenn der Akku sie stützen müsste. Neu im Schritt Regeln: „Beim Beenden den Akku herausrechnen“ (an). Wirkt nur mit hinterlegter Leistung der Batterie.
- Neue Ausschaltschwelle −300 W statt 300 W. Wer die Regeln schon einmal gespeichert hat, behält seinen Wert und sollte ihn prüfen.
- Absenken über Nacht: Geht das Absenkfenster über Mitternacht (etwa 21:00 bis 10:00 Uhr), zählt vor Mitternacht die Prognose für morgen.
- Bereich Wärme: Kennwert „Überschuss ohne Akku“, im Verlauf als gestrichelte Linie, im Logbuch bei jedem Eintrag.
- Bereich Wärme: Der PV-Überschuss wird nie unter 0 W angezeigt, auch nicht im Verlauf und im Logbuch. Netzbezug zählt dort als 0 W. Im Export stehen weiter die echten Werte.
- Bereich PV: Die Erklärung unter „Wechselrichter und Optimierer“ steht jetzt hinter einem i-Knopf neben der Überschrift und nimmt so keinen Platz mehr weg.

## 0.5.6 – 2026-11-20

- Tagesleiste unten in allen Bereichen: Sie zeigt, welcher Tag zu sehen ist. Mit den Pfeilen geht es einen Tag zurück oder vor, „Heute“ springt zurück auf heute. Gibt es keine älteren Daten mehr, ist der Pfeil zurück ausgegraut.
- An einem früheren Tag zeigen Übersicht, Strom, PV und Wärme dessen Tageswerte, Verläufe und Ranglisten, etwa „Verbrauch gestern“ oder „Paneele am 17. November“. Was gerade passiert, bleibt live: Leistung jetzt, Kacheln „Paneele jetzt“, Lage der Heizung.
- Tage, die länger zurückliegen, als Home Assistant die genauen Werte aufhebt (von sich aus zehn Tage), kommen aus den Stundenwerten der Statistik und sind entsprechend gröber.

## 0.5.5 – 2026-11-20

- Zeitleiste im Bereich PV: Unter „Paneele jetzt“ steht die Leistung der Anlage über den Tag. Wer mit dem Finger darüber wischt oder mit der Maus darüberfährt, sieht auf den Kacheln die Leistung jedes Paneels zu dieser Uhrzeit, etwa um zu erkennen, wann ein Modul im Schatten liegt. Beim Loslassen zeigen die Kacheln wieder die aktuellen Werte.
- Vor dem ersten Licht des Tages zeigt die Zeitleiste den Tag davor. Mit der Tastatur geht es über die Pfeiltasten.

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
