import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { globeSubsystems, globeTileAddresses, type GlobeSubsystems } from "./globeSubsystems";
import { BODIES, type BodySlug } from "./bodies";
import { PUBLISHED } from "./tileAddress";
import { VECTOR_PRODUCT, sourceLayer, type VectorProduct } from "./sourceLayers";

/**
 * The claim under test is C5's whole point: a body that publishes only relief and a visitor asking
 * for `?bare` want the same globe, so there is one code path rather than two.
 *
 * These can all be written TODAY, before `/mars/` draws anything, which is the reason the answer is
 * a pure function of a slug and a `URLSearchParams` rather than something read off a live page.
 */
const ALL_BODIES = Object.keys(BODIES) as BodySlug[];
const NO_FLAGS = new URLSearchParams();
const OVERLAYS = ["polarCaps", "borders", "heroes"] as const;

/** Flag combinations a visitor can actually produce, including the nonsense ones. */
const FLAG_SETS = ["", "bare", "nocaps", "bare&nocaps", "terrain=2", "bare&terrain=2", "perf"];

describe("what a body's globe draws", () => {
  it("gives Earth all five, because Earth is the body every one of them was built for", () => {
    expect(globeSubsystems("earth", NO_FLAGS)).toEqual({
      polarCaps: true,
      terrain: true,
      vectorProduct: "countries",
      borders: true,
      heroes: true,
    } satisfies GlobeSubsystems);
  });

  it("gives a body its own vector product rather than the one Earth publishes", () => {
    // The caps are not an exception — they are the projection's repair rather than a layer over it.
    // Web Mercator carries no data past ~85°, so a globe without them draws `shade_planet.CAP_RGB`
    // at both poles: a flat pale disc, tested on Earth and rejected.
    //
    // `vectorProduct` is the field this case exists for now that Mars publishes vectors. It read
    // `countries: false` while Mars published nothing, which was true and proved nothing about the
    // question — whether a second body's overlay can be told apart from Earth's. It can, and a
    // boolean could not have said so.
    expect(globeSubsystems("mars", NO_FLAGS)).toEqual({
      polarCaps: true,
      terrain: false,
      vectorProduct: "features",
      borders: false,
      heroes: false,
    } satisfies GlobeSubsystems);
  });

  it("is measuring bodies that actually DISAGREE, or the two cases above prove nothing", () => {
    // Both of the above would pass on a function that ignored its argument and returned a constant,
    // if the registry happened to answer the same way for every planet. It does not, and this is
    // what fails on the day someone adds a third body by copying Earth's row.
    //
    // `polarCaps` is not in the list, and the omission is the point rather than an oversight: a cap
    // is a Web Mercator repair, so it is what every body wants once its ramps are ratified. Asking
    // the registry to keep disagreeing about it would be asking a planet to keep a hole at its pole
    // to satisfy a test. What still gates it per visit is `?bare` and `?nocaps`, below.
    const answers = ALL_BODIES.map((body) => globeSubsystems(body, NO_FLAGS));
    for (const subsystem of ["terrain", "borders", "heroes"] as const) {
      const given = new Set(answers.map((answer) => answer[subsystem]));
      expect(given, `every body answers the same for ${subsystem}`).toEqual(new Set([true, false]));
    }
    // Its own assertion because it is no longer a boolean: what has to differ is WHICH product,
    // and a set of size two is the same claim the loop above makes.
    const products = new Set(answers.map((answer) => answer.vectorProduct));
    expect(products.size, "every body draws the same vector product").toBe(ALL_BODIES.length);
  });
});

