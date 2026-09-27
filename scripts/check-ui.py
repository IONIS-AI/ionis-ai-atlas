"""check-ui.py — drive the ADIF section in headless Chromium and fail on any broken behaviour.

Covers SPEC R15 (lists paged and searched on the server) and R16 (names from the spec): the page
counts, the pager, search that runs before paging and says what it left out, page size, a stale
page number coming back to the last page, links from before R16 redirecting, curated views paging
too, and a sidebar that only navigates. Counts are ADIF 3.1.7's.

    make check-ui BASE=http://localhost:8080     (the stack must be up: make dev or make up)
"""
import asyncio
import sys

from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
fails, notes = [], []


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
        check(c.startswith("1–100 of 1,965"), f"PAS first page count: {c!r}")
        check(await rows() == 100, f"PAS renders 100 rows, not 1,965 ({await rows()})")
        pager = await pg.locator(".pager span").inner_text()
        check(pager == "Page 1 of 20", f"pager: {pager!r}")
        src = await pg.locator(".source").inner_text()
        check("Primary_Administrative_Subdivision" in src and "enumerations_primary_administrative_subdivision.json" in src
              and "GET /api/v1/adif/enumerations/primary_administrative_subdivision" in src, f"R16 source line: {src!r}")
        h = await pg.locator("h1").inner_text()
        check(h == "Primary Administrative Subdivision", f"label: {h!r}")

        # 2. Next page
        await pg.get_by_label("Next page").click()
        await settle()
        c = await count()
        check(c.startswith("101–200 of 1,965") and "page=2" in pg.url, f"page 2: {c!r} url={pg.url}")

        # 3. Search, server-side, back to page 1, says what it left out
        await pg.get_by_label("Search Primary Administrative Subdivision").fill("oblast")
        await pg.wait_for_timeout(700)
        await settle()
        c = await count()
        check(c.startswith("1–82 of 82 matching “oblast”") and "1,965 in all" in c and await rows() == 82
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
        check(c.startswith("1–25 of 1,965") and await rows() == 25 and "size=25" in pg.url, f"size 25: {c!r}")
        check((await pg.locator(".pager span").inner_text()) == "Page 1 of 79", "79 pages at 25 rows")

        # 6. A page past the end (e.g. from a stale link) comes back to the last page
        await pg.goto(f"{BASE}/adif/enumerations/secondary_administrative_subdivision?page=9")
        await settle()
        await pg.wait_for_timeout(500)
        c = await count()
        check(c.startswith("1–58 of 58") and "page=" not in pg.url, f"page past end clamps: {c!r} url={pg.url}")

        # 7. A link from before R16 still works
        await pg.goto(f"{BASE}/adif/secondary_administrative_subdivision")
        await settle()
        check(pg.url.endswith("/adif/enumerations/secondary_administrative_subdivision")
              and (await count()).startswith("1–58 of 58"), f"legacy link redirected: {pg.url}")

        # 8. Curated views page and search on the server too
        await pg.goto(f"{BASE}/adif/enumerations/mode?q=ft4")
        await settle()
        first = await pg.locator("tbody tr td strong").first.inner_text()
        check(first == "MFSK" and (await count()).startswith("1–1 of 1"), "mode search by submode finds MFSK")
        await pg.goto(f"{BASE}/adif/fields?size=50&page=4")
        await settle()
        c = await count()
        check(c.startswith("151–186 of 186"), f"fields page 4 of 50: {c!r}")

        # 9. The sidebar navigates by canonical route and carries only the ADIF version
        await pg.goto(f"{BASE}/adif/enumerations/band?v=3.1.6&q=20m")
        await settle()
        href = await pg.locator('nav[aria-label="ADIF enumerations"] a', has_text="Submode").get_attribute("href")
        check(href == "/adif/enumerations/submode?v=3.1.6", f"sidebar link: {href!r}")
        check(await pg.locator('.sidebar input[type="search"]').count() == 0, "no search box left in the sidebar")

        check(not errors, f"no console errors ({errors[:3]})")
        await b.close()
    print("\n".join(notes + fails))
    print(f"\n{len(notes)} passed, {len(fails)} failed")
    sys.exit(1 if fails else 0)


asyncio.run(main())
