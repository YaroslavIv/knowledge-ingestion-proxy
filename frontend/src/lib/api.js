const BASE_URL = import.meta.env.VITE_PROXY_API_BASE_URL || "http://localhost:8123";

// The proxy's own front door: a *personal* Open WebUI bearer token (an
// sk-... API key from that person's own Settings -> Account -> API Keys),
// entered once through the Login screen and cached per-browser here —
// deliberately NOT baked into the build like an earlier version of this file
// did, since that meant anyone who merely loaded the page already had a
// working key with no login at all. Cleared automatically on a 401 (see
// request() below) so an expired/revoked key reliably drops back to Login
// instead of leaving the app stuck showing failed requests.
const TOKEN_KEY = "proxy_owui_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

// For the handful of call sites that fetch a file directly (to inspect its
// content-type, or build a Blob/object URL for a preview or download) instead
// of going through request() below — they still need the same bearer token.
export function authHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// Used by the Login screen: signs in against this deployment's own Open
// WebUI instance (see backend/app/routers/auth.py) and, on success, caches
// the returned personal token. Deliberately a plain fetch, not request() —
// a wrong password here is a normal 401 that should surface as an inline
// form error, not trigger request()'s global "drop the token and reload"
// handling (there's no token to drop yet, and reloading would just wipe out
// the error message the user needs to see).
export async function login(email, password) {
  const resp = await fetch(`${BASE_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  let body = null;
  try {
    body = await resp.json();
  } catch {
    // ignore, body stays null
  }
  if (!resp.ok) throw new Error(body?.detail || resp.statusText);
  setToken(body.token);
  return body;
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}), ...authHeaders() };
  const resp = await fetch(`${BASE_URL}${path}`, { ...options, headers });
  if (resp.status === 401) {
    // The stored token stopped working (revoked/expired/never valid) —
    // drop it and reload, which re-shows Login instead of leaving the rest
    // of the app stuck mid-render with a wall of failed requests.
    clearToken();
    window.location.reload();
  }
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail || detail;
    } catch {
      // ignore, keep statusText
    }
    throw new Error(detail);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

export function listConnections() {
  return request("/api/connections");
}

export function getActiveConnection() {
  return request("/api/connections/active");
}

export function connect(label, baseUrl, email, password) {
  return request("/api/connections", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label, base_url: baseUrl, email, password }),
  });
}

export function activateConnection(id) {
  return request(`/api/connections/${id}/activate`, { method: "POST" });
}

export function deleteConnection(id) {
  return request(`/api/connections/${id}`, { method: "DELETE" });
}

export function uploadDocument(file) {
  const form = new FormData();
  form.append("file", file);
  return request("/api/documents", { method: "POST", body: form });
}

export function getDocument(sessionId) {
  return request(`/api/documents/${sessionId}`);
}

export function patchDocument(sessionId, patch) {
  return request(`/api/documents/${sessionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export function finalizeDocument(sessionId) {
  return request(`/api/documents/${sessionId}/finalize`, { method: "POST" });
}

export function listKnowledgeBases() {
  return request("/api/kb");
}

export function createKnowledgeBase(name, description = "", versionTag = "v1.0") {
  return request("/api/kb", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, description, version_tag: versionTag }),
  });
}

export function getKnowledgeBaseDetail(knowledgeId) {
  return request(`/api/kb/${knowledgeId}`);
}

export function getKnowledgeLineage(knowledgeId) {
  return request(`/api/kb/${knowledgeId}/lineage`);
}

export function listAllTags() {
  return request("/api/tags");
}

export function getLatestCollectionsByTag(tag) {
  return request(`/api/tags/${encodeURIComponent(tag)}/collections`);
}

export function updateCollectionTags(knowledgeId, tags) {
  return request(`/api/kb/${knowledgeId}/tags`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tags }),
  });
}

export function cloneKnowledgeBase(knowledgeId, name, versionTag) {
  return request(`/api/kb/${knowledgeId}/clone`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, version_tag: versionTag }),
  });
}

