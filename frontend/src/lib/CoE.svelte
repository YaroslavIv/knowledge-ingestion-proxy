<script>
  import { compareByTag, getLatestCollectionsByTag, listKnowledgeBases, searchByTag, updateCollectionTags } from "./api.js";

  // Hardcoded on purpose — this is a dedicated tab for the one tag the team
  // actually uses to mean "in active use", not a general tag browser.
  const TAG = "coe";

  let { onOpenKnowledge = (_id, _name) => {} } = $props();

  let rows = $state(null);
  let error = $state(null);
  let copiedId = $state(null);

  let adding = $state(false);
  let allItems = $state(null);
  let addQuery = $state("");
  let addBusy = $state(false);

  async function load() {
    error = null;
    try {
      rows = await getLatestCollectionsByTag(TAG);
    } catch (e) {
      error = e.message;
    }
  }

  load();

  async function copyId(id) {
    try {
      await navigator.clipboard.writeText(id);
      copiedId = id;
      setTimeout(() => {
        if (copiedId === id) copiedId = null;
      }, 1500);
    } catch {
      // Clipboard API unavailable (e.g. insecure context) — nothing to fall back to.
    }
  }

  async function openAdd() {
    adding = true;
    addQuery = "";
    if (allItems === null) {
      try {
        allItems = await listKnowledgeBases();
      } catch (e) {
        error = e.message;
      }
    }
  }

  const addCandidates = $derived(
    (allItems ?? [])
      .filter((kb) => !(kb.tags ?? []).includes(TAG))
      .filter((kb) => !addQuery || kb.name.toLowerCase().includes(addQuery.toLowerCase())),
  );

  async function addToTag(kb) {
    addBusy = true;
    error = null;
    try {
      await updateCollectionTags(kb.id, [...(kb.tags ?? []), TAG]);
      adding = false;
      await load();
    } catch (e) {
      error = e.message;
    } finally {
      addBusy = false;
    }
  }

  // --- search (pure retrieval, no generation) ---
  // For judging embedding-model quality directly: are the real top matches
  // for a query actually relevant, without an LLM's phrasing smoothing over
  // mediocre retrieval either way.
  let searchQuery = $state("");
  let searching = $state(false);
  let searchError = $state(null);
  let searchResults = $state(null); // null = no search run yet
  let expandedResults = $state(new Set()); // indices of results shown in full

  async function handleSearch() {
    const query = searchQuery.trim();
    if (!query) return;
    searching = true;
    searchError = null;
    try {
      const resp = await searchByTag(TAG, query);
      searchResults = resp.results;
      expandedResults = new Set();
    } catch (e) {
      searchError = e.message;
    } finally {
      searching = false;
    }
  }

  function formatScore(score) {
    return score === null || score === undefined ? "—" : score.toFixed(3);
  }

  function toggleExpanded(i) {
    const next = new Set(expandedResults);
    if (next.has(i)) next.delete(i);
    else next.add(i);
    expandedResults = next;
  }

  // --- compare two queries (still pure retrieval, no generation) ---
  // For robustness checks: does a paraphrase, a translation, or reordered
  // wording of "the same" question retrieve the same content? Diffs two
  // independent searches — see backend/app/retrieval_router.py's
  // compare_searches for how files/chunks are matched and scored.
  let compareMode = $state(false);
  let queryA = $state("");
  let queryB = $state("");
  let comparing = $state(false);
  let compareError = $state(null);
  let compareResult = $state(null); // { results_a, results_b, comparison } | null
  let expandedA = $state(new Set());
  let expandedB = $state(new Set());

  async function handleCompare() {
    const a = queryA.trim();
    const b = queryB.trim();
    if (!a || !b) return;
    comparing = true;
    compareError = null;
    try {
      compareResult = await compareByTag(TAG, a, b);
      expandedA = new Set();
      expandedB = new Set();
    } catch (e) {
      compareError = e.message;
    } finally {
      comparing = false;
    }
  }

  function toggleExpandedIn(which, i) {
    const current = which === "a" ? expandedA : expandedB;
    const next = new Set(current);
    if (next.has(i)) next.delete(i);
    else next.add(i);
    if (which === "a") expandedA = next;
    else expandedB = next;
  }

  function formatDistance(d) {
    if (d === null || d === undefined) return "unknown position";
    if (d === 0) return "same chunk";
    return `${d} chunk${d > 1 ? "s" : ""} apart`;
  }

  function formatDelta(d) {
    if (d === null || d === undefined) return "—";
    return `${d > 0 ? "+" : ""}${d.toFixed(3)}`;
  }

  const avgAbsDelta = $derived.by(() => {
    if (!compareResult) return null;
    const deltas = compareResult.comparison.matches
      .map((m) => m.score_delta)
      .filter((d) => d !== null && d !== undefined);
    if (deltas.length === 0) return null;
    return deltas.reduce((sum, d) => sum + Math.abs(d), 0) / deltas.length;
  });
