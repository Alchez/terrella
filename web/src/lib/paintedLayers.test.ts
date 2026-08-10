import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { RATIFIED_LAYERS, neverPaintingLayerIds, ratifiedLayerIds } from "./paintedLayers";
import { CAP_POLES, capLayerId } from "./polarCaps";
import { featureFillLayer, featureLinearHitLayer } from "./featureOverlay";
import { hitLayer } from "./countryHighlight";
import { VECTOR_BINDING } from "./countryHighlight";

/**
 * THE CONSENT GATE. Every other guard in this repo asks whether the code is CORRECT; this one asks
 * whether anyone agreed to what it puts on the planet. See paintedLayers.ts for the failure that
 * bought it.
 *
 * IT IS A SOURCE SCAN, WHICH IS THE WEAKEST KIND OF GUARD, AND THAT IS FORCED. Layers are added
 * inside a page's client script and a WebGL custom layer; nothing can import either, and a unit
 * test cannot drive a real globe with real archives on CI. What a scan buys is the case that
 * actually happens — a layer spec written into the source and never mentioned to anyone.
 *
 * WHAT IT DOES NOT COVER, stated rather than left for someone to discover: a layer whose id is
 * neither a string literal nor produced by `capLayerId`. There is exactly one dynamic-id site today
 * and the count below pins it, so a second one fails here rather than passing quietly.
 */

const LIB_DIR = path.dirname(fileURLToPath(import.meta.url));
const SRC_DIR = path.resolve(LIB_DIR, "..");

/** Every MapLibre layer type. `raster` is also a SOURCE type, which is why the scan pairs `id:`
 *  with `type:` rather than counting type tokens — a source spec carries no `id` field. */
const LAYER_TYPES = [
  "background", "fill", "line", "symbol", "circle", "raster",
  "fill-extrusion", "heatmap", "hillshade", "custom", "color-relief",
];

/** The types a SOURCE can never be, so an unpaired one of these is a layer the scan failed to
 *  read — the blindness this file would otherwise have. */
const LAYER_ONLY_TYPES = LAYER_TYPES.filter((type) => type !== "raster");

/** Every file a layer spec could be written into. Walked rather than listed: a listing goes stale
 *  the day someone adds a module, and it goes stale SILENTLY, which is this test's whole subject. */
function sourceFiles(directory: string = SRC_DIR): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    if (!/\.(ts|astro)$/.test(entry.name) || entry.name.includes(".test.")) return [];
    return [full];
  });
}

const TYPE_ALTERNATION = LAYER_TYPES.join("|");
/** `id:` then `type:`, the order every spec in this repo is written in. */
const ID_FIRST = new RegExp(
  String.raw`\bid:\s*([^,\n]+?),\s*\n?\s*type:\s*"(${TYPE_ALTERNATION})"`, "g",
);
/** The reverse order, matched so the convention cannot be evaded by writing the fields the other
 *  way round — which would otherwise leave a `raster` layer invisible to this scan. */
const TYPE_FIRST = new RegExp(
  String.raw`\btype:\s*"(${TYPE_ALTERNATION})",\s*\n?\s*id:\s*([^,\n]+?),`, "g",
);

interface ScannedSpec {
  /** The id as written. A quoted literal is unwrapped; anything else is kept verbatim and counted
   *  as dynamic. */
  id: string;
  literal: boolean;
  type: string;
  file: string;
}

/** Read one file's layer specs. Takes the TEXT rather than a path, so the reverse-order branch can
 *  be exercised on a built string — no spec in this repo is written that way today, which would
 *  otherwise leave that regex as untested code holding up a completeness claim. */
function specsIn(source: string, file: string): ScannedSpec[] {
  const found: ScannedSpec[] = [];
  const record = (rawId: string, type: string) => {
    const quoted = /^"([^"]+)"$/.exec(rawId.trim());
    found.push({ id: quoted?.[1] ?? rawId.trim(), literal: !!quoted, type, file });
  };
  for (const [, rawId, type] of source.matchAll(ID_FIRST)) record(rawId!, type!);
  for (const [, type, rawId] of source.matchAll(TYPE_FIRST)) record(rawId!, type!);
  return found;
}

function scanLayerSpecs(): ScannedSpec[] {
  return sourceFiles().flatMap((file) =>
    specsIn(readFileSync(file, "utf8"), path.relative(SRC_DIR, file)));
}

