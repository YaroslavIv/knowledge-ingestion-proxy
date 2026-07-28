const BASE_URL = import.meta.env.VITE_PROXY_API_BASE_URL || "http://localhost:8123";
// Compatible with Open WebUI's own convention (Authorization: Bearer <key>).
// Left unset, no header is sent — matches the backend's PROXY_API_KEY being
// unset by default (API open, same as before this existed).
const API_KEY = import.meta.env.VITE_PROXY_API_KEY || "";

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (API_KEY) headers.Authorization = `Bearer ${API_KEY}`;
  const resp = await fetch(`${BASE_URL}${path}`, { ...options, headers });
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
  const { includeMaterials = false, includeOtherModules = false, regenerateFromScratch = false } = options;
  return request(`/api/courses/${projectId}/modules/${moduleId}/output/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model,
      instruction,
      include_materials: includeMaterials,
      include_other_modules: includeOtherModules,
      regenerate_from_scratch: regenerateFromScratch,
    }),
  });
}

export function getModuleOutputContent(projectId, moduleId, versionId) {
  return request(`/api/courses/${projectId}/modules/${moduleId}/output/versions/${versionId}/content`);
}
