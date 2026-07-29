<script>
  import {
    authHeaders,
    cloneKnowledgeBase,
    deleteKnowledgeBase,
    deleteKnowledgeFile,
    finalizeDocument,
    getChunkPreview,
    getKnowledgeBaseDetail,
    getKnowledgeFileContent,
    getKnowledgeFileOriginalUrl,
    getKnowledgeLineage,
    listAllTags,
    listKnowledgeBaseFiles,
    patchDocument,
    previewChunks,
    reparseKnowledgeFile,
    updateFileTags,
    updateKnowledgeFile,
    uploadDocument,
  } from "./api.js";
  import HighlightedEditor from "./HighlightedEditor.svelte";
  import { suggestNextVersionTag } from "./versionTag.js";

  let { knowledgeId, knowledgeName, initialFileId = null, onBack = () => {}, onOpenKnowledge = (_id, _name, _fileId) => {} } = $props();

  let files = $state([]);
  let filesLoading = $state(true);
  let filesError = $state(null);
  let deleting = $state(false);
  let deletingFileId = $state(null);

  // --- version / lineage ---
  let versionTag = $state(null);
  let parentKb = $state(null); // { knowledge_id, name, version_tag } | null
  let cloning = $state(false);
  let cloneName = $state("");
  let cloneVersionTag = $state("");
  let cloneError = $state(null);
  let cloneInProgress = $state(false);
  let showLineage = $state(false);
  // Hides the file-list sidebar and the chunk-override bar so the two panes
  // (editable text + original file) get the full window width — most useful
  // once you're actually comparing them and every extra pixel counts.
  let sidebarCollapsed = $state(false);
  let idCopied = $state(false);
  let idCopyTimer = null;

  async function copyKnowledgeId() {
    try {
      await navigator.clipboard.writeText(knowledgeId);
      idCopied = true;
      clearTimeout(idCopyTimer);
      idCopyTimer = setTimeout(() => (idCopied = false), 1500);
    } catch {
      // clipboard permission denied or unavailable — nothing useful to do
    }
  }

  // --- lineage tree (ancestors + children, git-branch-like) ---
  let lineageAncestors = $state([]);
  let lineageChildren = $state([]);
  let lineageExpanded = $state({}); // knowledge_id -> bool
  let lineageChangedFiles = $state({}); // knowledge_id -> KnowledgeFileSummary[] | "loading"

  async function loadLineage() {
    try {
      const lineage = await getKnowledgeLineage(knowledgeId);
      lineageAncestors = lineage.ancestors;
      lineageChildren = lineage.children;
    } catch (e) {
      // non-critical — the rest of the page still works without lineage
    }
  }

  async function toggleLineageNode(node) {
    const isOpen = !!lineageExpanded[node.knowledge_id];
    lineageExpanded = { ...lineageExpanded, [node.knowledge_id]: !isOpen };
    if (isOpen || lineageChangedFiles[node.knowledge_id]) return;
    if (node.knowledge_id === knowledgeId) {
      // this collection's own files are already loaded — no need to re-fetch
      lineageChangedFiles = { ...lineageChangedFiles, [node.knowledge_id]: files.filter((f) => f.changed) };
      return;
    }
    lineageChangedFiles = { ...lineageChangedFiles, [node.knowledge_id]: "loading" };
    try {
      const nodeFiles = await listKnowledgeBaseFiles(node.knowledge_id);
      lineageChangedFiles = { ...lineageChangedFiles, [node.knowledge_id]: nodeFiles.filter((f) => f.changed) };
    } catch (e) {
      lineageChangedFiles = { ...lineageChangedFiles, [node.knowledge_id]: [] };
    }
  }

  const currentLineageNode = $derived({
    knowledge_id: knowledgeId,
    name: knowledgeName,
    version_tag: versionTag || "",
    exists: true,
    kind: "current",
    changed_file_count: files.filter((f) => f.changed).length,
    total_file_count: files.length,
  });
  const lineageRows = $derived([
    ...lineageAncestors.map((n) => ({ ...n, kind: "ancestor" })),
    currentLineageNode,
    ...lineageChildren.map((n) => ({ ...n, kind: "child" })),
  ]);

  // --- freeform tag filter/editing ---
  let tagFilter = $state(null);
  let editingTagsForFileId = $state(null);
  let newTagInput = $state("");

  async function loadKbDetail() {
    try {
      const detail = await getKnowledgeBaseDetail(knowledgeId);
      versionTag = detail.version_tag;
      parentKb = detail.parent;
      cloneName = `${detail.name} copy`;
      cloneVersionTag = suggestNextVersionTag(detail.version_tag || "v1.0");
    } catch (e) {
      filesError = e.message;
    }
  }

  loadKbDetail();
  loadLineage();

  // --- global tag dictionary (shared across every collection, so a name
  // typed once shows up as a suggestion everywhere afterward) ---
  let knownTags = $state([]);

  async function loadKnownTags() {
    try {
      knownTags = await listAllTags();
    } catch (e) {
      // non-critical — freeform typing still works without suggestions
    }
  }

  loadKnownTags();

  async function handleClone() {
    if (!cloneName.trim() || !cloneVersionTag.trim()) return;
    cloneInProgress = true;
    cloneError = null;
    try {
      const result = await cloneKnowledgeBase(knowledgeId, cloneName.trim(), cloneVersionTag.trim());
      if (result.skipped?.length) {
        const lines = result.skipped.map((s) => `- ${s.filename}: ${s.reason}`).join("\n");
        alert(
          `Cloned ${result.files_copied} file(s). ${result.skipped.length} file(s) couldn't be copied ` +
            `(no extracted content in Open WebUI):\n\n${lines}`
        );
      }
      onOpenKnowledge(result.id, result.name);
    } catch (e) {
      cloneError = e.message;
    } finally {
      cloneInProgress = false;
    }
  }

  const allTags = $derived([...new Set(files.flatMap((f) => f.tags ?? []))].sort());
  const visibleFiles = $derived(tagFilter ? files.filter((f) => (f.tags ?? []).includes(tagFilter)) : files);

  async function addTag(file, tag) {
    const trimmed = tag.trim();
    if (!trimmed) return;
    const current = file.tags ?? [];
    if (current.includes(trimmed)) return;
    await saveTags(file, [...current, trimmed]);
    if (!knownTags.includes(trimmed)) knownTags = [...knownTags, trimmed].sort();
  }

  async function removeTag(file, tag) {
    await saveTags(
      file,
      (file.tags ?? []).filter((t) => t !== tag),
    );
  }

  async function saveTags(file, tags) {
    try {
      await updateFileTags(knowledgeId, file.id, tags);
      files = files.map((f) => (f.id === file.id ? { ...f, tags } : f));
    } catch (e) {
      filesError = e.message;
    }
  }

  // Shared chunk-size override, in tokens, applied to both editing panes
  // below (empty = use the target Open WebUI instance's real config).
  let chunkSizeOverride = $state("");
  let chunkOverlapOverride = $state("");
  let lastChunkConfig = $state(null); // { chunkSize, chunkOverlap, textSplitter } most recently used

  // `min` defaults to requiring a positive value (chunk size must be at
  // least 1 token) — pass min=0 for overlap, where "no overlap" is a
  // perfectly valid, common choice that must not be silently discarded and
  // fall back to a mismatched default (see with_token_overrides on the
  // backend for what happens when overlap ends up larger than chunk size).
  function parsedOverride(value, min = 1) {
    if (value === "" || value === null || value === undefined) return null;
    const n = parseInt(value, 10);
    return Number.isFinite(n) && n >= min ? n : null;
  }

  async function handleDeleteFile(file) {
    if (!confirm(`Delete "${file.filename}" from this knowledge base? This cannot be undone.`)) return;
    deletingFileId = file.id;
    filesError = null;
    try {
      await deleteKnowledgeFile(knowledgeId, file.id);
      files = files.filter((f) => f.id !== file.id);
      if (activeFileId === file.id) {
        mode = null;
        activeFileId = null;
      }
    } catch (e) {
      filesError = e.message;
    } finally {
      deletingFileId = null;
    }
  }

  async function handleDeleteKnowledgeBase() {
    if (!confirm(`Delete knowledge base "${knowledgeName}"? This cannot be undone.`)) return;
    deleting = true;
    try {
      await deleteKnowledgeBase(knowledgeId);
      onBack();
    } catch (e) {
      filesError = e.message;
      deleting = false;
    }
  }

  // mode: null (nothing selected) | "existing" (viewing/editing a committed file) | "new" (ingesting a fresh upload)
  let mode = $state(null);

  // --- "existing file" editing state ---
  let activeFileId = $state(null);
  let activeFilename = $state("");
  let fileText = $state("");
  let fileRedactions = $state([]);
  let fileChunks = $state([]);
  let fileLoading = $state(false);
  let fileSaving = $state(false);
  let fileError = $state(null);
  let fileSaved = $state(false);
  let fileChunkTimer = null;
  let reparsing = $state(false);
  let reparseWarnings = $state([]);

  // Original-file preview for an already-committed document. This proxy
  // caches the real original locally at upload time (see original_storage.py
  // on the backend) specifically so this can show a true PDF/DOCX rather
  // than the cleaned text again — Open WebUI itself never receives it. Falls
  // back to whatever Open WebUI has stored if no local cache exists (e.g.
  // the file entered the collection some other way). The renamed-to-.md
  // filename in the KB listing doesn't reflect the real original's type, so
  // this fetches the response and trusts its actual content-type instead of
  // guessing from `file.filename`.
  let fileOriginalKind = $state(null); // "pdf" | "html" | "text" | "other" | null
  let fileOriginalUrl = $state(null);
  let fileOriginalRawText = $state("");
  let fileOriginalFilename = $state("");
  let fileOriginalError = $state(null);
  // Only pdf/html are visually worth a second pane by default — showing the
  // same plain text/markdown again next to the (identical) editor is just
  // wasted space, and was also where a stale request used to surface as a
  // confusing "Failed to fetch" for files with no visual original at all.
  let forceShowOriginalExisting = $state(false);
  const showOriginalPaneExisting = $derived(
    fileOriginalKind === "pdf" || fileOriginalKind === "html" || forceShowOriginalExisting,
  );

  async function loadExistingOriginalPreview(file) {
    fileOriginalError = null;
    fileOriginalRawText = "";
    fileOriginalKind = null;
    forceShowOriginalExisting = false;
    if (fileOriginalUrl) URL.revokeObjectURL(fileOriginalUrl);
    fileOriginalUrl = null;
    fileOriginalFilename = file.filename;

    try {
      const resp = await fetch(getKnowledgeFileOriginalUrl(knowledgeId, file.id), { headers: authHeaders() });
      if (!resp.ok) throw new Error(`Open WebUI returned ${resp.status}`);
      const contentType = resp.headers.get("content-type") || "";
      const rawFilename = resp.headers.get("x-original-filename");
      fileOriginalFilename = rawFilename ? decodeURIComponent(rawFilename) : file.filename;

      if (contentType.includes("pdf")) {
        fileOriginalUrl = URL.createObjectURL(await resp.blob());
        fileOriginalKind = "pdf";
      } else if (contentType.includes("html")) {
        fileOriginalUrl = URL.createObjectURL(await resp.blob());
        fileOriginalKind = "html";
      } else if (contentType.startsWith("text/") || contentType.includes("markdown")) {
        fileOriginalRawText = await resp.text();
        fileOriginalKind = "text";
      } else {
        fileOriginalUrl = URL.createObjectURL(await resp.blob());
        fileOriginalKind = "other";
      }
    } catch (e) {
      fileOriginalError = e.message;
    }
  }

  // --- "new ingestion" state ---
  let sessionId = $state(null);
  let newFilename = $state("");
  let newText = $state("");
  let newRedactions = $state([]);
  let newChunks = $state([]);
  let newWarnings = $state([]);
  let newPhase = $state("editing"); // editing | submitting | done
  let newSaving = $state(false);
  let newError = $state(null);
  let newResult = $state(null);
  let newSaveTimer = null;

  async function loadFiles() {
    filesLoading = true;
    filesError = null;
    try {
      files = await listKnowledgeBaseFiles(knowledgeId);
      if (initialFileId) {
        const target = files.find((f) => f.id === initialFileId);
        if (target) await openExistingFile(target);
      }
    } catch (e) {
      filesError = e.message;
    } finally {
      filesLoading = false;
    }
  }

  loadFiles();

  async function openExistingFile(file) {
    mode = "existing";
    activeFileId = file.id;
    activeFilename = file.filename;
    fileLoading = true;
    fileError = null;
    fileSaved = false;
    reparseWarnings = [];
    loadExistingOriginalPreview(file);
    try {
      const data = await getKnowledgeFileContent(knowledgeId, file.id);
      fileText = data.content;
      fileChunks = data.chunks;
      fileRedactions = [];
    } catch (e) {
      fileError = e.message;
    } finally {
      fileLoading = false;
    }
  }

  function scheduleFileChunkPreview() {
    clearTimeout(fileChunkTimer);
    fileChunkTimer = setTimeout(async () => {
      try {
        const preview = await previewChunks(fileText, fileRedactions, parsedOverride(chunkSizeOverride), parsedOverride(chunkOverlapOverride, 0));
        fileChunks = preview.chunks;
        lastChunkConfig = { chunkSize: preview.chunk_size, chunkOverlap: preview.chunk_overlap, textSplitter: preview.text_splitter };
      } catch (e) {
        fileError = e.message;
      }
    }, 400);
  }

  // Set right before we reassign fileText/fileRedactions ourselves (after a
  // successful update) so the effect below doesn't immediately flip
  // `fileSaved` back to false in reaction to our own "clean" reassignment.
  let suppressDirtyFlag = false;

  $effect(() => {
    if (mode !== "existing") return;
    // Recompute on every text edit, redaction, and chunk-size/overlap
    // override change — this is also what makes "I erased something" (a
    // redaction or a plain delete) immediately recompute the chunk bands.
    void fileText;
    void fileRedactions;
    void chunkSizeOverride;
    void chunkOverlapOverride;
    if (suppressDirtyFlag) {
      suppressDirtyFlag = false;
    } else {
      fileSaved = false;
    }
    scheduleFileChunkPreview();
  });

  async function handleReparseFile() {
    if (!activeFileId) return;
    reparsing = true;
    fileError = null;
    reparseWarnings = [];
    try {
      const result = await reparseKnowledgeFile(knowledgeId, activeFileId);
      fileText = result.content;
      fileChunks = result.chunks;
      fileRedactions = [];
      reparseWarnings = result.warnings ?? [];
      // Not saved yet — the user still reviews/edits and presses Update
      // (or just navigates away to discard), exactly like any other edit.
    } catch (e) {
      fileError = e.message;
    } finally {
      reparsing = false;
    }
  }

  async function handleUpdateFile() {
    if (!activeFileId) return;
    fileSaving = true;
    fileError = null;
    try {
      const result = await updateKnowledgeFile(knowledgeId, activeFileId, fileText, fileRedactions);
      suppressDirtyFlag = true;
      fileText = result.content;
      fileChunks = result.chunks;
      fileRedactions = [];
      fileSaved = true;
      await loadFiles();
    } catch (e) {
      fileError = e.message;
    } finally {
      fileSaving = false;
    }
  }

  // Set when ingesting a *replacement* for an existing file (via "Replace
  // file" on the existing-file pane) rather than adding a brand-new one —
  // finalize() then updates this file_id in place instead of creating a new
  // file, and the backend bumps its version tag with last_change_method
  // "file_replace" (as opposed to "text_edit" for the simple Update button).
  let replaceTargetFileId = $state(null);
  let replaceTargetFilename = $state("");

  // Original-file preview pane, shown side-by-side with the editable text so
  // the user can spot anything the parser dropped or mangled and go fix (or
  // delete) it themselves on the left. This is purely a client-side object
  // URL over the same File the browser already holds — never uploaded
  // anywhere new, never written to disk, gone the moment it's revoked.
  let newOriginalUrl = $state(null);
  let newOriginalKind = $state(null); // "pdf" | "html" | "text" | "other" | null
  let newOriginalRawText = $state("");
  // Only pdf/html are visually worth a second pane by default — showing the
  // same plain text/markdown again next to the (identical) editor is just
  // wasted space. This lets the user override that for one open file.
  let forceShowOriginalNew = $state(false);
  const showOriginalPaneNew = $derived(
    newOriginalKind === "pdf" || newOriginalKind === "html" || forceShowOriginalNew,
  );

  function revokeOriginalPreview() {
    if (newOriginalUrl) URL.revokeObjectURL(newOriginalUrl);
    newOriginalUrl = null;
    newOriginalKind = null;
    newOriginalRawText = "";
    forceShowOriginalNew = false;
  }

  function startNewIngestion() {
    mode = "new";
    activeFileId = null;
    replaceTargetFileId = null;
    replaceTargetFilename = "";
    sessionId = null;
    newFilename = "";
    newText = "";
    newRedactions = [];
    newChunks = [];
    newWarnings = [];
    newPhase = "editing";
    newError = "";
    newResult = null;
    revokeOriginalPreview();
  }

  function startReplaceFile() {
    const targetId = activeFileId;
    const targetFilename = activeFilename;
    startNewIngestion();
    replaceTargetFileId = targetId;
    replaceTargetFilename = targetFilename;
  }

  function scheduleNewSave() {
    if (newPhase !== "editing") return;
    clearTimeout(newSaveTimer);
    newSaveTimer = setTimeout(doNewSave, 500);
  }

  async function doNewSave() {
    if (!sessionId) return;
    newSaving = true;
    try {
      await patchDocument(sessionId, {
        text: newText,
        redactions: newRedactions,
        target_knowledge_id: knowledgeId,
        replace_file_id: replaceTargetFileId,
      });
      const preview = await getChunkPreview(sessionId, parsedOverride(chunkSizeOverride), parsedOverride(chunkOverlapOverride, 0));
      newChunks = preview.chunks;
      lastChunkConfig = { chunkSize: preview.chunk_size, chunkOverlap: preview.chunk_overlap, textSplitter: preview.text_splitter };
    } catch (e) {
      newError = e.message;
    } finally {
      newSaving = false;
    }
  }

  $effect(() => {
    if (mode !== "new") return;
    void newText;
    void newRedactions;
    void chunkSizeOverride;
    void chunkOverlapOverride;
    scheduleNewSave();
  });

  // The object URLs behind both original-file previews are never written
  // anywhere — just make sure they're released when this KB view goes away.
  $effect(() => {
    return () => {
      revokeOriginalPreview();
      if (fileOriginalUrl) URL.revokeObjectURL(fileOriginalUrl);
    };
  });

  function loadOriginalPreview(file) {
    revokeOriginalPreview();
    newOriginalUrl = URL.createObjectURL(file);
    const ext = (file.name.split(".").pop() || "").toLowerCase();
    if (file.type === "application/pdf" || ext === "pdf") {
      newOriginalKind = "pdf";
    } else if (file.type === "text/html" || ext === "html" || ext === "htm") {
      newOriginalKind = "html";
    } else if (file.type.startsWith("text/") || ext === "txt" || ext === "md") {
      newOriginalKind = "text";
      file.text().then((t) => (newOriginalRawText = t));
    } else {
      newOriginalKind = "other";
    }
  }

  async function handleNewFileChange(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    newError = "";
    try {
      loadOriginalPreview(file);
      const created = await uploadDocument(file);
      sessionId = created.session_id;
      newFilename = created.filename;
      newText = created.text;
      newWarnings = created.warnings;
      newRedactions = [];
      newChunks = [];
      newPhase = "editing";
      doNewSave();
    } catch (e) {
      newError = e.message;
    }
  }

  async function handleFinalizeNew() {
    if (!sessionId) return;
    clearTimeout(newSaveTimer);
    await doNewSave();
    newPhase = "submitting";
    newError = "";
    try {
      newResult = await finalizeDocument(sessionId);
      newPhase = "done";
      await loadFiles();
    } catch (e) {
      newError = e.message;
      newPhase = "editing";
    }
  }