describe("?bare strips a globe to the raster baseline, on every body", () => {
  it("strips every body down to the same floor, whatever that body publishes", () => {
    // The thesis, executable. It used to be spelled as `?bare` Earth == plain Mars, which read well
    // while Mars published nothing but relief and quietly stopped being an assertion the moment it
    // published anything — the two sides met at "all false" because Mars had nothing to take away.
    // Stated as the floor itself it survives a body acquiring subsystems, and Mars acquiring caps is
    // what makes the `?bare` path do real work on a second planet for the first time.
    //
    // Compared on the OVERLAYS only: `?bare` isolates the raster baseline from what is drawn over
    // it, and terrain is the raster in three dimensions rather than a thing on top of it — so
    // `?bare&terrain=2` stays a combination worth asking for.
    for (const body of ALL_BODIES) {
      const bare = globeSubsystems(body, new URLSearchParams("bare"));
      for (const overlay of OVERLAYS) {
        expect(bare[overlay], `?bare ${body} still draws ${overlay}`).toBe(false);
      }
      // The vector overlay says the same thing in its own type. It left `OVERLAYS` when it stopped
      // being a boolean, and asserting it here rather than dropping it is the difference between
      // "?bare strips the overlays" and "?bare strips the overlays that are still booleans".
      expect(bare.vectorProduct, `?bare ${body} still draws vectors`).toBeNull();
    }
  });

  it("keeps terrain on a bare Earth, so the flag cannot silently delete a diagnostic", () => {
    // The one field the case above deliberately does not compare, asserted rather than assumed —
    // otherwise "compared on the overlays only" would be a comment with nothing behind it.
    expect(globeSubsystems("earth", new URLSearchParams("bare")).terrain).toBe(true);
  });
});

