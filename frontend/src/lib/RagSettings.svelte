<script>
  import { getRagSettings, listKnowledgeBaseFiles, listKnowledgeBases, reembedFile, updateRagSettings } from "./api.js";

  let settings = $state(null); // {chunk_size, chunk_overlap, embedding_engine, embedding_model} | null
  let loadError = $state(null);

  let chunkSize = $state("");
  let chunkOverlap = $state("");
  let chunkBusy = $state(false);
  let chunkError = $state(null);
  let chunkSaved = $state(false);

  let embeddingEngine = $state("");
  let embeddingModel = $state("");
  let embeddingBatchSize = $state("");
  let embeddingConcurrentRequests = $state("");
  let embeddingBusy = $state(false);
  let embeddingError = $state(null);
  let embeddingSaved = $state(false);

  async function load() {
    loadError = null;
    try {
      settings = await getRagSettings();
      chunkSize = String(settings.chunk_size);
      chunkOverlap = String(settings.chunk_overlap);
      embeddingEngine = settings.embedding_engine;
      embeddingModel = settings.embedding_model;
      embeddingBatchSize = String(settings.embedding_batch_size);
      embeddingConcurrentRequests = String(settings.embedding_concurrent_requests);
    } catch (e) {
      loadError = e.message;
    }
  }

  load();

  async function saveChunking() {
    chunkBusy = true;
    chunkError = null;
    chunkSaved = false;
    try {
      settings = await updateRagSettings({ chunk_size: Number(chunkSize), chunk_overlap: Number(chunkOverlap) });
      chunkSaved = true;
    } catch (e) {
      chunkError = e.message;
    } finally {
      chunkBusy = false;
    }
  }

  async function saveEmbedding() {
    embeddingBusy = true;
    embeddingError = null;
    embeddingSaved = false;
    try {
      settings = await updateRagSettings({
        embedding_engine: embeddingEngine,
        embedding_model: embeddingModel,
        embedding_batch_size: Number(embeddingBatchSize),
        embedding_concurrent_requests: Number(embeddingConcurrentRequests),
      });
      embeddingSaved = true;
    } catch (e) {
      embeddingError = e.message;
    } finally {
      embeddingBusy = false;
    }
  }

  // --- re-embed every file in every collection — the instance-wide version
  // of the per-collection button on the Knowledge page. Driven from here
  // (rather than one backend call looping internally) for the same reason
  // as the per-collection version: live progress across what can be a very
  // large amount of work, instead of one opaque wait. ---
  let reembedBusy = $state(false);
  let reembedProgress = $state(null); // {collectionsDone, collectionsTotal, filesDone, filesTotal, collectionName, filename} | null
  let reembedFailed = $state([]); // [{collection, filename, reason}]

  async function handleReembedAll() {
    let knowledgeBases;
    try {
      knowledgeBases = await listKnowledgeBases();
    } catch (e) {
      loadError = e.message;
      return;
    }

    const perCollectionFiles = [];
    for (const kb of knowledgeBases) {
      try {
        perCollectionFiles.push({ kb, files: await listKnowledgeBaseFiles(kb.id) });
      } catch (e) {
        reembedFailed = [...reembedFailed, { collection: kb.name, filename: "(listing files)", reason: e.message }];
      }
    }
    const filesTotal = perCollectionFiles.reduce((sum, c) => sum + c.files.length, 0);

    if (
      !confirm(
        `Re-embed every file across all ${knowledgeBases.length} collection(s) (${filesTotal} file(s) total) using ` +
          "Open WebUI's current embedding model and chunk settings?\n\n" +
          "This re-pushes each file's existing text unchanged, one file at a time, and can take a long while for " +
          "this many files — don't close this tab while it runs.",
      )
    )
      return;

    reembedBusy = true;
    reembedFailed = [];
    reembedProgress = {
      collectionsDone: 0,
      collectionsTotal: perCollectionFiles.length,
      filesDone: 0,
      filesTotal,
      collectionName: "",
      filename: "",
    };

    for (const { kb, files } of perCollectionFiles) {
      reembedProgress = { ...reembedProgress, collectionName: kb.name };
      for (const f of files) {
        reembedProgress = { ...reembedProgress, filename: f.filename };
        try {
          await reembedFile(kb.id, f.id);
        } catch (e) {
          reembedFailed = [...reembedFailed, { collection: kb.name, filename: f.filename, reason: e.message }];
        }
        reembedProgress = { ...reembedProgress, filesDone: reembedProgress.filesDone + 1 };
      }
      reembedProgress = { ...reembedProgress, collectionsDone: reembedProgress.collectionsDone + 1 };
    }
    reembedBusy = false;
  }
