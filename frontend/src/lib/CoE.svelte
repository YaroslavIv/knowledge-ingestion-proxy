<script>
  import { getLatestCollectionsByTag, listKnowledgeBases, updateCollectionTags } from "./api.js";

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
</script>

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
</div>
