/**
 * What the page knew when the GPU died — and whether it genuinely came back.
 *
 * THE INCIDENT THIS EXISTS FOR
 * ----------------------------
 * A 2K tab froze with Chrome's GPU process holding 6.2 GB and crash-looping (4m31s old, no NVRM
 * Xid, so the driver was healthy — Chrome killed itself). Four context losses survived reloads.
 * Afterwards the map was a ZOMBIE: `isContextLost()` read false, so by every check we had the
 * context was fine, while `map.style` carried zero sources and zero layers and the projection was
 * gone, which made every render and every `unproject` throw. The page showed no error at all,
 * because our own `webglcontextrestored` handler cleared the "could not recover" notice the
 * instant the event fired — the event says the BROWSER returned a context, not that MapLibre
 * rebuilt anything on top of it. "Restored" is not "recovered", and conflating them is what made
 * a total failure look like a working page that had stopped moving.
 *
 * WHY THE STATE IS SAMPLED WHILE HEALTHY, NOT AT THE MOMENT OF LOSS
 * -----------------------------------------------------------------
 * The obvious design — read everything inside the `webglcontextlost` handler — was built first and
 * is WRONG, which a live forced loss showed within a minute: it logged `no sources · caps none`
 * on a map that had five sources and both caps resident a tenth of a second earlier. MapLibre
 * registers its own canvas listener in the `Map` constructor, so by the time our listener runs the
 * style has already been torn down. The proof is in the console ordering — MapLibre's own
 * "Custom layer with id 'polar-cap-north' cannot be restored" warnings print BEFORE our line.
 *
 * So the loss handler cannot be where the reading happens. The state is sampled on `idle` instead
 * and the last healthy sample is what gets reported, labelled with its age. A snapshot that always
 * reads empty is worse than no snapshot: it is indistinguishable from a genuine finding.
 *
 * WHAT THIS DELIBERATELY DOES NOT CLAIM
 * -------------------------------------
 * None of this measures VRAM. No web API reports it, and the 6.2 GB figure came from `nvidia-smi`
 * against a GPU process shared by every tab — an upper bound on our share, not a measurement of
 * it. What this module records is the state a later attribution pass has to be checked against,
 * plus the one VRAM term we can name exactly because we allocate it ourselves: the polar cap
 * textures, at 256 MiB each when both sit on the 8192 rung.
 */

import { CAP_POLES, capLayerId } from "./polarCaps";
import { summariseDemCache, type DemCacheSummary, type TileManagerLike } from "./tileCacheBudget";

/** How long a loss may go unrecovered before we tell the reader to reload.
 *
 *  MapLibre handles the ordinary loss unaided, so announcing one immediately would tell people to
 *  reload a map that is about to heal a second later. */
export const GL_RESTORE_GRACE_MS = 4000;

/** How long to keep re-checking after `webglcontextrestored` before declaring the restore failed.
 *
 *  The style is re-applied asynchronously, so the first read after the event is legitimately empty
 *  on a perfectly healthy recovery. A single delayed check has to guess that delay; polling to a
 *  deadline does not, and passes on the first clean read. */
export const GL_RECOVERY_VERIFY_MS = 3000;

/** Gap between recovery checks. Cheap reads (object key counts), so the rate is set by how fast we
 *  want to retract a wrongly-shown notice, not by cost. */
export const GL_RECOVERY_POLL_MS = 250;

/** How long to keep watching AFTER the notice has gone up.
 *
 *  A forced loss recovered once at roughly six seconds — past the verify deadline, so the notice
 *  was already showing and nothing ever took it down. "Could not recover" left over a working
 *  globe is the same defect as a dead globe with no message, pointed the other way, so the watch
 *  outlives its own verdict and retracts it if the map comes back. Bounded rather than endless
 *  because on a genuinely dead map (measured: `isContextLost()` still true a full minute on, after
 *  a second explicit `restoreContext()`) there is nothing left to wait for. */
export const GL_RECOVERY_CEILING_MS = 60_000;

/** How many losses one page life may recover from before it stops trying and asks for a reload.
 *
 *  Two, so an ordinary transient loss heals silently and a SECOND one still gets the benefit of the
 *  doubt, while the third is treated as a pattern. The incident logged four. */
