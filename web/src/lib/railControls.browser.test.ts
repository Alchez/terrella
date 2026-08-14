import { describe, it, expect, afterEach } from "vitest";
import { createRailToggle, findRailGroup, joinRailGroup } from "./railControls";

/**
 * Runs in a real headless Chromium (the `browser` project in vitest.config.ts), not jsdom and
 * not node. Two of these tests are impossible anywhere else — a disabled button's click
 * suppression and real layout geometry — and the layout one doubles as this project's positive
 * control: `getBoundingClientRect()` is all zeroes without a renderer, so if the browser project
 * ever stops being wired, that test fails loudly instead of the file quietly not running.
 */

const mounted: HTMLElement[] = [];

/** Put a node in the live document so layout and event dispatch are real, and take it back out. */
function mount<T extends HTMLElement>(element: T): T {
  document.body.append(element);
  mounted.push(element);
  return element;
}

afterEach(() => {
  for (const element of mounted.splice(0)) element.remove();
});

describe("createRailToggle — the accessible name", () => {
  it("carries title AND aria-label, in agreement", () => {
    // The button's only content is a decorative masked span, so without both of these it has no
    // accessible name at all. This is the trap the credit's glyph hit when it stopped being words.
    const toggle = createRailToggle({
      className: "rg-ctrl-spin",
      label: "Toggle globe auto-rotate",
      onToggle: () => {},
    });
    expect(toggle.button.title).toBe("Toggle globe auto-rotate");
    expect(toggle.button.getAttribute("aria-label")).toBe("Toggle globe auto-rotate");
  });

  it("flips the name when the control's name depends on its state", () => {
    // A button that has just hidden the controls cannot still be labelled "Hide controls" — it is
    // now the only way back. Spin's name does NOT flip, which is why pressedLabel is optional.
    const toggle = createRailToggle({
      className: "rg-ctrl-quiet",
      label: "Hide controls",
      pressedLabel: "Show controls",
      onToggle: () => {},
    });
    expect(toggle.button.title).toBe("Hide controls");
    toggle.setPressed(true);
    expect(toggle.button.title).toBe("Show controls");
    expect(toggle.button.getAttribute("aria-label")).toBe("Show controls");
    toggle.setPressed(false);
    expect(toggle.button.title).toBe("Hide controls");
  });

  it("leaves a non-flipping control's name alone across state changes", () => {
    const toggle = createRailToggle({
      className: "rg-ctrl-spin",
      label: "Toggle globe auto-rotate",
      onToggle: () => {},
    });
    toggle.setPressed(true);
    expect(toggle.button.title).toBe("Toggle globe auto-rotate");
  });
});

describe("createRailToggle — the markup mirrors MapLibre's own", () => {
  it("is a button wrapping a decorative .maplibregl-ctrl-icon span", () => {
    // One CSS block styles every icon in the rail, ours and theirs. If this shape drifts, our two
    // buttons silently render without an icon while MapLibre's four keep theirs.
    const toggle = createRailToggle({ className: "rg-ctrl-spin", label: "Spin", onToggle: () => {} });
    expect(toggle.button.tagName).toBe("BUTTON");
    expect(toggle.button.type).toBe("button");
    expect(toggle.button.className).toBe("rg-ctrl-spin");
    const icon = toggle.button.querySelector(".maplibregl-ctrl-icon");
    expect(icon, "no .maplibregl-ctrl-icon — the rail's icon CSS will not reach this button").not
      .toBeNull();
    expect(icon?.getAttribute("aria-hidden")).toBe("true");
  });
});