export function deleteKnowledgeBase(knowledgeId) {
  return request(`/api/kb/${knowledgeId}`, { method: "DELETE" });
}

export function reembedFile(knowledgeId, fileId) {
  return request(`/api/kb/${knowledgeId}/files/${fileId}/reembed`, { method: "POST" });
}

// --- RAG settings: chunking + embedding model, applied across the whole
// Open WebUI instance (not per-collection) ---

export function getRagSettings() {
  return request("/api/rag-settings");
}

export function updateRagSettings(payload) {
  return request("/api/rag-settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// --- Local backups (originals + course outputs + this proxy's own DB) ---

export function listBackups() {
  return request("/api/backups");
}

export function triggerBackup() {
  return request("/api/backups", { method: "POST" });
}

export function getBackupDownloadUrl(filename) {
  return `${BASE_URL}/api/backups/${encodeURIComponent(filename)}/download`;
}

export function listKnowledgeBaseFiles(knowledgeId) {
  return request(`/api/kb/${knowledgeId}/files`);
}

export function updateFileTags(knowledgeId, fileId, tags) {
  return request(`/api/kb/${knowledgeId}/files/${fileId}/tags`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tags }),
  });
}

export function getKnowledgeFileContent(knowledgeId, fileId) {
  return request(`/api/kb/${knowledgeId}/files/${fileId}`);
}

export function getKnowledgeFileOriginalUrl(knowledgeId, fileId) {
  return `${BASE_URL}/api/kb/${knowledgeId}/files/${fileId}/original`;
}

export function deleteKnowledgeFile(knowledgeId, fileId) {
  return request(`/api/kb/${knowledgeId}/files/${fileId}`, { method: "DELETE" });
}

export function reparseKnowledgeFile(knowledgeId, fileId) {
  return request(`/api/kb/${knowledgeId}/files/${fileId}/reparse`, { method: "POST" });
}

export function getChunkPreview(sessionId, chunkSizeOverride = null, chunkOverlapOverride = null) {
  const params = new URLSearchParams();
  if (chunkSizeOverride != null) params.set("chunk_size", chunkSizeOverride);
  if (chunkOverlapOverride != null) params.set("chunk_overlap", chunkOverlapOverride);
  const query = params.toString();
  return request(`/api/documents/${sessionId}/chunk-preview${query ? `?${query}` : ""}`);
}

export function updateKnowledgeFile(knowledgeId, fileId, text, redactions) {
  return request(`/api/kb/${knowledgeId}/files/${fileId}/content`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, redactions }),
  });
}

export function previewChunks(text, redactions, chunkSizeOverride = null, chunkOverlapOverride = null) {
  return request("/api/preview/chunks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text,
      redactions,
      chunk_size: chunkSizeOverride,
      chunk_overlap: chunkOverlapOverride,
    }),
  });
}

// --- Course generator ---

export function listAvailableModels() {
  return request("/api/courses/available-models");
}

export function listCourseProjects() {
  return request("/api/courses");
}

export function createCourseProject(payload) {
  return request("/api/courses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getCourseProject(projectId) {
  return request(`/api/courses/${projectId}`);
}

export function deleteCourseProject(projectId) {
  return request(`/api/courses/${projectId}`, { method: "DELETE" });
}

export function addCourseMaterial(projectId, knowledgeId) {
  return request(`/api/courses/${projectId}/materials`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ knowledge_id: knowledgeId }),
  });
}

export function removeCourseMaterial(projectId, knowledgeId) {
  return request(`/api/courses/${projectId}/materials/${knowledgeId}`, { method: "DELETE" });
}

export function addCourseCompetitor(projectId, knowledgeId) {
  return request(`/api/courses/${projectId}/competitors`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ knowledge_id: knowledgeId }),
  });
}

export function removeCourseCompetitor(projectId, knowledgeId) {
  return request(`/api/courses/${projectId}/competitors/${knowledgeId}`, { method: "DELETE" });
}

