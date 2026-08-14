/**
 * Whether the globe lights what the pointer is on — the persisted visitor preference behind the
 * view bar's cursor button.
 *
 * ITS OWN MODULE BECAUSE OF WHO READS IT. The layout writes it and the globe reacts to it, and
 * those two live in different bundles: `Base.astro` must not pull in map state to answer "is this
 * on", and `Globe.astro` must not spell the storage key a second time. Borders and Focus predate
 * this and each spell their key in both places — the shape this exists not to repeat.
 *
 * DEFAULT ON, WHICH INVERTS THE READ. Borders and Focus are opt-in overlays, so absent means off
 * and `=== "1"` is the right test for them. This one ships on, so the only value that turns it off
 * is an explicit `"0"` — written `=== "1"` a first-time visitor would arrive with the highlight
 * switched off and no way to know it had ever been on.
 */

/** The localStorage key. Same string as the event, deliberately: one name for one concept. */
export const HIGHLIGHT_KEY = "rg:highlight";

/**
 * The document event the layout broadcasts on a change.
 *
 * The globe listens for THIS rather than for the button's click, which keeps the layout the single
 * writer of the persisted state — the same split Borders uses, and the reason a page with no map
 * can host the control at all.
 */
export const HIGHLIGHT_EVENT = "rg:highlight";

/** What the event carries. Read rather than re-derived, so a listener cannot disagree with the
 *  writer about which way the toggle just went. */
export interface HighlightChange {
  on: boolean;
}

/**
 * Is the highlight on for this visitor?
 *
 * Takes the storage so a test can answer without touching the real one; production passes nothing.
 */
export function highlightEnabled(storage: Pick<Storage, "getItem"> = localStorage): boolean {
  return storage.getItem(HIGHLIGHT_KEY) !== "0";
}

/** The value to persist. Spelled here so the writer and {@link highlightEnabled} cannot drift over
 *  which string means off. */
export function highlightStorageValue(on: boolean): string {
  return on ? "1" : "0";
}