</script>

{#snippet resultCard(result, expanded, onToggle)}
  <div class="flex flex-col gap-1 rounded-xl border border-gray-100 dark:border-gray-850 p-2.5">
    <div class="flex items-center justify-between gap-2">
      <span class="text-xs font-medium truncate">{result.filename ?? "(unknown file)"}</span>
      <span class="text-xs font-mono text-gray-500 shrink-0">score {formatScore(result.score)}</span>
    </div>
    <p class="text-xs text-gray-600 dark:text-gray-400 whitespace-pre-wrap {expanded ? '' : 'line-clamp-4'}">
      {result.document}
    </p>
    {#if result.document.length > 240}
      <button type="button" class="text-xs text-gray-500 underline self-start" onclick={onToggle}>
        {expanded ? "Show less" : "Show full chunk"}
      </button>
    {/if}
  </div>
{/snippet}

{#snippet spinner()}
  <svg class="animate-spin size-3.5 shrink-0" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V4a8 8 0 00-8 8h0z"></path>
  </svg>
{/snippet}

<div class="flex flex-col gap-3">
  <div class="flex justify-between items-center px-1">
    <div class="flex items-center gap-2 text-xl font-medium">
      <div>CoE</div>
      <div class="text-lg font-medium text-gray-500 dark:text-gray-500">{rows?.length ?? 0}</div>
    </div>
    <button
      type="button"
      class="px-2 py-1.5 rounded-xl bg-black text-white dark:bg-white dark:text-black transition font-medium text-sm flex items-center"
      onclick={openAdd}
    >
      <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor" class="size-3">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
      </svg>
      <div class="ml-1 text-xs">Add collection</div>
    </button>
  </div>

  {#if adding}
    <div class="flex flex-col gap-2 bg-white dark:bg-gray-900 rounded-2xl border border-gray-100/30 dark:border-gray-850/30 p-3">
      <input
        class="text-sm px-3 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden"
        placeholder="Search knowledge bases…"
        bind:value={addQuery}
      />
      {#if allItems === null}
        <div class="text-sm text-gray-500 py-2">Loading…</div>
      {:else if addCandidates.length === 0}
        <div class="text-sm text-gray-500 py-2">Nothing left to add — everything matching is already tagged "{TAG}".</div>
      {:else}
        <div class="flex flex-col max-h-64 overflow-y-auto">
          {#each addCandidates as kb (kb.id)}
            <button
              type="button"
              class="flex justify-between items-center text-sm px-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 text-left disabled:opacity-40"
              disabled={addBusy}
              onclick={() => addToTag(kb)}
            >
              <span class="truncate">{kb.name}</span>
              {#if kb.version_tag}<span class="text-xs font-mono text-gray-500 shrink-0 ml-2">{kb.version_tag}</span>{/if}
            </button>
          {/each}
        </div>
      {/if}
      <button type="button" class="text-xs text-gray-500 self-start" onclick={() => (adding = false)}>Cancel</button>
    </div>
  {/if}

  <div class="py-2 bg-white dark:bg-gray-900 rounded-3xl border border-gray-100/30 dark:border-gray-850/30 overflow-x-auto">
    {#if rows === null}
      <div class="w-full h-full flex justify-center items-center py-10">
        <span class="text-sm text-gray-500 animate-pulse">Loading…</span>
      </div>
    {:else if rows.length === 0}
      <div class="w-full flex flex-col justify-center items-center my-12">
        <div class="text-lg font-medium mb-1">Nothing tagged "{TAG}" yet</div>
        <div class="text-gray-500 text-center text-xs">
          Use "Add collection" above, or tag one from the Knowledge tab.
        </div>
      </div>
    {:else}
      <table class="w-full text-sm">
        <thead>
          <tr class="text-xs text-gray-500 text-left">
            <th class="px-3 py-1.5 font-medium">Name</th>
            <th class="px-3 py-1.5 font-medium">Version</th>
            <th class="px-3 py-1.5 font-medium">ID</th>
          </tr>
        </thead>
        <tbody>
          {#each rows as row (row.id)}
            <tr
              class="hover:bg-gray-50 dark:hover:bg-gray-850/50 cursor-pointer"
              onclick={() => onOpenKnowledge(row.id, row.name)}
            >
              <td class="px-3 py-2 font-medium">{row.name}</td>
              <td class="px-3 py-2 font-mono text-xs text-gray-500">{row.version_tag}</td>
              <td class="px-3 py-2">
                <div class="flex items-center gap-1.5">
                  <span class="font-mono text-xs text-gray-500 truncate max-w-[12rem]">{row.id}</span>
                  <button
                    type="button"
                    class="text-xs px-1.5 py-0.5 rounded-md border border-gray-200 dark:border-gray-800 hover:bg-gray-100 dark:hover:bg-gray-850 shrink-0"
                    onclick={(e) => {
                      e.stopPropagation();
                      copyId(row.id);
                    }}
                  >
                    {copiedId === row.id ? "Copied" : "Copy"}
                  </button>
                </div>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  </div>

  {#if error}<p class="text-red-500 text-sm">{error}</p>{/if}

  <div class="flex flex-col gap-2 bg-white dark:bg-gray-900 rounded-3xl border border-gray-100/30 dark:border-gray-850/30 p-3">
    <div class="flex items-start justify-between gap-2 px-1">
      <div class="flex flex-col gap-0.5">
        <div class="text-sm font-medium">Search</div>
        <div class="text-xs text-gray-500">
          Retrieval only — no model, no generated answer. Shows the real top-matching chunks across every "{TAG}"
          collection and their relevance scores, for judging embedding-model quality directly.
        </div>
      </div>
      <button
        type="button"
        aria-label="Compare two queries"
        title="Compare two queries — check retrieval stability across paraphrases/translations"
        class="p-1.5 rounded-full transition shrink-0 {compareMode
          ? 'bg-black text-white dark:bg-white dark:text-black'
          : 'text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-850 hover:text-gray-700 dark:hover:text-gray-200'}"
        onclick={() => (compareMode = !compareMode)}
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-4">
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            d="M9 4.5v15m6-15v15m-10.875 0h15.75c.621 0 1.125-.504 1.125-1.125V5.625c0-.621-.504-1.125-1.125-1.125H4.125C3.504 4.5 3 5.004 3 5.625v12.75c0 .621.504 1.125 1.125 1.125Z"
          />
        </svg>
      </button>
    </div>

    {#if !compareMode}
      <div class="flex gap-2 px-1">
        <input
          class="flex-1 min-w-0 text-sm px-3 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden"
          placeholder="Type a query…"
          bind:value={searchQuery}
          disabled={searching}
          onkeydown={(e) => {
            if (e.key === "Enter") handleSearch();
          }}
        />
        <button
          type="button"
          class="primary flex items-center gap-1.5 px-4 shrink-0"
          disabled={searching || !searchQuery.trim()}
          onclick={handleSearch}
        >
          {#if searching}{@render spinner()}{/if}
          {searching ? "Searching…" : "Search"}
        </button>
      </div>

      {#if searchError}<p class="text-red-500 text-sm px-1">{searchError}</p>{/if}

      {#if searchResults !== null}
        {#if searchResults.length === 0}
          <div class="text-sm text-gray-500 px-1 py-2">No matching content found.</div>
        {:else}
          <div class="flex flex-col gap-1.5 px-1 max-h-[50vh] overflow-y-auto">
            {#each searchResults as result, i (i)}
              {@render resultCard(result, expandedResults.has(i), () => toggleExpanded(i))}
            {/each}
          </div>
        {/if}
      {/if}
    {:else}
      <div class="flex flex-col gap-2 px-1">
        <div class="flex flex-col sm:flex-row gap-2">
          <input
            class="flex-1 min-w-0 text-sm px-3 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden"
            placeholder="Query A…"
            bind:value={queryA}
            disabled={comparing}
            onkeydown={(e) => {
              if (e.key === "Enter") handleCompare();
            }}
          />
          <input
            class="flex-1 min-w-0 text-sm px-3 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden"
            placeholder="Query B…"
            bind:value={queryB}
            disabled={comparing}
            onkeydown={(e) => {
              if (e.key === "Enter") handleCompare();
            }}
          />
        </div>
        <button
          type="button"
          class="primary flex items-center justify-center gap-1.5 self-start px-4"
          disabled={comparing || !queryA.trim() || !queryB.trim()}
          onclick={handleCompare}
        >
          {#if comparing}{@render spinner()}{/if}
          {comparing ? "Comparing…" : "Compare"}
        </button>
      </div>

      {#if compareError}<p class="text-red-500 text-sm px-1">{compareError}</p>{/if}

      {#if compareResult}
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 px-1">
          <div class="flex flex-col gap-1.5 max-h-[40vh] overflow-y-auto">
            <div class="text-xs font-medium text-gray-500">Query A results</div>
            {#if compareResult.results_a.length === 0}
              <div class="text-sm text-gray-500 py-2">No matching content found.</div>
            {/if}
            {#each compareResult.results_a as result, i (i)}
              {@render resultCard(result, expandedA.has(i), () => toggleExpandedIn("a", i))}
            {/each}
          </div>
          <div class="flex flex-col gap-1.5 max-h-[40vh] overflow-y-auto">
            <div class="text-xs font-medium text-gray-500">Query B results</div>
            {#if compareResult.results_b.length === 0}
              <div class="text-sm text-gray-500 py-2">No matching content found.</div>
            {/if}
            {#each compareResult.results_b as result, i (i)}
              {@render resultCard(result, expandedB.has(i), () => toggleExpandedIn("b", i))}
            {/each}
          </div>
        </div>

        <div class="flex flex-col gap-1.5 px-1 pt-1 border-t border-gray-100 dark:border-gray-850">
          <div class="text-xs font-medium">Comparison</div>
          <div class="text-xs text-gray-500">
            {compareResult.comparison.file_overlap}/{compareResult.comparison.file_total} files overlap ·
            {compareResult.comparison.matches.length} matched chunk{compareResult.comparison.matches.length === 1 ? "" : "s"}
            {#if avgAbsDelta !== null} · avg |Δ| {avgAbsDelta.toFixed(3)}{/if}
          </div>

          {#if compareResult.comparison.matches.length > 0}
            <div class="flex flex-col gap-1 max-h-[30vh] overflow-y-auto">
              {#each compareResult.comparison.matches as match, i (i)}
                <div class="flex items-center justify-between gap-2 text-xs rounded-lg border border-gray-100 dark:border-gray-850 px-2.5 py-1.5">
                  <span class="truncate flex-1 min-w-0">{match.filename ?? "(unknown file)"}</span>
                  <span class="text-gray-500 shrink-0">{formatDistance(match.chunk_distance)}</span>
                  <span class="font-mono shrink-0">A {formatScore(match.score_a)}</span>
                  <span class="font-mono shrink-0">B {formatScore(match.score_b)}</span>
                  <span class="font-mono shrink-0 font-medium">Δ {formatDelta(match.score_delta)}</span>
                </div>
              {/each}
            </div>
          {/if}
        </div>
      {/if}
    {/if}
  </div>
</div>
