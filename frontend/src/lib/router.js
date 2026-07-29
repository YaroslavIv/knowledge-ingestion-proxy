// Tiny hand-rolled router — this app has no router library (plain Vite +
// Svelte, not SvelteKit). Two sections, each optionally scoped to one id:
//   /knowledge            -> Knowledge list
//   /knowledge/<id>        -> one knowledge base
//   /courses               -> Courses list
//   /courses/<id>          -> one course project
// Anything else (bare "/", unknown path) falls back to the Knowledge list so
// there's always a valid, normalizable route.
const SECTIONS = new Set(["knowledge", "courses"]);

// Vite bakes whatever --base was passed at build time into
// import.meta.env.BASE_URL (e.g. "/proxy/" behind the reverse-proxy deploy,
// "/" for plain local dev) — every pushState'd/parsed path must include it,
// or the address bar ends up showing a path the reverse proxy doesn't
// recognize as ours, and reloading that URL 404s.
const BASE = import.meta.env.BASE_URL.replace(/\/$/, "");

export function parseRoute(pathname) {
  const withoutBase = BASE && pathname.startsWith(BASE) ? pathname.slice(BASE.length) : pathname;
  const parts = (withoutBase || "/").split("/").filter(Boolean).map(decodeURIComponent);
  const section = SECTIONS.has(parts[0]) ? parts[0] : "knowledge";
  const id = section === parts[0] && parts[1] ? parts[1] : null;
  return { section, id };
}

export function buildPath(section, id) {
  const base = SECTIONS.has(section) ? section : "knowledge";
  return `${BASE}${id ? `/${base}/${encodeURIComponent(id)}` : `/${base}`}`;
}
