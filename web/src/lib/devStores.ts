// Where the dev server finds one body's packaged tile archives on disk.
//
// NODE-ONLY. `astro.config.ts` imports this and nothing in the browser can: a disk layout is not a
// fact about the page. It lives in src/lib/ anyway because that is where the config's other
// contracts already live (reliefTiles, terrainSource, countryTiles) — and because a config file
// cannot be unit-tested while a module it imports can.
//
// WHY A CONVENTION RATHER THAN ONE ENV VAR PER ARCHIVE. Three variables used to spell out three
// absolute paths, one per pyramid, and that shape does not survive a second planet: each body
// multiplies the count, and every one of them is machine-specific state a fresh checkout must be
// told before the site will draw anything. The pipeline already writes each archive somewhere
// derivable — `pipeline/bodies.py`'s `work_dir(body, stage)` — so the dev server can COMPUTE what
// it used to be told, and the only thing left to configure is the root the pipeline itself takes
// from `MAPS_DATA`.
//
// THE ROOT IS THE PIPELINE'S OWN SEAM, NOT A SECOND ONE. `pipeline/paths.py` resolves the data
// store as `MAPS_DATA`, falling back to `<repo>/data`; this resolves it identically, from the same
// variable. A dev-only name would let the two halves of one machine disagree about where the data
// is — and the symptom of that disagreement is an archive that is "missing", which is precisely the
// error this module reports.
//
// FAIL-LOUD IS PRESERVED, AND MOVED. The old rule was that an unset store variable 500s with
// instructions rather than defaulting, because a store pointing at the wrong place serves the wrong
// pixels under a 200. A derived path cannot be unset, so the check becomes "no archive is there",
// answered with the path that was looked at, the stage that writes it, and the one variable that
// relocates the lot.

import path from "node:path";

import type { BodySlug } from "./bodies";

/** The three pyramids the dev middleware answers out of, named by what they draw rather than by
 *  their file names — the router dispatches on URL prefix, and this is that dispatch's other half. */
export type ArchiveKind = "relief" | "terrain" | "countries";

/** One archive's place in the pipeline's work tree, and the stage that puts it there. */
interface ArchiveLocation {
  /** Directory name under a body's work tree — the `stage` argument of `bodies.work_dir`. */
  stage: string;
  /** The packaged archive inside that directory. Also what error messages call it. */
  file: string;
  /** The pipeline entry point that writes it, quoted verbatim into the missing-archive message.
   *  A dev server that says only "not found" leaves the reader to go looking for the stage; the
   *  whole cost of being useful here is one string per archive. */
  producedBy: string;
}

/** Every archive, and where its own pipeline stage leaves it.
 *
 *  A RECORD OVER THE KIND UNION, so a fourth pyramid is a compile error here rather than a route
 *  that silently resolves to `undefined` and reads a path spelled "undefined/undefined". */
const ARCHIVES: Record<ArchiveKind, ArchiveLocation> = {
  relief: {
    stage: "planet_tiles",
    file: "planet.pmtiles",
    producedBy: "pipeline/tile/shade_planet.py, then pipeline/tile/pack_pmtiles.py",
  },
  terrain: {
    stage: "planet_terrain",
    file: "terrain.pmtiles",
    producedBy: "pipeline/tile/terrain_rgb.py, then pipeline/tile/pack_pmtiles.py",
  },
  countries: {
    stage: "planet_countries",
    file: "countries.pmtiles",
    producedBy: "pipeline/compose/countries_pmtiles.py",
  },
};

/** Directory segment a body's outputs nest under, restating `Body.path_prefix` in
 *  `pipeline/bodies.py`.
 *
 *  Earth's is empty there and empty here, for the reason that module gives: its work tree already
 *  holds ~100 GB at the un-prefixed paths, and moving it would make every stage read as missing and
 *  re-derive a whole planet to produce identical pixels. A body that nests pays no such cost.
 *
 *  THE COPY IS SELF-CHECKING, WHICH IS WHY NO TEST PINS IT. A prefix that disagrees with the
 *  pipeline names a directory the pipeline never wrote, so the first tile request 500s with the
 *  path it looked at. Drift here cannot be silent and cannot reach a served pixel — unlike a copied
 *  colour or radius, which renders. `Record<BodySlug, string>` is what forces a new body to answer. */
const WORK_PREFIX: Record<BodySlug, string> = {
  earth: "",
};

/** Store variables the dev server no longer reads. Kept by name so a checkout that still sets one
 *  is told, rather than left wondering why editing it changes nothing. */
const RETIRED_STORE_VARS = ["PMTILES_STORE", "TERRAIN_PMTILES_STORE", "COUNTRIES_PMTILES_STORE"];

/** The data store the pipeline writes into, as an absolute path.
 *
 *  Takes the environment rather than reading `process.env`, because the dev config gets its values
 *  from Vite's `loadEnv` (which merges `web/.env` over the process environment) and a module that
 *  read the process directly would ignore the file the checkout is actually configured by.
 *
 *  A blank value counts as unset — an empty line in a `.env` should behave like no line at all,
 *  not like the filesystem root. Same rule `resolveAssetBase` applies to the base URLs. */
export function resolveDataRoot(
  env: Record<string, string | undefined>,
  repoRoot: string,
): string {
  const configured = env.MAPS_DATA?.trim();
  return configured ? path.resolve(configured) : path.resolve(repoRoot, "data");
}

/** Absolute path to one body's archive of `kind`, under an already-resolved data root.
 *
 *  Mirrors `bodies.work_dir(body, stage) / file`. The empty prefix collapses, which is what keeps
 *  Earth's archives exactly where they have always been. */
export function archivePath(dataRoot: string, body: BodySlug, kind: ArchiveKind): string {
  return path.join(dataRoot, "work", WORK_PREFIX[body], ARCHIVES[kind].stage, ARCHIVES[kind].file);
}

/** What an archive is called, for the messages that name one. */
export function archiveFileName(kind: ArchiveKind): string {
  return ARCHIVES[kind].file;
}

/** The 500 body for a request whose archive is not on disk.
 *
 *  Says the three things the reader needs and cannot guess: where it looked, what would have put a
 *  file there, and how to point the server somewhere else. */
export function describeMissingArchive(
  body: BodySlug,
  kind: ArchiveKind,
  expected: string,
  dataRoot: string,
): string {
  return [
    `No ${body} ${kind} archive at ${expected}.`,
    `It is written by ${ARCHIVES[kind].producedBy}.`,
    `The dev server derives that path from the data store at ${dataRoot} — set MAPS_DATA to`,
    "relocate it (the same variable pipeline/paths.py reads), or run the stage above.",
  ].join("\n");
}

/** A warning for store variables that are still set but no longer read, or null when none are.
 *
 *  Worth saying out loud exactly once at startup: a variable that used to steer the server and now
 *  does nothing is the kind of state someone edits, restarts, and then disbelieves the result of. */
export function describeRetiredStoreVars(env: Record<string, string | undefined>): string | null {
  const stillSet = RETIRED_STORE_VARS.filter((name) => env[name]?.trim());
  if (stillSet.length === 0) return null;
  return (
    `web/.env sets ${stillSet.join(", ")}, which the dev server no longer reads — archive paths ` +
    "are derived from the pipeline's work tree now (MAPS_DATA relocates it). Safe to delete."
  );
}