export const GL_RECOVERY_ATTEMPT_LIMIT = 2;

/** How long a map must run healthy for an earlier loss to stop counting against it.
 *
 *  Without this the budget is a lifetime quota: a map left open all day would refuse to recover at
 *  tea time because of two losses that morning, which are no evidence about the GPU's state now. */
export const GL_LOSS_AMNESTY_MS = 5 * 60_000;

/**
 * Losses still counting against the recovery budget once the new one is charged.
 *
 * A sliding window, oldest dropped: anything further back than the amnesty is not evidence about
 * this loss. Pure and total — the caller keeps the returned array and hands it back next time.
 */
export function chargeLoss(previousLosses: readonly number[], lostAtMs: number): number[] {
  const stillCounting = previousLosses.filter(
    (previous) => lostAtMs - previous <= GL_LOSS_AMNESTY_MS,
  );
  return [...stillCounting, lostAtMs];
}

/**
 * Recover from this loss, or stop and ask for a reload?
 *
 * WHY THIS IS NOT CONDITIONED ON THE CAUSE
 * ----------------------------------------
 * It cannot be. The web platform reports no reason for a context loss, which was measured rather
 * than assumed: `WebGLContextEvent.statusMessage` is defined on the prototype and came back the
 * empty string on a forced loss, and no `browser said:` segment ever appeared across the incident's
 * real ones. `getGraphicsResetStatus` is not exposed on `WebGL2RenderingContext` and `EXT_robustness`
 * is absent. So "was this transient?" has no direct answer.
 *
 * RECURRENCE IS THE SIGNAL WE ACTUALLY HAVE
 * -----------------------------------------
 * A single loss is usually transient — a driver reset, a suspended tab, a recycled GPU process —
 * and recovering costs the user nothing. Losing the context repeatedly in a few minutes is the
 * signature of a machine or a page in trouble, and rebuilding the same working set into it just
 * feeds the loop. That is precisely the incident's shape: four losses that survived reloads, each
 * silently rebuilding an uncapped map.
 */
export function recoveryVerdict(chargedLosses: readonly number[]): "recover" | "give-up" {
  return chargedLosses.length > GL_RECOVERY_ATTEMPT_LIMIT ? "give-up" : "recover";
}

/** The sentence for the log when the budget is spent — states the count and the window, because
 *  "gave up" without either reads like a bug rather than a policy. */
export function describeGiveUp(chargedLosses: readonly number[]): string {
  const windowMinutes = Math.round(GL_LOSS_AMNESTY_MS / 60_000);
  return (
    `[gl] ${chargedLosses.length} context losses within ${windowMinutes} min — not rebuilding ` +
    `again. Repeated loss means the GPU or this page is in trouble, and recovering into the same ` +
    `working set feeds the loop. Reload to start clean.`
  );
}

/** Bytes one polar cap texture occupies on the GPU at a given rung: RGBA, no mipmaps.
 *
 *  8192² × 4 = 268,435,456 B = 256 MiB, and desktop takes the top rung for BOTH poles
 *  (`capTextureBudget(false)` is `Infinity`) — so 512 MiB of VRAM is ours, by design, before
 *  MapLibre allocates anything at all. It is the largest single term anyone has been able to name
 *  in the 6.2 GB, which is exactly why it is reported at the moment of loss. */
export function capTextureBytes(rungPx: number): number {
  return rungPx * rungPx * 4;
}

/**
 * The subset of MapLibre's `Map` this module reads.
 *
 * Structural rather than the real `Map` so the tests can build a fake, and every field here is
 * declared in MapLibre's own `.d.ts` (`Map.style`, `Style._layers`, `Style._order`,
 * `Style.tileManagers`, `Style.projection`, `Map.painter`) — underscored, but typed, so none of
 * this needs a cast.
 */
export interface MapLike {
  getCanvas?: () => HTMLCanvasElement;
  getLayer?: (layerId: string) => unknown;
  getTerrain?: () => unknown;
  painter?: unknown;
  style?: {
    _layers?: Record<string, unknown>;
    _order?: readonly string[];
    tileManagers?: Record<string, TileManagerLike>;
    projection?: unknown;
  };
}

