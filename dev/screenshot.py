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

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parents[1]
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/shots")
OUT.mkdir(parents=True, exist_ok=True)

SHOTS = [
    ("desktop-light-boost", 1360, 900, "?mode=boost"),
    ("desktop-dark-setback", 1360, 900, "?mode=setback&theme=dark"),
    ("desktop-light-empty", 1360, 900, "?mode=empty"),
    ("mobile-light-override", 390, 844, "?mode=override"),
    ("mobile-dark-normal", 390, 844, "?mode=normal&theme=dark"),
]

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keine Zugriffszeilen im Terminal
        pass


handler = functools.partial(Quiet, directory=str(ROOT))
server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_address[1]}/dev/preview.html"

problems = []
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome")
    for name, w, h, query in SHOTS:
        page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
        page.on("console", lambda m, n=name: m.type == "error" and "404" not in m.text and problems.append(f"{n}: {m.text}"))
        page.on("pageerror", lambda e, n=name: problems.append(f"{n}: {e}"))
        page.goto(base + query)
        page.wait_for_timeout(700)
        if name.startswith("desktop-light-boost"):
            box = page.evaluate(
                "() => { const r = document.querySelector('wp-leitstand-panel').shadowRoot"
                ".querySelector('.plots').getBoundingClientRect(); return [r.left, r.top, r.width]; }"
            )
            page.mouse.move(box[0] + box[2] * 0.62, box[1] + 120)
            page.wait_for_timeout(100)
        overflow = page.evaluate("() => document.documentElement.scrollWidth - innerWidth")
        if overflow > 0:
            problems.append(f"{name}: Seite ist {overflow}px breiter als das Fenster")
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
        page.close()
    browser.close()
server.shutdown()

print("Bilder in", OUT)
print("\n".join(problems) if problems else "Keine Konsolenfehler, kein horizontales Überlaufen")
sys.exit(1 if problems else 0)
