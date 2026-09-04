/**
 * Everything that decorates whatever the pointer is on, and whether that is switched on at all.
 *
 * ONE OWNER FOR WHAT WAS TWO COPIES. Earth's country painter and Mars's feature painter were the
 * same six lines with different nouns — clear the one being left, set the one being entered, over a
 * list of feature-state targets. That was survivable while the rule was fixed; it stopped being
 * survivable when the rule gained a switch, because a preference honoured in one copy and not the
 * other is a globe that half obeys its own control, on whichever body was edited second.
 *
 * THE NAME CHIP IS PART OF THE DECORATION, NOT A NEIGHBOUR OF IT. The rule is that a visitor who
 * switches this off is asking not to have the thing under the pointer dressed up, and a floating
 * label is exactly that. So the chip is driven from here rather than from the tracker's callback,
 * which is also what stops the two from disagreeing — a switch repaints both or neither.
 *
 * WHAT IT DOES NOT TOUCH IS THE CURSOR. `pointer` over a clickable feature is an affordance rather
 * than a decoration: the click still flies and still opens the card with this off, so suppressing
 * the cursor would make the globe lie about what it does.
 *
 * NOR IS THIS THE SUPPRESSION THAT WAS DECLINED. The chip yielding to a card, or to a narrow
 * viewport, stays rejected — a chip that vanishes because a box happens to overlap it reads as
 * broken. Vanishing because the visitor switched it off does not.
 *
 * IT TRACKS WHAT IS LIT RATHER THAN BEING TOLD. `HoverTracker` hands over both the feature being
 * entered and the one being left, and the painters used to take both — but a switch has to repaint
 * with no pointer event to go on, so somebody has to remember. Keeping that here rather than in the
 * caller means there is exactly one answer to "what is lit", instead of a module and its caller
 * holding two that can disagree the moment either is switched off.
 *
 * FEATURE STATE IS WRITTEN THROUGH AN INJECTED CALL, so this module never imports MapLibre and can
 * be driven in node. The globe passes a closure over its own map; that closure is also what keeps
 * the source ids coming from a binding rather than from literals — see `featureStateTargets`, whose
 * header records what naming them cost in production.
 */

/** What `map.setFeatureState` needs to address one layer's features. Structural on purpose: Earth
 *  builds these from its country binding and Mars from its overlay's, and neither type reaches
 *  here. */
export interface HighlightTarget {
  source: string;
  sourceLayer?: string;
}

export interface HoverHighlightOptions {
  /** Every source-layer that carries hover paint for this body. One write per target, because
   *  feature state keys on (source, sourceLayer, id) and one write cannot serve two layers. */
  targets: HighlightTarget[];
  /** Write one feature's `hover` flag. Production's is a `map.setFeatureState` closure. */
  write: (target: HighlightTarget, id: string, hover: boolean) => void;
  /** Name what the pointer is on, or clear the name. Production's is the chip's painter, which is
   *  shared between bodies — one chip, whichever resolver is answering. */
  label: (id: string | null) => void;
  /** Whether decoration starts switched on. The persisted preference, read by the caller. */
  enabled: boolean;
}

export interface HoverHighlight {
  /**
   * The pointer is now on `id`, or on nothing.
   *
   * Takes only what is being ENTERED. Whatever was lit before is this module's own business, which
   * is what lets {@link setEnabled} repaint correctly without a pointer event.
   */
  paint(id: string | null): void;
  /** Switch decoration on or off, repainting whatever the pointer is currently on. */
  setEnabled(enabled: boolean): void;
  /**
   * Re-apply the label with no pointer event and no state write.
   *
   * For the one caller that needs it: closing the detail card has to restore the name of whatever
   * the pointer is still on, and the tracker's own re-resolve only fires on a CHANGE — which this
   * usually is not, because the pointer is generally still on the place the card was describing.
   */
  relabel(): void;
  isEnabled(): boolean;
  /** What the pointer is on — whether or not it is currently decorated. */
  lit(): string | null;
}

export function createHoverHighlight({
  targets,
  write,
  label,
  enabled,
}: HoverHighlightOptions): HoverHighlight {
  let litId: string | null = null;

  const writeAll = (id: string, hover: boolean) => {
    for (const target of targets) write(target, id, hover);
  };

  /** The label always answers the SWITCH as well as the pointer, so there is no path that shows a
   *  name while the paint is off. */
  const relabel = () => label(enabled ? litId : null);

  return {
    paint(id) {
      // Clearing is conditional on `enabled` for the same reason setting is: switched off, nothing
      // was ever written, and clearing a flag that was never set would be a write per pointer move
      // for no painted result.
      if (enabled && litId !== null) writeAll(litId, false);
      litId = id;
      if (enabled && id !== null) writeAll(id, true);
      relabel();
    },

    setEnabled(next) {
      if (next === enabled) return; // idempotent: no redundant writes on a repeated broadcast
      enabled = next;
      // The pointer is parked on something the moment the switch flips, and there is no event
      // coming to repaint it. Without this the globe would keep the old state until the visitor
      // moved the mouse — which reads as the button having done nothing.
      if (litId !== null) writeAll(litId, next);
      relabel();
    },

    relabel,
    isEnabled: () => enabled,
    lit: () => litId,
  };
}