describe("createRailToggle — clicking", () => {
  it("reports the state it is moving TO, not the state it is in", () => {
    const seen: boolean[] = [];
    const toggle = mount(
      createRailToggle({ className: "rg-ctrl-spin", label: "Spin", onToggle: (next) => seen.push(next) })
        .button,
    );
    toggle.click();
    toggle.setAttribute("aria-pressed", "true");
    toggle.click();
    expect(seen).toEqual([true, false]);
  });

  it("reads the DOM rather than a captured flag, so state set elsewhere is honoured", () => {
    // setPressed is called for reasons that never touch this button — a drag retiring the spin,
    // the FPS watchdog, a country pick. A closure variable would go stale against all three.
    const seen: boolean[] = [];
    const control = createRailToggle({
      className: "rg-ctrl-spin",
      label: "Spin",
      pressed: true,
      onToggle: (next) => seen.push(next),
    });
    mount(control.button);
    control.setPressed(false); // as if a drag had just halted the spin
    control.button.click();
    expect(seen).toEqual([true]);
  });

  it("does not fire while unavailable — the browser suppresses a disabled button's click", () => {
    // Only checkable with a real event loop: assigning `disabled` and calling click() in a stub
    // would happily invoke the listener.
    const seen: boolean[] = [];
    const control = createRailToggle({
      className: "rg-ctrl-search",
      label: "Search countries",
      onToggle: (next) => seen.push(next),
    });
    mount(control.button);
    control.setAvailable(false, "Search countries (loading the catalogue)");
    control.button.click();
    expect(seen).toEqual([]);
    control.setAvailable(true);
    control.button.click();
    expect(seen).toEqual([true]);
  });
});

describe("createRailToggle — availability", () => {
  it("disables, greys, and says what would make it work again", () => {
    const control = createRailToggle({
      className: "rg-ctrl-search",
      label: "Search countries",
      onToggle: () => {},
    });
    control.setAvailable(false, "Search countries (loading the catalogue)");
    expect(control.button.disabled).toBe(true);
    expect(control.button.classList.contains("is-unavailable")).toBe(true);
    expect(control.button.title).toBe("Search countries (loading the catalogue)");
    control.setAvailable(true);
    expect(control.button.disabled).toBe(false);
    expect(control.button.classList.contains("is-unavailable")).toBe(false);
    expect(control.button.title).toBe("Search countries");
  });

  it("does not let a state change while unavailable overwrite the unavailable name", () => {
    // The pressed state is written by the PAGE as well as by this button — the search box's open
    // state is driven by the panel — so it can change while the button is still greyed.
    const control = createRailToggle({
      className: "rg-ctrl-search",
      label: "Search countries",
      pressedLabel: "Close search",
      pressed: true,
      onToggle: () => {},
    });
    control.setAvailable(false, "Search countries (loading the catalogue)");
    control.setPressed(false);
    expect(control.button.title).toBe("Search countries (loading the catalogue)");
    control.setAvailable(true);
    expect(control.button.title).toBe("Search countries");
  });
});

