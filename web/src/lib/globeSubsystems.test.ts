import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  globeSubsystems,
  globeTileAddresses,
  hasHoverHighlight,
  type GlobeSubsystems,
} from "./globeSubsystems";
import { BODIES, type BodyDescriptor, type BodySlug } from "./bodies";
import { PUBLISHED, type PublishedArchives } from "./tileAddress";
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

/** What a REGISTERED body's globe draws, with the three records gathered the way `Globe.astro`
 *  gathers them. The tests that write a body the registry does not contain call `globeSubsystems`
 *  directly, which is the whole reason it takes records rather than a slug. */
const drawnFor = (slug: BodySlug, flags: URLSearchParams) =>
  globeSubsystems(BODIES[slug], PUBLISHED[slug], VECTOR_PRODUCT[slug], flags);

/** A body the registry does not contain, which is the only thing that can tell a derivation from a
 *  constant. Every registered body publishes every layer and renders caps, so an answer written as
 *  a literal agrees with the registry on all of them; only a record belonging to no planet
 *  disagrees. `tests/test_bodies.py` and its neighbours have built these with `dataclasses.replace`
 *  on the pipeline side for as long as there have been two bodies.
 *
 *  Every case below is an assertion and its control: the second half switches the field back on and
 *  expects the answer to move, so a function that hardcoded either answer fails one of the two. */
const publishing = (overrides: Partial<PublishedArchives>): PublishedArchives =>
  ({ ...PUBLISHED.earth, ...overrides });
const describing = (overrides: Partial<BodyDescriptor>): BodyDescriptor =>
  ({ ...BODIES.earth, ...overrides });
const OVERLAYS = ["polarCaps", "borders", "heroes"] as const;

/** Flag combinations a visitor can actually produce, including the nonsense ones. */
const FLAG_SETS = ["", "bare", "nocaps", "bare&nocaps", "terrain=2", "bare&terrain=2", "perf"];

