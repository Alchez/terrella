// @ts-check
import { defineConfig, fontProviders } from 'astro/config';
import fs from 'node:fs';
import path from 'node:path';

// Where the rendered hero WebP variants live (the pipeline's asset store).
// Overridable via HERO_STORE for a different checkout / machine.
const HERO_STORE =
  process.env.HERO_STORE ||
  '/home/rohan/projects/maps/blender/renders/variants';

// Dev-only: serve /heroes/* straight from the external render store, so we never
// copy tens of GB of hero variants into public/ or the build. In production,
// nginx serves /heroes/ from the same store (see deploy notes). The build itself
// only emits HTML/CSS/JS that *references* /heroes/… — the images are external.
function heroDevServer() {
  return {
    name: 'hero-dev-server',
    /** @param {import('vite').ViteDevServer} server */
    configureServer(server) {
      server.middlewares.use('/heroes', (req, res, next) => {
        const rel = decodeURIComponent((req.url || '').split('?')[0]).replace(/^\/+/, '');
        const file = path.resolve(HERO_STORE, rel);
        if (!file.startsWith(path.resolve(HERO_STORE)) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
          return next();
        }
        const type = file.endsWith('.webp') ? 'image/webp'
          : file.endsWith('.png') ? 'image/png'
          : 'application/octet-stream';
        res.setHeader('Content-Type', type);
        res.setHeader('Cache-Control', 'no-cache');
        fs.createReadStream(file).pipe(res);
      });
    },
  };
}

// https://astro.build/config
export default defineConfig({
  // Self-hosted display serif (Astro 7 Fonts API) — Fraunces, an optical
  // old-style serif. Downloaded at build, served from _astro/fonts; no runtime
  // external requests. Exposed as --font-serif, wired into --serif in global.css.
  fonts: [
    {
      provider: fontProviders.fontsource(),
      name: 'Fraunces',
      cssVariable: '--font-serif',
      weights: [400, 600],
      fallbacks: ['Georgia', 'Times New Roman', 'serif'],
    },
  ],
  vite: { plugins: [heroDevServer()] },
});