describe("joinRailGroup — a widget lands in the pill it belongs to", () => {
  function rail(html: string): HTMLElement {
    const container = mount(document.createElement("div"));
    container.className = "maplibregl-ctrl-top-right";
    container.innerHTML = html;
    return container;
  }

  it("appends into the group holding the named button, not a pill of its own", () => {
    const container = rail(
      `<div class="maplibregl-ctrl maplibregl-ctrl-group"><button class="maplibregl-ctrl-zoom-in"></button></div>
       <div class="maplibregl-ctrl maplibregl-ctrl-group"><button class="maplibregl-ctrl-fullscreen"></button></div>`,
    );
    const spin = createRailToggle({ className: "rg-ctrl-spin", label: "Spin", onToggle: () => {} });
    const landed = joinRailGroup(container, ".maplibregl-ctrl-zoom-in", spin.button);

    expect(container.querySelectorAll(".maplibregl-ctrl-group")).toHaveLength(2); // no new pill
    expect(landed.querySelector(".maplibregl-ctrl-zoom-in")).not.toBeNull();
    expect(spin.button.parentElement).toBe(landed);
  });

  it("finds the group semantically, so it is not fooled by control order", () => {
    // `:nth-child` would retarget silently the first time a control is added or reordered, and a
    // button in the wrong pill reads as a styling bug rather than a lookup one.
    const container = rail(
      `<div class="maplibregl-ctrl maplibregl-ctrl-group"><button class="maplibregl-ctrl-fullscreen"></button></div>
       <div class="maplibregl-ctrl maplibregl-ctrl-group"><button class="maplibregl-ctrl-zoom-in"></button></div>`,
    );
    const quiet = createRailToggle({ className: "rg-ctrl-quiet", label: "Hide", onToggle: () => {} });
    const landed = joinRailGroup(container, ".maplibregl-ctrl-fullscreen", quiet.button);
    expect(landed.querySelector(".maplibregl-ctrl-fullscreen")).not.toBeNull();
    expect(landed.querySelector(".maplibregl-ctrl-zoom-in")).toBeNull();
  });

  it("makes a group of its own when the host control never rendered", () => {
    // FullscreenControl draws nothing where the Fullscreen API is absent — iPhone Safari. The
    // quiet toggle is the only way back out of quiet mode, so it must not vanish with it.
    const container = rail(
      `<div class="maplibregl-ctrl maplibregl-ctrl-group"><button class="maplibregl-ctrl-zoom-in"></button></div>`,
    );
    const quiet = createRailToggle({ className: "rg-ctrl-quiet", label: "Hide", onToggle: () => {} });
    const landed = joinRailGroup(container, ".maplibregl-ctrl-fullscreen", quiet.button);

    expect(container.querySelectorAll(".maplibregl-ctrl-group")).toHaveLength(2);
    expect(landed.className).toContain("maplibregl-ctrl-group");
    expect(quiet.button.parentElement).toBe(landed);
    expect(landed.parentElement).toBe(container);
  });

  it("findRailGroup reports absence rather than guessing", () => {
    const container = rail(`<div class="maplibregl-ctrl maplibregl-ctrl-group"></div>`);
    expect(findRailGroup(container, ".maplibregl-ctrl-fullscreen")).toBeNull();
  });

  it('puts a "start" button ahead of the control it joins', () => {
    // The quiet toggle's case. It is the one control quiet mode leaves on screen, so it has to lead
    // its pill or it inherits a divider from the button above it — see railIcons.browser.test.
    const container = rail(
      `<div class="maplibregl-ctrl maplibregl-ctrl-group"><button class="maplibregl-ctrl-fullscreen"></button></div>`,
    );
    const quiet = createRailToggle({ className: "rg-ctrl-quiet", label: "Hide", onToggle: () => {} });
    const landed = joinRailGroup(container, ".maplibregl-ctrl-fullscreen", quiet.button, "start");

    expect(landed.firstElementChild).toBe(quiet.button);
  });

  it('carries "start" to the fallback GROUP too, not just to the button', () => {
    // The half that is easy to miss, and it fails on exactly one device class. Where
    // `FullscreenControl` renders nothing there is no group to lead, so the placement has to decide
    // where the NEW pill goes — and appending it would park the eye below the camera group: a lone
    // glyph partway down an otherwise empty right edge, which is the state the whole reorder exists
    // to remove. A button-only reading of "start" passes the test above and still ships that.
    const container = rail(
      `<div class="maplibregl-ctrl maplibregl-ctrl-group"><button class="maplibregl-ctrl-zoom-in"></button></div>`,
    );
    const quiet = createRailToggle({ className: "rg-ctrl-quiet", label: "Hide", onToggle: () => {} });
    const landed = joinRailGroup(container, ".maplibregl-ctrl-fullscreen", quiet.button, "start");

    expect(container.querySelectorAll(".maplibregl-ctrl-group")).toHaveLength(2);
    expect(container.firstElementChild, "the fallback pill must lead the corner").toBe(landed);
  });

  it('still appends by default, which is what spin and search rely on', () => {
    // The default is load-bearing: two other callers join the camera group and must land AFTER
    // zoom and compass. A placement that changed meaning without them would reorder the rail.
    const container = rail(
      `<div class="maplibregl-ctrl maplibregl-ctrl-group"><button class="maplibregl-ctrl-zoom-in"></button></div>`,
    );
    const spin = createRailToggle({ className: "rg-ctrl-spin", label: "Spin", onToggle: () => {} });
    const landed = joinRailGroup(container, ".maplibregl-ctrl-zoom-in", spin.button);

    expect(landed.lastElementChild).toBe(spin.button);
  });
});

describe("the browser project is actually running in a browser", () => {
  it("lays out a real button with a non-zero box", () => {
    // THE POSITIVE CONTROL for vitest.config.ts's `browser` project. Every rect is 0×0 without a
    // renderer, so this fails loudly if these tests ever silently fall back to node — the failure
    // mode a projects split introduces, where a green run has executed nothing.
    const control = createRailToggle({ className: "rg-ctrl-spin", label: "Spin", onToggle: () => {} });
    control.button.style.width = "29px";
    control.button.style.height = "29px";
    mount(control.button);
    const box = control.button.getBoundingClientRect();
    expect(box.width).toBeGreaterThan(0);
    expect(box.height).toBeGreaterThan(0);
  });
});
