// The navigation pane's collapsed state (SPEC "The shell"; #35, #42). Remembered per browser, and
// collapsed by default at phone width, where an open pane would push the content off the screen.
// Browser storage can be absent or refuse (private windows, blocked site data), so every access is
// guarded and the page works without it: the default simply applies.
export const NAV_KEY = "atlas.nav.collapsed";
export const PHONE_MAX = 760; // px; keep in step with the @media rule in styles.css

type Store = Pick<Storage, "getItem" | "setItem">;

/** The choice the reader made, or null if they have not made one (or storage is unavailable). */
export function readSaved(store: Store | undefined): boolean | null {
  try {
    const saved = store?.getItem(NAV_KEY);
    if (saved === "1" || saved === "0") return saved === "1";
  } catch {
    // no storage: no saved choice
  }
  return null;
}

/** Collapsed or not: the reader's choice if they made one, else the default for this width. */
export function readCollapsed(store: Store | undefined, width: number): boolean {
  return readSaved(store) ?? width <= PHONE_MAX;
}

export function saveCollapsed(store: Store | undefined, collapsed: boolean): void {
  try {
    store?.setItem(NAV_KEY, collapsed ? "1" : "0");
  } catch {
    // not remembered this time; the choice still applies for this visit
  }
}
