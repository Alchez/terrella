// The globe's search field — typing at the planet instead of hunting across it.
//
// WHY IT IS IN THE CAMERA GROUP AND NOT WITH THE DISPLAY TOGGLES. The rail's grouping states a
// concern: the top-right holds the camera and the frame, the bottom bar holds what the globe SHOWS,
// and the top-left holds ways off the globe. Choosing a search result flies the camera and opens
// the card — byte for byte what a click already does — so it is a camera control that happens to
// take words. It joins zoom, compass and spin for the same reason spin did.
//
// IT NEVER IMPORTS THE CATALOGUE OR THE MATCHER. `search` arrives as a function, which keeps this
// module a DOM widget with no data in it: the page owns the seam where `featureIndex` is fetched on
// its own chunk, and a widget that reached for the array itself would drag 324 KB of Martian place
// names into every Earth visitor's download. It cannot, because there is nothing here to reach with.
//
// THE FIELD IS THE SECOND WAY INTO ONE CARD, NOT A SECOND CARD. `onChoose` hands the entry back and
// the page runs its ordinary pick path with it, so a card a visitor searched to and a card they
// tapped are the same card built by the same builder. Nothing about a result row is authored here
// beyond the row itself.
//
// IT FORMATS NOTHING. A row's second line arrives already written, because the body that owns a
// catalogue owns how it reads — and the alternative was this module importing Mars's kind and size
// formatters, which is how a widget with no data in it acquires a planet.

import type { SearchEntry, SearchResults } from "./catalogueSearch";
import { isTypingTarget } from "./quietMode";

/**
 * The key that opens the field from anywhere on the page.
 *
 * `/` is the web's own convention for this and costs no modifier, which matters because the other
 * shortcut on this globe is a bare `Z`. It is also the key Firefox binds to quick-find, so the
 * handler has to prevent the default or the browser's own search bar opens underneath ours.
 */
export const SEARCH_SHORTCUT = "/";

/** How many rows the list offers.
 *
 *  Eight rather than a scrolling list: the panel hangs beside the rail on a globe, and a list long
 *  enough to scroll would cover the thing the visitor is about to be flown to. The count that was
 *  dropped is stated instead, which is what `SearchResults.total` is carried for. */
export const SEARCH_RESULT_LIMIT = 8;

export interface CatalogueSearchBoxOptions {
  /** Run a query. Injected, so this module holds no catalogue — see the note above. */
  search: (query: string, limit: number) => SearchResults;
  /** A visitor picked a row. The page flies and opens the card, exactly as it does for a click. */
  onChoose: (entry: SearchEntry) => void;
  /** Called when the panel opens or closes, so the rail button can mirror its own state. */
  onOpenChange?: (open: boolean) => void;
  /** Rows to offer. Defaults to `SEARCH_RESULT_LIMIT`. */
  limit?: number;
  /** The document to build in. Injectable so a test can isolate. */
  doc?: Document;
}

export interface CatalogueSearchBox {
  /** The panel, for the caller to mount. Starts closed. */
  readonly element: HTMLElement;
  isOpen(): boolean;
  open(): void;
  close(): void;
  /** Drop the listeners and remove the panel. */
  destroy(): void;
}

const OPTION_ID_PREFIX = "rg-search-option-";

