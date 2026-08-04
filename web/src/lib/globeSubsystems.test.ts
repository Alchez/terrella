import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { globeSubsystems, globeTileAddresses, type GlobeSubsystems } from "./globeSubsystems";
import { BODIES, type BodySlug } from "./bodies";
import { PUBLISHED } from "./tileAddress";

/**
 * The claim under test is C5's whole point: a body that publishes only relief and a visitor asking
 * for `?bare` want the same globe, so there is one code path rather than two.
 *
 * These can all be written TODAY, before `/mars/` draws anything, which is the reason the answer is
 * a pure function of a slug and a `URLSearchParams` rather than something read off a live page.
 */
const ALL_BODIES = Object.keys(BODIES) as BodySlug[];
const NO_FLAGS = new URLSearchParams();
const OVERLAYS = ["polarCaps", "countries", "borders", "heroes"] as const;

/** Flag combinations a visitor can actually produce, including the nonsense ones. */
const FLAG_SETS = ["", "bare", "nocaps", "bare&nocaps", "terrain=2", "bare&terrain=2", "perf"];

describe("what a body's globe draws", () => {
  it("gives Earth all five, because Earth is the body every one of them was built for", () => {
    expect(globeSubsystems("earth", NO_FLAGS)).toEqual({
      polarCaps: true,
      terrain: true,
      countries: true,
      borders: true,
      heroes: true,
    } satisfies GlobeSubsystems);
  });

  it("gives a relief-only body its raster and nothing else", () => {
    expect(globeSubsystems("mars", NO_FLAGS)).toEqual({
      polarCaps: false,
      terrain: false,
      countries: false,
      borders: false,
      heroes: false,
    } satisfies GlobeSubsystems);
  });

  it("is measuring bodies that actually DISAGREE, or the two cases above prove nothing", () => {
    // Both of the above would pass on a function that ignored its argument and returned a constant,
    // if the registry happened to answer the same way for every planet. It does not, and this is
    // what fails on the day someone adds a third body by copying Earth's row.
    const answers = ALL_BODIES.map((body) => globeSubsystems(body, NO_FLAGS));
    for (const subsystem of ["polarCaps", "terrain", "countries", "borders", "heroes"] as const) {
      const given = new Set(answers.map((answer) => answer[subsystem]));
      expect(given, `every body answers the same for ${subsystem}`).toEqual(new Set([true, false]));
    }
  });
});

describe("?bare and a body that publishes only relief are one code path", () => {
  it("takes away from Earth exactly what Mars never had", () => {
    // The thesis, executable. Compared on the OVERLAYS only: `?bare` isolates the raster baseline
    // from what is drawn over it, and terrain is the raster in three dimensions rather than a thing
    // on top of it — so `?bare&terrain=2` stays a combination worth asking for.
    const bareEarth = globeSubsystems("earth", new URLSearchParams("bare"));
    const plainMars = globeSubsystems("mars", NO_FLAGS);
    for (const overlay of OVERLAYS) {
      expect(bareEarth[overlay], `?bare Earth vs plain Mars disagree on ${overlay}`).toBe(
        plainMars[overlay],
      );
    }
  });

  it("keeps terrain on a bare Earth, so the flag cannot silently delete a diagnostic", () => {
    // The one field the case above deliberately does not compare, asserted rather than assumed —
    // otherwise "compared on the overlays only" would be a comment with nothing behind it.
    expect(globeSubsystems("earth", new URLSearchParams("bare")).terrain).toBe(true);
  });
});

describe("the tile addresses a globe draws from", () => {
  it("resolves for a body that publishes only relief, instead of throwing at page load", () => {
    // THE DEFECT THIS COMMIT CLOSES, and the reason it is worth a test rather than a read-through:
    // building an address for an unpublished layer throws, the page did it at module scope, and the
    // result was a blank globe with one console line. It was invisible because nothing loads a Mars
    // globe — and it stays invisible until C6 unless the address is a function something can call.
    const drawn = globeSubsystems("mars", NO_FLAGS);
    expect(() => globeTileAddresses("mars", drawn)).not.toThrow();
    const addresses = globeTileAddresses("mars", drawn);
    expect(addresses.relief).toContain("mars/relief");
    expect(addresses.terrain).toBeNull();
    expect(addresses.countries).toBeNull();
  });

  it("gives Earth all three, so the case above is not passing on a body with nothing to build", () => {
    const addresses = globeTileAddresses("earth", globeSubsystems("earth", NO_FLAGS));
    expect(addresses.relief).toContain("earth/relief");
    expect(addresses.terrain).toContain("earth/terrain");
    expect(addresses.countries).toContain("earth/countries");
  });

  it("withholds an address the flags turned off, so nothing can fetch behind a closed gate", () => {
    // `?bare` is not only a "do not draw" — it is a "do not address". A template built anyway is a
    // live URL sitting in scope, one careless line away from a source that fetches the pyramid the
    // visitor asked not to see.
    const bare = globeTileAddresses("earth", globeSubsystems("earth", new URLSearchParams("bare")));
    expect(bare.countries).toBeNull();
    expect(bare.relief, "?bare is the raster BASELINE, so relief must survive it").toContain(
      "earth/relief",
    );
  });
});

