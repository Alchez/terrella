import { afterEach, describe, expect, it, vi } from "vitest";
import "../styles/global.css";
import baseLayout from "../layouts/Base.astro?raw";
import { bodyRoutes } from "./bodyRoutes";
import { QUALITY_KEY } from "./capability";
import { REFUSAL, REFUSAL_VISIBLE_MS, wireTierPicker, type PickerEffects } from "./tierPicker";

/**
 * Real browser, real markup: the picker's buttons and its refusal line are cut out of the layout's
 * source, so a control renamed or dropped there fails here rather than passing on a copy.
 */
const PICKER = /<div class="quality-fab"[\s\S]*?<\/div>/;
const REFUSAL_LINE = /<p class="picker-refusal"[^>]*><\/p>/;

let mounted: HTMLElement | null = null;

function mount(): HTMLElement {
  const picker = baseLayout.match(PICKER)?.[0];
  const refusal = baseLayout.match(REFUSAL_LINE)?.[0];
  expect(picker, "Base.astro no longer renders the tier picker").toBeTruthy();
  expect(refusal, "Base.astro renders nowhere for the picker to say why it refused").toBeTruthy();
  mounted = document.createElement("div");
  mounted.className = "view-bar";
  mounted.innerHTML = `${picker}${refusal}`;
  document.body.append(mounted);
  return mounted;
}

function effects(overrides: Partial<PickerEffects> = {}) {
  const calls = { assigned: [] as string[], reloads: 0 };
  const live: PickerEffects = {
    probe: () => ({ webgl2: true, softwareGpu: false }),
    tier: () => "full",
    stored: () => "auto",
    assign: (url) => calls.assigned.push(url),
    reload: () => {
      calls.reloads += 1;
    },
    ...overrides,
  };
  return { live, calls };
}

const button = (bar: HTMLElement, quality: string) =>
  bar.querySelector<HTMLButtonElement>(`button[data-quality="${quality}"]`)!;

afterEach(() => {
  mounted?.remove();
  mounted = null;
  localStorage.removeItem(QUALITY_KEY);
  vi.useRealTimers();
});

describe("the tier picker on a lite page", () => {
  it("lights Lite, which is what the page is showing", () => {
    const bar = mount();
    wireTierPicker(bar, { path: "/", routes: bodyRoutes("earth") }, effects().live);
    expect(button(bar, "lite").getAttribute("aria-pressed")).toBe("true");
    expect(button(bar, "globe").getAttribute("aria-pressed")).toBe("false");
  });

  it("sends a device that can draw the globe to this body's own globe, and remembers the pick", () => {
    const bar = mount();
    const { live, calls } = effects();
    wireTierPicker(bar, { path: "/mars/lite/", routes: bodyRoutes("mars") }, live);
    button(bar, "globe").click();
    expect(calls.assigned).toEqual(["/mars/"]);
    expect(localStorage.getItem(QUALITY_KEY)).toBe("globe");
  });

  it("refuses Globe and Full on a device the guard would bounce, saves nothing, and says why", () => {
    const bar = mount();
    const { live, calls } = effects({ probe: () => ({ webgl2: false, softwareGpu: false }) });
    wireTierPicker(bar, { path: "/", routes: bodyRoutes("earth") }, live);
    button(bar, "full").click();
    expect(calls.assigned, "a refused press navigated anyway").toEqual([]);
    expect(calls.reloads).toBe(0);
    expect(localStorage.getItem(QUALITY_KEY), "a refused press saved a pick the guard will undo").toBeNull();
    expect(button(bar, "globe").getAttribute("aria-disabled")).toBe("true");
    expect(button(bar, "full").getAttribute("aria-disabled")).toBe("true");
    expect(button(bar, "lite").getAttribute("aria-disabled")).toBeNull();
    expect(bar.querySelector(".picker-refusal")?.textContent).toBe(REFUSAL);
  });

  it("takes a software rasterizer for the same refusal, the guard bouncing it just as surely", () => {
    const bar = mount();
    const { live, calls } = effects({ probe: () => ({ webgl2: true, softwareGpu: true }) });
    wireTierPicker(bar, { path: "/", routes: bodyRoutes("earth") }, live);
    button(bar, "globe").click();
    expect(calls.assigned).toEqual([]);
    expect(bar.querySelector(".picker-refusal")?.textContent).toBe(REFUSAL);
  });

  it("still lets Lite through on that device", () => {
    const bar = mount();
    const { live, calls } = effects({ probe: () => ({ webgl2: false, softwareGpu: false }) });
    wireTierPicker(bar, { path: "/", routes: bodyRoutes("earth") }, live);
    button(bar, "lite").click();
    expect(calls.assigned).toEqual(["/earth/lite/"]);
    expect(localStorage.getItem(QUALITY_KEY)).toBe("lite");
  });

  it("draws nothing while it has nothing to say, then the reason above the bar and both tiers dimmed", () => {
    const bar = mount();
    const reason = bar.querySelector<HTMLElement>(".picker-refusal")!;
    expect(getComputedStyle(reason).display, "an empty refusal line still draws").toBe("none");
    wireTierPicker(bar, { path: "/", routes: bodyRoutes("earth") }, effects({ probe: () => ({ webgl2: false, softwareGpu: false }) }).live);
    button(bar, "globe").click();
    expect(getComputedStyle(reason).display).not.toBe("none");
    expect(reason.getBoundingClientRect().bottom, "the reason sits on the bar rather than above it").toBeLessThanOrEqual(
      bar.getBoundingClientRect().top,
    );
    expect(Number(getComputedStyle(button(bar, "full")).opacity)).toBeLessThan(1);
    expect(Number(getComputedStyle(button(bar, "lite")).opacity)).toBe(1);
  });

  it("clears the refusal line after a while, and a second press brings it back", () => {
    vi.useFakeTimers();
    const bar = mount();
    wireTierPicker(bar, { path: "/", routes: bodyRoutes("earth") }, effects({ probe: () => ({ webgl2: false, softwareGpu: false }) }).live);
    const refusal = bar.querySelector(".picker-refusal")!;
    button(bar, "globe").click();
    vi.advanceTimersByTime(REFUSAL_VISIBLE_MS);
    expect(refusal.textContent).toBe("");
    button(bar, "globe").click();
    expect(refusal.textContent).toBe(REFUSAL);
  });
});