/** Per-source tile occupancy at a moment in time.
 *
 *  `counts` is null — never zero — when MapLibre's internals moved and the read failed. A source
 *  holding no tiles and a source we can no longer read are different facts, and the second one is
 *  the only one that means this instrument is broken. */
export interface SourceTileCount {
  source: string;
  counts: DemCacheSummary | null;
}

/**
 * Tile occupancy for EVERY source, not just the terrain one.
 *
 * The DEM cache is the source we root-caused, but it is not the only one holding megabyte-scale
 * tiles: relief tiles are 512 px WebP decoded to RGBA the same way, and they get their own
 * view-dependent cache. A loss snapshot that reported only the source we already suspected would
 * confirm the hypothesis it was built from and see nothing else.
 *
 * Byte totals come from `DEMData`, so a raster source correctly reports zero bytes against real
 * slot counts — that is the summary being accurate about what it can weigh, not a failed read.
 */
export function tileCountsBySource(
  tileManagers: Record<string, TileManagerLike> | undefined,
): SourceTileCount[] {
  if (!tileManagers || typeof tileManagers !== "object") return [];
  return Object.keys(tileManagers)
    .sort()
    .map((source) => ({ source, counts: summariseDemCache(tileManagers[source]) }));
}

/** Which cap texture each pole has on the GPU. `loadedRungPx` is null when the layer is absent
 *  (`?nocaps`, or before `style.load` has run) and 0 while the first fetch is still in flight. */
export interface CapLayerState {
  layerId: string;
  loadedRungPx: number | null;
}

/**
 * Read the live cap rungs off the map.
 *
 * MapLibre wraps a `custom` layer in a `CustomStyleLayer` whose `implementation` field is the
 * object we handed to `addLayer` — declared public in the `.d.ts`, so the cap's own `loadedRungPx`
 * is reachable without a cast and without a second registry to drift from the first.
 */
export function capLayerStates(
  map: MapLike | undefined,
  layerIds: readonly string[] = CAP_POLES.map(capLayerId),
): CapLayerState[] {
  return layerIds.map((layerId) => {
    const layer = map?.getLayer?.(layerId);
    const implementation =
      layer && typeof layer === "object" && "implementation" in layer
        ? (layer as { implementation?: unknown }).implementation
        : undefined;
    const loadedRungPx =
      implementation && typeof implementation === "object" && "loadedRungPx" in implementation
        ? (implementation as { loadedRungPx?: unknown }).loadedRungPx
        : undefined;
    return { layerId, loadedRungPx: typeof loadedRungPx === "number" ? loadedRungPx : null };
  });
}

/** Total cap texture bytes resident on the GPU across both poles. */
export function totalCapTextureBytes(states: readonly CapLayerState[]): number {
  return states.reduce(
    (total, state) => total + (state.loadedRungPx ? capTextureBytes(state.loadedRungPx) : 0),
    0,
  );
}

export interface GlLossSnapshot {
  /** `sampled` is the routine idle reading; the other two are taken from the matching event. */
  phase: "lost" | "restored" | "sampled";
  /** MapLibre's own version. Every canary in this repo is version-sensitive, and a snapshot that
   *  does not say which library produced it is one bump away from being unreadable. */
  libraryVersion: string | null;
  /** Tiles this camera needs, from `Map.coveringTiles` — a lower bound, see its docstring. */
  coveringTiles: number | null;
  msSinceLoad: number;
  cssWidth: number;
  cssHeight: number;
  bufferWidth: number;
  bufferHeight: number;
  devicePixelRatio: number;
  /** The browser's own reason, when it gives one — `WebGLContextEvent.statusMessage`. Often empty,
   *  and empty is worth recording as such rather than omitting the field. */
  statusMessage: string | null;
  terrainOn: boolean;
  sources: SourceTileCount[];
  caps: CapLayerState[];
  capTextureBytes: number;
}

