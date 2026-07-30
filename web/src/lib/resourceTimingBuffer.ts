// Raising the Resource Timing entry buffer, which has to happen before the map requests anything.
//
// WHY THIS IS NOT IN lib/perf/ WITH THE REST OF THE INSTRUMENT
// -----------------------------------------------------------
// Everything else that reads these entries is `?perf`-only and loads lazily, and the rule for that
// directory is that no page may statically import from it. This cannot follow that rule: the
// default buffer is 250 entries, one fresh viewport at Full already costs 97 tile requests, and an
// entry dropped before the instrument mounts is gone for good — there is no API to read the limit
// back or to learn that anything was discarded. So the raise has to run in the same synchronous
// task as page setup, ahead of `new maplibregl.Map`, which a dynamic import cannot promise.
//
// It lives here, outside the instrument, because leaving it in `perfNetwork.ts` put that module's
// static import into the main bundle and dragged the whole 268-line instrument in with it — **+2,362
// bytes shipped to every visitor**, including the gallery tier that has no panel at all. Rollup
// places a module wherever it is statically imported, so a dynamic import of the same module later
// changes nothing; splitting the import site does not split the chunk. Splitting the MODULE does.
//
// Fifteen lines is the price of the ordering guarantee. The rest of the instrument stays lazy.

/**
 * Entries to retain. Deliberately generous: an entry is a small object, and the failure mode of too
 * few is a silent floor on every byte total rather than a visible error.
 */
export const RESOURCE_TIMING_BUFFER_SIZE = 3000;

/**
 * Set the buffer size and return it, so a caller can report the number it actually chose.
 *
 * Returning the size matters more than it looks: `bufferFull` downstream is `entries.length >= size`,
 * and that comparison is only meaningful against a size we picked rather than one we assumed. The
 * platform offers no getter.
 *
 * `target` is injected so this tests without a DOM.
 */
export function raiseResourceTimingBuffer(
  target: Pick<Performance, "setResourceTimingBufferSize">,
  size: number,
): number {
  target.setResourceTimingBufferSize(size);
  return size;
}
