import { defineConfig } from "vite";
import fs from "node:fs";
import path from "node:path";
import type { Plugin } from "vite";

// Backend origin for the dev proxy. The backend runs on 8000 in
// backend/README.md's local startup procedure; override if you moved it.
const API_TARGET = process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8000";

// Every path prefix the API owns (see the router mounts in app/main.py).
// The Mini App's own routes are HASH routes (`/#/catalog`, `/#/admin`, ...),
// so the real HTTP path is always `/` and these prefixes can never collide
// with a frontend route.
const API_PREFIXES = [
  "/auth",
  "/catalog",
  "/cart",
  "/orders",
  "/payments",
  "/admin",
  "/owner",
  "/vehicles",
  "/health",
  "/telegram",
];

/**
 * DEV ONLY: serve `/files/...` out of the local uploads directory.
 *
 * In production Nginx serves this path and verifies the ADR-13 signature
 * (`secure_link_md5`); the FastAPI app only ever *generates* signed URLs and
 * has no `/files` route at all. Without this, every product image and receipt
 * in a locally-run Mini App is a broken image — which looks like a bug during
 * device testing but is just the missing Nginx half.
 *
 * This middleware does NOT verify the signature. It is a convenience for
 * looking at the UI on a real device, never a stand-in for Nginx, and it is
 * inert unless COMFORT_UPLOADS_ROOT is set. `vite build` ignores `server`
 * entirely, so none of this can reach a production bundle.
 */
function devUploadsPlugin(): Plugin {
  const uploadsRoot = process.env.COMFORT_UPLOADS_ROOT;
  return {
    name: "comfort-dev-uploads",
    apply: "serve",
    configureServer(server) {
      if (!uploadsRoot) return;
      const root = path.resolve(uploadsRoot);
      server.middlewares.use((req, res, next) => {
        if (!req.url?.startsWith("/files/")) return next();
        const relative = decodeURIComponent(req.url.slice("/files/".length).split("?")[0]);
        const filePath = path.resolve(root, relative);
        // Never serve outside the uploads root, even in a dev helper.
        if (filePath !== root && !filePath.startsWith(root + path.sep)) {
          res.statusCode = 403;
          return res.end("forbidden");
        }
        fs.readFile(filePath, (err, data) => {
          if (err) {
            res.statusCode = 404;
            return res.end("not found");
          }
          const ext = path.extname(filePath).toLowerCase();
          const types: Record<string, string> = {
            ".webp": "image/webp",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
          };
          res.setHeader("Content-Type", types[ext] ?? "application/octet-stream");
          res.end(data);
        });
      });
    },
  };
}

export default defineConfig({
  plugins: [devUploadsPlugin()],
  build: {
    // §18 performance budget (<400KB first load) — fail loudly instead of
    // silently shipping a bundle that blows the budget.
    chunkSizeWarningLimit: 400,
  },
  server: {
    // Telegram can only open an HTTPS URL, so local device testing goes
    // through a temporary tunnel. Vite 5.4 rejects any request whose Host
    // header it does not recognise ("Blocked request. This host is not
    // allowed."), which is exactly what a tunnel hostname is.
    allowedHosts: [".ngrok-free.app", ".ngrok.app", ".ngrok.io", ".trycloudflare.com", ".loca.lt"],
    // Same-origin API, mirroring production: there Nginx serves the Mini App
    // and proxies the API under one origin, so the frontend's default
    // API_BASE of "" is correct and no CORS grant exists. Proxying here keeps
    // local dev on that same model — one tunnel, no CORS, nothing to
    // configure in the frontend.
    proxy: Object.fromEntries(
      API_PREFIXES.map((prefix) => [prefix, { target: API_TARGET, changeOrigin: true }]),
    ),
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.ts"],
  },
});