export interface GlLossSnapshotOptions {
  phase: "lost" | "restored" | "sampled";
  msSinceLoad: number;
  devicePixelRatio: number;
  statusMessage?: string | null;
  capLayerIds?: readonly string[];
  /** Injected rather than read here: `getVersion` is a module-level export of `maplibre-gl`, and
   *  importing the library into a pure module would drag the whole bundle into every test. */
  libraryVersion?: string | null;
  /** From `terrainCoveringTileCount` — injected for the same reason the version is. */
  coveringTiles?: number | null;
}

/**
 * Everything worth knowing about the page at the instant the context died.
 *
 * `devicePixelRatio` and the clock are injected rather than read from globals so this is testable
 * and so the DPR recorded is the one the map was actually rendering at — the page can lower it
 * (the degradation ladder's second rung), and `window.devicePixelRatio` would keep reporting the
 * display's, which is the wrong number in precisely the situation this runs in.
 */
export function snapshotGlLoss(
  map: MapLike | undefined,
  options: GlLossSnapshotOptions,
): GlLossSnapshot {
  const canvas = map?.getCanvas?.();
  const caps = capLayerStates(map, options.capLayerIds);
  return {
    phase: options.phase,
    libraryVersion: options.libraryVersion ?? null,
    coveringTiles: options.coveringTiles ?? null,
    msSinceLoad: options.msSinceLoad,
    cssWidth: canvas?.clientWidth ?? 0,
    cssHeight: canvas?.clientHeight ?? 0,
    bufferWidth: canvas?.width ?? 0,
    bufferHeight: canvas?.height ?? 0,
    devicePixelRatio: options.devicePixelRatio,
    statusMessage: options.statusMessage ?? null,
    terrainOn: Boolean(map?.getTerrain?.()),
    sources: tileCountsBySource(map?.style?.tileManagers),
    caps,
    capTextureBytes: totalCapTextureBytes(caps),
  };
}

function megabytes(bytes: number): string {
  return (bytes / (1024 * 1024)).toFixed(0);
}

/** The state itself, with no event or timestamp attached.
 *
 *  Split out because the reading and the event that prompted it can come from different moments —
 *  the loss report carries the LOSS's time and the SAMPLE's numbers, and stapling the sample's own
 *  "restored" prefix onto a loss line (as the first live run did) mislabels it. */
export function glStateLine(snapshot: GlLossSnapshot): string {
  const sources = snapshot.sources
    .map(({ source, counts }) => {
      if (counts === null) return `${source} unreadable`;
      const bytes =
        counts.cachedBytes + counts.inViewBytes > 0
          ? ` ${megabytes(counts.cachedBytes)}+${megabytes(counts.inViewBytes)} MB`
          : "";
      return `${source} ${counts.cachedTiles}/${counts.maxSlots} slots +${counts.inViewTiles} view${bytes}`;
    })
    .join(" · ");
  const caps = snapshot.caps
    .map((cap) => `${cap.layerId.replace("polar-cap-", "")} ${cap.loadedRungPx ?? "none"}`)
    .join("/");
  const status = snapshot.statusMessage ? ` · browser said: ${snapshot.statusMessage}` : "";
  const version = snapshot.libraryVersion ? `maplibre ${snapshot.libraryVersion} · ` : "";
  const covering =
    snapshot.coveringTiles === null ? "" : ` · camera needs ${snapshot.coveringTiles} tiles`;
  return (
    version +
    `canvas ${snapshot.cssWidth}x${snapshot.cssHeight} css / ` +
    `${snapshot.bufferWidth}x${snapshot.bufferHeight} buffer @ DPR ${snapshot.devicePixelRatio} · ` +
    `terrain ${snapshot.terrainOn ? "on" : "off"} · ` +
    `caps ${caps} = ${megabytes(snapshot.capTextureBytes)} MB · ` +
    (sources || "no sources") +
    covering +
    status
  );
}

/** One greppable line. The structured snapshot goes to the console alongside it, so this trades
 *  completeness for being readable in a scrollback a week later. */
export function formatGlLoss(snapshot: GlLossSnapshot): string {
  return (
    `[gl] context ${snapshot.phase} at ${(snapshot.msSinceLoad / 1000).toFixed(1)}s · ` +
    glStateLine(snapshot)
  );
}

