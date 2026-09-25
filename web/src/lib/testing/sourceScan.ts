/**
 * Slice one function out of a source file read with `?raw`.
 *
 * Source scanning is how the guards here reach code that cannot be imported: `Globe.astro`'s
 * script is a page, not a module. Matching a whole body rather than the file keeps an assertion
 * from passing on some other function that happens to mention the same names.
 */
export function functionBody(source: string, signature: string): string {
  const start = source.indexOf(signature);
  if (start < 0) throw new Error(`the source no longer contains \`${signature}\``);
  let depth = 0;
  for (let index = start + signature.length - 1; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    else if (source[index] === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(start, index + 1);
    }
  }
  throw new Error(`unbalanced braces after \`${signature}\``);
}
