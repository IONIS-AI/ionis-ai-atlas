/** Case-insensitive match of `query` against any of a row's string fields. Empty query keeps all. */
export function matches(row: Record<string, unknown>, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return Object.values(row).some((v) =>
    Array.isArray(v) ? v.some((x) => String(x).toLowerCase().includes(q)) : v != null && String(v).toLowerCase().includes(q),
  );
}

/** "12 of 403 shown" — always say what the filter discarded (spec R6d). */
export function shownOf(shown: number, total: number): string {
  return shown === total ? `${total} shown` : `${shown} of ${total} shown`;
}
