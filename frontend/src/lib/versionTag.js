// Mirrors backend/app/versioning.py::suggest_next_version_tag — used to
// prefill the clone dialog's version-tag field before the request round-trips.
const TRAILING_VERSION_RE = /(\d+)\.(\d+)$/;

export function suggestNextVersionTag(tag) {
  const match = TRAILING_VERSION_RE.exec(tag);
  if (!match) return `${tag} v2`.trim();
  const major = match[1];
  const minor = parseInt(match[2], 10) + 1;
  return tag.replace(TRAILING_VERSION_RE, `${major}.${minor}`);
}
