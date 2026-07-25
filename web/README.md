# Terrella — frontend (`web/`)

The Astro site: Tier-1 gallery, country detail pages, About, and the `/globe` route (a MapLibre
globe over the raster tile pyramid), with a capability probe that auto-steers between tiers.

## First-run setup (fresh checkout / worktree)

`web/` depends on three things that are **not** in git — they are generated or machine-specific,
so a fresh clone or worktree has none of them and **every route 500s (`FailedToLoadModuleSSR`)
until all three exist**. In order:

1. **`.env`** — store paths for the dev middleware, which serves `/heroes`, `/borders` and
   `/tiles` straight off disk (the static build never reads them; a deploy points the site at
   object storage instead, via the `PUBLIC_*_BASE` vars the same template documents).
   Copy the template and set each var to an absolute local path — there is no fallback, an unset
   var fails the dev server with a clear message:
   ```sh
   cp .env.example .env
   # edit HERO_STORE / BORDERS_STORE / PMTILES_STORE, e.g. PMTILES_STORE=/path/to/maps/data/work/planet_tiles
   ```
   `.env` is gitignored (machine-specific), which is why it does not travel with the checkout.

2. **Dependencies**:
   ```sh
   pnpm install
   ```

3. **The gallery manifest** `src/data/countries.json` — generated from the hero-variant store,
   and imported by all three pages (index, `[slug]`, globe), so its absence 500s the whole site.
   Also gitignored. Regenerate it whenever heroes are re-rendered:
   ```sh
   ../.venv/bin/python scripts/gen_manifest.py --out src/data/countries.json
   ```
   Requires the hero WebP variants and the Natural Earth admin-0 shapefile to already exist.

Then start the server (add `--host` to reach it from another device on your LAN, e.g. a phone):
```sh
pnpm dev --host
```

> If you rebuilt the tile pyramid while the server was running, the browser may hold stale tiles
> and a failed SSR import can stay cached — a server restart plus a hard reload clears both.

## 🚀 Project Structure

Inside of your Astro project, you'll see the following folders and files:

```text
/
├── public/
├── src/
│   └── pages/
│       └── index.astro
└── package.json
```

Astro looks for `.astro` or `.md` files in the `src/pages/` directory. Each page is exposed as a route based on its file name.

There's nothing special about `src/components/`, but that's where we like to put any Astro/React/Vue/Svelte/Preact components.

Any static assets, like images, can be placed in the `public/` directory.

## 🧞 Commands

All commands are run from the root of the project, from a terminal:

| Command                   | Action                                           |
| :------------------------ | :----------------------------------------------- |
| `pnpm install`             | Installs dependencies                            |
| `pnpm dev`             | Starts local dev server at `localhost:4321`      |
| `pnpm build`           | Build your production site to `./dist/`          |
| `pnpm preview`         | Preview your build locally, before deploying     |
| `pnpm astro ...`       | Run CLI commands like `astro add`, `astro check` |
| `pnpm astro -- --help` | Get help using the Astro CLI                     |

## 👀 Want to learn more?

Feel free to check [our documentation](https://docs.astro.build) or jump into our [Discord server](https://astro.build/chat).