</script>

{#snippet spinner()}
  <svg class="animate-spin size-3.5 shrink-0" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V4a8 8 0 00-8 8h0z"></path>
  </svg>
{/snippet}

<div class="flex flex-col gap-3">
  <div class="text-xl font-medium px-1">RAG Settings</div>

  {#if loadError}
    <p class="text-red-500 text-sm px-1">{loadError}</p>
  {/if}

  {#if settings === null && !loadError}
    <div class="text-sm text-gray-500 animate-pulse px-1">Loading…</div>
  {:else if settings}
    <div class="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100/30 dark:border-gray-850/30 p-3 flex flex-col gap-2">
      <div class="text-sm font-medium">Chunking</div>
      <div class="text-xs text-gray-500">
        Applies to files processed from now on. Existing files keep whatever chunks they already have until
        re-embedded (see below) — this alone never deletes anything.
      </div>
      <div class="grid grid-cols-2 gap-2">
        <div class="flex flex-col gap-0.5">
          <label for="chunk-size" class="text-xs text-gray-500">Chunk size</label>
          <input
            id="chunk-size"
            type="number"
            min="1"
            class="text-sm px-2 py-1.5 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden"
            bind:value={chunkSize}
          />
        </div>
        <div class="flex flex-col gap-0.5">
          <label for="chunk-overlap" class="text-xs text-gray-500">Chunk overlap</label>
          <input
            id="chunk-overlap"
            type="number"
            min="0"
            class="text-sm px-2 py-1.5 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden"
            bind:value={chunkOverlap}
          />
        </div>
      </div>
      <div class="flex items-center gap-2">
        <button
          type="button"
          class="primary flex items-center gap-1.5 px-4"
          disabled={chunkBusy || !chunkSize || chunkOverlap === ""}
          onclick={saveChunking}
        >
          {#if chunkBusy}{@render spinner()}{/if}
          {chunkBusy ? "Saving…" : "Save chunking"}
        </button>
        {#if chunkSaved}<span class="text-xs text-green-600 dark:text-green-400">Saved.</span>{/if}
      </div>
      {#if chunkError}<p class="text-red-500 text-xs">{chunkError}</p>{/if}
    </div>

    <div class="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100/30 dark:border-gray-850/30 p-3 flex flex-col gap-2">
      <div class="text-sm font-medium">Embedding model</div>
      <div class="text-xs text-gray-500">
        Applies to files embedded from now on. Existing files keep their current vectors — computed with whatever
        model was active when they were last (re-)embedded — until you re-embed them (see below). Changing this
        alone never deletes anything; that lives on Open WebUI's own separate "Reset" actions, which this proxy
        never calls.
      </div>
      <div class="grid grid-cols-2 gap-2">
        <div class="flex flex-col gap-0.5">
          <label for="embedding-engine" class="text-xs text-gray-500">Engine</label>
          <select
            id="embedding-engine"
            class="text-sm px-2 py-1.5 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden"
            bind:value={embeddingEngine}
          >
            <option value="">Default (local)</option>
            <option value="ollama">Ollama</option>
            <option value="openai">OpenAI-compatible</option>
            <option value="azure_openai">Azure OpenAI</option>
          </select>
        </div>
        <div class="flex flex-col gap-0.5">
          <label for="embedding-model" class="text-xs text-gray-500">Model</label>
          <input
            id="embedding-model"
            class="text-sm px-2 py-1.5 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden"
            placeholder="e.g. qwen3-embedding:0.6b"
            bind:value={embeddingModel}
          />
        </div>
        <div class="flex flex-col gap-0.5">
          <label for="embedding-batch-size" class="text-xs text-gray-500">Batch size (chunks per request)</label>
          <input
            id="embedding-batch-size"
            type="number"
            min="1"
            class="text-sm px-2 py-1.5 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden"
            bind:value={embeddingBatchSize}
          />
        </div>
        <div class="flex flex-col gap-0.5">
          <label for="embedding-concurrency" class="text-xs text-gray-500">Max concurrent requests</label>
          <input
            id="embedding-concurrency"
            type="number"
            min="1"
            class="text-sm px-2 py-1.5 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden"
            bind:value={embeddingConcurrentRequests}
          />
          <span class="text-[0.65rem] text-gray-400">
            0 here means Open WebUI applies no limit at all — with batch size 1, embedding a large document can open
            one connection per chunk at once and exhaust the server's open-file limit. Keep this at 1 or higher.
          </span>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <button
          type="button"
          class="primary flex items-center gap-1.5 px-4"
          disabled={embeddingBusy || !embeddingModel.trim() || !embeddingBatchSize || !embeddingConcurrentRequests}
          onclick={saveEmbedding}
        >
          {#if embeddingBusy}{@render spinner()}{/if}
          {embeddingBusy ? "Saving…" : "Save embedding model"}
        </button>
        {#if embeddingSaved}<span class="text-xs text-green-600 dark:text-green-400">Saved.</span>{/if}
      </div>
      {#if embeddingError}<p class="text-red-500 text-xs">{embeddingError}</p>{/if}
    </div>

    <div class="bg-white dark:bg-gray-900 rounded-2xl border border-gray-100/30 dark:border-gray-850/30 p-3 flex flex-col gap-2">
      <div class="text-sm font-medium">Re-embed everything</div>
      <div class="text-xs text-gray-500">
        Re-pushes every file's existing text, unchanged, across <strong>every</strong> collection — forcing Open
        WebUI to recompute embeddings for all of it under whatever chunking/model is active above. Use this after
        changing either setting so existing content actually picks it up. Only re-pushes text that's already
        there — never deletes a collection, a file, or anything else.
      </div>
      <button
        type="button"
        class="primary self-start flex items-center gap-1.5 px-4"
        disabled={reembedBusy}
        onclick={handleReembedAll}
      >
        {#if reembedBusy}{@render spinner()}{/if}
        {reembedBusy ? "Re-embedding…" : "Re-embed all collections"}
      </button>

      {#if reembedProgress}
        <div class="text-xs px-2.5 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 flex flex-col gap-1.5">
          <div class="flex items-center gap-1.5 text-gray-600 dark:text-gray-400">
            <span class="font-medium">
              {reembedBusy ? "Re-embedding" : "Re-embedded"}
              {reembedProgress.filesDone}/{reembedProgress.filesTotal} file(s) across
              {reembedProgress.collectionsDone}/{reembedProgress.collectionsTotal} collection(s)
            </span>
            {#if reembedBusy}
              <span class="truncate opacity-70">— {reembedProgress.collectionName} / {reembedProgress.filename}</span>
            {/if}
            {#if !reembedBusy}
              <button
                type="button"
                class="ml-auto text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 underline shrink-0"
                onclick={() => (reembedProgress = null)}
              >
                Dismiss
              </button>
            {/if}
          </div>
          <div class="w-full h-1.5 rounded-full bg-gray-200 dark:bg-gray-800 overflow-hidden">
            <div
              class="h-full bg-black dark:bg-white transition-[width] duration-150"
              style="width: {reembedProgress.filesTotal ? Math.round((reembedProgress.filesDone / reembedProgress.filesTotal) * 100) : 0}%"
            ></div>
          </div>
          {#if reembedFailed.length > 0}
            <div class="text-red-500">
              {reembedFailed.length} failed:
              {reembedFailed.map((f) => `${f.collection} / ${f.filename} (${f.reason})`).join("; ")}
            </div>
          {/if}
        </div>
      {/if}
    </div>
  {/if}
</div>
