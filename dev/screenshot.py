#!/usr/bin/env python3
"""Rendert dev/preview.html in mehreren Varianten und meldet Konsolenfehler.

Prüft dazu die Exporte, das Anordnen der Optimierer und die Zeitleiste unter den Kacheln.

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
    # früh am Morgen, vor dem ersten Licht: die Zeitleiste zeigt gestern
    ("pv-mobile-morgen", 390, 844, "?tab=pv&mode=normal", 6),
    ("pv-desktop-empty", 1360, 900, "?tab=pv&mode=empty", 13),
    ("pv-desktop-raster", 1360, 900, "?tab=pv&mode=boost&raster=dach", 13),
    ("pv-mobile-raster", 390, 844, "?tab=pv&mode=boost&raster=dach", 13),
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
    # Optimierer anordnen: A1 auf A2 ziehen (tauschen), dann A3 mit der Tastatur nach unten
    for name, w, h in (("pv-anordnen-desktop", 1360, 900), ("pv-anordnen-mobile", 390, 844)):
        page = browser.new_page(viewport={"width": w, "height": h})
        page.clock.set_fixed_time(FIXED.replace(hour=13, minute=20))
        page.on("pageerror", lambda e, n=name: problems.append(f"{n}: {e}"))
        sent = []
        page.on("console", lambda m: "set_pv_grid" in m.text and sent.append(m.text))
        page.goto(base + "?tab=pv&mode=boost")
        page.wait_for_timeout(700)
        page.get_by_role("button", name="Anordnen").click()
        if not page.evaluate("() => document.querySelector('energy-hub-panel').shadowRoot.querySelector('.daybar').hidden"):
            problems.append(f"{name}: Zeitleiste bleibt beim Anordnen sichtbar")
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
        tile = lambda label: page.locator(f"energy-hub-panel .tile-grid .tile:has(span:text-is('{label}'))")
        a, b = tile("A1").bounding_box(), tile("A2").bounding_box()
        page.mouse.move(a["x"] + a["width"] / 2, a["y"] + a["height"] / 2)
        page.mouse.down()
        page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, steps=6)
        page.mouse.up()
        tile("A3").focus()
        page.keyboard.press("ArrowDown")
        area = lambda label: page.evaluate(
            f"() => [...document.querySelector('energy-hub-panel').shadowRoot.querySelectorAll('.tile')]"
            f".find((t) => t.querySelector('span').textContent === '{label}').style.gridArea")
        got = [area(label) for label in ("A1", "A2", "A3")]
        if got != ["2 / 3", "2 / 2", "3 / 4"] or len(sent) != 2:
            problems.append(f"{name}: Anordnen ergab {got}, {len(sent)}× gespeichert")
        page.get_by_role("button", name="Fertig").click()
        page.screenshot(path=str(OUT / f"{name}-fertig.png"), full_page=True)
        page.close()
    # Zeitleiste unter den Kacheln: Maus darüber, Finger wischen, Tastatur; danach wieder jetzt
    ROOT_JS = "document.querySelector('energy-hub-panel').shadowRoot"
    head = f"() => {ROOT_JS}.querySelector('main:not([hidden]) .lage h2').textContent"
    a9 = f"() => [...{ROOT_JS}.querySelectorAll('main:not([hidden]) .tile')].find((t) => t.querySelector('span').textContent === 'A9').className"
    for name, w, h in (("pv-zeitleiste-desktop", 1360, 900), ("pv-zeitleiste-mobile", 390, 844)):
        mobile = w < 500
        ctx = browser.new_context(viewport={"width": w, "height": h}, has_touch=mobile, is_mobile=mobile)
        page = ctx.new_page()
        page.clock.set_fixed_time(FIXED)
        page.on("pageerror", lambda e, n=name: problems.append(f"{n}: {e}"))
        page.goto(base + "?tab=pv&mode=boost&raster=dach")
        page.wait_for_timeout(700)
        box = page.evaluate(f"() => {{ const r = {ROOT_JS}.querySelector('main:not([hidden]) .day-plot').getBoundingClientRect();"
                            " return [r.left, r.top, r.width]; }")
        y = box[1] + 30
        x_at = lambda f: box[0] + box[2] * f
        if mobile:
            # echter Touch über das DevTools-Protokoll, damit touch-action wie auf dem Telefon greift
            cdp = ctx.new_cdp_session(page)
            touch = lambda kind, x: cdp.send("Input.dispatchTouchEvent",
                                             {"type": kind, "touchPoints": [] if kind == "touchEnd" else [{"x": x, "y": y}]})
            touch("touchStart", x_at(0.3))
            for k in range(1, 9):
                touch("touchMove", x_at(0.3 + 0.5 * k / 8))
        else:
            page.mouse.move(x_at(0.8), y)
        page.wait_for_timeout(100)
        during, cls = page.evaluate(head), page.evaluate(a9)
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
        if mobile:
            touch("touchEnd", 0)
        else:
            page.mouse.move(5, 5)
        page.wait_for_timeout(100)
        after = page.evaluate(head)
        # um 15 Uhr liegt A9 in den Beispieldaten im Schatten
        if not during.startswith("Paneele um 1") or "low" not in cls or after != "Paneele jetzt":
            problems.append(f"{name}: Zeitleiste ergab „{during}“, A9 „{cls}“, danach „{after}“")
        if not mobile:
            page.locator("energy-hub-panel .daybar").focus()
            page.keyboard.press("PageDown")
            keyed = page.evaluate(head)
            page.keyboard.press("Escape")
            if keyed != "Paneele um 15:55 Uhr" or page.evaluate(head) != "Paneele jetzt":
                problems.append(f"{name}: Tastatur ergab „{keyed}“, danach „{page.evaluate(head)}“")
        ctx.close()
    browser.close()
server.shutdown()

print("Bilder in", OUT)
print("\n".join(problems) if problems else "Keine Konsolenfehler, kein horizontales Überlaufen")
sys.exit(1 if problems else 0)
