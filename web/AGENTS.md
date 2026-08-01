# Working in `web/`

Only the things the codebase does not tell you on its own.

## What `pnpm install` leaves undone

- **It fetches no browser.** The `playwright` package ships no install script, so the vitest `browser` project cannot launch until you run `pnpm exec playwright install --only-shell chromium`. Skip it and `pnpm test` passes fewer files than it collected, beside an unhandled launch error — which reads like a flake rather than a missing binary. `--only-shell` is coupled to `headless: true` in `vitest.config.ts`; CI runs the same command.
- **Three files a fresh checkout has none of**, because they are generated or machine-specific → [README.md](README.md) § First-run setup. Until all three exist every route 500s with `FailedToLoadModuleSSR`, which names none of them.

## The dev server

```sh
pnpm dev --background
```

- `--background` keeps it off the shell for the rest of the session. `astro dev stop`, `astro dev status` and `astro dev logs [--follow]` manage it afterwards.
- **`pnpm dev`, never bare `astro dev`.** `--host` lives in the package script, and it is what makes the globe reachable from a phone. Bare `astro dev --background` binds localhost, silently.
- **Restart it after touching `astro.config.ts` or anything it imports.** Vite hot-reloads page and lib code but not the config, so a changed tile contract leaves the running `/tiles` middleware answering the old request shape — every tile 404s and nothing says why.

## Norms no test can state

- **`src/lib/perf/` is a lazy boundary.** No page may statically value-import from it, so a visitor without `?perf` never downloads the instrument. An import there that fails `lazyBoundary.test.ts` means the rule is working, not broken.
- **A guard is not finished until a sabotage case proves it can fail.** `uv run scripts/sabotage.py` breaks each guard's subject in turn and requires the *named* test to catch it — `--list` prints the table. Add your case when you add a guard → [README.md](README.md) § Proving a guard is not vacuous.
