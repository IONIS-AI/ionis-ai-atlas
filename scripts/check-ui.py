"""check-ui.py — drive the ADIF section in headless Chromium and fail on any broken behaviour.

Covers SPEC R15 (lists paged and searched on the server) and R16 (names from the spec): the page
counts, the pager, search that runs before paging and says what it left out, page size, a stale
page number coming back to the last page, links from before R16 redirecting, curated views paging
too, and a sidebar that only navigates.

Version-agnostic (SPEC R17): no count is written here. The page must show what the API says, so the
expected totals are read from the API first; the API's own numbers are checked against ADIF's
published files by the API tests.

    make check-ui BASE=http://localhost:8080     (the stack must be up: make dev or make up)
"""
import asyncio
import json
import sys
import urllib.request

from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
fails, notes = [], []


def api(path: str):
    with urllib.request.urlopen(f"{BASE}/api/v1{path}", timeout=30) as r:
        return json.load(r), r.headers


n = lambda x: f"{x:,}"
TOTALS = {e["table"]: e["records"] for e in api("/adif/enumerations")[0]}
PAS, SAS = TOTALS["primary_administrative_subdivision"], TOTALS["secondary_administrative_subdivision"]
FIELDS = int(api("/adif/fields?limit=1")[1]["X-Total-Count"])
OBLAST = api("/adif/enumerations/primary_administrative_subdivision?q=oblast&limit=1")[0]["total"]


