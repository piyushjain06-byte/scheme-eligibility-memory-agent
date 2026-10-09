"""Make chat replies compact: collapse the sources list and hide the long per-scheme eligibility cards
unless they carry real news (ELIGIBLE / NEEDS_INFORMATION).

Run once from the project root:   python patch_ui.py
A backup is saved as templates/index.html.bak
"""
import shutil
import sys
from pathlib import Path

PATH = Path("templates/index.html")

EDITS = [
    # 1) Only show eligibility cards that matter; hide "Can't check automatically" noise.
    (
        '        if (extras.demo) box.append(el("div", "demo-flag", "DEMO / TEST DATA ONLY — not verified government information."));\n'
        '        if (extras.eligibility && extras.eligibility.length) box.append(renderEligibility(extras.eligibility));\n',
        '        const shown = (extras.eligibility || []).filter((r) => r.status === "ELIGIBLE" || r.status === "NEEDS_INFORMATION").slice(0, 5);\n'
        '        if (extras.demo) box.append(el("div", "demo-flag", "DEMO / TEST DATA ONLY — not verified government information."));\n'
        '        if (shown.length) box.append(renderEligibility(shown));\n',
    ),
    # 2) Sources collapsed behind a small "Sources (N)" toggle.
    (
        '          box.append(sources);\n',
        '          const details = el("details", "src-details");\n'
        '          details.append(el("summary", "", `Sources (${extras.citations.length})`), sources);\n'
        '          box.append(details);\n',
    ),
    # 3) Disclaimer only when cards are shown.
    (
        'if (extras.eligibility && extras.eligibility.length && extras.disclaimer)',
        'if (shown.length && extras.disclaimer)',
    ),
    # 4) Small style for the toggle.
    (
        '    .saved { font-size: .8rem; color: var(--muted); }\n',
        '    .saved { font-size: .8rem; color: var(--muted); }\n'
        '    .src-details summary { cursor: pointer; font-size: .8rem; color: var(--muted); }\n'
        '    .src-details .sources { margin-top: .4rem; }\n',
    ),
]


def main():
    if not PATH.exists():
        sys.exit("Run this from the project root (templates/index.html not found).")
    text = PATH.read_text(encoding="utf-8")
    if "src-details" in text:
        sys.exit("Already patched.")
    for number, (old, new) in enumerate(EDITS, 1):
        if text.count(old) != 1:
            sys.exit(f"Edit {number} could not be applied (found {text.count(old)} matches). Send me your index.html.")
        text = text.replace(old, new)
    shutil.copyfile(PATH, PATH.with_suffix(".html.bak"))
    PATH.write_text(text, encoding="utf-8")
    print("templates/index.html patched (backup: templates/index.html.bak)")


if __name__ == "__main__":
    main()
