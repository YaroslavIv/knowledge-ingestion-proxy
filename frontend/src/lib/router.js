// Tiny hand-rolled router — this app has no router library (plain Vite +
// Svelte, not SvelteKit). Two sections, each optionally scoped to one id:
//   /knowledge            -> Knowledge list
//   /knowledge/<id>        -> one knowledge base
//   /courses               -> Courses list
//   /courses/<id>          -> one course project
// Anything else (bare "/", unknown path) falls back to the Knowledge list so
// there's always a valid, normalizable route.
const SECTIONS = new Set(["knowledge", "courses"]);

export function parseRoute(pathname) {
  const parts = (pathname || "/").split("/").filter(Boolean).map(decodeURIComponent);
  const section = SECTIONS.has(parts[0]) ? parts[0] : "knowledge";
  const id = section === parts[0] && parts[1] ? parts[1] : null;
  return { section, id };
}

export function buildPath(section, id) {
  const base = SECTIONS.has(section) ? section : "knowledge";
  return id ? `/${base}/${encodeURIComponent(id)}` : `/${base}`;
}