export function addCourseInstructions(projectId, knowledgeId) {
  return request(`/api/courses/${projectId}/instructions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ knowledge_id: knowledgeId }),
  });
}

export function removeCourseInstructions(projectId, knowledgeId) {
  return request(`/api/courses/${projectId}/instructions/${knowledgeId}`, { method: "DELETE" });
}

export function setCourseVisual(projectId, knowledgeId) {
  return request(`/api/courses/${projectId}/visual`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ knowledge_id: knowledgeId }),
  });
}

export function clearCourseVisual(projectId) {
  return request(`/api/courses/${projectId}/visual`, { method: "DELETE" });
}

export function seedCourseFeedback(projectId, text) {
  return request(`/api/courses/${projectId}/feedback/seed`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}

export function listCourseFeedback(projectId) {
  return request(`/api/courses/${projectId}/feedback`);
}

export function listCourseModules(projectId) {
  return request(`/api/courses/${projectId}/modules`);
}

export function createCourseModule(projectId, payload) {
  return request(`/api/courses/${projectId}/modules`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function updateCourseModule(projectId, moduleId, patch) {
  return request(`/api/courses/${projectId}/modules/${moduleId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export function deleteCourseModule(projectId, moduleId) {
  return request(`/api/courses/${projectId}/modules/${moduleId}`, { method: "DELETE" });
}

export function approveCourseModule(projectId, moduleId) {
  return request(`/api/courses/${projectId}/modules/${moduleId}/approve`, { method: "POST" });
}

export function rejectCourseModule(projectId, moduleId) {
  return request(`/api/courses/${projectId}/modules/${moduleId}/reject`, { method: "POST" });
}

export function splitCourseIntoModules(projectId, model) {
  return request(`/api/courses/${projectId}/split`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  });
}

export function publishModuleOutput(projectId, moduleId, file, notes = "") {
  const form = new FormData();
  form.append("file", file);
  form.append("notes", notes);
  return request(`/api/courses/${projectId}/modules/${moduleId}/output`, {
    method: "POST",
    body: form,
  });
}

export function listModuleOutputVersions(projectId, moduleId) {
  return request(`/api/courses/${projectId}/modules/${moduleId}/output/versions`);
}

export function getModuleOutputDownloadUrl(projectId, moduleId, versionId) {
  return `${BASE_URL}/api/courses/${projectId}/modules/${moduleId}/output/versions/${versionId}/download`;
}

export function getModuleOutputViewUrl(projectId, moduleId, versionId) {
  return `${BASE_URL}/api/courses/${projectId}/modules/${moduleId}/output/versions/${versionId}/view`;
}

export function bumpOutputVersion(projectId, versionTag) {
  return request(`/api/courses/${projectId}/bump-output-version`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ version_tag: versionTag }),
  });
}

export function generateModuleOutput(projectId, moduleId, model, instruction, options = {}) {
  const {
    productKnowledgeIds = null,
    competitorKnowledgeIds = null,
    instructionsKnowledgeIds = null,
    includeVisual = true,
    otherModuleIds = [],
    styleReferenceModuleId = null,
    regenerateFromScratch = false,
  } = options;
  return request(`/api/courses/${projectId}/modules/${moduleId}/output/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model,
      instruction,
      product_knowledge_ids: productKnowledgeIds,
      competitor_knowledge_ids: competitorKnowledgeIds,
      instructions_knowledge_ids: instructionsKnowledgeIds,
      include_visual: includeVisual,
      other_module_ids: otherModuleIds,
      style_reference_module_id: styleReferenceModuleId,
      regenerate_from_scratch: regenerateFromScratch,
    }),
  });
}

export function getModuleOutputContent(projectId, moduleId, versionId) {
  return request(`/api/courses/${projectId}/modules/${moduleId}/output/versions/${versionId}/content`);
}

export function getGenerationContext(projectId, moduleId) {
  return request(`/api/courses/${projectId}/modules/${moduleId}/generation-context`);
}