/** Build the search panel. Nothing is queried until a visitor types. */
export function createCatalogueSearchBox(options: CatalogueSearchBoxOptions): CatalogueSearchBox {
  const { search, onChoose, onOpenChange, limit = SEARCH_RESULT_LIMIT, doc = document } = options;

  const element = doc.createElement("div");
  element.className = "rg-search";
  element.hidden = true;

  const field = doc.createElement("input");
  field.type = "text";
  field.className = "rg-search-field";
  field.placeholder = "Search features";
  field.setAttribute("aria-label", "Search features");
  // A browser's own suggestions would cover the result list with a list of its own, and a
  // spell-checker underlines most of this catalogue in red.
  field.autocomplete = "off";
  field.spellcheck = false;
  field.setAttribute("enterkeyhint", "go");
  field.setAttribute("role", "combobox");
  field.setAttribute("aria-expanded", "false");
  field.setAttribute("aria-autocomplete", "list");

  const list = doc.createElement("ul");
  list.className = "rg-search-results";
  list.id = "rg-search-results";
  list.setAttribute("role", "listbox");
  field.setAttribute("aria-controls", list.id);

  // Says what happened when the list cannot: no matches at all, or a list that is a page of a
  // larger answer. A visitor shown eight rows with nothing else on screen reads them as the whole
  // answer, which for a two-letter query is wrong by three orders of magnitude.
  const status = doc.createElement("p");
  status.className = "rg-search-status";
  status.setAttribute("role", "status");

  element.append(field, list, status);

  let shown: SearchEntry[] = [];
  let active = -1;
  // `opened`, not `open` — and `setOpen` is called directly everywhere below rather than through a
  // local `close()`. BOTH ARE THE SAME LANDMINE, and one of them shipped: a bare `close()` here
  // resolves to `window.close`, which exists, takes no arguments, returns void and therefore
  // type-checks perfectly. Four linters and the whole suite stayed green; the only symptom was a
  // panel that never closed, which reads as a CSS oversight. `open` is a global function too.
  let opened = false;

  function renderStatus(results: SearchResults, query: string): void {
    if (query.length === 0) status.textContent = "";
    else if (results.total === 0) status.textContent = "No feature matches that.";
    else if (results.total > results.matches.length)
      status.textContent = `${results.matches.length} of ${results.total.toLocaleString("en-US")}`;
    else status.textContent = "";
  }

  function renderRows(): void {
    list.replaceChildren();
    shown.forEach((entry, index) => {
      const row = doc.createElement("li");
      row.className = "rg-search-row";
      row.id = `${OPTION_ID_PREFIX}${index}`;
      row.setAttribute("role", "option");
      row.setAttribute("aria-selected", String(index === active));

      const name = doc.createElement("span");
      name.className = "rg-search-name";
      name.textContent = entry.name;
      // A second spelling where the catalogue publishes one — on Mars the IAU's diacritic-free form,
      // for the same reason the gazetteer page carries it: a visitor who typed "Belen" should see
      // why Belén answered. `null` is the ordinary case and costs no element.
      const alias =
        entry.alias === null
          ? null
          : Object.assign(doc.createElement("span"), {
              className: "rg-search-alias",
              textContent: entry.alias,
            });

      const kind = doc.createElement("span");
      kind.className = "rg-search-kind";
      kind.textContent = entry.descriptor;

      row.append(name, ...(alias ? [alias] : []), kind);
      row.addEventListener("mousedown", (event) => {
        // `mousedown`, not `click`: the field losing focus on mouse-down would close the panel out
        // from under the click that was choosing a row.
        event.preventDefault();
        choose(index);
      });
      list.append(row);
    });
  }

  function setActive(index: number): void {
    active = index;
    [...list.children].forEach((row, position) =>
      row.setAttribute("aria-selected", String(position === active)),
    );
    if (active >= 0) field.setAttribute("aria-activedescendant", `${OPTION_ID_PREFIX}${active}`);
    else field.removeAttribute("aria-activedescendant");
  }

  function runQuery(): void {
    const query = field.value.trim();
    const results = query.length === 0 ? { matches: [], total: 0 } : search(query, limit);
    shown = results.matches;
    // The first row is pre-selected so Enter always has an answer — the ranking exists to make the
    // top row the likely one, and a visitor who types a whole name should not have to reach for an
    // arrow key to accept it.
    active = shown.length > 0 ? 0 : -1;
    renderRows();
    setActive(active);
    renderStatus(results, query);
    field.setAttribute("aria-expanded", String(shown.length > 0));
  }

  function choose(index: number): void {
    const entry = shown[index];
    if (!entry) return;
    setOpen(false);
    onChoose(entry);
  }

  function onKeyDown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.stopPropagation(); // the globe has its own Escape; a visitor means "leave the field"
      setOpen(false);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      choose(active);
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault(); // or the caret jumps to either end of the field as the list moves
    if (shown.length === 0) return;
    const step = event.key === "ArrowDown" ? 1 : -1;
    setActive((active + step + shown.length) % shown.length);
  }

  /**
   * `/` anywhere on the page opens the field.
   *
   * `isTypingTarget` is quiet mode's, imported rather than restated — it is the reason a bare
   * single-letter shortcut does not eat keystrokes, and it guards this field's own input too, so
   * typing a slash INTO the search box types a slash.
   */
  function onDocumentKeyDown(event: KeyboardEvent): void {
    // A modifier means the chord belongs to the browser or the OS, exactly as quiet mode reasons.
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.repeat) return;
    if (event.key !== SEARCH_SHORTCUT) return;
    if (isTypingTarget(event.target)) return;
    event.preventDefault(); // Firefox's quick-find binds this key and would open beneath us
    setOpen(true);
  }

  field.addEventListener("input", runQuery);
  field.addEventListener("keydown", onKeyDown);
  doc.addEventListener("keydown", onDocumentKeyDown);

  function setOpen(next: boolean): void {
    if (next === opened) return; // idempotent: no repeated focus steal, no repeated onOpenChange
    opened = next;
    element.hidden = !next;
    if (next) {
      field.focus();
      field.select(); // reopening resumes the last query, and typing replaces it
      runQuery();
    } else {
      field.setAttribute("aria-expanded", "false");
    }
    onOpenChange?.(next);
  }

  return {
    element,
    isOpen: () => opened,
    open: () => setOpen(true),
    close: () => setOpen(false),
    destroy(): void {
      field.removeEventListener("input", runQuery);
      field.removeEventListener("keydown", onKeyDown);
      doc.removeEventListener("keydown", onDocumentKeyDown);
      element.remove();
    },
  };
}
