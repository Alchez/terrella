## Development

**A fresh checkout/worktree needs three setup steps before the dev server will serve — see
[README.md](README.md) § First-run setup** (`.env`, `pnpm install`, generate
`src/data/countries.json`). Skipping any of them 500s every route with `FailedToLoadModuleSSR`.

When starting the dev server, use background mode:

```
astro dev --background
```

Manage the background server with `astro dev stop`, `astro dev status`, and `astro dev logs`.

**Restart it after touching `astro.config.ts` or `src/lib/reliefTiles.ts`.** Vite hot-reloads page
and lib code but *not* the config, so a changed tile contract leaves the running `/tiles` middleware
answering the old request shape while the freshly-compiled globe asks for the new one — every tile
404s and nothing says why.

## What this project actually is

Worth knowing before reaching for a framework guide: this is a **static Astro site with no UI
framework** — no React, Vue, Svelte, Tailwind, content collections or i18n. Pages are `.astro` with
plain CSS in `src/styles/`, and the only client-side JavaScript of consequence is the globe
(MapLibre GL, in `src/pages/globe.astro` and `src/lib/`). Astro's guides for those other stacks do
not apply here, which is why they are not linked.

The parts with real depth are documented where they live:

- **The tile request contract**, the diagnostic flags, and the baked-or-live rule → [README.md](README.md)
- **Deploying** — two separate deploys, and what the free tier buys → [DEPLOY.md](DEPLOY.md)

`src/lib/perf/` is a **lazy boundary**: no page may statically value-import from it, so a visitor
without `?perf` never downloads the instrument. `lazyBoundary.test.ts` enforces that for the whole
directory — if an import there fails a test, the rule is working, not broken.

**A new guard is not finished until a sabotage case proves it fails.** `uv run scripts/sabotage.py`
breaks each guard's subject in turn and requires the *named* test to catch it — 81 cases across
`pnpm test` and `pytest`. Add your case to its table, and `pytest` will tell you when a refactor moves
the string out from under it → [README.md](README.md) § Proving a guard is not vacuous.

## Documentation

Astro's own reference: https://docs.astro.build — the sections that apply to this codebase are
[routing and middleware](https://docs.astro.build/en/guides/routing/) and
[Astro components](https://docs.astro.build/en/basics/astro-components/).