/** Did this snapshot read anything at all?
 *
 *  False is the signature of a read taken after MapLibre tore the style down — the case the loss
 *  handler always hits. Distinguishing it is the whole reason the healthy sample exists. */
export function snapshotHasContent(snapshot: GlLossSnapshot): boolean {
  return snapshot.sources.length > 0;
}

/**
 * What to actually log when the context is lost.
 *
 * Prefers the loss-time read and falls back to the last healthy sample, ALWAYS saying which it is
 * and how old it is. Never silently substitutes one for the other: a stale reading presented as a
 * live one is the failure this whole module was built to stop being possible.
 */
export function describeLoss(
  atLoss: GlLossSnapshot,
  lastHealthy: GlLossSnapshot | null,
): string {
  if (snapshotHasContent(atLoss)) return formatGlLoss(atLoss);
  if (lastHealthy === null) {
    return `${formatGlLoss(atLoss)} · nothing readable at loss time and no earlier sample`;
  }
  const ageSeconds = (atLoss.msSinceLoad - lastHealthy.msSinceLoad) / 1000;
  // The LOSS's time with the SAMPLE's numbers, and the gap between them stated outright. Taking
  // the sample's own prefix instead labelled a loss report "context restored", which is the sort
  // of quietly wrong line someone would later reason from.
  return (
    `[gl] context ${atLoss.phase} at ${(atLoss.msSinceLoad / 1000).toFixed(1)}s · ` +
    `${glStateLine(lastHealthy)} · READ ${ageSeconds.toFixed(1)}s EARLIER ` +
    `(MapLibre had already torn the style down by the time this handler ran)`
  );
}

/**
 * Is the map actually usable again, or did only the CONTEXT come back?
 *
 * Returns null when everything needed to render is present, otherwise the reason. The checks are
 * the failure modes the incident actually produced, in the order that makes the most fundamental
 * one report first — not a guess at what else might break, because a speculative check that fires
 * on a healthy page trains the reader to ignore the one that matters.
 *
 * Deliberately absent: an `isContextLost()` probe. `webglcontextrestored` fires precisely because
 * the browser handed a context back, so that check can only ever pass here, and reaching it via
 * `canvas.getContext()` would CREATE a context on a canvas that had none — an allocation, on the
 * one code path where the GPU is already known to be in trouble.
 */
export function restoreFault(map: MapLike | undefined): string | null {
  if (!map || typeof map !== "object") return "no map";
  const style = map.style;
  if (!style || typeof style !== "object") {
    return "the context came back but MapLibre never rebuilt the style";
  }
  if (style.projection === undefined || style.projection === null) {
    return "the style has no projection — every render and every unproject will throw";
  }
  if (map.painter === undefined || map.painter === null) {
    return "the painter was never rebuilt";
  }
  const layerCount = style._layers ? Object.keys(style._layers).length : 0;
  const sourceCount = style.tileManagers ? Object.keys(style.tileManagers).length : 0;
  const orderCount = style._order?.length ?? 0;
  if (layerCount === 0 || orderCount === 0 || sourceCount === 0) {
    return (
      `the style came back empty — ${sourceCount} sources, ${layerCount} layers, ` +
      `${orderCount} in draw order`
    );
  }
  return null;
}

/**
 * MapLibre's own signal that a GPU context could not be created at all.
 *
 * `GPUInitializationError` is thrown through the map's `error` event and carries the requested
 * canvas attributes plus, when the browser supplies one, the `webglcontextcreationerror`
 * `statusMessage`. It is the failure that follows a GPU process that has died for good: not a
 * loss to recover from, but a context that will never exist. We inferred that state from a
 * four-second timeout before; MapLibre names it.
 *
 * Typed structurally so this stays testable without constructing a real MapLibre error — the
 * `instanceof GPUInitializationError` branch lives at the call site, which is the only place that
 * has the class.
 */
export interface GpuInitializationFailureLike {
  statusMessage?: string | null;
  requestedAttributes?: unknown;
}

export function formatGpuInitFailure(error: GpuInitializationFailureLike): string {
  const reason = error.statusMessage ? `: ${error.statusMessage}` : " (browser gave no reason)";
  return `[gl] the GPU context could not be created${reason} — this is not a recoverable loss`;
}
