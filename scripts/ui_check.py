"""Drive the real UI through the integrated loop and capture screenshots.

Usage (servers running):
    python scripts/ui_check.py
Requires: pip install playwright  (uses the installed Chrome, no browser download needed)
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "screenshots"
OUT.mkdir(exist_ok=True)
BASE = "http://localhost:5173"


def main() -> int:
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 950})
        page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

        page.goto(BASE, wait_until="networkidle")
        page.wait_for_selector(".ff-node", state="attached", timeout=15000)
        page.wait_for_timeout(900)
        nodes = page.locator(".ff-node").count()
        print(f"canvas nodes: {nodes}")
        page.screenshot(path=str(OUT / "01-canvas.png"))

        # Run the workflow
        page.get_by_role("button", name="▶ Run workflow").click()
        page.wait_for_selector(".tl-step", timeout=20000)
        page.wait_for_timeout(1800)
        statuses = page.locator(".tl-step .chip").all_inner_texts()
        print("timeline:", statuses)
        run_status = page.locator(".canvas-toolbar .chip").first.inner_text()
        print("run status chip:", run_status)
        page.screenshot(path=str(OUT / "02-after-run.png"))

        # Inspect the failing node
        page.locator(".tl-step").filter(has_text="Contract").first.click()
        page.wait_for_timeout(600)
        page.screenshot(path=str(OUT / "03-node-inspector.png"))

        # WhatIf: run all scenarios
        page.get_by_role("button", name="WhatIf AI").click()
        page.get_by_role("button", name="Run all", exact=False).click()
        page.wait_for_timeout(6000)
        chips = page.locator(".btn-row .chip").all_inner_texts()
        print("whatif:", chips)
        page.screenshot(path=str(OUT / "04-whatif.png"))

        # Doctor: diagnose current trace
        page.get_by_role("button", name="Doctor", exact=True).click()
        # Select the baseline-defect trace explicitly, as a user would after observing a run.
        page.get_by_role("button", name="Black Box").click()
        page.get_by_role("button", name="Trace", exact=True).click()
        page.wait_for_timeout(500)
        page.get_by_role("button", name="Doctor", exact=True).click()
        page.get_by_role("button", name="Diagnose this execution").click()
        page.wait_for_selector("text=Likely cause", timeout=20000)
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "05-diagnosis.png"))

        # Approve -> regression
        page.on("dialog", lambda d: d.accept())
        page.get_by_role("button", name="Approve & apply as new version").click()
        page.wait_for_selector("text=Regression verification", timeout=40000)
        page.wait_for_timeout(1200)
        summary = page.locator(".banner.ok, .banner.warn, .banner.err").filter(has_text="regression checks pass").first.inner_text()
        print("verification:", " ".join(summary.split()))
        assert "6/6" in summary, f"expected a verified 6/6 repair, got: {summary}"
        page.screenshot(path=str(OUT / "06-verified.png"))

        # Black box on the repaired trace
        page.get_by_role("button", name="Black Box").click()
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "07-blackbox.png"))

        browser.close()

    real = [e for e in errors if "favicon" not in e.lower()]
    if real:
        print("\nBROWSER ERRORS:")
        for e in real[:20]:
            print(" ", e)
        return 1
    print("\nno browser console errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
