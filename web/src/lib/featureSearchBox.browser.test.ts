import { describe, it, expect, afterEach, vi } from "vitest";
import { createFeatureSearchBox, SEARCH_SHORTCUT, type FeatureSearchBox } from "./featureSearchBox";
import globalCss from "../styles/global.css?raw";
import globeCss from "../styles/globe.css?raw";
import maplibreCss from "maplibre-gl/dist/maplibre-gl.css?raw";
import { createFeatureSearch } from "./featureSearch";
import { featureIndex, type NamedFeature } from "./featureIndex";

/**
 * The search panel, driven as a real widget in a real document.
 *
 * IN THE BROWSER PROJECT BECAUSE THE BUG THAT SHIPPED HERE NEEDED ONE. A bare `close()` in this
 * module resolved to `window.close` — a real global, no arguments, returns void, so it type-checked
 * and linted clean — and the only symptom was a panel that would not close. Nothing that reads
 * source could see it and nothing that reads types could either; only running it can.
 */

const matcher = createFeatureSearch(featureIndex);
const built: FeatureSearchBox[] = [];

function mount(overrides: Partial<Parameters<typeof createFeatureSearchBox>[0]> = {}) {
  const chosen: NamedFeature[] = [];
  const opens: boolean[] = [];
  const box = createFeatureSearchBox({
    search: (query, limit) => matcher.search(query, limit),
    onChoose: (feature) => chosen.push(feature),
    onOpenChange: (open) => opens.push(open),
    ...overrides,
  });
  document.body.append(box.element);
  built.push(box);
  const field = box.element.querySelector<HTMLInputElement>(".rg-search-field")!;
  const type = (text: string) => {
    field.value = text;
    field.dispatchEvent(new Event("input", { bubbles: true }));
  };
  const press = (key: string) =>
    field.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  const rows = () => [...box.element.querySelectorAll(".rg-search-name")].map((n) => n.textContent);
  return { box, field, type, press, rows, chosen, opens };
}

/** The shortcut, sent where a page-wide handler would hear it. */
const slash = (target: EventTarget = document) =>
  target.dispatchEvent(
    new KeyboardEvent("keydown", { key: SEARCH_SHORTCUT, bubbles: true, cancelable: true }),
  );

afterEach(() => {
  built.splice(0).forEach((box) => box.destroy());
});

describe("the panel opens and closes for real", () => {
  it("starts closed and shows itself on open", () => {
    const { box } = mount();
    expect(box.isOpen()).toBe(false);
    expect(box.element.hidden).toBe(true);
    box.open();
    expect(box.isOpen()).toBe(true);
    expect(box.element.hidden).toBe(false);
  });

  it("CLOSES ON ESCAPE — the branch a global shadow silently took over", () => {
    // `close()` here once resolved to `window.close`, which does nothing on a page a script did not
    // open. Escape looked wired, was wired, and left the panel up.
    const { box, press } = mount();
    box.open();
    press("Escape");
    expect(box.isOpen()).toBe(false);
    expect(box.element.hidden).toBe(true);
  });

  it("closes itself before handing the feature over, so the card is not opened underneath it", () => {
    // The card docks in the corner this panel hangs in. Ordering matters: the page opens the card
    // inside `onChoose`, so a panel that closed afterwards would flash over its own answer.
    const { box, type, press, chosen } = mount();
    box.open();
    type("olympus mons");
    const openAtChoice: boolean[] = [];
    press("Enter");
    openAtChoice.push(box.isOpen());
    expect(chosen.map((feature) => feature.name)).toEqual(["Olympus Mons"]);
    expect(openAtChoice).toEqual([false]);
  });

  it("tells its caller both ways, so the rail button can never disagree with the panel", () => {
    const { box, opens } = mount();
    box.open();
    box.close();
    expect(opens).toEqual([true, false]);
  });

  it("is idempotent, so a repeated open does not re-steal focus or re-announce", () => {
    const { box, opens } = mount();
    box.open();
    box.open();
    box.close();
    box.close();
    expect(opens).toEqual([true, false]);
  });
});