describe("the tile addresses a globe draws from", () => {
  it("resolves for a body missing a pyramid, instead of throwing at page load", () => {
    // THE DEFECT THIS CLOSES, and the reason it is worth a test rather than a read-through:
    // building an address for an unpublished layer throws, the page did it at module scope, and the
    // result was a blank globe with one console line. Terrain is the layer carrying the case now —
    // Mars publishes relief and vectors and no DEM-derived heights, so the mixed body is still the
    // one under test rather than a planet that answers null to everything.
    const drawn = globeSubsystems("mars", NO_FLAGS);
    expect(() => globeTileAddresses("mars", drawn)).not.toThrow();
    const addresses = globeTileAddresses("mars", drawn);
    expect(addresses.relief).toContain("mars/relief");
    expect(addresses.terrain).toBeNull();
    // THE ROLE, not the product: Mars's archive holds features and its URL still says `vector`,
    // which is the whole point of the segment naming a role. A path spelling `mars/features` here
    // would mean the address grammar had grown a per-body case.
    expect(addresses.vector).toContain("mars/vector");
  });

  it("gives Earth all three, so the case above is not passing on a body with nothing to build", () => {
    const addresses = globeTileAddresses("earth", globeSubsystems("earth", NO_FLAGS));
    expect(addresses.relief).toContain("earth/relief");
    expect(addresses.terrain).toContain("earth/terrain");
    expect(addresses.vector).toContain("earth/vector");
  });

  it("withholds an address the flags turned off, so nothing can fetch behind a closed gate", () => {
    // `?bare` is not only a "do not draw" — it is a "do not address". A template built anyway is a
    // live URL sitting in scope, one careless line away from a source that fetches the pyramid the
    // visitor asked not to see.
    const bare = globeTileAddresses("earth", globeSubsystems("earth", new URLSearchParams("bare")));
    expect(bare.vector).toBeNull();
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
        if (drawn.vectorProduct !== null) expect(PUBLISHED[body].vector, where).not.toBeNull();
      }
    }
  });

  it("names a product the body's own archive holds, never another planet's", () => {
    // WHAT THE PLANTED FORCING FUNCTION ASKED FOR, kept as a guard rather than retired with it.
    // The flag it replaced was a boolean derived from `PUBLISHED[body].vector` alone, so Mars
    // publishing an archive turned Earth's country overlay on for Mars — style layers naming
    // `country_fill` over tiles that hold `feature_fill`. MapLibre paints an unmatched
    // `source-layer` as EMPTY: no error, no warning, no network difference.
    //
    // The claim is not tautological even though both sides live in sourceLayers.ts: `VECTOR_PRODUCT`
    // and `SOURCE_LAYERS` are two independent records, and this is what stops one being edited
    // without the other. `test_source_layers.py` pins the second to the Python that cuts it.
    const fillFor: Record<VectorProduct, string> = {
      countries: "country_fill",
      features: "feature_fill",
    };
    for (const body of ALL_BODIES) {
      for (const flags of FLAG_SETS) {
        const product = globeSubsystems(body, new URLSearchParams(flags)).vectorProduct;
        if (product === null) continue;
        expect(sourceLayer(body, "fill"), `${body} ?${flags}`).toBe(fillFor[product]);
      }
    }
  });

  it("has a globe branch for every product the registry can hand it", () => {
    // The failure the `if` chain in Globe.astro cannot be typed against: a third `VectorProduct`
    // added to the registry, published by some body, and gated nowhere. The idle block then adds a
    // source and no layers — a globe that draws nothing and reports nothing, which is the same
    // symptom as a wrong source-layer and just as silent.
    //
    // A source scan is the weakest kind of guard and the only kind available: these gates live in a
    // page's client script that nothing can import. It buys the case that actually happens, which
    // is a member added here and forgotten there.
    // A BRANCH THAT EXISTS IS NOT A BRANCH THAT DRAWS, which this asked for one commit too long.
    // The mutation that deletes the features gate was not caught, because a second `if` on the same
    // product — the interaction wiring — still satisfied a search for the condition alone. Naming
    // the call each branch has to make closes that, and the record is total, so a third product is
    // a compile error here rather than a globe that quietly draws nothing.
    const DRAWS_WITH: Record<VectorProduct, string> = {
      countries: "addCountryTiles();",
      features: "addFeatureOverlay();",
    };
    const globe = readFileSync(new URL("../components/Globe.astro", import.meta.url), "utf8");
    for (const product of Object.values(VECTOR_PRODUCT)) {
      const gate = globe.indexOf(`vectorProduct === "${product}"`);
      expect(gate, `no globe branch draws the ${product} overlay`).toBeGreaterThan(-1);
      const draws = globe.indexOf(DRAWS_WITH[product], gate);
      expect(draws, `the ${product} branch never calls ${DRAWS_WITH[product]}`).toBeGreaterThan(-1);
      // Within the gate's own statement rather than anywhere later in the file, or a call belonging
      // to some other body's branch would satisfy this one.
      expect(draws - gate, `${DRAWS_WITH[product]} is too far from its gate to be inside it`)
        .toBeLessThan(200);
    }
  });

  it("opens the hero panel only where a click has a country to land on", () => {
    // `heroes` without `countries` is a subsystem with no route into it — the panel opens exactly
    // one way, a map click hit-tested against the countries pyramid. The registry states the rule;
    // this holds it after the flags have had their say, which is where it could still come apart.
    for (const body of ALL_BODIES) {
      for (const flags of FLAG_SETS) {
        const drawn = globeSubsystems(body, new URLSearchParams(flags));
        if (drawn.heroes) expect(drawn.vectorProduct, `${body} ?${flags}`).toBe("countries");
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
    //
    // WHAT IT CANNOT BUY IS ONE GATE OUT OF SEVERAL. This asks whether a subsystem is read at all,
    // so a second reader of the same flag makes deleting the first invisible here. `heroes` has
    // been read twice and is now read once again, which changed nothing about this scan and changed
    // everything about what a mutation proves — a gate whose deletion must fail loudly needs its
    // own pin at its own site, and the heroes one lives in `detailPanel.test.ts`.
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
    for (const subsystem of ["terrain", "vectorProduct", "borders", "heroes"] as const) {
      expect(nocaps[subsystem], `?nocaps changed ${subsystem}`).toBe(plain[subsystem]);
    }
  });
});
