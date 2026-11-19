"""Jede Version braucht einen Abschnitt in CHANGELOG.md; die CI macht daraus den Text des Releases."""
from __future__ import annotations

import json
from pathlib import Path
import re

ROOT = Path(__file__).parents[1]


def _sections() -> dict[str, str]:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    parts = re.split(r"^## ", text, flags=re.MULTILINE)[1:]
    return {part.split()[0]: part.split("\n", 1)[1].strip() for part in parts}


def test_aktuelle_version_steht_im_changelog():
    version = json.loads((ROOT / "custom_components" / "energy_hub" / "manifest.json").read_text())["version"]
    sections = _sections()
    assert version in sections, f"CHANGELOG.md braucht einen Abschnitt „## {version} – Datum“"
    assert sections[version].startswith("- "), "Der Abschnitt braucht mindestens einen Punkt"


def test_versionen_stehen_absteigend():
    versions = [tuple(int(x) for x in v.split(".")) for v in _sections()]
    assert versions == sorted(versions, reverse=True)
