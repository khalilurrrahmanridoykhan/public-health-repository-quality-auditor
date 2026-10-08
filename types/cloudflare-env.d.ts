// Declaration-merges with @opennextjs/cloudflare's global `CloudflareEnv`
// interface, which only declares the bindings *it* knows about. `DB` is
// this project's own binding (see wrangler.jsonc's `d1_databases`), so it
// has to be added here rather than edited into node_modules.
declare global {
  interface CloudflareEnv {
    DB?: D1Database;
  }
}

export {};
