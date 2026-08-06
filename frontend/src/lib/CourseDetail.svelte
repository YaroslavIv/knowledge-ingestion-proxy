<script>
  import {
    addCourseMaterial,
    approveCourseModule,
    authHeaders,
    bumpOutputVersion,
    createCourseModule,
    deleteCourseModule,
    deleteCourseProject,
    generateModuleOutput,
    getCourseProject,
    getGenerationContext,
    getKnowledgeBaseDetail,
    getModuleOutputContent,
    getModuleOutputDownloadUrl,
    getModuleOutputViewUrl,
    listAvailableModels,
    listCourseFeedback,
    listCourseModules,
    listKnowledgeBases,
    listModuleOutputVersions,
    publishModuleOutput,
    rejectCourseModule,
    removeCourseMaterial,
    seedCourseFeedback,
    splitCourseIntoModules,
    updateCourseModule,
  } from "./api.js";
  import { defaultModelId } from "./defaultModel.js";
  import DiffViewer from "./DiffViewer.svelte";
  import { suggestNextVersionTag } from "./versionTag.js";

  let { projectId, onBack = () => {}, onOpenKnowledgeCollection = (_id, _name) => {} } = $props();

  let project = $state(null);
  let modules = $state([]);
  let feedback = $state([]);
  let models = $state([]);
  let selectedModel = $state("");
  let error = $state(null);
  let deleting = $state(false);

  let feedbackText = $state("");
  let seedingFeedback = $state(false);
  let showFeedbackForm = $state(false);

  let splitting = $state(false);

  let addingModule = $state(false);
  let newModuleTitle = $state("");

  let editingModuleId = $state(null);
  let editTitle = $state("");
  let editObjectives = $state("");
  let editSourceRefs = $state("");

  async function loadAll() {
    error = null;
    try {
      const [p, m, f, mo] = await Promise.all([
        getCourseProject(projectId),
        listCourseModules(projectId),
        listCourseFeedback(projectId),
        listAvailableModels().catch(() => []),
      ]);
      project = p;
      modules = m;
      feedback = f;
      models = mo;
      if (!selectedModel && models.length > 0) selectedModel = defaultModelId(models);
      await loadCollectionDetails();
    } catch (e) {
      error = e.message;
    }
  }

  loadAll();

  // --- collections this project is built from (what they're for, what version) ---
  let collectionDetails = $state({}); // knowledgeId -> {name, version_tag, ...} | {error}

  const collectionRoles = $derived(
    project
      ? [
          {
            key: "competitors",
            label: "Competitors",
            description: "Competitive intelligence — competitor brochures and positioning. Optional.",
            knowledgeId: project.competitors_knowledge_id,
            emptyLabel: "Not used for this course",
          },
          {
            key: "instructions",
            label: "Instructions",
            description: "Course-generation methodology and accumulated review feedback — specific to how this course is built, kept separate from reusable product material.",
            knowledgeId: project.instructions_knowledge_id,
            emptyLabel: "Not set",
          },
          {
            key: "output",
            label: "Output",
            description: "Generated course deliverables — the actual lecture content per module, versioned per release.",
            knowledgeId: project.output_knowledge_id,
            emptyLabel: "Not published yet",
          },
        ]
      : [],
  );

  async function loadCollectionDetails() {
    if (!project) return;
    const ids = [
      ...(project.product_knowledge_ids ?? []),
      project.competitors_knowledge_id,
      project.instructions_knowledge_id,
      project.output_knowledge_id,
    ].filter(Boolean);
    const results = await Promise.all(
      ids.map((id) => getKnowledgeBaseDetail(id).then((d) => [id, d]).catch((e) => [id, { error: e.message }])),
    );
    collectionDetails = Object.fromEntries(results);
  }

  // --- product material: possibly several collections, add/remove ---
  let addingMaterial = $state(false);
  let allKnowledgeBases = $state(null);
  let materialQuery = $state("");
  let materialBusy = $state(false);

  async function openAddMaterial() {
    addingMaterial = true;
    materialQuery = "";
    if (allKnowledgeBases === null) {
      try {
        allKnowledgeBases = await listKnowledgeBases();
      } catch (e) {
        error = e.message;
      }
    }
  }

  const materialCandidates = $derived(
    (allKnowledgeBases ?? [])
      .filter((kb) => !(project?.product_knowledge_ids ?? []).includes(kb.id))
      .filter((kb) => !materialQuery || kb.name.toLowerCase().includes(materialQuery.toLowerCase())),
  );

  async function confirmAddMaterial(kb) {
    materialBusy = true;
    error = null;
    try {
      project = await addCourseMaterial(projectId, kb.id);
      addingMaterial = false;
      await loadCollectionDetails();
    } catch (e) {
      error = e.message;
    } finally {
      materialBusy = false;
    }
  }

  async function confirmRemoveMaterial(knowledgeId) {
    materialBusy = true;
    error = null;
    try {
      project = await removeCourseMaterial(projectId, knowledgeId);
      await loadCollectionDetails();
    } catch (e) {
      error = e.message;
    } finally {
      materialBusy = false;
    }
  }

  async function handleDeleteProject() {
    if (!confirm(`Delete course project "${project.name}"? This cannot be undone.`)) return;
    deleting = true;
    try {
      await deleteCourseProject(projectId);
      onBack();
    } catch (e) {
      error = e.message;
      deleting = false;
    }
  }

  async function handleSeedFeedback() {
    if (!feedbackText.trim()) return;
    seedingFeedback = true;
    error = null;
    try {
      await seedCourseFeedback(projectId, feedbackText);
      feedback = await listCourseFeedback(projectId);
      feedbackText = "";
      showFeedbackForm = false;
    } catch (e) {
      error = e.message;
    } finally {
      seedingFeedback = false;
    }
  }

  async function handleSplit() {
    if (!selectedModel) return;
    splitting = true;
    error = null;
    try {
      await splitCourseIntoModules(projectId, selectedModel);
      modules = await listCourseModules(projectId);
    } catch (e) {
      error = e.message;
    } finally {
      splitting = false;
    }
  }

  async function handleAddModule() {
    if (!newModuleTitle.trim()) return;
    try {
      const m = await createCourseModule(projectId, { title: newModuleTitle.trim() });
      modules = [...modules, m];
      newModuleTitle = "";
      addingModule = false;
    } catch (e) {
      error = e.message;
    }
  }

  function startEdit(m) {
    editingModuleId = m.id;
    editTitle = m.title;
    editObjectives = m.learning_objectives.join("\n");
    editSourceRefs = m.source_refs.join(", ");
  }

  async function saveEdit(m) {
    try {
      const updated = await updateCourseModule(projectId, m.id, {
        title: editTitle.trim(),
        learning_objectives: editObjectives.split("\n").map((s) => s.trim()).filter(Boolean),
        source_refs: editSourceRefs.split(",").map((s) => s.trim()).filter(Boolean),
      });
      modules = modules.map((x) => (x.id === m.id ? updated : x));
      editingModuleId = null;
    } catch (e) {
      error = e.message;
    }
  }

  async function handleApprove(m) {
    try {
      const updated = await approveCourseModule(projectId, m.id);
      modules = modules.map((x) => (x.id === m.id ? updated : x));
    } catch (e) {
      error = e.message;
    }
  }

  async function handleReject(m) {
    try {
      const updated = await rejectCourseModule(projectId, m.id);
      modules = modules.map((x) => (x.id === m.id ? updated : x));
    } catch (e) {
      error = e.message;
    }
  }

  async function handleDeleteModule(m) {
    if (!confirm(`Delete module "${m.title}"?`)) return;
    try {
      await deleteCourseModule(projectId, m.id);
      modules = modules.filter((x) => x.id !== m.id);
    } catch (e) {
      error = e.message;
    }
  }

  async function move(m, direction) {
    const idx = modules.findIndex((x) => x.id === m.id);
    const swapIdx = idx + direction;
    if (swapIdx < 0 || swapIdx >= modules.length) return;
    const other = modules[swapIdx];
    try {
      const [a, b] = await Promise.all([
        updateCourseModule(projectId, m.id, { order_index: other.order_index }),
        updateCourseModule(projectId, other.id, { order_index: m.order_index }),
      ]);
      const next = [...modules];
      next[idx] = b;
      next[swapIdx] = a;
      modules = next.sort((x, y) => x.order_index - y.order_index);
    } catch (e) {
      error = e.message;
    }
  }

  // --- output versioning ---
  let bumpingRelease = $state(false);
  let newReleaseTag = $state("");
  let publishingModuleId = $state(null);
  let publishNotes = $state("");
  let publishFile = $state(null);
  let openVersionsModuleId = $state(null);
  let versionsByModule = $state({});

  // Best-effort "current release" tag: the highest version_tag any module's
  // output currently carries (they normally all match right after a bump,
  // then diverge as modules get individually republished).
  const currentReleaseTag = $derived(
    [...modules.map((m) => m.current_output_version).filter(Boolean)].sort().pop() ?? "v1.0",
  );

  function startBumpRelease() {
    newReleaseTag = suggestNextVersionTag(currentReleaseTag);
    bumpingRelease = true;
  }

  async function confirmBumpRelease() {
    if (!newReleaseTag.trim()) return;
    try {
      project = await bumpOutputVersion(projectId, newReleaseTag.trim());
      await loadCollectionDetails();
      bumpingRelease = false;
    } catch (e) {
      error = e.message;
    }
  }

  function startPublish(m) {
    publishingModuleId = m.id;
    publishNotes = "";
    publishFile = null;
  }

  function handleFilePicked(event) {
    publishFile = event.target.files?.[0] ?? null;
  }

  async function confirmPublish(m) {
    if (!publishFile) return;
    try {
      await publishModuleOutput(projectId, m.id, publishFile, publishNotes);
      modules = await listCourseModules(projectId);
      project = await getCourseProject(projectId);
      await loadCollectionDetails();
      publishingModuleId = null;
      if (openVersionsModuleId === m.id) versionsByModule = { ...versionsByModule, [m.id]: await listModuleOutputVersions(projectId, m.id) };
    } catch (e) {
      error = e.message;
    }
  }

  async function toggleVersions(m) {
    const isOpen = openVersionsModuleId === m.id;
    openVersionsModuleId = isOpen ? null : m.id;
    if (!isOpen && !versionsByModule[m.id]) {
      try {
        versionsByModule = { ...versionsByModule, [m.id]: await listModuleOutputVersions(projectId, m.id) };
      } catch (e) {
        error = e.message;
      }
    }
  }

  // getModuleOutputViewUrl/getModuleOutputDownloadUrl point straight at the
  // backend — a plain <a href> navigation to them can't carry the
  // Authorization header, so once PROXY_REQUIRE_OWUI_AUTH is on they'd just
  // 401. Fetch with the header instead and hand the browser a blob URL,
  // same approach KnowledgeDetail.svelte already uses for the PDF preview.
  async function openModuleOutputFile(url, downloadFilename = null) {
    try {
      const resp = await fetch(url, { headers: authHeaders() });
      if (!resp.ok) throw new Error(`Failed to fetch (${resp.status})`);
      const blobUrl = URL.createObjectURL(await resp.blob());
      if (downloadFilename) {
        const a = document.createElement("a");
        a.href = blobUrl;
        a.download = downloadFilename;
        document.body.appendChild(a);
        a.click();
        a.remove();
      } else {
        window.open(blobUrl, "_blank", "noopener,noreferrer");
      }
      setTimeout(() => URL.revokeObjectURL(blobUrl), 30000);
    } catch (e) {
      error = e.message;
    }
  }

  // --- AI generate / revise ---
  let generatingModuleId = $state(null);
  let generateModel = $state("");
  let generateInstruction = $state("");
  let generateBusy = $state(false);
  // A brand-new module (e.g. a final test) may need to know what the other
  // modules actually cover, not just raw product material — opt in to pull
  // their real generated content into the prompt. Ignored when revising.
  let generateIncludeOtherModules = $state(false);
  // For a module that already exists but came out unusable (wrong layout,
  // colors, whatever) — small find/replace edits can't fix that, so this
  // discards the current version's content and does a full from-scratch
  // rewrite instead, keeping the old version in history.
  let generateRegenerateFromScratch = $state(false);
  // Shown right in the generate form itself, not just the page-level error
  // banner up top — that one's easy to miss when the module you're
  // generating for is scrolled far down the list.
  let generateError = $state(null);
  // What this exact call will pull in — always fetched fresh from the
  // collections (see backend's generate_output), never toggled off, so this
  // is a transparent preview, not a set of options that change what gets
  // sent. null while loading, so the panel can show "checking…" instead of
  // a misleading empty list.
  let generationContext = $state(null);
  let generationContextError = $state(null);

  async function startGenerate(m) {
    generatingModuleId = m.id;
    generateModel = generateModel || selectedModel || defaultModelId(models);
    generateInstruction = "";
    generateIncludeOtherModules = false;
    generateRegenerateFromScratch = false;
    generateError = null;
    generationContext = null;
    generationContextError = null;
    try {
      generationContext = await getGenerationContext(projectId, m.id);
    } catch (e) {
      generationContextError = e.message;
    }
  }

  async function confirmGenerate(m) {
    if (!generateModel || !generateInstruction.trim()) return;
    generateBusy = true;
    generateError = null;
    error = null;
    try {
      await generateModuleOutput(projectId, m.id, generateModel, generateInstruction.trim(), {
        includeOtherModules: generateIncludeOtherModules,
        regenerateFromScratch: generateRegenerateFromScratch,
      });
      modules = await listCourseModules(projectId);
      project = await getCourseProject(projectId);
      await loadCollectionDetails();
      generatingModuleId = null;
      if (openVersionsModuleId === m.id) {
        versionsByModule = { ...versionsByModule, [m.id]: await listModuleOutputVersions(projectId, m.id) };
      }
    } catch (e) {
      generateError = e.message;
    } finally {
      generateBusy = false;
    }
  }

  // --- diff between two versions of a module's output ---
  let diffModuleId = $state(null);
  let diffOldLabel = $state("");
  let diffNewLabel = $state("");
  let diffOldText = $state("");
  let diffNewText = $state("");
  let diffLoading = $state(false);

  async function showDiff(m, olderVersion, newerVersion) {
    if (diffModuleId === m.id && diffOldLabel === olderVersion.version_tag && diffNewLabel === newerVersion.version_tag) {
      diffModuleId = null;
      return;
    }
    diffLoading = true;
    error = null;
    try {
      const [oldRes, newRes] = await Promise.all([
        getModuleOutputContent(projectId, m.id, olderVersion.id),
        getModuleOutputContent(projectId, m.id, newerVersion.id),
      ]);
      diffOldText = oldRes.content;
      diffNewText = newRes.content;
      diffOldLabel = olderVersion.version_tag;
      diffNewLabel = newerVersion.version_tag;
      diffModuleId = m.id;
    } catch (e) {
      error = e.message;
    } finally {
      diffLoading = false;
    }
  }

  function statusBadgeClass(status) {
    if (status === "approved") return "bg-black text-white dark:bg-white dark:text-black";
    if (status === "rejected") return "bg-red-500/20 text-red-700 dark:text-red-300";
    return "bg-gray-200 dark:bg-gray-800 text-gray-600 dark:text-gray-400";
  }
