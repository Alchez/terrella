// Display formatting shared by every diagnostic read-out. Extracted for CONSISTENCY, not for
// brevity: how many decimal places a megabyte gets is a display policy, and a panel where one line
// says `384 MB` while the next says `383.9 MB` reads as broken rather than precise. Two copies of
// this rule already existed (glDiagnostics, demCacheLine) and the perf snapshot work would have
// made a third.

/** Bytes as whole mebibytes, no unit suffix — callers place the "MB" so they can write `12+3 MB`. */
export function megabytes(bytes: number): string {
  return (bytes / (1024 * 1024)).toFixed(0);
}
