#!/usr/bin/env python3
"""Rendert dev/preview.html in mehreren Varianten und meldet Konsolenfehler.

Aufruf (im Hauptordner):  python3 dev/screenshot.py /tmp/shots
Braucht Playwright und einen installierten Chrome.
"""
from __future__ import annotations

import functools
import http.server
import sys
import threading
from pathlib import Path

import datetime

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parents[1]
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/shots")
OUT.mkdir(parents=True, exist_ok=True)

SHOTS = [
    ("overview-desktop-light", 1360, 900, "?tab=overview&mode=boost"),
    ("overview-desktop-dark", 1360, 900, "?tab=overview&mode=setback&theme=dark"),
    ("overview-mobile-light", 390, 844, "?tab=overview&mode=boost"),
    ("power-desktop-light", 1360, 900, "?tab=power&mode=boost"),
    ("power-desktop-dark", 1360, 900, "?tab=power&mode=setback&theme=dark"),
    ("power-mobile-dark", 390, 844, "?tab=power&mode=normal&theme=dark"),
    # PV mittags, damit die Optimierer Werte haben (fünfter Wert: Stunde)
    ("pv-desktop-light", 1360, 900, "?tab=pv&mode=boost", 13),
    ("pv-desktop-dark", 1360, 900, "?tab=pv&mode=boost&theme=dark", 15),
    ("pv-mobile-light", 390, 844, "?tab=pv&mode=boost", 13),
    ("pv-desktop-night", 1360, 900, "?tab=pv&mode=normal", None),
    ("pv-desktop-empty", 1360, 900, "?tab=pv&mode=empty", 13),
    ("overview-desktop-empty", 1360, 900, "?tab=overview&mode=empty"),
    ("desktop-light-boost", 1360, 900, "?tab=heat&mode=boost"),
    ("desktop-dark-setback", 1360, 900, "?tab=heat&mode=setback&theme=dark"),
    ("desktop-light-empty", 1360, 900, "?tab=heat&mode=empty"),
    ("mobile-light-override", 390, 844, "?tab=heat&mode=override"),
    ("mobile-dark-normal", 390, 844, "?tab=heat&mode=normal&theme=dark"),
]

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keine Zugriffszeilen im Terminal
        pass


handler = functools.partial(Quiet, directory=str(ROOT))
server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_address[1]}/dev/preview.html"

problems = []
# Feste Uhrzeit, damit die Bilder unabhängig von der Tageszeit einen gefüllten Tag zeigen
FIXED = datetime.datetime.now().replace(hour=17, minute=40, second=0, microsecond=0)
if FIXED > datetime.datetime.now():
    FIXED -= datetime.timedelta(days=1)
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    for name, w, h, query, *rest in SHOTS:
        page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
        page.clock.set_fixed_time(FIXED.replace(hour=rest[0], minute=20) if rest and rest[0] is not None else FIXED)
        page.on("console", lambda m, n=name: m.type == "error" and "404" not in m.text and problems.append(f"{n}: {m.text}"))
        page.on("pageerror", lambda e, n=name: problems.append(f"{n}: {e}"))
        page.goto(base + query)
        page.wait_for_timeout(900)
        if name == "pv-desktop-dark":
            root = "document.querySelector('energy-hub-panel').shadowRoot"
            page.evaluate(f"() => {{ for (const l of ['A9', 'A4', 'A12']) [...{root}.querySelectorAll('.tile')]"
                          ".find((b) => b.textContent.startsWith(l + ' ') || b.querySelector('span').textContent === l).click(); }")
            page.wait_for_timeout(600)
        if name.startswith("desktop-light-boost") or name == "pv-desktop-dark":
            box = page.evaluate(
                "() => { const r = document.querySelector('energy-hub-panel').shadowRoot"
                ".querySelector('main:not([hidden]) .plots').getBoundingClientRect(); return [r.left, r.top, r.width]; }"
            )
            page.mouse.move(box[0] + box[2] * 0.62, box[1] + 120)
            page.wait_for_timeout(100)
        overflow = page.evaluate("() => document.documentElement.scrollWidth - innerWidth")
        if overflow > 0:
            problems.append(f"{name}: Seite ist {overflow}px breiter als das Fenster")
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
        page.close()
    # Export: Dialog öffnen, beide Exporte erstellen und die heruntergeladenen Dateien ablegen
    DIALOG = "document.querySelector('energy-hub-panel').shadowRoot"
    for name, w, h in (("export-desktop", 1360, 900), ("export-mobile", 390, 844)):
        page = browser.new_page(viewport={"width": w, "height": h}, accept_downloads=True)
        page.clock.set_fixed_time(FIXED)
        page.on("pageerror", lambda e, n=name: problems.append(f"{n}: {e}"))
        page.goto(base + "?tab=heat&mode=boost")
        page.wait_for_timeout(500)
        page.get_by_role("button", name="Export", exact=True).click()
        page.screenshot(path=str(OUT / f"{name}-dialog.png"))
        for kind, label in (("verlauf", "Verlauf und Entscheidungen"), ("effizienz", "Effizienz")):
            page.get_by_label(label).check()
            page.get_by_role("button", name="Export erstellen").click()
            page.get_by_role("button", name="Herunterladen").wait_for(timeout=20000)
            status = page.evaluate(f"() => {DIALOG}.querySelector('.dlg-status').textContent")
            if name == "export-desktop":
                with page.expect_download() as info:
                    page.get_by_role("button", name="Herunterladen").click()
                info.value.save_as(str(OUT / f"{kind}.csv"))
                print(f"{kind}: {info.value.suggested_filename} | {status}")
            else:
                page.screenshot(path=str(OUT / f"{name}-{kind}-fertig.png"))
        page.close()
    # PV-Export
    page = browser.new_page(viewport={"width": 1360, "height": 900}, accept_downloads=True)
    page.clock.set_fixed_time(FIXED.replace(hour=13, minute=20))
    page.on("pageerror", lambda e: problems.append(f"pv-export: {e}"))
    page.goto(base + "?tab=pv&mode=boost")
    page.wait_for_timeout(700)
    page.get_by_role("button", name="Export", exact=True).click()
    page.screenshot(path=str(OUT / "pv-export-dialog.png"))
    page.get_by_role("button", name="Export erstellen").click()
    page.get_by_role("button", name="Herunterladen").wait_for(timeout=30000)
    status = page.evaluate(f"() => {DIALOG}.querySelector('.dlg-status').textContent")
    with page.expect_download() as info:
        page.get_by_role("button", name="Herunterladen").click()
    info.value.save_as(str(OUT / "pv.csv"))
    print(f"pv: {info.value.suggested_filename} | {status}")
    page.close()
    browser.close()
server.shutdown()

print("Bilder in", OUT)
print("\n".join(problems) if problems else "Keine Konsolenfehler, kein horizontales Überlaufen")
sys.exit(1 if problems else 0)