</script>

<div class="flex flex-col gap-3">
  <div class="flex items-center gap-2 px-1">
    <button type="button" aria-label="Back to Knowledge list" class="p-1 rounded-full hover:bg-gray-100 dark:hover:bg-gray-850 transition" onclick={onBack}>
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="size-4">
        <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5 8.25 12l7.5-7.5" />
      </svg>
    </button>
    <div class="text-xl font-medium capitalize">{knowledgeName}</div>
    {#if versionTag}
      <span class="text-xs font-mono bg-gray-100 dark:bg-gray-850 text-gray-700 dark:text-gray-300 px-2 py-0.5 rounded-full">
        {versionTag}
      </span>
    {/if}
    <button
      type="button"
      class="text-[0.7rem] font-mono text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition flex items-center gap-1"
      title={knowledgeId}
      onclick={copyKnowledgeId}
    >
      {knowledgeId.slice(0, 8)}…
      {#if idCopied}
        <span class="text-green-600 dark:text-green-400">copied</span>
      {:else}
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-3">
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M15.666 3.888A2.25 2.25 0 0 0 13.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 0 1-.75.75H9a.75.75 0 0 1-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 0 1-2.25 2.25H6.75A2.25 2.25 0 0 1 4.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 0 1 1.927-.184"
          />
        </svg>
      {/if}
    </button>
    {#if parentKb}
      <button
        type="button"
        class="text-xs text-gray-500 underline hover:text-gray-800 dark:hover:text-gray-200"
        onclick={() => onOpenKnowledge(parentKb.knowledge_id, parentKb.name)}
      >
        forked from {parentKb.version_tag}
      </button>
    {/if}
    <button
      type="button"
      class="text-xs px-2.5 py-1 rounded-full border border-gray-200 dark:border-gray-800 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
      onclick={() => (showLineage = !showLineage)}
    >
      History
    </button>
    <button
      type="button"
      class="text-xs px-2.5 py-1 rounded-full border border-gray-200 dark:border-gray-800 hover:bg-gray-100 dark:hover:bg-gray-850 transition flex items-center gap-1"
      title={sidebarCollapsed ? "Show file list and chunk settings" : "Hide file list and chunk settings for more room"}
      onclick={() => (sidebarCollapsed = !sidebarCollapsed)}
    >
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="size-3">
        {#if sidebarCollapsed}
          <path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
        {:else}
          <path stroke-linecap="round" stroke-linejoin="round" d="m15.75 4.5-7.5 7.5 7.5 7.5" />
        {/if}
      </svg>
      {sidebarCollapsed ? "Show panel" : "Hide panel"}
    </button>
    <button
      type="button"
      class="ml-auto text-xs px-2.5 py-1 rounded-full border border-gray-200 dark:border-gray-800 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
      onclick={() => (cloning = !cloning)}
    >
      Clone
    </button>
    <button
      type="button"
      aria-label="Delete knowledge base"
      class="p-1.5 rounded-full hover:bg-red-500/20 text-gray-400 hover:text-red-600 dark:hover:text-red-400 transition disabled:opacity-40"
      disabled={deleting}
      onclick={handleDeleteKnowledgeBase}
    >
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-4">
        <path
          stroke-linecap="round"
          stroke-linejoin="round"
          d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"
        />
      </svg>
    </button>
  </div>

  {#if showLineage}
    <div class="lineage-panel flex flex-col gap-0.5 bg-white dark:bg-gray-900 rounded-2xl border border-gray-100/30 dark:border-gray-850/30 px-3 py-2.5">
      <div class="text-xs text-gray-500 mb-1">Version history</div>
      {#each lineageRows as node (node.knowledge_id)}
        <div class="flex flex-col">
          <div class="flex items-center gap-2 py-1">
            <span class="text-xs w-3 text-center {node.kind === 'current' ? 'opacity-60' : 'opacity-30'}">
              {node.kind === "current" ? "●" : "│"}
            </span>
            {#if node.kind === "current"}
              <span class="text-sm font-medium">{node.name}</span>
            {:else}
              <button
                type="button"
                class="text-sm hover:underline text-left disabled:opacity-50 disabled:no-underline disabled:cursor-default"
                disabled={!node.exists}
                onclick={() => node.exists && onOpenKnowledge(node.knowledge_id, node.name)}
              >
                {node.name}
              </button>
            {/if}
            <span class="text-[0.65rem] font-mono bg-gray-100 dark:bg-gray-850 text-gray-600 dark:text-gray-300 px-1.5 py-0.5 rounded-full shrink-0">
              {node.version_tag}
            </span>
            {#if node.total_file_count > 0}
              <button
                type="button"
                class="text-[0.7rem] text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 shrink-0"
                onclick={() => toggleLineageNode(node)}
              >
                {node.changed_file_count}/{node.total_file_count} changed {lineageExpanded[node.knowledge_id] ? "▾" : "▸"}
              </button>
            {/if}
          </div>
          {#if lineageExpanded[node.knowledge_id]}
            <div class="ml-8 flex flex-col gap-0.5 pb-1.5">
              {#if lineageChangedFiles[node.knowledge_id] === "loading"}
                <span class="text-xs text-gray-500">Loading…</span>
              {:else if (lineageChangedFiles[node.knowledge_id] ?? []).length === 0}
                <span class="text-xs text-gray-500">No changed files in this version.</span>
              {:else}
                {#each lineageChangedFiles[node.knowledge_id] as f (f.id)}
                  <button
                    type="button"
                    class="text-xs text-left hover:underline w-fit"
                    onclick={() => onOpenKnowledge(node.knowledge_id, node.name, f.id)}
                  >
                    ▤ {f.filename}
                  </button>
                {/each}
              {/if}
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}

  {#if cloning}
    <div class="flex flex-wrap items-end gap-2 bg-white dark:bg-gray-900 rounded-2xl border border-gray-100/30 dark:border-gray-850/30 px-3 py-2.5">
      <div class="flex flex-col gap-0.5">
        <label for="clone-name" class="text-xs text-gray-500">New knowledge base name</label>
        <input id="clone-name" class="w-56 text-sm px-2 py-1 rounded-lg bg-gray-50 dark:bg-gray-850 outline-hidden" bind:value={cloneName} />
      </div>
      <div class="flex flex-col gap-0.5">
        <label for="clone-tag" class="text-xs text-gray-500">Version tag</label>
        <input id="clone-tag" class="w-32 text-sm px-2 py-1 rounded-lg bg-gray-50 dark:bg-gray-850 outline-hidden font-mono" bind:value={cloneVersionTag} />
      </div>
      <button
        type="button"
        class="primary"
        disabled={cloneInProgress || !cloneName.trim() || !cloneVersionTag.trim()}
        onclick={handleClone}
      >
        {cloneInProgress ? "Cloning…" : `Duplicate ${files.length} file${files.length === 1 ? "" : "s"}`}
      </button>
      {#if cloneError}<span class="text-xs text-red-500">{cloneError}</span>{/if}
    </div>
  {/if}

  {#if !sidebarCollapsed}
  <div class="flex flex-wrap items-end gap-3 bg-white dark:bg-gray-900 rounded-2xl border border-gray-100/30 dark:border-gray-850/30 px-3 py-2.5">
    <div class="flex flex-col gap-0.5">
      <label for="chunk-size-override" class="text-xs text-gray-500">Chunk size (tokens)</label>
      <input
        id="chunk-size-override"
        type="number"
        min="1"
        class="w-28 text-sm px-2 py-1 rounded-lg bg-gray-50 dark:bg-gray-850 outline-hidden"
        placeholder={lastChunkConfig ? String(lastChunkConfig.chunkSize) : "default"}
        bind:value={chunkSizeOverride}
      />
    </div>
    <div class="flex flex-col gap-0.5">
      <label for="chunk-overlap-override" class="text-xs text-gray-500">Overlap (tokens)</label>
      <input
        id="chunk-overlap-override"
        type="number"
        min="0"
        class="w-28 text-sm px-2 py-1 rounded-lg bg-gray-50 dark:bg-gray-850 outline-hidden"
        placeholder={lastChunkConfig ? String(lastChunkConfig.chunkOverlap) : "default"}
        bind:value={chunkOverlapOverride}
      />
    </div>
    {#if chunkSizeOverride || chunkOverlapOverride}
      <button
        type="button"
        class="text-xs underline text-gray-500 hover:text-gray-800 dark:hover:text-gray-200"
        onclick={() => {
          chunkSizeOverride = "";
          chunkOverlapOverride = "";
        }}
      >
        Reset to instance default
      </button>
    {/if}
    {#if lastChunkConfig}
      <span class="text-xs text-gray-500">
        Currently previewing with: {lastChunkConfig.chunkSize}
        {lastChunkConfig.textSplitter === "token" ? "tokens" : "chars"}, overlap {lastChunkConfig.chunkOverlap}
        {#if !chunkSizeOverride && !chunkOverlapOverride}(instance default){/if}
      </span>
    {/if}
  </div>
  {/if}

  {#snippet originalPreview(kind, url, rawText, filename, err)}
    <div class="flex flex-col gap-1 min-h-0">
      <div class="text-xs text-gray-500 shrink-0">
        Original file — for comparison only, never sent anywhere but here
      </div>
      <div class="flex-1 min-h-0 rounded-xl border border-gray-100/30 dark:border-gray-850/30 overflow-hidden bg-white dark:bg-gray-900">
        {#if err}
          <div class="w-full h-full flex items-center justify-center text-sm text-red-500 px-4 text-center">{err}</div>
        {:else if kind === "pdf"}
          <embed src={url} type="application/pdf" class="w-full h-full" />
        {:else if kind === "html"}
          <iframe src={url} title="Original HTML preview" class="w-full h-full border-0" sandbox="allow-same-origin allow-scripts"></iframe>
        {:else if kind === "text"}
          <pre class="original-text">{rawText}</pre>
        {:else if kind === "other"}
          <div class="w-full h-full flex flex-col items-center justify-center gap-2 text-sm text-gray-500 px-4 text-center">
            <span>No inline preview for this file type.</span>
            <a href={url} download={filename} class="underline hover:text-gray-800 dark:hover:text-gray-200">
              Download original to check it
            </a>
          </div>
        {/if}
      </div>
    </div>
  {/snippet}

  <div class="grid grid-cols-1 {sidebarCollapsed ? '' : 'md:grid-cols-[336px_1fr]'} gap-3 items-start">
    {#if !sidebarCollapsed}
    <div class="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100/30 dark:border-gray-850/30 p-2 flex flex-col gap-1">
      <button
        type="button"
        class="flex items-center gap-2 w-full text-left px-2.5 py-2 rounded-xl bg-black text-white dark:bg-white dark:text-black text-sm font-medium"
        onclick={startNewIngestion}
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor" class="size-3">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
        </svg>
        Add Content
      </button>

      {#if filesLoading}
        <div class="text-xs text-gray-500 px-2 py-2">Loading…</div>
      {:else if filesError}
        <div class="text-xs text-red-500 px-2 py-2">{filesError}</div>
      {:else if files.length === 0}
        <div class="text-xs text-gray-500 px-2 py-2">No documents yet.</div>
      {:else}
        {#if allTags.length > 0}
          <div class="flex flex-wrap gap-1 px-1 pt-1">
            {#each allTags as tag}
              <button
                type="button"
                class="text-xs px-2 py-0.5 rounded-full border transition {tagFilter === tag
                  ? 'bg-black text-white dark:bg-white dark:text-black border-transparent'
                  : 'border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-850'}"
                onclick={() => (tagFilter = tagFilter === tag ? null : tag)}
              >
                {tag}
              </button>
            {/each}
          </div>
        {/if}

        <div class="flex flex-col gap-1.5 mt-1 max-h-[60vh] overflow-y-auto">
          {#each visibleFiles as f (f.id)}
            <div
              class="flex flex-col w-full rounded-xl text-sm hover:bg-gray-100 dark:hover:bg-gray-850 transition {activeFileId ===
              f.id
                ? 'bg-gray-100 dark:bg-gray-850'
                : ''}"
            >
              <div class="flex items-center gap-1 w-full">
                <button type="button" class="flex items-center gap-2 flex-1 min-w-0 text-left px-2.5 py-2" onclick={() => openExistingFile(f)}>
                  <span class="opacity-60 text-xs">▤</span>
                  <span class="flex-1 truncate">{f.filename}</span>
                </button>
                <button
                  type="button"
                  aria-label="Delete file"
                  class="p-1 mr-1.5 rounded-full hover:bg-red-500/20 text-gray-400 hover:text-red-600 dark:hover:text-red-400 transition disabled:opacity-40 shrink-0"
                  disabled={deletingFileId === f.id}
                  onclick={() => handleDeleteFile(f)}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-3.5">
                    <path
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"
                    />
                  </svg>
                </button>
              </div>

              <div class="flex flex-wrap items-center gap-1.5 px-2.5 pb-2">
                {#if f.version_tag}
                  {#if f.changed}
                    <span class="text-[0.65rem] font-medium leading-normal whitespace-nowrap px-1.5 py-0.5 rounded-full bg-black text-white dark:bg-white dark:text-black">
                      Changed in {f.version_tag}
                    </span>
                  {:else}
                    <span class="text-[0.65rem] leading-normal whitespace-nowrap px-1.5 py-0.5 rounded-full bg-gray-200 dark:bg-gray-800 text-gray-600 dark:text-gray-400">
                      Since {f.version_tag}
                    </span>
                  {/if}
                {/if}
                {#each f.tags ?? [] as tag}
                  <span class="flex items-center gap-1 text-[0.65rem] leading-normal whitespace-nowrap px-1.5 py-0.5 rounded-full border border-gray-200 dark:border-gray-800">
                    {tag}
                    <button type="button" aria-label="Remove tag" class="opacity-60 hover:opacity-100" onclick={() => removeTag(f, tag)}>×</button>
                  </span>
                {/each}
                <button
                  type="button"
                  class="text-[0.65rem] whitespace-nowrap opacity-50 hover:opacity-100"
                  onclick={() => {
                    editingTagsForFileId = editingTagsForFileId === f.id ? null : f.id;
                    newTagInput = "";
                  }}
                >
                  + tag
                </button>
              </div>

              {#if editingTagsForFileId === f.id}
                <div class="flex gap-1 px-2.5 pb-2">
                  <input
                    class="flex-1 min-w-0 text-xs px-2 py-1 rounded-lg bg-gray-50 dark:bg-gray-900 outline-hidden"
                    placeholder="tag name"
                    list="tag-suggestions-{f.id}"
                    bind:value={newTagInput}
                    onkeydown={(e) => {
                      if (e.key === "Enter") {
                        addTag(f, newTagInput);
                        newTagInput = "";
                      }
                    }}
                  />
                  <datalist id="tag-suggestions-{f.id}">
                    {#each knownTags.filter((t) => !(f.tags ?? []).includes(t)) as suggestion}
                      <option value={suggestion}></option>
                    {/each}
                  </datalist>
                  <button
                    type="button"
                    class="text-xs px-2 py-1 rounded-lg bg-gray-50 dark:bg-gray-900 shrink-0"
                    onclick={() => {
                      addTag(f, newTagInput);
                      newTagInput = "";
                    }}
                  >
                    Add
                  </button>
                </div>
              {/if}
            </div>
          {/each}
        </div>
      {/if}
    </div>
    {/if}

    <div class="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100/30 dark:border-gray-850/30 p-3 min-h-[60vh] flex flex-col gap-3">
      {#if mode === null}
        <div class="flex-1 flex items-center justify-center text-sm text-gray-500">
          Select a document to view it, or Add Content to ingest a new one.
        </div>
      {:else if mode === "existing"}
        <div class="flex items-center gap-3">
          <strong class="text-sm">{activeFilename}</strong>
          {#if fileSaving}<span class="text-xs text-gray-500">saving…</span>{/if}
          {#if fileSaved}<span class="text-xs text-green-600 dark:text-green-400">updated</span>{/if}
        </div>

        {#if fileLoading}
          <div class="text-sm text-gray-500">Loading…</div>
        {:else if showOriginalPaneExisting}
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-3 h-[90vh]">
            <div class="overflow-hidden min-h-0">
              <HighlightedEditor bind:text={fileText} bind:redactions={fileRedactions} chunks={fileChunks} />
            </div>
            {@render originalPreview(fileOriginalKind, fileOriginalUrl, fileOriginalRawText, fileOriginalFilename, fileOriginalError)}
          </div>

          {#if fileError}<p class="text-red-500 text-sm">{fileError}</p>{/if}

          {#if reparseWarnings.length > 0}
            <ul class="text-xs text-yellow-600">
              {#each reparseWarnings as w}<li>{w}</li>{/each}
            </ul>
          {/if}

          <div class="flex gap-2">
            <button type="button" class="primary self-start" disabled={fileSaving} onclick={handleUpdateFile}>
              {fileSaving ? "Updating…" : "Update"}
            </button>
            <button type="button" class="self-start" onclick={startReplaceFile}>Replace file…</button>
            {#if fileOriginalKind && !fileOriginalError}
              <button
                type="button"
                class="self-start"
                disabled={reparsing}
                title="Re-run our parser against the original file and pull the fresh text into the editor (still requires Update to save)"
                onclick={handleReparseFile}
              >
                {reparsing ? "Re-parsing…" : "Re-parse content"}
              </button>
            {/if}
          </div>
        {:else}
          <div class="h-[90vh] overflow-hidden min-h-0">
            <HighlightedEditor bind:text={fileText} bind:redactions={fileRedactions} chunks={fileChunks} />
          </div>

          {#if fileOriginalKind && !fileOriginalError}
            <button
              type="button"
              class="text-xs text-gray-500 underline self-start"
              onclick={() => (forceShowOriginalExisting = true)}
            >
              Show original anyway
            </button>
          {/if}

          {#if fileError}<p class="text-red-500 text-sm">{fileError}</p>{/if}

          {#if reparseWarnings.length > 0}
            <ul class="text-xs text-yellow-600">
              {#each reparseWarnings as w}<li>{w}</li>{/each}
            </ul>
          {/if}

          <div class="flex gap-2">
            <button type="button" class="primary self-start" disabled={fileSaving} onclick={handleUpdateFile}>
              {fileSaving ? "Updating…" : "Update"}
            </button>
            <button type="button" class="self-start" onclick={startReplaceFile}>Replace file…</button>
            {#if fileOriginalKind && !fileOriginalError}
              <button
                type="button"
                class="self-start"
                disabled={reparsing}
                title="Re-run our parser against the original file and pull the fresh text into the editor (still requires Update to save)"
                onclick={handleReparseFile}
              >
                {reparsing ? "Re-parsing…" : "Re-parse content"}
              </button>
            {/if}
          </div>
        {/if}
      {:else if mode === "new"}
        {#if !sessionId}
          <div class="flex flex-col gap-2">
            <div class="text-sm font-medium">
              {replaceTargetFileId ? `Replace "${replaceTargetFilename}"` : "Upload a document"}
            </div>
            <div class="text-xs text-gray-500">PDF, DOCX, TXT or Markdown</div>
            <input type="file" accept=".pdf,.docx,.txt,.md" onchange={handleNewFileChange} />
          </div>
        {:else}
          <div class="flex items-center gap-3">
            <strong class="text-sm">{newFilename}</strong>
            {#if replaceTargetFileId}
              <span class="text-xs text-gray-500">replacing {replaceTargetFilename}</span>
            {/if}
            {#if newSaving}<span class="text-xs text-gray-500">saving…</span>{/if}
          </div>

          {#if newWarnings.length > 0}
            <ul class="text-xs text-yellow-600">
              {#each newWarnings as w}<li>{w}</li>{/each}
            </ul>
          {/if}

          {#if showOriginalPaneNew}
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-3 h-[80vh]">
              <div class="overflow-hidden min-h-0">
                <HighlightedEditor bind:text={newText} bind:redactions={newRedactions} chunks={newChunks} disabled={newPhase !== "editing"} />
              </div>
              {@render originalPreview(newOriginalKind, newOriginalUrl, newOriginalRawText, newFilename, null)}
            </div>
          {:else}
            <div class="h-[80vh] overflow-hidden min-h-0">
              <HighlightedEditor bind:text={newText} bind:redactions={newRedactions} chunks={newChunks} disabled={newPhase !== "editing"} />
            </div>
            {#if newOriginalKind}
              <button
                type="button"
                class="text-xs text-gray-500 underline self-start"
                onclick={() => (forceShowOriginalNew = true)}
              >
                Show original anyway
              </button>
            {/if}
          {/if}

          {#if newError}<p class="text-red-500 text-sm">{newError}</p>{/if}

          {#if newPhase === "done"}
            <p class="text-green-600 dark:text-green-400 text-sm">
              {#if replaceTargetFileId}
                Done — file <code>{newResult.owui_file_id}</code> replaced.
              {:else}
                Done — file <code>{newResult.owui_file_id}</code> added.
              {/if}
            </p>
            <button type="button" class="primary self-start" onclick={startNewIngestion}>Add another document</button>
          {:else}
            <button
              type="button"
              class="primary self-start"
              disabled={newPhase === "submitting"}
              onclick={handleFinalizeNew}
            >
              {newPhase === "submitting" ? "Sending to Open WebUI…" : "Send to Open WebUI"}
            </button>
          {/if}
        {/if}
      {/if}
    </div>
  </div>
</div>