describe("a query becomes rows a visitor can act on", () => {
  it("finds a name typed the way a keyboard makes it, not the way the IAU prints it", () => {
    const { box, type, rows } = mount();
    box.open();
    type("kovalsky");
    expect(rows()).toEqual(["Koval'sky"]);
  });

  it("answers a kind, which is the only route to a crater", () => {
    const { box, type, rows } = mount();
    box.open();
    type("crater");
    expect(rows()).toHaveLength(8);
    expect(box.element.querySelector(".rg-search-status")!.textContent).toBe("8 of 1,233");
  });

  it("states the count it dropped, and says nothing when it dropped nothing", () => {
    // A visitor shown eight rows and no count reads them as the whole answer. For "crater" that is
    // wrong by three orders of magnitude; for an exact name it would be noise.
    const { box, type } = mount();
    box.open();
    const status = () => box.element.querySelector(".rg-search-status")!.textContent;
    type("olympus mons");
    expect(status()).toBe("");
    type("zzzzzz");
    expect(status()).toBe("No feature matches that.");
  });

  it("shows the diacritic-free spelling only where it differs", () => {
    const { box, type } = mount();
    box.open();
    type("belen");
    expect(box.element.querySelector(".rg-search-alias")!.textContent).toBe("Belen");
    type("gale");
    expect(box.element.querySelector(".rg-search-alias")).toBeNull();
  });

  it("clears the list when the query is emptied, rather than leaving a stale answer up", () => {
    const { box, type, rows } = mount();
    box.open();
    type("gale");
    expect(rows().length).toBeGreaterThan(0);
    type("");
    expect(rows()).toEqual([]);
  });
});

describe("the keyboard drives the list", () => {
  it("arms the first row, so Enter always has an answer without reaching for an arrow", () => {
    const { box, type } = mount();
    box.open();
    type("crater");
    expect(box.element.querySelector('[aria-selected="true"] .rg-search-name')!.textContent).toBe(
      "Huygens",
    );
  });

  it("moves the armed row and wraps at both ends", () => {
    const { box, type, press } = mount();
    box.open();
    type("crater");
    const armed = () =>
      box.element.querySelector('[aria-selected="true"] .rg-search-name')!.textContent;
    press("ArrowDown");
    expect(armed()).toBe("Schiaparelli");
    press("ArrowUp");
    press("ArrowUp");
    expect(armed()).toBe("de Vaucouleurs"); // wrapped past the top to the last row
  });

  it("chooses the ARMED row, not the first one", () => {
    const { box, type, press, chosen } = mount();
    box.open();
    type("crater");
    press("ArrowDown");
    press("Enter");
    expect(chosen.map((feature) => feature.name)).toEqual(["Schiaparelli"]);
  });

  it("chooses nothing when nothing matched, rather than throwing on an empty list", () => {
    const { box, type, press, chosen } = mount();
    box.open();
    type("zzzzzz");
    press("Enter");
    expect(chosen).toEqual([]);
    expect(box.isOpen()).toBe(true); // still there to be corrected
  });

  it("keeps the highlight and the armed row as one fact, so Enter cannot surprise", () => {
    // `aria-selected` is both what the CSS paints and what `Enter` reads. Two sources would let the
    // list show one row armed and act on another.
    const { box, type, press } = mount();
    box.open();
    type("crater");
    press("ArrowDown");
    press("ArrowDown");
    const painted = box.element.querySelectorAll('[aria-selected="true"]');
    expect(painted).toHaveLength(1);
    expect(box.element.querySelector(".rg-search-field")!.getAttribute("aria-activedescendant")).toBe(
      painted[0]!.id,
    );
  });
});

describe("a row is chosen with the pointer without the field losing it first", () => {
  it("acts on mousedown, because losing focus on mouse-down would close the panel mid-click", () => {
    const { box, type, chosen } = mount();
    box.open();
    type("olympus mons");
    const row = box.element.querySelector(".rg-search-row")!;
    row.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
    expect(chosen.map((feature) => feature.name)).toEqual(["Olympus Mons"]);
  });
});

describe("it holds no catalogue of its own", () => {
  it("asks the function it was given and never a module", () => {
    // The whole reason this takes `search` as an argument: a widget that imported the index would
    // be reached statically from the shared globe component and put 324 KB of Martian place names
    // into Earth's download.
    const search = vi.fn(() => ({ matches: [], total: 0 }));
    const { box, type } = mount({ search });
    box.open();
    type("gale");
    expect(search).toHaveBeenCalledWith("gale", 8);
  });
});

