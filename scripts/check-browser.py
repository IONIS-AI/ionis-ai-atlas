#!/usr/bin/env python3
"""check-browser.py -- render Atlas in a real browser and fail on anything the CSP blocks.

The Content-Security-Policy is enforced by the browser, so no server-side test can tell whether
the pages still work under it: a blocked script is a silent, correct 200 from the API's side. This
drives headless Chromium over both pages, collects every securitypolicyviolation event, console
message, uncaught error and failed request, and exits non-zero if any of them appear.

It also clicks Try it out -> Execute on /api/v1/health, because that is what proves connect-src
'self' permits the page's own fetches -- asserting on the header only proves the header.

    scripts/check-browser.py [base-url]        default http://localhost:8080

Needs Playwright's Chromium:  uv run --with playwright playwright install chromium
"""
import sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("playwright is not installed: uv run --with playwright playwright install chromium")

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080").rstrip("/")

# The page must render something real, not just return 200: an empty <div id="root"> is a pass
# for curl and a blank screen for a user.
PAGES = [
    ("app", "/", "#root", lambda p: p.eval_on_selector("#root", "e => e.children.length") > 0,
     "React app mounted"),
    ("docs", "/api/docs", ".swagger-ui", lambda p: p.locator(".opblock").count() > 0,
     "Swagger UI rendered operations"),
]

HOOK = """
window.__csp = [];
document.addEventListener('securitypolicyviolation', e => window.__csp.push(
  {directive: e.effectiveDirective, blocked: e.blockedURI, line: e.lineNumber, src: e.sourceFile}));
"""


def check(browser, name, path, selector, rendered, what):
    page, console, errors, failed = browser.new_page(), [], [], []
    page.on("console", lambda m: console.append((m.type, m.text)))
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("requestfailed", lambda r: failed.append(r.url))
    page.add_init_script(HOOK)

    problems = []
    try:
        resp = page.goto(BASE + path, wait_until="networkidle", timeout=30_000)
    except Exception as exc:  # unreachable, TLS, timeout: a failure to report, not a crash
        print(f"\n  {name}  {BASE}{path}")
        print(f"    unreachable   {exc.__class__.__name__}")
        page.close()
        return [f"{path}: could not load: {str(exc).splitlines()[0][:160]}"]

    print(f"\n  {name}  {BASE}{path}  HTTP {resp.status}")
    try:
        # attached, not visible: an empty <div id="root"> is present but invisible, and that is
        # precisely the blank-screen case this check exists to catch.
        page.wait_for_selector(selector, state="attached", timeout=15_000)
        page.wait_for_timeout(1_000)
    except Exception:
        problems.append(f"{path}: {selector} never appeared (page did not render)")
    if resp.status != 200:
        problems.append(f"HTTP {resp.status}")
    if not resp.header_value("content-security-policy"):
        problems.append("no Content-Security-Policy header")
    try:
        ok = rendered(page)
    except Exception as exc:
        ok, _ = False, problems.append(f"{path}: render probe failed: {exc.__class__.__name__}")
    if ok:
        print(f"    rendered      {what}")
    else:
        problems.append(f"{path}: did not render ({what})")

    for v in page.evaluate("window.__csp || []"):
        problems.append(f"CSP {v['directive']} blocked {v['blocked']} ({v['src']}:{v['line']})")
    for t, m in console:
        problems.append(f"console [{t}] {m[:200]}")
    for e in errors:
        problems.append(f"uncaught error: {e[:200]}")
    for u in failed:
        problems.append(f"request failed: {u}")
    if not problems:
        print("    clean         no CSP violations, no console output, no failed requests")
    page.close()
    return problems


def check_live_call(browser):
    """Try it out -> Execute on GET /api/v1/health: connect-src 'self' must permit the fetch."""
    page, problems = browser.new_page(), []
    print(f"\n  live call  GET /api/v1/health from the docs page")
    try:
        page.goto(f"{BASE}/api/docs", wait_until="networkidle", timeout=30_000)
        page.locator(".opblock").filter(has_text="/api/v1/health").first.click()
        page.get_by_role("button", name="Try it out").first.click()
        page.get_by_role("button", name="Execute").first.click()
        page.wait_for_timeout(2_000)
        body = page.locator(".responses-table .microlight").first.inner_text()
    except Exception as exc:
        page.close()
        return [f"live call could not be driven: {exc.__class__.__name__}: "
                f"{str(exc).splitlines()[0][:160]}"]
    if '"status"' in body and '"ok"' in body:
        print("    ok            the page's own fetch completed under connect-src 'self'")
    else:
        problems.append(f"docs page could not call the API: {body[:200]!r}")
    page.close()
    return problems


def main() -> int:
    print(f"Browser check against {BASE}")
    problems = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for args in PAGES:
                problems += check(browser, *args)
            problems += check_live_call(browser)
        finally:
            browser.close()
    if problems:
        print(f"\nFAIL: {len(problems)} problem(s)")
        for p in problems:
            print(f"  ! {p}")
        return 1
    print("\nPASS: both pages render, nothing blocked, console silent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
