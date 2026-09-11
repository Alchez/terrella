// The Lite / Globe / Full picker in the view bar: the persisted override that beats the probe.
import { isSamePath, type BodyRoutes } from "./bodyRoutes";
import {
  currentGlobeTier,
  getQuality,
  guardBouncesOffGlobe,
  probeSignals,
  setQuality,
  type CapabilitySignals,
  type Quality,
  type Tier,
} from "./capability";

/** What the picker reads from the device and does to the page, passed in so a test can drive it
 *  without a GPU and without leaving. */
export interface PickerEffects {
  probe: () => Pick<CapabilitySignals, "webgl2" | "softwareGpu">;
  tier: () => Tier;
  /** The visitor's saved pick, `auto` until they press one. */
  stored: () => Quality;
  assign: (url: string) => void;
  reload: () => void;
}

export const LIVE_EFFECTS: PickerEffects = {
  probe: probeSignals,
  tier: currentGlobeTier,
  stored: getQuality,
  assign: (url) => location.assign(url),
  reload: () => location.reload(),
};

/** What a refused press says, in the About note's own words for the same case. */
export const REFUSAL = "This browser can't draw the globe well";

/** How long that stays up after a press. A choice, not a measurement: long enough to read twice. */
export const REFUSAL_VISIBLE_MS = 4000;

/**
 * Light the tier the page is showing, tag it when the site picked it, and wire the presses.
 *
 * The lit button is what the visitor is SEEING: Lite on a lite page, and on a globe Globe or Full by
 * `tier`, which cannot answer `gallery` for a soft signal, so a device that cannot run the globe and
 * one merely skipping the extras never light the same chip.
 *
 * The site picked it on a globe until the visitor presses anything, and on a lite page only when
 * the pre-paint guard kept them there (`keptOnLite`), a return to the gallery being their own.
 *
 * A press persists and navigates, and touches no session flag: every arrival at a globe is already
 * permitted by the stored pick, and clearing the steer flag only re-armed the auto-steer, which then
 * hijacked the next deliberate trip back to a lite page.
 */
export function wireTierPicker(
  bar: HTMLElement,
  page: { path: string; routes: BodyRoutes; keptOnLite?: boolean },
  effects: PickerEffects = LIVE_EFFECTS,
): void {
  const control = bar.querySelector<HTMLElement>(".quality-fab");
  if (!control) return;
  const buttons = [...control.querySelectorAll<HTMLButtonElement>("button")];
  const onGlobe = isSamePath(page.path, page.routes.globe);
  const active: Quality = !onGlobe ? "lite" : effects.tier() === "full" ? "full" : "globe";
  const sitePicked = onGlobe ? effects.stored() === "auto" : page.keptOnLite === true;
  for (const button of buttons) {
    const isActive = button.dataset.quality === active;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
    button.toggleAttribute("data-auto", isActive && sitePicked);
  }

  const reason = bar.querySelector<HTMLElement>(".picker-refusal");
  let clearReason: ReturnType<typeof setTimeout> | undefined;
  const refuse = () => {
    for (const button of buttons) {
      if (button.dataset.quality === "lite") continue;
      button.setAttribute("aria-disabled", "true");
      button.title = REFUSAL;
    }
    if (!reason) return;
    reason.textContent = REFUSAL;
    clearTimeout(clearReason);
    clearReason = setTimeout(() => (reason.textContent = ""), REFUSAL_VISIBLE_MS);
  };

  for (const button of buttons) {
    button.addEventListener("click", () => {
      const choice = button.dataset.quality as Quality;
      // Asked on a lite page only, and only on press: a globe page's guard has already let this
      // device through, and a probe at load would spend a WebGL context on every visitor.
      if (choice !== "lite" && !onGlobe && guardBouncesOffGlobe(effects.probe())) {
        refuse();
        return;
      }
      setQuality(choice);
      const target = choice === "lite" ? page.routes.lite : page.routes.globe;
      if (isSamePath(page.path, target)) effects.reload();
      else effects.assign(target);
    });
  }
}
