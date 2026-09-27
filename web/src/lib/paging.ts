// Paging (SPEC R15). The API filters and pages; the browser only ever holds one page, so there is
// no client-side filtering here: a filter over one page would silently miss matches on the others.
export const PAGE_SIZES = [25, 50, 100, 250, 500] as const;
export const DEFAULT_SIZE = 100;

const n = (x: number) => x.toLocaleString("en-US");

/** "1–100 of 1,965": rows offset+1 to offset+count of total. Says what the page leaves out (R6d). */
export function rangeOf(offset: number, count: number, total: number): string {
  if (count === 0) return `0 of ${n(total)}`;
  return `${n(offset + 1)}–${n(offset + count)} of ${n(total)}`;
}

/** Pages needed for `total` rows; at least 1, so an empty result is "page 1 of 1". */
export function pageCount(total: number, size: number): number {
  return Math.max(1, Math.ceil(total / size));
}

/** Page (1-based) and page size from the URL, falling back to page 1 and the default size. */
export function readPaging(params: URLSearchParams): { page: number; size: number } {
  const size = Number(params.get("size"));
  const page = Number(params.get("page"));
  return {
    size: (PAGE_SIZES as readonly number[]).includes(size) ? size : DEFAULT_SIZE,
    page: Number.isInteger(page) && page >= 1 ? page : 1,
  };
}