const tagged = (bar: HTMLElement) =>
  [...bar.querySelectorAll<HTMLButtonElement>("button[data-auto]")].map((tier) => tier.dataset.quality);

describe("the auto tag says the site picked the lit tier", () => {
  it("tags the lit tier on a globe the visitor has never picked for", () => {
    const bar = mount();
    wireTierPicker(bar, { path: "/earth/", routes: bodyRoutes("earth") }, effects({ tier: () => "globe" }).live);
    expect(tagged(bar)).toEqual(["globe"]);
  });

  it("tags nothing on a globe once the visitor has picked", () => {
    const bar = mount();
    wireTierPicker(bar, { path: "/earth/", routes: bodyRoutes("earth") }, effects({ stored: () => "globe" }).live);
    expect(tagged(bar)).toEqual([]);
  });

  it("tags Lite on a lite page the site kept the visitor on", () => {
    const bar = mount();
    wireTierPicker(bar, { path: "/", routes: bodyRoutes("earth"), keptOnLite: true }, effects().live);
    expect(tagged(bar)).toEqual(["lite"]);
  });

  it("tags nothing on a lite page the visitor came to themselves", () => {
    const bar = mount();
    wireTierPicker(bar, { path: "/", routes: bodyRoutes("earth"), keptOnLite: false }, effects().live);
    expect(tagged(bar)).toEqual([]);
  });
});

describe("the tier picker on a globe", () => {
  it("lights the tier the globe is running", () => {
    const bar = mount();
    wireTierPicker(bar, { path: "/earth/", routes: bodyRoutes("earth") }, effects({ tier: () => "globe" }).live);
    expect(button(bar, "globe").getAttribute("aria-pressed")).toBe("true");
    expect(button(bar, "full").getAttribute("aria-pressed")).toBe("false");
  });

  it("reloads rather than navigates when the pick is the page it is on, by either spelling", () => {
    const bar = mount();
    const { live, calls } = effects();
    wireTierPicker(bar, { path: "/earth", routes: bodyRoutes("earth") }, live);
    button(bar, "full").click();
    expect(calls.reloads).toBe(1);
    expect(calls.assigned).toEqual([]);
  });

  it("never probes on a globe, where the guard has already let the device through", () => {
    const probe = vi.fn(() => ({ webgl2: false, softwareGpu: false }));
    const bar = mount();
    const { live, calls } = effects({ probe });
    wireTierPicker(bar, { path: "/earth/", routes: bodyRoutes("earth") }, live);
    button(bar, "globe").click();
    expect(probe).not.toHaveBeenCalled();
    expect(calls.reloads).toBe(1);
  });
});
