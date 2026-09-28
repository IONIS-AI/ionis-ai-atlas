// The filters each curated ADIF view supports (#62). A curated view calls its own endpoint, which
// takes only these; any other `f.` in the URL would be dropped on the way to the API while the page
// said it was applied. The generic enumeration view forwards every filter, and the API refuses
// (400) one naming a column the enumeration does not have.
export const CURATED_FILTERS: Record<string, string[]> = {
  datatypes: [], fields: ["data_type"], band: ["freq_mhz"], mode: [],
};

const human = (k: string) => k.replace(/_/g, " ").replace(/\bmhz\b/i, "(MHz)");

/** What is wrong with the URL's filters for this view, or null when they can be applied. */
export function invalidFilter(view: string, filters: Record<string, string>): string | null {
  const supported = CURATED_FILTERS[view];
  if (!supported) return null;
  const unknown = Object.keys(filters).find((k) => !supported.includes(k));
  if (unknown) {
    return supported.length ? `This view filters only by ${supported.map(human).join(", ")}, not by “${unknown}”.`
      : `This view has no filters, so “${unknown}” can't be applied.`;
  }
  const f = filters.freq_mhz;
  if (f !== undefined && !(f.trim() !== "" && Number.isFinite(Number(f)) && Number(f) >= 0)) {
    return `“${f}” is not a frequency in MHz.`;
  }
  return null;
}
