"""Automated browser verification of the React workspace (docs/BROWSER_VERIFICATION.md).

Drives a real Chrome/Chromium through Playwright against a running deployment and
writes docs/evidence/browser_verification.json plus screenshots in docs/images/ui/.

Requirements (not part of the runtime lockfile):
    pip install playwright==1.55.0      # uses the installed Google Chrome (channel="chrome")

Usage:
    docker compose up -d                                  # workspace on 127.0.0.1:5173, API proxied at /api
    python scripts/browser_check.py --base http://127.0.0.1:5173 --api http://127.0.0.1:5173/api

The script runs analyses and records clearly labelled demonstration review events on the
target deployment. Use a disposable deployment; demonstration events are not expert validation.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
WIDTHS = {"mobile": (375, 812), "tablet": (768, 1024), "desktop": (1440, 900)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5173")
    ap.add_argument("--api", default="http://127.0.0.1:5173/api")
    ap.add_argument("--channel", default="chrome")
    args = ap.parse_args()
    shots = ROOT / "docs" / "images" / "ui"; shots.mkdir(parents=True, exist_ok=True)
    checks, console_errors = [], []

    def check(name, ok, detail=""):
        checks.append({"check": name, "passed": bool(ok), "detail": detail})
        print(("PASS " if ok else "FAIL ") + name + (f" - {detail}" if detail else ""))

    with sync_playwright() as p:
        browser = p.chromium.launch(channel=args.channel, headless=True)
        version = browser.version
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        page = ctx.new_page()
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        review_requests = []
        page.on("request", lambda r: review_requests.append(r.url) if "/reviews?" in r.url else None)

        def run_id_on_screen():
            m = re.search(r"Run ([0-9a-f]{8})", page.locator(".run-strip small").inner_text())
            return m.group(1) if m else None

        def analyze(clusters=None, dataset=None):
            if dataset:
                page.get_by_label("Dataset").select_option(dataset)
            if clusters:
                page.get_by_label("Requested clusters").fill(str(clusters))
            page.get_by_role("button", name="Run analysis").click()
            expect(page.get_by_role("status").filter(has_text="Published")).to_be_visible(timeout=60000)
            page.wait_for_timeout(500)

        page.goto(args.base)
        page.wait_for_load_state("networkidle")
        if page.locator(".run-strip").count() == 0:
            analyze()

        # 1. Overview content and provenance
        body = page.locator("main").inner_text()
        check("overview shows analysed totals", "Reviews analyzed" in body and "517" in body)
        check("overview shows cleaning transparency", "603 raw" in body and "84 duplicates" in body)
        check("score semantics stated (polarity, not confidence)", "not confidence" in body)
        check("actual provider label shown", "Rule-based" in body)

        # 2. Responsive layout at three widths
        for label, (w, h) in WIDTHS.items():
            page.set_viewport_size({"width": w, "height": h})
            page.wait_for_timeout(400)
            overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            labels = [b.inner_text().strip() for b in page.locator("nav button").all()]
            visible = all(b.is_visible() for b in page.locator("nav button").all())
            check(f"{label} {w}px: no horizontal overflow", overflow <= 1, f"overflow {overflow}px")
            check(f"{label} {w}px: navigation labels readable", visible and labels == ["Overview", "Theme evidence", "Action review"])
            page.screenshot(path=str(shots / f"overview_{label}.png"), full_page=False)
        page.set_viewport_size({"width": 1440, "height": 900})

        # 3. Keyboard navigation and focus visibility
        page.locator("nav button").first.focus()
        page.keyboard.press("Tab")
        focused = page.evaluate("document.activeElement.innerText")
        outline = page.evaluate("getComputedStyle(document.activeElement).outlineStyle")
        page.keyboard.press("Enter")
        current = page.locator("nav button[aria-current=page]").inner_text()
        check("keyboard Tab/Enter switches view", focused == "Theme evidence" and current == "Theme evidence")
        check("keyboard focus is visibly outlined", outline not in ("none", ""), f"outline-style {outline}")

        # 4. Theme selection, rerun with different K, no stale detail
        page.locator(".theme").nth(1).click()
        before_title = page.locator(".theme-grid h2").nth(1).inner_text()
        old_run = run_id_on_screen()
        review_requests.clear()
        analyze(clusters=5)
        page.locator("nav button", has_text="Theme evidence").click()
        page.wait_for_timeout(800)
        new_run = run_id_on_screen()
        names = [t.inner_text().split("\n")[0] for t in page.locator(".theme").all()]
        title = page.locator(".theme-grid h2").nth(1).inner_text()
        pinned = [u for u in review_requests if "run_id=" in u]
        check("rerun publishes a new run", new_run and new_run != old_run, f"{old_run} -> {new_run}")
        check("rerun refreshes theme list (K=5)", len(names) == 5, f"{len(names)} themes")
        check("selected theme detail belongs to new run", title in names, title)
        check("review requests pinned to the new run id",
              bool(pinned) and all(new_run in u for u in pinned[-1:]), f"{len(pinned)} requests")
        page.get_by_label("Requested clusters").fill("7")

        # 5. Historical run selection
        options = page.get_by_label("Analysis run").locator("option").all()
        hist_value = options[-1].get_attribute("value")
        review_requests.clear()
        page.get_by_label("Analysis run").select_option(hist_value)
        page.wait_for_timeout(1200)
        page.locator(".theme").first.click(); page.wait_for_timeout(800)
        check("historical run selection switches run", run_id_on_screen() == hist_value[:8], hist_value[:8])
        check("historical drill-down uses that run id",
              bool(review_requests) and all(hist_value in u for u in review_requests), f"{len(review_requests)} requests")
        page.get_by_label("Analysis run").select_option("")
        page.wait_for_timeout(1000)

        # 6. Evidence link from action to theme
        page.locator("nav button", has_text="Action review").click()
        card = page.locator(".card").first
        card_theme = card.locator("h3").inner_text()
        card.locator("summary", has_text="Selected source evidence").click()
        evidence_text = card.locator("blockquote").first.inner_text()
        card.get_by_role("button", name="Open theme evidence").click()
        page.wait_for_timeout(800)
        check("action evidence opens matching theme", page.locator(".theme-grid h2").nth(1).inner_text() == card_theme, card_theme)
        check("evidence shows exact source text and row", "Source row" in evidence_text)
        page.screenshot(path=str(shots / "theme_evidence_desktop.png"))

        # 7. Human review event and stale conflict surfaced in the UI
        page.locator("nav button", has_text="Action review").click()
        card = page.locator(".card").first
        card.locator("summary", has_text="Record a human review").click()
        card.get_by_label("Reviewer name or pseudonym").fill("Demo reviewer (not expert)")
        card.get_by_label("Reason and evidence checked").fill("Demonstration event recorded by the browser check script.")
        card.get_by_role("button", name="Save review event").click()
        page.wait_for_timeout(1200)
        card = page.locator(".card").filter(has_text=card_theme).first
        check("review event saved and shown", "accepted by Demo reviewer" in card.inner_text())
        second = page.locator(".card").nth(1)
        second.locator("summary", has_text="Record a human review").click()
        second.get_by_label("Reviewer name or pseudonym").fill("Demo reviewer (not expert)")
        second.get_by_label("Reason and evidence checked").fill("Second demonstration event to provoke a conflict.")
        snap = requests.get(args.api + "/dashboard/snapshot", timeout=10).json()
        target = [a for a in snap["insights"] if a["theme_name"] == second.locator("h3").inner_text()][0]
        requests.post(f"{args.api}/insights/{target['id']}/review", timeout=10, json={
            "expected_version": target["review_version"], "decision": "rejected",
            "reviewer": "Concurrent demo", "note": "Concurrent change made via the API by the check script."})
        second.get_by_role("button", name="Save review event").click()
        page.wait_for_timeout(1000)
        alert = second.get_by_role("alert")
        check("stale concurrent review rejected with clear message",
              alert.count() > 0 and "reviewed elsewhere" in alert.inner_text())
        page.screenshot(path=str(shots / "action_review_desktop.png"))

        # 8. Export bundle matches the screen
        with page.expect_download() as dl:
            page.get_by_role("button", name="Export evidence bundle").click()
        bundle = json.loads(Path(dl.value.path()).read_text(encoding="utf-8"))
        page.locator("nav button", has_text="Overview").click()
        shown_total = page.locator(".metric").first.locator("h2").inner_text()
        check("export bundle matches displayed run",
              bundle["run"]["id"].startswith(run_id_on_screen()) and str(len(bundle["reviews"])) == shown_total,
              f"{bundle['run']['id'][:8]} reviews {len(bundle['reviews'])}")
        check("export retains original advice and review history",
              any(a["review_history"] for a in bundle["insights"]) and all(a.get("engineering_recommendation") for a in bundle["insights"]))

        # 9. API failure shows an error, not an empty-data screen
        page.route("**/api/**", lambda r: r.abort())
        page.reload(); page.wait_for_timeout(1500)
        err = page.get_by_role("alert")
        empty = page.locator(".empty").count()
        check("API outage shows actionable error and retry, not empty data",
              err.count() > 0 and "Cannot reach" in err.inner_text() and empty == 0
              and page.get_by_role("button", name="Retry loading").count() == 1)
        page.screenshot(path=str(shots / "api_error_desktop.png"))
        page.unroute("**/api/**")
        page.get_by_role("button", name="Retry loading").click(); page.wait_for_timeout(1500)
        check("retry recovers after API returns", page.locator(".run-strip").count() == 1)

        # 10. Long public text on mobile
        analyze(dataset="nhtsa_public_sample.csv")
        page.set_viewport_size({"width": 375, "height": 812})
        page.locator("nav button").nth(1).click(); page.wait_for_timeout(1000)
        overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        clipped = page.evaluate("""[...document.querySelectorAll('button')].filter(b => {const r=b.getBoundingClientRect(); return r.width>0 && (r.right>window.innerWidth+1 || r.left<-1)}).length""")
        check("NHTSA long text wraps on mobile without overflow", overflow <= 1, f"overflow {overflow}px")
        check("no clipped buttons on mobile", clipped == 0, f"{clipped} clipped")
        page.screenshot(path=str(shots / "theme_evidence_mobile_nhtsa.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 900})
        analyze(dataset="reviews_raw.csv")  # leave the default dataset published

        relevant = [e for e in console_errors if "net::ERR_FAILED" not in e and "Failed to fetch" not in e and "Failed to load resource" not in e]
        check("no unexpected console errors", not relevant, "; ".join(relevant[:3]))
        browser.close()

    result = {"generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "browser": f"Chrome {version} (headless, Playwright)",
              "base_url": args.base, "passed": sum(c["passed"] for c in checks), "total": len(checks), "checks": checks,
              "note": "Demonstration review events were recorded by a script; they are not expert validation."}
    out = ROOT / "docs" / "evidence" / "browser_verification.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\n{result['passed']}/{result['total']} browser checks passed")
    sys.exit(0 if result["passed"] == result["total"] else 1)


if __name__ == "__main__":
    main()