describe("every layer the globe can add is one the maintainer has seen", () => {
  it("finds layer specs at all, or everything below is vacuous", () => {
    // The blindness control, first because it is the failure that reads as success: a regex that
    // matches nothing makes every set comparison below compare two empty sets and pass.
    const scanned = scanLayerSpecs();
    expect(scanned.length, "the scan found no layer specs — the convention or the regex moved")
      .toBeGreaterThan(8);
  });

  it("names every literal-id layer in the ledger, and ledgers no layer that does not exist", () => {
    // BOTH DIRECTIONS ON PURPOSE. Unledgered code is the failure this file was built for; a
    // ledgered entry with no code is how the ledger rots into a description of a globe from
    // several commits ago, which is the state that makes a reader stop trusting it.
    const scanned = scanLayerSpecs().filter((spec) => spec.literal);
    const inSource = new Set(scanned.map((spec) => spec.id));
    const dynamicIds = new Set(CAP_POLES.map(capLayerId));
    const ledgered = new Set([...ratifiedLayerIds()].filter((id) => !dynamicIds.has(id)));

    const unledgered = [...inSource].filter((id) => !ledgered.has(id));
    expect(unledgered, "these layers put pixels on the globe and nobody approved them — add them "
      + "to paintedLayers.ts AFTER the maintainer has seen them on a globe").toEqual([]);
    const missing = [...ledgered].filter((id) => !inSource.has(id));
    expect(missing, "paintedLayers.ts names layers no spec in the source builds").toEqual([]);
  });

  it("covers the one layer whose id is not a literal, by asking the function that makes it", () => {
    // The polar caps are `custom` layers built as `polar-cap-${pole}`, so a literal-id scan cannot
    // see them. Executed rather than scanned, which is stronger than the scan and not weaker: this
    // fails if a third pole appears or the id spelling changes.
    for (const pole of CAP_POLES) {
      expect(ratifiedLayerIds(), `${capLayerId(pole)} is added but not ledgered`)
        .toContain(capLayerId(pole));
    }
  });

  it("has exactly one dynamic-id layer site, so a second cannot arrive unseen", () => {
    // The residual hole in the scan, pinned to its current size. A new spec with a computed id
    // fails here — which is the signal to give it an executable check of its own, like the caps
    // above, rather than to raise this number.
    const dynamic = scanLayerSpecs().filter((spec) => !spec.literal);
    expect(dynamic.map((spec) => `${spec.file}: ${spec.id}`)).toEqual(["lib/polarCaps.ts: opts.layerId"]);
  });

  it("reads a spec written either way round, on text built for the purpose", () => {
    // The positive control for the reverse-order branch, BUILT rather than borrowed: nothing in the
    // repo is written type-first, so borrowing a case from the live source would test the branch
    // that already runs and leave the other one dead behind a completeness claim.
    const idFirst = specsIn('{ id: "a-layer", type: "line", paint: {} }', "built.ts");
    const typeFirst = specsIn('{ type: "line", id: "a-layer", paint: {} }', "built.ts");
    expect(idFirst).toEqual(typeFirst);
    expect(idFirst).toEqual([{ id: "a-layer", literal: true, type: "line", file: "built.ts" }]);
    // A computed id is kept verbatim and marked dynamic, which is what the site count relies on.
    expect(specsIn("{ id: opts.layerId, type: \"custom\" }", "built.ts")[0])
      .toMatchObject({ id: "opts.layerId", literal: false });
    // A SOURCE spec carries no `id`, which is the whole reason the scan pairs the two fields.
    expect(specsIn('{ type: "raster", tiles: [] }', "built.ts")).toEqual([]);
  });

  it("cannot be evaded by writing the fields in the other order", () => {
    // Every layer-only type token has to belong to a spec the scan read. If one does not, a layer
    // exists that this file cannot see — and the set comparison above would pass while blind to it.
    const scanned = scanLayerSpecs();
    for (const file of sourceFiles()) {
      const source = readFileSync(file, "utf8");
      const relative = path.relative(SRC_DIR, file);
      for (const type of LAYER_ONLY_TYPES) {
        const tokens = source.split(`type: "${type}"`).length - 1;
        const paired = scanned.filter((spec) => spec.file === relative && spec.type === type).length;
        expect(paired, `${relative} writes type: "${type}" ${tokens}x but the scan paired ${paired} `
          + "— a layer spec is written in a shape this guard cannot read").toBe(tokens);
      }
    }
  });
});

describe("a layer the ledger says paints NOTHING really paints nothing", () => {
  /** The factory per invisible layer, so the claim is checked against the spec that ships rather
   *  than against a sentence next to it. A `never` entry with no factory here fails below. */
  const INVISIBLE_SPECS: Record<string, () => { paint?: Record<string, unknown> }> = {
    "country-hit": () => hitLayer(["==", ["get", "ADMIN"], "nowhere"], VECTOR_BINDING.hit),
    "feature-fill": featureFillLayer,
    "feature-linear-hit": featureLinearHitLayer,
  };

  it("checks every one of them, rather than whichever ones someone remembered", () => {
    expect(new Set(Object.keys(INVISIBLE_SPECS))).toEqual(neverPaintingLayerIds());
  });

  it("holds each at a literal zero, so `never` cannot decay into a promise", () => {
    // THE HALF THAT MAKES `timing` MACHINE-CHECKED. Mars's fill was painted once already; a
    // ledger entry saying it is invisible is worth nothing if the opacity beside it can drift.
    for (const [id, build] of Object.entries(INVISIBLE_SPECS)) {
      const paint = build().paint ?? {};
      const opacity = Object.entries(paint).find(([key]) => key.endsWith("-opacity"));
      expect(opacity, `${id} is ledgered as painting nothing but declares no opacity at all`)
        .toBeDefined();
      expect(opacity?.[1], `${id} is ledgered as painting nothing and paints ${opacity?.[1]}`)
        .toBe(0);
    }
  });
});

describe("the ledger is readable as a record of what was approved", () => {
  it("describes the PIXELS of every layer, not its code", () => {
    // A ledger whose entries say "the fill layer" tells a reviewer nothing they could have checked
    // against a screen, and this file is only worth its cost if a reader can compare it to a globe.
    for (const layer of RATIFIED_LAYERS) {
      expect(layer.looks.length, `${layer.id} has no description of what it looks like`)
        .toBeGreaterThan(20);
    }
  });

  it("names bodies that exist", () => {
    for (const layer of RATIFIED_LAYERS) {
      if (layer.bodies === "all") continue;
      expect(layer.bodies.length, `${layer.id} lists no bodies and is not "all"`).toBeGreaterThan(0);
    }
  });
});
