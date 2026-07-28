// Collections carry freeform tags (see TrackedCollection.tags); hierarchy is
// expressed purely by convention — "course/uvss" is a child of "course". No
// tree ever needs to be stored: it's rebuilt from whatever tag strings are
// actually present on the current list of collections.
export function buildTagTree(items) {
  const roots = new Map();

  for (const item of items) {
    for (const tag of item.tags ?? []) {
      const parts = tag.split("/").filter(Boolean);
      let level = roots;
      let pathSoFar = "";
      for (const part of parts) {
        pathSoFar = pathSoFar ? `${pathSoFar}/${part}` : part;
        if (!level.has(part)) level.set(part, { name: part, path: pathSoFar, children: new Map() });
        level = level.get(part).children;
      }
    }
  }

  function toArray(map) {
    return [...map.values()]
      .map((node) => ({ name: node.name, path: node.path, children: toArray(node.children) }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }

  return toArray(roots);
}

// Does this collection belong under the selected tag path — either tagged
// with that exact path, or with something nested under it?
export function matchesTagPath(item, path) {
  if (!path) return true;
  const prefix = `${path}/`;
  return (item.tags ?? []).some((t) => t === path || t.startsWith(prefix));
}
