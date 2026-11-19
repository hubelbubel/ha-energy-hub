"""Energy-Hub-Zeichen: ein „E“ aus den Bilanzbalken des Panels. Erzeugt docs/logo.svg, docs/logo-dark.svg und die PNG in custom_components/energy_hub/brand/.

Aufruf: python3 dev/brand.py  (braucht Playwright und Chromium)
"""

from pathlib import Path
from playwright.sync_api import sync_playwright

LIGHT = dict(ink="#1c1c1c", pv="#eda100", ret="#2a78d6", flow="#eb6834")
DARK = dict(ink="#e8e8e8", pv="#e0a21a", ret="#4a93e8", flow="#e8693a")

def svg(c, size=256):
    # Rücken in Tinte; Arme: Dach (gelb), Strom (blau), Wärme (orange). Rechte Enden gerundet wie die Balken im Panel.
    arm = lambda x0, x1, y0, y1, fill: (
        f'<path d="M{x0} {y0} H{x1 - 14} a14 14 0 0 1 14 14 V{y1 - 14} a14 14 0 0 1 -14 14 H{x0} Z" fill="{fill}"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="{size}" height="{size}">'
            f'<path d="M40 0 H78 V256 H40 a10 10 0 0 1 -10 -10 V10 a10 10 0 0 1 10 -10 Z" fill="{c["ink"]}"/>'
            + arm(84, 226, 0, 60, c["pv"]) + arm(84, 180, 98, 158, c["ret"]) + arm(84, 226, 196, 256, c["flow"])
            + "</svg>")

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / "custom_components" / "energy_hub" / "brand"
out.mkdir(parents=True, exist_ok=True)
docs = ROOT / "docs"
(docs / "logo.svg").write_text(svg(LIGHT, 256) + "\n")
(docs / "logo-dark.svg").write_text(svg(DARK, 256) + "\n")
with sync_playwright() as pw:
    b = pw.chromium.launch()
    for name, pal in (("icon", LIGHT), ("dark_icon", DARK)):
        for scale, suffix in ((256, ""), (512, "@2x")):
            p = b.new_page(viewport={"width": scale, "height": scale})
            p.set_content(f'<html><body style="margin:0;background:transparent">{svg(pal, scale)}</body></html>')
            p.screenshot(path=str(out / f"{name}{suffix}.png"), omit_background=True,
                         clip={"x": 0, "y": 0, "width": scale, "height": scale})
            p.close()
    b.close()
print("ok")
