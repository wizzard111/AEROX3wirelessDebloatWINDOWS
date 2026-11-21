"""Write the changelog section of one version (release-notes.md) for the GitHub release page.
Usage: python packaging/release_notes.py v5.0.1"""
import re
import sys
from pathlib import Path

version = sys.argv[1].lstrip("vV")
text = (Path(__file__).resolve().parents[1] / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
m = re.search(r"^## V" + re.escape(version) + r"\s*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
notes = m.group(1).strip() if m else text
Path("release-notes.md").write_text(notes + "\n", encoding="utf-8")
print("release notes:", "section V" + version if m else "whole changelog (no section for this version)")