describe("the registry is the only thing that can switch a subsystem ON", () => {
  it("never advertises a pyramid the body does not publish, whatever the URL says", () => {
    // A flag may only take away. The failure this forbids is the expensive one: a URL that turns
    // terrain on for a body with no terrain archive builds a tile address that throws, and it
    // throws at module scope — before a map exists — so the globe is a blank page.
    for (const body of ALL_BODIES) {
      for (const flags of FLAG_SETS) {
        const drawn = globeSubsystems(body, new URLSearchParams(flags));
        const where = `${body} ?${flags}`;
        if (drawn.terrain) expect(PUBLISHED[body].terrain, where).not.toBeNull();
        if (drawn.countries) expect(PUBLISHED[body].countries, where).not.toBeNull();
      }
    }
  });

  it("opens the hero panel only where a click has a country to land on", () => {
    // `heroes` without `countries` is a subsystem with no route into it — the panel opens exactly
    // one way, a map click hit-tested against the countries pyramid. The registry states the rule;
    // this holds it after the flags have had their say, which is where it could still come apart.
    for (const body of ALL_BODIES) {
      for (const flags of FLAG_SETS) {
        const drawn = globeSubsystems(body, new URLSearchParams(flags));
        if (drawn.heroes) expect(drawn.countries, `${body} ?${flags}`).toBe(true);
      }
    }
  });

  it("is READ by the globe for every answer it gives, so none of them is decoration", () => {
    // Derived from the module's own return value rather than a list written here, which is what
    // makes it catch the case worth catching: a sixth subsystem added to the record and gated
    // nowhere. That failure is silent by construction — the answer is computed, tested, correct,
    // and simply never consulted, so the layer it was meant to gate mounts on every planet.
    //
    // A source scan is the weakest kind of guard and it is the only kind available here: these
    // gates live in a page's client script, which nothing can import and no unit test can drive.
    // It buys deletion and rename, which is how a gate actually gets lost.
    const globe = readFileSync(new URL("../components/Globe.astro", import.meta.url), "utf8");
    for (const subsystem of Object.keys(globeSubsystems("earth", NO_FLAGS))) {
      expect(globe, `nothing in the globe reads subsystems.${subsystem}`).toContain(
        `subsystems.${subsystem}`,
      );
    }
  });

  it("is the only thing reading the flags it owns, so one place decides", () => {
    // `?bare` and `?nocaps` used to be read at the gate sites, and a second reader is how the two
    // answers drift: the caps check and the vector check disagreeing about what "bare" means is
    // not a failure anything reports, it is just a globe that draws three of four layers.
    const globe = readFileSync(new URL("../components/Globe.astro", import.meta.url), "utf8");
    for (const flag of ["bare", "nocaps"]) {
      expect(globe, `the globe reads ?${flag} itself instead of asking globeSubsystems`).not.toMatch(
        new RegExp(String.raw`urlFlags\.(has|get)\("${flag}"\)`),
      );
    }
  });

  it("leaves ?nocaps isolating the caps and nothing else", () => {
    // It predates ?bare and keeps its own meaning: it is what cornered the black-disc-on-restore
    // bug, and a flag that quietly took more than its name says would have made that hunt useless.
    const plain = globeSubsystems("earth", NO_FLAGS);
    const nocaps = globeSubsystems("earth", new URLSearchParams("nocaps"));
    expect(nocaps.polarCaps).toBe(false);
    for (const subsystem of ["terrain", "countries", "borders", "heroes"] as const) {
      expect(nocaps[subsystem], `?nocaps changed ${subsystem}`).toBe(plain[subsystem]);
    }
  });
});