describe("what a body's globe draws", () => {
  it("gives Earth all five, because Earth is the body every one of them was built for", () => {
    expect(drawnFor("earth", NO_FLAGS)).toEqual({
      polarCaps: true,
      terrain: true,
      vectorProduct: "countries",
      borders: true,
      heroes: true,
    } satisfies GlobeSubsystems);
  });

  it("gives a body its own vector product rather than the one Earth publishes", () => {
    // The caps are not an exception — they are the projection's repair rather than a layer over it.
    // Web Mercator carries no data past ~85°, so a globe without them draws the polar plug
    // at both poles: a flat pale disc, tested on Earth and rejected.
    //
    // `vectorProduct` is the field this case exists for now that Mars publishes vectors. It read
    // `countries: false` while Mars published nothing, which was true and proved nothing about the
    // question — whether a second body's overlay can be told apart from Earth's. It can, and a
    // boolean could not have said so.
    expect(drawnFor("mars", NO_FLAGS)).toEqual({
      polarCaps: true,
      terrain: true,
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
    //
    // `terrain` LEFT THIS LIST THE DAY MARS PUBLISHED A DEM, by that same rule rather than by
    // weakening it: a body holding elevation data wants displacement, so demanding disagreement
    // here would be asking Mars to stay flat to satisfy a test. The list is what still separates
    // the bodies, and it shrinks as the second planet catches up — when it empties, the two cases
    // above stop proving anything and this assertion is what will say so.
    const answers = ALL_BODIES.map((body) => drawnFor(body, NO_FLAGS));
    for (const subsystem of ["borders", "heroes"] as const) {
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
      const bare = drawnFor(body, new URLSearchParams("bare"));
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
    expect(drawnFor("earth", new URLSearchParams("bare")).terrain).toBe(true);
  });
});

describe("the tile addresses a globe draws from", () => {
  it("builds no address for a subsystem that is off, instead of throwing at page load", () => {
    // THE DEFECT THIS CLOSES, and the reason it is worth a test rather than a read-through:
    // building an address for an unpublished layer throws, the page did it at module scope, and the
    // result was a blank globe with one console line.
    //
    // THE RECORD IS BUILT HERE RATHER THAN TAKEN FROM A BODY, and it had to be. This case read
    // `globeSubsystems("mars", NO_FLAGS)` while Mars published no DEM, and the day Mars published
    // one it would have gone on passing having asserted nothing about the null branch — the
    // subsystem it was watching had quietly turned on. A negative instance borrowed from live data
    // lasts exactly as long as the gap it was borrowed from, and nothing announces its end.
    const nothingButRelief: GlobeSubsystems = {
      polarCaps: true, terrain: false, vectorProduct: null, borders: false, heroes: false,
    };
    expect(() => globeTileAddresses("mars", nothingButRelief)).not.toThrow();
    const addresses = globeTileAddresses("mars", nothingButRelief);
    expect(addresses.relief).toContain("mars/relief");
    expect(addresses.terrain).toBeNull();
    expect(addresses.vector).toBeNull();
  });

  it("addresses Mars's vector archive by its ROLE, not by the product inside it", () => {
    // Mars's archive holds features and its URL still says `vector`, which is the whole point of
    // the segment naming a role. A path spelling `mars/features` would mean the address grammar had
    // grown a per-body case. Split out of the case above when that one stopped using a real body.
    const addresses = globeTileAddresses("mars", drawnFor("mars", NO_FLAGS));
    expect(addresses.vector).toContain("mars/vector");
    expect(addresses.vector).not.toContain("features");
    expect(addresses.terrain).toContain("mars/terrain");
  });

  it("gives Earth all three, so the case above is not passing on a body with nothing to build", () => {
    const addresses = globeTileAddresses("earth", drawnFor("earth", NO_FLAGS));
    expect(addresses.relief).toContain("earth/relief");
    expect(addresses.terrain).toContain("earth/terrain");
    expect(addresses.vector).toContain("earth/vector");
  });

  it("withholds an address the flags turned off, so nothing can fetch behind a closed gate", () => {
    // `?bare` is not only a "do not draw" — it is a "do not address". A template built anyway is a
    // live URL sitting in scope, one careless line away from a source that fetches the pyramid the
    // visitor asked not to see.
    const bare = globeTileAddresses("earth", drawnFor("earth", new URLSearchParams("bare")));
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
        const drawn = drawnFor(body, new URLSearchParams(flags));
        const where = `${body} ?${flags}`;
        if (drawn.terrain) expect(PUBLISHED[body].terrain, where).not.toBeNull();
        if (drawn.vectorProduct !== null) expect(PUBLISHED[body].vector, where).not.toBeNull();
      }
    }
    // THE LOOP ABOVE CANNOT FAIL ON THE REGISTERED BODIES, AND SAYING SO IS THE POINT. Both
    // implications are conditional on a body publishing nothing, and since Mars's DEM landed every
    // body publishes every layer — so `terrain: true` hardcoded satisfies every iteration here.
    // What discriminates is the block below, which writes the body the registry does not contain.
  });

  it("draws no terrain for a body publishing no terrain pyramid, and terrain for one that does",
     () => {
       const bare = globeSubsystems(describing({}), publishing({ terrain: null }), "countries",
                                    NO_FLAGS);
       const full = globeSubsystems(describing({}), publishing({}), "countries", NO_FLAGS);
       expect(bare.terrain, "terrain stopped being derived from the archives").toBe(false);
       expect(full.terrain, "the control: terrain never comes on at all").toBe(true);
     });

  it("draws no vector product for a body publishing no vector archive, and one for a body that does",
     () => {
       const bare = globeSubsystems(describing({}), publishing({ vector: null }), "features",
                                    NO_FLAGS);
       const full = globeSubsystems(describing({}), publishing({}), "features", NO_FLAGS);
       expect(bare.vectorProduct, "the product stopped being derived from the archives").toBeNull();
       expect(full.vectorProduct, "the control: the product never arrives at all").toBe("features");
     });

  it("draws no polar caps for a body that renders none, and caps for one that does", () => {
    // The registry cannot express this today and `bodies.test.ts` says so in its own header:
    // `rendersPolarCaps` is outside EARTH_ONLY_FLAGS because both bodies answer true, so it is the
    // one descriptor flag no registered pair can falsify.
    const capless = globeSubsystems(describing({ rendersPolarCaps: false }), publishing({}),
                                    "countries", NO_FLAGS);
    const capped = globeSubsystems(describing({ rendersPolarCaps: true }), publishing({}),
                                   "countries", NO_FLAGS);
    expect(capless.polarCaps, "the caps stopped being the descriptor's answer").toBe(false);
    expect(capped.polarCaps, "the control: the caps never come on at all").toBe(true);
  });

  it("lights nothing under the pointer for a body publishing no vectors, and does for one that does",
     () => {
       // `hasHoverHighlight`'s own docstring records that it reads `true` twice on the registered
       // bodies. This is the case that makes it a predicate rather than a constant.
       expect(hasHoverHighlight(publishing({ vector: null }))).toBe(false);
       expect(hasHoverHighlight(publishing({})), "the control").toBe(true);
     });

  it("is handed each planet's OWN records by the globe, which is what taking them costs", () => {
    // WITH THE LOOKUPS INSIDE, A WRONG BODY HERE WAS IMPOSSIBLE. Moving them to the call site buys
    // the four assertions above and opens one failure that did not exist: a globe handed another
    // planet's archives draws layers its own tiles do not hold, and MapLibre paints an unmatched
    // `source-layer` as EMPTY — no error, no warning, no network difference.
    const globe = readFileSync(new URL("../components/Globe.astro", import.meta.url), "utf8");
    const call = /globeSubsystems\(([^;]*?)\);/s.exec(globe);
    expect(call, "Globe.astro no longer calls globeSubsystems; everything below is vacuous")
      .not.toBeNull();
    const args = call![1];
    expect(args, "the descriptor is not the page's own body").toMatch(/(^|\W)body,/);
    expect(args, "the archives are not this body's").toContain("PUBLISHED[body.slug]");
    expect(args, "the product is not this body's").toContain("VECTOR_PRODUCT[body.slug]");
    for (const slug of ALL_BODIES) {
      expect(args, `the call names ${slug} outright instead of the body the page resolved`)
        .not.toContain(`"${slug}"`);
    }
  });

  it("is handed this body's archives by every page that asks about the pointer", () => {
    // The same cost on the other exported predicate. `viewBar.browser.test.ts` evaluates these
    // expressions for real and throws on one it cannot resolve, so this is the cheaper half: it
    // says WHICH spelling, where that one says the spelling still answers correctly.
    for (const slug of ALL_BODIES) {
      const page = readFileSync(
        new URL(`../pages/${slug}/index.astro`, import.meta.url), "utf8");
      expect(page, `${slug}/index.astro stopped asking about its own body`)
        .toContain("hasHoverHighlight(PUBLISHED[body.slug])");
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
        const product = drawnFor(body, new URLSearchParams(flags)).vectorProduct;
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

  it("arms the search field for every product the registry can hand it", () => {
    // THE GATE ON THE FIELD IS NOW `vectorProduct !== null`, so every product gets a button — and a
    // button is BORN DISABLED. A product with no arming therefore ships a control that is present,
    // greyed, and captioned "loading the catalogue" forever: not a crash, not a blank globe, just a
    // rail that looks like it is still waiting. It read `=== "features"` before Earth arrived, which
    // is what made this failure unreachable and is exactly what changed.
    //
    // Total over products, so a third one is a compile error here rather than a dead button. The
    // arming call is what is named, not the gate — a body can be gated and still never arm.
    const ARMS_WITH: Record<VectorProduct, string> = {
      countries: "matcher = createCatalogueSearch(manifest.countries.map(countrySearchEntry))",
      features: "matcher = createCatalogueSearch(featureIndex.map(featureSearchEntry))",
    };
    const globe = readFileSync(new URL("../components/Globe.astro", import.meta.url), "utf8");
    for (const product of Object.values(VECTOR_PRODUCT)) {
      expect(globe, `nothing arms the search matcher for the ${product} product`).toContain(
        ARMS_WITH[product],
      );
    }
    expect(globe, "the field's gate narrowed back to one product, so the other loses its button")
      .toContain("if (subsystems.vectorProduct !== null) {");
  });

  it("opens the hero panel only where a click has a country to land on", () => {
    // `heroes` without `countries` is a subsystem with no route into it — the panel opens exactly
    // one way, a map click hit-tested against the countries pyramid. The registry states the rule;
    // this holds it after the flags have had their say, which is where it could still come apart.
    for (const body of ALL_BODIES) {
      for (const flags of FLAG_SETS) {
        const drawn = drawnFor(body, new URLSearchParams(flags));
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
    for (const subsystem of Object.keys(drawnFor("earth", NO_FLAGS))) {
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
    const plain = drawnFor("earth", NO_FLAGS);
    const nocaps = drawnFor("earth", new URLSearchParams("nocaps"));
    expect(nocaps.polarCaps).toBe(false);
    for (const subsystem of ["terrain", "vectorProduct", "borders", "heroes"] as const) {
      expect(nocaps[subsystem], `?nocaps changed ${subsystem}`).toBe(plain[subsystem]);
    }
  });
});
