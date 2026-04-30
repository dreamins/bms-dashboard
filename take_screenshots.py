"""Start the dashboard, take desktop + mobile screenshots, shut it down."""
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

APP_URL    = "http://127.0.0.1:8080"
OUT_DIR    = Path(__file__).parent / "screenshots"
OUT_DIR.mkdir(exist_ok=True)

PYTHON     = str(Path(__file__).parent / ".venv" / "Scripts" / "python.exe")
APP        = str(Path(__file__).parent / "dashboard_app" / "dashboard.py")
CONFIG     = Path(__file__).parent / "dashboard_app" / "batteries_config.json"

REDACT_NAMES = {
    "LiTime-Battery-01": "LiTime-Battery-01",
    "LiTime-Battery-01":         "LiTime-Battery-01",
    "EG4-Battery-01":                 "EG4-Battery-01",
}

def patch_config():
    """Temporarily rename batteries in config so the app shows generic names."""
    import json
    if not CONFIG.exists():
        return None
    original = CONFIG.read_text(encoding="utf-8")
    data = json.loads(original)
    for entry in data:
        for real, fake in REDACT_NAMES.items():
            if entry.get("name") == real:
                entry["name"] = fake
            if entry.get("mac") == real:
                entry["mac"] = fake
    CONFIG.write_text(json.dumps(data), encoding="utf-8")
    return original

def restore_config(original):
    if original is not None:
        CONFIG.write_text(original, encoding="utf-8")

def start_app():
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [PYTHON, APP],
        cwd=str(Path(__file__).parent / "dashboard_app"),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Wait for NiceGUI to be ready
    import urllib.request, urllib.error
    for _ in range(30):
        try:
            urllib.request.urlopen(APP_URL, timeout=1)
            break
        except Exception:
            time.sleep(1)
    return proc

REPLACEMENTS = {
    "EG4-Battery-01":       "EG4-Battery-01",
    "LiTime-Battery-01": "LiTime-Battery-01",
}

def redact_text(page):
    """Replace real device IDs everywhere in the DOM."""
    for real, fake in REPLACEMENTS.items():
        page.evaluate(f"""() => {{
            // Text nodes
            const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            let node;
            while ((node = walk.nextNode())) {{
                if (node.nodeValue.includes({repr(real)}))
                    node.nodeValue = node.nodeValue.replaceAll({repr(real)}, {repr(fake)});
            }}
            // Elements whose value attribute contains the ID (inputs, etc.)
            document.querySelectorAll('[value]').forEach(el => {{
                if (el.value && el.value.includes({repr(real)}))
                    el.value = el.value.replaceAll({repr(real)}, {repr(fake)});
            }});
            // Any element whose innerHTML contains it as plain text
            document.querySelectorAll('*').forEach(el => {{
                if (el.children.length === 0 && el.textContent.includes({repr(real)}))
                    el.textContent = el.textContent.replaceAll({repr(real)}, {repr(fake)});
            }});
        }}""")

def shoot(page, path, label):
    page.goto(APP_URL, wait_until="networkidle", timeout=15000)
    page.wait_for_timeout(10000)
    redact_text(page)
    page.wait_for_timeout(500)
    page.screenshot(path=str(path), full_page=False)
    print(f"  saved {label} → {path}")

def main():
    print("Patching config…")
    original_config = patch_config()
    print("Starting dashboard…")
    proc = start_app()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            # Desktop (1920 × 1080)
            print("Capturing desktop view…")
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            shoot(page, OUT_DIR / "desktop.png", "desktop")
            page.close()

            # Mobile (390 × 844 — iPhone 14)
            print("Capturing mobile view…")
            page = browser.new_page(viewport={"width": 390, "height": 844})
            shoot(page, OUT_DIR / "mobile.png", "mobile")
            page.close()

            browser.close()
    finally:
        proc.terminate()
        restore_config(original_config)
        print("Done.")

if __name__ == "__main__":
    main()