describe("the panel is reachable by a real pointer, not just by a synthetic event", () => {
  // THE BUG THIS FILE'S SECOND ROUND EXISTS FOR. MapLibre makes its control corners
  // `pointer-events: none` and hands it back only to `.maplibregl-ctrl`. This panel is not one, so
  // it shipped click-through: the field could not be focused by clicking, and every click on it
  // reached the globe underneath and flew somewhere. `.click()` and `.focus()` in a test bypass
  // hit-testing entirely, so the whole first round of tests passed over it — as did the screenshots.
  const sheets: HTMLStyleElement[] = [];
  const inject = (css: string) => {
    const element = document.createElement("style");
    element.textContent = css;
    document.head.append(element);
    sheets.push(element);
    return element;
  };

  afterEach(() => sheets.splice(0).forEach((sheet) => sheet.remove()));

  function mountInRail() {
    inject(globalCss);
    inject(globeCss);
    inject(maplibreCss); // LAST, as its ES-module import lands in production
    const corner = document.createElement("div");
    corner.className = "maplibregl-ctrl-top-right";
    const group = document.createElement("div");
    group.className = "maplibregl-ctrl maplibregl-ctrl-group";
    group.append(document.createElement("button"));
    corner.append(group);
    document.body.append(corner);
    const { box } = mount();
    corner.append(box.element);
    box.open();
    return { box, corner };
  }

  it("proves MapLibre really does disarm the corner, so the fix is not superstition", () => {
    const { corner } = mountInRail();
    expect(getComputedStyle(corner).pointerEvents).toBe("none");
    corner.remove();
  });

  it("takes pointer events back for the panel, so a click on the field lands on the field", () => {
    const { box, corner } = mountInRail();
    const field = box.element.querySelector<HTMLInputElement>(".rg-search-field")!;
    expect(getComputedStyle(box.element).pointerEvents).toBe("auto");
    // Hit-testing, not computed style: this is the question a visitor's finger asks.
    const rect = field.getBoundingClientRect();
    const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    expect(hit).toBe(field);
    corner.remove();
  });
});

describe("a keyboard opens the field from anywhere on the page", () => {
  it("opens on the shortcut and puts the caret in the field", () => {
    const { box, field } = mount();
    expect(box.isOpen()).toBe(false);
    slash();
    expect(box.isOpen()).toBe(true);
    expect(document.activeElement).toBe(field);
  });

  it("prevents the default, or Firefox quick-find opens underneath it", () => {
    mount();
    const event = new KeyboardEvent("keydown", {
      key: SEARCH_SHORTCUT,
      bubbles: true,
      cancelable: true,
    });
    document.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it("types a slash INTO the field rather than re-opening it", () => {
    // The guard is quiet mode's `isTypingTarget`, imported rather than restated — one owner for
    // what counts as somewhere a keystroke belongs.
    const { box, field } = mount();
    box.open();
    const event = new KeyboardEvent("keydown", {
      key: SEARCH_SHORTCUT,
      bubbles: true,
      cancelable: true,
    });
    field.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });

  it("leaves a modified chord to the browser", () => {
    const { box } = mount();
    for (const modifier of ["ctrlKey", "metaKey", "altKey"] as const) {
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: SEARCH_SHORTCUT, [modifier]: true, bubbles: true }),
      );
    }
    expect(box.isOpen()).toBe(false);
  });

  it("stops listening once destroyed, so a torn-down globe leaves no key bound", () => {
    const { box } = mount();
    box.destroy();
    slash();
    expect(box.isOpen()).toBe(false);
  });
});

describe("the rail's footprint has one owner, and both boxes clear it", () => {
  it("derives the button size and the clearance from one declaration", () => {
    // Three things keep clear of the rail now — this panel, the detail card, and whatever is added
    // beside them next. Written out separately they drift, and the symptom is a control covered by
    // a panel, which reads as a z-index problem rather than an arithmetic one.
    expect(globeCss).toMatch(/--rail-button-size:\s*2\.15rem;/);
    expect(globeCss).toMatch(/--rail-clearance:\s*calc\(var\(--rail-button-size\)/);
    // The rule that sizes the buttons reads the token rather than restating the number.
    expect(globeCss).toContain("width: var(--rail-button-size);");
    expect(globeCss).not.toMatch(/^\s*width:\s*2\.15rem;/m);
  });

  it("fills the free width narrow by naming both edges, not by capping the width", () => {
    // `width: min(22rem, …)` left a phone with the panel hugging the rail and dead space beside it.
    const narrow = globeCss.slice(globeCss.indexOf("@media (max-width: 40rem)"));
    expect(narrow).toContain("left: 0.75rem;");
    expect(narrow).toContain("right: var(--rail-clearance);");
    expect(narrow).toContain("width: auto;");
  });
});