</script>

<div class="flex flex-col gap-3">
  <div class="flex items-center gap-2 px-1">
    <button type="button" aria-label="Back to Courses" class="p-1 rounded-full hover:bg-gray-100 dark:hover:bg-gray-850 transition" onclick={onBack}>
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="size-4">
        <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5 8.25 12l7.5-7.5" />
      </svg>
    </button>
    <div class="text-xl font-medium">{project?.name ?? ""}</div>
    {#if project}
      <span class="text-xs font-mono bg-gray-100 dark:bg-gray-850 text-gray-700 dark:text-gray-300 px-2 py-0.5 rounded-full">
        {project.pedagogy_version} · {project.language}
      </span>
    {/if}
    <button
      type="button"
      aria-label="Delete course project"
      class="ml-auto p-1.5 rounded-full hover:bg-red-500/20 text-gray-400 hover:text-red-600 dark:hover:text-red-400 transition disabled:opacity-40"
      disabled={deleting}
      onclick={handleDeleteProject}
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

  {#if bumpingRelease}
    <div class="flex items-end gap-2 px-1">
      <div class="flex flex-col gap-0.5">
        <label for="release-tag" class="text-xs text-gray-500">New release tag</label>
        <input id="release-tag" class="text-sm px-2 py-1.5 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden font-mono w-32" bind:value={newReleaseTag} />
      </div>
      <button type="button" class="primary px-3 py-1.5" onclick={confirmBumpRelease}>Confirm</button>
      <button type="button" class="text-xs px-3 py-1.5" onclick={() => (bumpingRelease = false)}>Cancel</button>
      <span class="text-xs text-gray-500">
        Doesn't touch any module — the next module you publish output for becomes "changed in {newReleaseTag || "…"}".
      </span>
    </div>
  {/if}

  {#if error}<p class="text-red-500 text-sm px-1">{error}</p>{/if}

  <!-- Collections this course is built from -->
  <div class="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100/30 dark:border-gray-850/30 p-3 flex flex-col gap-2">
    <div class="text-sm font-medium">Collections</div>

    <!-- Product Material — possibly several collections, unlike the single-collection roles below -->
    <div class="flex flex-col gap-1.5 text-xs">
      <div class="flex items-center justify-between flex-wrap gap-1">
        <div class="flex flex-col gap-0.5">
          <span class="text-sm font-medium">Product Material</span>
          <span class="text-gray-500">Raw product material — datasheets, specs, positioning. Reusable for other tasks; not course-specific. Can span several collections.</span>
        </div>
        <button
          type="button"
          class="text-xs px-2.5 py-1 rounded-full border border-gray-200 dark:border-gray-800 hover:bg-gray-100 dark:hover:bg-gray-850 transition shrink-0"
          onclick={openAddMaterial}
        >
          + Add collection
        </button>
      </div>
      {#each project?.product_knowledge_ids ?? [] as knowledgeId (knowledgeId)}
        <div class="flex items-center gap-2 pl-2">
          <span class="text-gray-500 truncate flex-1">{collectionDetails[knowledgeId]?.name ?? knowledgeId}</span>
          {#if collectionDetails[knowledgeId]?.version_tag}
            <span class="font-mono px-1.5 py-0.5 rounded-full bg-gray-100 dark:bg-gray-850">{collectionDetails[knowledgeId].version_tag}</span>
          {/if}
          <button
            type="button"
            class="underline text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 shrink-0"
            onclick={() => onOpenKnowledgeCollection(knowledgeId, collectionDetails[knowledgeId]?.name ?? knowledgeId)}
          >
            Open
          </button>
          <button
            type="button"
            class="underline text-gray-500 hover:text-red-600 dark:hover:text-red-400 shrink-0 disabled:opacity-40"
            disabled={materialBusy}
            onclick={() => confirmRemoveMaterial(knowledgeId)}
          >
            Remove
          </button>
        </div>
      {/each}

      {#if addingMaterial}
        <div class="flex flex-col gap-2 bg-gray-50 dark:bg-gray-850 rounded-lg p-2">
          <input
            class="text-xs px-2 py-1.5 rounded-lg bg-white dark:bg-gray-900 outline-hidden"
            placeholder="Search knowledge bases…"
            bind:value={materialQuery}
          />
          {#if allKnowledgeBases === null}
            <div class="text-gray-500 py-1">Loading…</div>
          {:else if materialCandidates.length === 0}
            <div class="text-gray-500 py-1">Nothing left to add.</div>
          {:else}
            <div class="flex flex-col max-h-48 overflow-y-auto">
              {#each materialCandidates as kb (kb.id)}
                <button
                  type="button"
                  class="text-left px-2 py-1 rounded-lg hover:bg-white dark:hover:bg-gray-900 disabled:opacity-40"
                  disabled={materialBusy}
                  onclick={() => confirmAddMaterial(kb)}
                >
                  {kb.name}
                </button>
              {/each}
            </div>
          {/if}
          <button type="button" class="text-gray-500 self-start" onclick={() => (addingMaterial = false)}>Cancel</button>
        </div>
      {/if}
    </div>

    {#each collectionRoles as role (role.key)}
      <div class="flex items-center gap-3 text-xs border-t border-gray-100 dark:border-gray-850 pt-2">
        <div class="flex flex-col gap-0.5 flex-1 min-w-0">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="text-sm font-medium">{role.label}</span>
            {#if role.knowledgeId}
              <span class="text-gray-500 truncate">{collectionDetails[role.knowledgeId]?.name ?? ""}</span>
              {#if collectionDetails[role.knowledgeId]?.version_tag}
                <span class="font-mono px-1.5 py-0.5 rounded-full bg-gray-100 dark:bg-gray-850">
                  {collectionDetails[role.knowledgeId].version_tag}
                </span>
              {/if}
            {/if}
          </div>
          <span class="text-gray-500">{role.description}</span>
        </div>
        {#if role.knowledgeId}
          <button
            type="button"
            class="underline text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 shrink-0"
            onclick={() => onOpenKnowledgeCollection(role.knowledgeId, collectionDetails[role.knowledgeId]?.name ?? role.label)}
          >
            Open
          </button>
          {#if role.key === "output"}
            <button
              type="button"
              class="text-xs px-2.5 py-1 rounded-full border border-gray-200 dark:border-gray-800 hover:bg-gray-100 dark:hover:bg-gray-850 transition shrink-0"
              onclick={startBumpRelease}
            >
              Cut new release
            </button>
          {/if}
        {:else}
          <span class="text-gray-400 shrink-0">{role.emptyLabel}</span>
        {/if}
      </div>
    {/each}
  </div>

  <!-- Feedback / accumulated guidance -->
  <div class="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100/30 dark:border-gray-850/30 p-3 flex flex-col gap-2">
    <div class="flex items-center justify-between">
      <div class="text-sm font-medium">Generation guidance ({feedback.length})</div>
      <button type="button" class="text-xs underline text-gray-500 hover:text-gray-800 dark:hover:text-gray-200" onclick={() => (showFeedbackForm = !showFeedbackForm)}>
        + Add feedback notes
      </button>
    </div>
    {#if showFeedbackForm}
      <div class="flex flex-col gap-1.5">
        <textarea
          class="text-sm px-3 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden font-mono"
          rows="6"
          placeholder={"Paste reviewer feedback here (freeform text — optionally use ===Module N=== headings to scope notes to a module)"}
          bind:value={feedbackText}
        ></textarea>
        <button type="button" class="primary self-start px-4" disabled={seedingFeedback || !feedbackText.trim()} onclick={handleSeedFeedback}>
          {seedingFeedback ? "Parsing…" : "Parse & save notes"}
        </button>
      </div>
    {/if}
    {#if feedback.length > 0}
      <div class="flex flex-wrap gap-1.5">
        {#each feedback as note}
          <span class="text-xs px-2 py-1 rounded-lg border border-gray-200 dark:border-gray-800" title={note.note_text}>
            <span class="opacity-50">[{note.category}]</span>
            {note.note_text.length > 60 ? note.note_text.slice(0, 60) + "…" : note.note_text}
          </span>
        {/each}
      </div>
    {:else}
      <div class="text-xs text-gray-500">No guidance saved yet — past-mistake notes will be fed into every generation run for this project.</div>
    {/if}
  </div>

  <!-- Module splitting -->
  <div class="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100/30 dark:border-gray-850/30 p-3 flex flex-wrap items-end gap-2">
    <div class="flex flex-col gap-0.5">
      <label for="split-model" class="text-xs text-gray-500">Model</label>
      <select id="split-model" class="text-sm px-2 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden w-56" bind:value={selectedModel}>
        {#each models as m}<option value={m.id}>{m.name || m.id}</option>{/each}
      </select>
    </div>
    <button type="button" class="primary px-4" disabled={splitting || !selectedModel} onclick={handleSplit}>
      {splitting ? "Proposing modules…" : "Propose module breakdown"}
    </button>
    <span class="text-xs text-gray-500">Adds newly proposed modules — never touches ones already approved.</span>
  </div>

  <!-- Modules -->
  <div class="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100/30 dark:border-gray-850/30 p-3 flex flex-col gap-2">
    <div class="flex items-center justify-between">
      <div class="text-sm font-medium">Modules ({modules.length})</div>
      <button type="button" class="text-xs underline text-gray-500 hover:text-gray-800 dark:hover:text-gray-200" onclick={() => (addingModule = !addingModule)}>
        + Add module manually
      </button>
    </div>

    {#if addingModule}
      <div class="flex gap-1.5">
        <input class="flex-1 text-sm px-3 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden" placeholder="Module title" bind:value={newModuleTitle} />
        <button type="button" class="px-3 py-1.5 rounded-xl bg-black text-white dark:bg-white dark:text-black text-sm" onclick={handleAddModule}>Add</button>
      </div>
    {/if}

    {#if modules.length === 0}
      <div class="text-sm text-gray-500 px-1 py-4 text-center">No modules yet — propose a breakdown above, or add one manually.</div>
    {/if}

    {#each modules as m, i (m.id)}
      <div class="rounded-xl border border-gray-100 dark:border-gray-850 p-3 flex flex-col gap-2">
        <div class="flex items-center gap-2">
          <div class="flex flex-col">
            <button type="button" class="text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 disabled:opacity-30" disabled={i === 0} onclick={() => move(m, -1)}>▲</button>
            <button type="button" class="text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 disabled:opacity-30" disabled={i === modules.length - 1} onclick={() => move(m, 1)}>▼</button>
          </div>

          {#if editingModuleId === m.id}
            <input class="flex-1 text-sm font-medium px-2 py-1 rounded-lg bg-gray-50 dark:bg-gray-850 outline-hidden" bind:value={editTitle} />
          {:else}
            <div class="flex-1 text-sm font-medium">{m.title}</div>
          {/if}

          <span class="text-[0.65rem] px-1.5 py-0.5 rounded-full {statusBadgeClass(m.status)}">{m.status}</span>

          {#if editingModuleId === m.id}
            <button type="button" class="text-xs px-2 py-1 rounded-lg bg-black text-white dark:bg-white dark:text-black" onclick={() => saveEdit(m)}>Save</button>
            <button type="button" class="text-xs px-2 py-1 rounded-lg" onclick={() => (editingModuleId = null)}>Cancel</button>
          {:else}
            <button type="button" class="text-xs underline text-gray-500" onclick={() => startEdit(m)}>Edit</button>
          {/if}

          {#if m.status !== "approved"}
            <button type="button" class="text-xs px-2 py-1 rounded-lg border border-gray-200 dark:border-gray-800" onclick={() => handleApprove(m)}>Approve</button>
          {/if}
          {#if m.status !== "rejected"}
            <button type="button" class="text-xs px-2 py-1 rounded-lg border border-gray-200 dark:border-gray-800" onclick={() => handleReject(m)}>Reject</button>
          {/if}
          <button
            type="button"
            aria-label="Delete module"
            class="p-1 rounded-full hover:bg-red-500/20 text-gray-400 hover:text-red-600 dark:hover:text-red-400 transition"
            onclick={() => handleDeleteModule(m)}
          >
            <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-3.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {#if editingModuleId === m.id}
          <div class="flex flex-col gap-1 pl-6">
            <label class="text-xs text-gray-500" for="objectives-{m.id}">Learning objectives (one per line)</label>
            <textarea id="objectives-{m.id}" class="text-xs px-2 py-1.5 rounded-lg bg-gray-50 dark:bg-gray-850 outline-hidden" rows="3" bind:value={editObjectives}></textarea>
            <label class="text-xs text-gray-500" for="refs-{m.id}">Source files (comma-separated filenames)</label>
            <input id="refs-{m.id}" class="text-xs px-2 py-1.5 rounded-lg bg-gray-50 dark:bg-gray-850 outline-hidden" bind:value={editSourceRefs} />
          </div>
        {:else}
          <div class="pl-6 flex flex-col gap-1">
            {#if m.learning_objectives.length > 0}
              <ul class="text-xs text-gray-600 dark:text-gray-400 list-disc pl-4">
                {#each m.learning_objectives as obj}<li>{obj}</li>{/each}
              </ul>
            {/if}
            {#if m.source_refs.length > 0}
              <div class="flex flex-wrap gap-1">
                {#each m.source_refs as ref}
                  <span class="text-[0.65rem] px-1.5 py-0.5 rounded-full border border-gray-200 dark:border-gray-800 text-gray-500">{ref}</span>
                {/each}
              </div>
            {/if}
          </div>
        {/if}

        <!-- Generated output — versioned deliverable for this module -->
        <div class="pl-6 flex flex-col gap-1.5 pt-1 border-t border-gray-100 dark:border-gray-850 mt-1">
          <div class="flex items-center gap-2 flex-wrap">
            {#if m.current_output_version}
              <span class="text-[0.65rem] font-medium px-1.5 py-0.5 rounded-full bg-black text-white dark:bg-white dark:text-black">
                Output {m.current_output_version}
              </span>
              <span class="text-xs text-gray-500 truncate">{m.output_filename}</span>
            {:else}
              <span class="text-xs text-gray-500">No output published yet</span>
            {/if}
            <button type="button" class="text-xs underline text-gray-500 hover:text-gray-800 dark:hover:text-gray-200" onclick={() => startPublish(m)}>
              {m.current_output_version ? "Publish new version" : "Publish output"}
            </button>
            <button type="button" class="text-xs underline text-gray-500 hover:text-gray-800 dark:hover:text-gray-200" onclick={() => startGenerate(m)}>
              {m.current_output_version ? "Revise with AI" : "Generate with AI"}
            </button>
            {#if m.current_output_version}
              <button type="button" class="text-xs underline text-gray-500 hover:text-gray-800 dark:hover:text-gray-200" onclick={() => toggleVersions(m)}>
                {openVersionsModuleId === m.id ? "Hide history" : "History"}
              </button>
            {/if}
          </div>

          {#if publishingModuleId === m.id}
            <div class="flex flex-col gap-1.5 bg-gray-50 dark:bg-gray-850 rounded-lg p-2">
              <input type="file" onchange={handleFilePicked} />
              <input class="text-xs px-2 py-1 rounded-lg bg-white dark:bg-gray-900 outline-hidden" placeholder="What changed in this version? (optional)" bind:value={publishNotes} />
              <div class="flex gap-1.5">
                <button type="button" class="text-xs px-2 py-1 rounded-lg bg-black text-white dark:bg-white dark:text-black" disabled={!publishFile} onclick={() => confirmPublish(m)}>
                  Publish
                </button>
                <button type="button" class="text-xs px-2 py-1 rounded-lg" onclick={() => (publishingModuleId = null)}>Cancel</button>
              </div>
            </div>
          {/if}

          {#if generatingModuleId === m.id}
            <div class="flex flex-col gap-1.5 bg-gray-50 dark:bg-gray-850 rounded-lg p-2">
              <div class="text-xs px-2 py-1.5 rounded-lg bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800">
                <div class="font-medium text-gray-500 mb-1">This will pull in:</div>
                {#if generationContextError}
                  <p class="text-red-500">{generationContextError}</p>
                {:else if generationContext === null}
                  <p class="text-gray-400 animate-pulse">Checking collections…</p>
                {:else}
                  <ul class="flex flex-col gap-0.5 text-gray-600 dark:text-gray-400">
                    <li>
                      Product material ({generationContext.product_files.length} collection{generationContext.product_files.length === 1 ? "" : "s"}):
                      {#if generationContext.product_files.length === 0}
                        none
                      {:else}
                        <ul class="pl-4 list-disc">
                          {#each generationContext.product_files as group (group.knowledge_id)}
                            <li>
                              {group.knowledge_name} — {group.filenames.length} file{group.filenames.length === 1 ? "" : "s"}{group.filenames.length
                                ? `: ${group.filenames.join(", ")}`
                                : ""}
                            </li>
                          {/each}
                        </ul>
                      {/if}
                    </li>
                    <li>
                      Instructions/methodology ({generationContext.instructions_files.length} file{generationContext.instructions_files.length === 1 ? "" : "s"}):
                      {generationContext.instructions_files.join(", ") || "none"}
                    </li>
                    <li>
                      {generationContext.feedback_notes_count} past-feedback note{generationContext.feedback_notes_count === 1 ? "" : "s"}
                      <span class="text-gray-400">(stored in this proxy, not a knowledge-base collection)</span>
                    </li>
                    {#if generationContext.has_current_version}
                      <li>
                        The module's current page — {generateRegenerateFromScratch
                          ? "will be discarded (regenerating from scratch)"
                          : "will be revised in place via targeted edits"}
                      </li>
                    {/if}
                  </ul>
                {/if}
              </div>
              <select class="text-xs px-2 py-1.5 rounded-lg bg-white dark:bg-gray-900 outline-hidden" bind:value={generateModel}>
                {#each models as mo}<option value={mo.id}>{mo.name || mo.id}</option>{/each}
              </select>
              <textarea
                class="text-xs px-2 py-1.5 rounded-lg bg-white dark:bg-gray-900 outline-hidden"
                rows="3"
                placeholder={m.current_output_version && !generateRegenerateFromScratch
                  ? "Describe the change, e.g. 'Add two more practice exercises' or 'Restyle the interactive blocks to use a blue accent color'"
                  : "Describe what this module's lecture page should cover — used together with the product material and methodology"}
                bind:value={generateInstruction}
              ></textarea>
              {#if m.current_output_version}
                <label class="flex items-center gap-1.5 text-xs text-gray-500">
                  <input type="checkbox" bind:checked={generateRegenerateFromScratch} />
                  Regenerate from scratch instead of revising (use if this module came out broken/unstyled — discards
                  its current content and rewrites it fully; the old version is kept in history)
                </label>
              {/if}
              {#if !m.current_output_version || generateRegenerateFromScratch}
                <label class="flex items-center gap-1.5 text-xs text-gray-500">
                  <input type="checkbox" bind:checked={generateIncludeOtherModules} />
                  Base this on the other modules' actual content (e.g. for a final test that should only quiz what's really in the course)
                </label>
              {/if}
              <div class="flex gap-1.5 items-center">
                <button
                  type="button"
                  class="text-xs px-2 py-1 rounded-lg bg-black text-white dark:bg-white dark:text-black disabled:opacity-40"
                  disabled={generateBusy || !generateModel || !generateInstruction.trim()}
                  onclick={() => confirmGenerate(m)}
                >
                  {generateBusy ? "Generating…" : "Generate"}
                </button>
                <button type="button" class="text-xs px-2 py-1 rounded-lg" disabled={generateBusy} onclick={() => (generatingModuleId = null)}>Cancel</button>
              </div>
              {#if generateError}
                <p class="text-red-500 text-xs">{generateError}</p>
              {/if}
            </div>
          {/if}

          {#if openVersionsModuleId === m.id}
            <div class="flex flex-col gap-1">
              {#each versionsByModule[m.id] ?? [] as v, vi}
                <div class="flex items-center gap-2 text-xs">
                  <span class="font-mono px-1.5 py-0.5 rounded-full {v.is_current ? 'bg-gray-200 dark:bg-gray-800' : 'opacity-50'}">{v.version_tag}</span>
                  <span class="text-gray-500 truncate flex-1">{v.filename}</span>
                  <span class="text-gray-400">{Math.round(v.size / 1024)} KB</span>
                  {#if v.has_html}
                    <button
                      type="button"
                      class="underline text-gray-500 hover:text-gray-800 dark:hover:text-gray-200"
                      onclick={() => openModuleOutputFile(getModuleOutputViewUrl(projectId, m.id, v.id))}
                    >
                      View
                    </button>
                  {/if}
                  <button
                    type="button"
                    class="underline text-gray-500 hover:text-gray-800 dark:hover:text-gray-200"
                    onclick={() => openModuleOutputFile(getModuleOutputDownloadUrl(projectId, m.id, v.id), v.filename)}
                  >
                    Download
                  </button>
                  {#if v.has_html && vi + 1 < (versionsByModule[m.id] ?? []).length && versionsByModule[m.id][vi + 1].has_html}
                    <button
                      type="button"
                      class="underline text-gray-500 hover:text-gray-800 dark:hover:text-gray-200"
                      disabled={diffLoading}
                      onclick={() => showDiff(m, versionsByModule[m.id][vi + 1], v)}
                    >
                      {diffModuleId === m.id && diffOldLabel === versionsByModule[m.id][vi + 1].version_tag && diffNewLabel === v.version_tag
                        ? "Hide diff"
                        : "Diff vs previous"}
                    </button>
                  {/if}
                </div>
              {/each}
            </div>

            {#if diffModuleId === m.id}
              <DiffViewer oldText={diffOldText} newText={diffNewText} oldLabel={diffOldLabel} newLabel={diffNewLabel} />
            {/if}
          {/if}
        </div>
      </div>
    {/each}
  </div>
</div>