def check(ok, what):
    (notes if ok else fails).append(("PASS " if ok else "FAIL ") + what)


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(str(e)))
        count = lambda: pg.locator(".controls .count").inner_text()
        rows = lambda: pg.locator("tbody tr").count()

        async def settle():
            await pg.wait_for_selector(".tablewrap:not(.loading), p.state", timeout=15000)
            await pg.wait_for_timeout(150)

        # 1. A big enumeration arrives paged
        await pg.goto(f"{BASE}/adif/enumerations/primary_administrative_subdivision")
        await settle()
        c = await count()
        check(c.startswith(f"1–100 of {n(PAS)}"), f"PAS first page count: {c!r}")
        check(await rows() == 100, f"PAS renders 100 rows, not {n(PAS)} ({await rows()})")
        pager = await pg.locator(".pager span").inner_text()
        check(pager == f"Page 1 of {-(-PAS // 100)}", f"pager: {pager!r}")
        src = await pg.locator(".source").inner_text()
        check("Primary_Administrative_Subdivision" in src and "enumerations_primary_administrative_subdivision.json" in src
              and "GET /api/v1/adif/enumerations/primary_administrative_subdivision" in src, f"R16 source line: {src!r}")
        h = await pg.locator("h1").inner_text()
        check(h == "Primary Administrative Subdivision", f"label: {h!r}")

        # 2. Next page
        await pg.get_by_label("Next page").click()
        await settle()
        c = await count()
        check(c.startswith(f"101–200 of {n(PAS)}") and "page=2" in pg.url, f"page 2: {c!r} url={pg.url}")

        # 3. Search, server-side, back to page 1, says what it left out
        await pg.get_by_label("Search Primary Administrative Subdivision").fill("oblast")
        await pg.wait_for_timeout(700)
        await settle()
        c = await count()
        check(OBLAST > 0 and c.startswith(f"1–{OBLAST} of {OBLAST} matching “oblast”") and f"{n(PAS)} in all" in c
              and await rows() == OBLAST
              and "page=" not in pg.url and "q=oblast" in pg.url,
              f"search: {c!r} url={pg.url}")

        # 4. Nothing matches
        await pg.get_by_label("Search Primary Administrative Subdivision").fill("zzzznothing")
        await pg.wait_for_timeout(700)
        await settle()
        st = await pg.locator("p.state").inner_text()
        check("matches “zzzznothing”" in st, f"no-match message: {st!r}")

        # 5. Page size
        await pg.goto(f"{BASE}/adif/enumerations/primary_administrative_subdivision")
        await settle()
        await pg.locator(".controls .size select").select_option("25")
        await settle()
        c = await count()
        check(c.startswith(f"1–25 of {n(PAS)}") and await rows() == 25 and "size=25" in pg.url, f"size 25: {c!r}")
        check((await pg.locator(".pager span").inner_text()) == f"Page 1 of {-(-PAS // 25)}", "page count at 25 rows")

        # 6. A page past the end (e.g. from a stale link) comes back to the last page
        await pg.goto(f"{BASE}/adif/enumerations/secondary_administrative_subdivision?page=9")
        await settle()
        await pg.wait_for_timeout(500)
        c = await count()
        check(c.startswith(f"1–{SAS} of {SAS}") and "page=" not in pg.url, f"page past end clamps: {c!r} url={pg.url}")

        # 7. A link from before R16 still works
        await pg.goto(f"{BASE}/adif/secondary_administrative_subdivision")
        await settle()
        check(pg.url.endswith("/adif/enumerations/secondary_administrative_subdivision")
              and (await count()).startswith(f"1–{SAS} of {SAS}"), f"legacy link redirected: {pg.url}")

        # 8. Curated views page and search on the server too
        await pg.goto(f"{BASE}/adif/enumerations/mode?q=ft4")
        await settle()
        first = await pg.locator("tbody tr td strong").first.inner_text()
        check(first == "MFSK" and (await count()).startswith("1–1 of 1"), "mode search by submode finds MFSK")
        last = -(-FIELDS // 50)
        await pg.goto(f"{BASE}/adif/fields?size=50&page={last}")
        await settle()
        c = await count()
        check(c.startswith(f"{n((last - 1) * 50 + 1)}–{n(FIELDS)} of {n(FIELDS)}"), f"fields last page at 50: {c!r}")

        # 9. The sidebar navigates by canonical route and carries only the ADIF version
        await pg.goto(f"{BASE}/adif/enumerations/band?v=3.1.6&q=20m")
        await settle()
        href = await pg.locator('nav[aria-label="ADIF enumerations"] a', has_text="Submode").get_attribute("href")
        check(href == "/adif/enumerations/submode?v=3.1.6", f"sidebar link: {href!r}")
        check(await pg.locator('.sidebar input[type="search"]').count() == 0, "no search box left in the sidebar")

        # 10. The brand is the way Home (#36), and Home says what's running and loaded (#37)
        await pg.goto(f"{BASE}/adif/enumerations/band")
        await settle()
        await pg.get_by_label("IONIS-AI Atlas home").click()
        await pg.wait_for_selector(".home .cards", timeout=15000)
        home = await pg.locator(".home").inner_text()
        release = api("/version")[0]
        loaded = [r["adif_version"] for r in api("/adif/releases")[0]]
        check(pg.url.rstrip("/") == BASE.rstrip("/") and "IONIS-AI Atlas" in await pg.locator("h1").inner_text(),
              f"brand opens Home: {pg.url}")
        check(("a development build" if release["version"] == "dev" else f"release {release['version']}") in home
              and all(v in home for v in loaded), "Home shows the running release and every loaded ADIF version")

        # 11. Each section opens on its own landing page, listing everything it holds (#44)
        await pg.get_by_role("link", name="ADIF Reference").first.click()
        # Wait for the list to settle, not for its first row: Data Types and Fields render before the
        # enumerations arrive. Polled from here: page.wait_for_function evaluates a string, which
        # Atlas's CSP (script-src 'self', no unsafe-eval) rightly refuses.
        for _ in range(75):
            if await rows() == 2 + len(TOTALS):
                break
            await pg.wait_for_timeout(200)
        check(pg.url.endswith("/adif") and await pg.locator("h1").inner_text() == "ADIF Reference"
              and await rows() == 2 + len(TOTALS), f"ADIF landing lists data types, fields and {len(TOTALS)} enumerations")

        # 12. The pane collapses, the content widens, and the choice survives a reload (#35)
        await pg.goto(f"{BASE}/adif/enumerations/band")
        await settle()
        wide_before = await pg.locator(".content").evaluate("e => e.getBoundingClientRect().width")
        await pg.get_by_label("Hide ADIF version and navigation").click()
        wide_after = await pg.locator(".content").evaluate("e => e.getBoundingClientRect().width")
        check("nav-collapsed" in (await pg.locator(".shell").get_attribute("class"))
              and await pg.locator('nav[aria-label="ADIF enumerations"]').is_hidden()
              and await pg.get_by_label("ADIF version", exact=True).is_hidden()
              and wide_after > wide_before + 150, f"collapse hides the navigation and widens the content ({wide_before:.0f} -> {wide_after:.0f}px)")
        await pg.reload()
        await settle()
        check("nav-collapsed" in (await pg.locator(".shell").get_attribute("class")), "still collapsed after a reload")
        await pg.get_by_label("Show ADIF version and navigation").click()
        check(await pg.locator('nav[aria-label="ADIF enumerations"]').is_visible(), "» brings the navigation back")
        # The toggle names the region it shows and hides, and that region is not the one holding it (#51)
        ctl = await pg.locator(".navtoggle").get_attribute("aria-controls")
        check(bool(ctl) and await pg.locator(f"#{ctl} .navtoggle").count() == 0 and await pg.locator(f"#{ctl} nav").count() > 0,
              f"the toggle's aria-controls ({ctl}) is the navigation it hides, not its own container")

        # 13. A phone: the pane starts collapsed and the content gets the screen (#42; it had 60px)
        phone = await b.new_context(viewport={"width": 390, "height": 844})
        pp = await phone.new_page()
        await pp.goto(f"{BASE}/adif/enumerations/primary_administrative_subdivision")
        await pp.wait_for_selector("tbody tr", timeout=15000)
        # What the reader can SEE of the table: its box clipped by the viewport and by every ancestor
        # that clips (a scroll container), after scrolling the page to bring it into view. The table's
        # own height would pass even if a 60px region clipped it, which is what #42 was.
        visible = """e => { e.scrollIntoView({block: "start"}); const r = e.getBoundingClientRect();
            let top = Math.max(r.top, 0), bottom = Math.min(r.bottom, innerHeight);
            for (let a = e.parentElement; a; a = a.parentElement) {
              const s = getComputedStyle(a);
              if (s.overflowY !== "visible" || s.overflowX !== "visible") {
                const b = a.getBoundingClientRect(); top = Math.max(top, b.top); bottom = Math.min(bottom, b.bottom);
              }
            }
            return Math.max(0, bottom - top); }"""
        top = await pp.locator(".tablewrap").evaluate("e => e.getBoundingClientRect().top")
        check("nav-collapsed" in (await pp.locator(".shell").get_attribute("class")), "phone: navigation starts collapsed")
        check(top < 844, f"phone: the table starts on the first screen (top {top:.0f}px)")
        seen = await pp.locator(".tablewrap").evaluate(visible)
        check(seen > 600, f"phone: {seen:.0f}px of the table is visible once scrolled to, of an 844px screen")
        # Paging from the bottom of a page lands at the top of the next (#51: the document scrolls here)
        await pp.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await pp.get_by_label("Next page").click()
        await pp.wait_for_url("**page=2**")
        await pp.wait_for_timeout(300)
        y = await pp.evaluate("window.scrollY")
        check(y < 50, f"phone: Next from the bottom returns to the top (scrollY {y})")
        # With no choice saved, the pane follows the window: widen to a desktop and it opens (#51)
        await pp.set_viewport_size({"width": 1280, "height": 844})
        await pp.wait_for_timeout(200)
        check("nav-collapsed" not in (await pp.locator(".shell").get_attribute("class")), "phone widened to desktop: the pane opens")
        await pp.set_viewport_size({"width": 390, "height": 844})
        await pp.wait_for_timeout(200)
        check("nav-collapsed" in (await pp.locator(".shell").get_attribute("class")), "and narrowed again: it collapses")
        await phone.close()

        # 15. A failing API is shown as unavailable, never as a zero count (#51). Its own context: the
        #     browser logs the 500s it is made to see, which are not errors of the page.
        broken = await b.new_context(viewport={"width": 1440, "height": 900})
        bp = await broken.new_page()
        await bp.route("**/api/v1/adif/enumerations?*", lambda r: r.fulfill(status=500, body="{}"))
        await bp.route("**/api/v1/adif/fields?*", lambda r: r.fulfill(status=500, body="{}"))
        await bp.goto(f"{BASE}/")
        await bp.wait_for_selector("p.state.error", timeout=15000)
        home = await bp.locator("main").inner_text()
        check("Unavailable" in home and "0 enumerations" not in home, "Home: a failing API reads as unavailable, not as 0")
        await bp.goto(f"{BASE}/adif")
        await bp.wait_for_selector("p.state.error", timeout=15000)
        side = await bp.locator(".sidebar").inner_text()
        check("(unavailable)" in side.lower() and "(0)" not in side, f"ADIF: the sidebar says unavailable, not (0): {side!r}")
        await broken.close()

        check(not errors, f"no console errors ({errors[:3]})")
        await b.close()
    print("\n".join(notes + fails))
    print(f"\n{len(notes)} passed, {len(fails)} failed")
    sys.exit(1 if fails else 0)


asyncio.run(main())
