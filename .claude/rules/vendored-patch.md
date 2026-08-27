---
paths:
  - "web/patches/**"
  - "web/pnpm-workspace.yaml"
  - "web/package.json"
---

# Touching a vendored dependency patch

**Never edit `node_modules` in place.** pnpm hardlinks package files from a global content-addressed store, so a file there usually has 2+ hardlinks and writing to it corrupts the copy every other project on this machine resolves.

- **The safe workflow:** `pnpm patch <name>@<exact-version>` prints a temp dir — edit *there* — then `pnpm patch-commit <that-dir>` writes `patches/<name>@<version>.patch` and records it. **pnpm 10 puts `patchedDependencies` in `pnpm-workspace.yaml`, not `package.json`**, which is where to look when it seems to have vanished.
- **Confirm `patches/` is tracked** — `git check-ignore -v` on it. A patch missing from the repo means a fresh clone silently builds unpatched.
- **The patch is keyed to an EXACT version, so a bump installs clean and silently unpatched.** A version bump means re-cutting: drop `patchedDependencies`, delete `patches/`, bump, install, re-patch.
- **Apply the edit with a count assertion that refuses to run when the target is not unique** — `assert src.count(old) == 1` — and after writing, assert the new form appears exactly once and the old form zero times.
- **Guard the patch with a test, because a dropped patch is invisible.** It does not error, does not warn during a build, and changes nothing CI renders; it just removes whatever the patch bought. `vendoredPatches.test.ts` is that guard, and it carries a line number, so a bump costs an update there — known price, not a surprise.
- **Take only the part you verified.** An upstream PR often bundles an unrelated behaviour change with its fix; vendor the fix alone, one variable at a time, and record what you left out.
- **Prefer the smallest expression that survives minification.** This patch targets one 136,196-character minified line, so keep the inline ternary rather than mirroring upstream's newer method form — patching a minified class method is the more fragile shape.

Casebook: memory `patching-a-dependency`.
