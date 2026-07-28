<script>
  import { createKnowledgeBase, deleteKnowledgeBase, listAllTags, listKnowledgeBases, updateCollectionTags } from "./api.js";
  import { buildTagTree, matchesTagPath } from "./tagTree.js";

  let { onOpen = (_kb) => {} } = $props();

  let items = $state(null);
  let query = $state("");
  let error = $state(null);
  let deletingId = $state(null);

  let creating = $state(false);
  let newName = $state("");
  let newDescription = $state("");
  let newVersionTag = $state("v1.0");

  async function load() {
    error = null;
    try {
      items = await listKnowledgeBases();
    } catch (e) {
      error = e.message;
    }
  }

  load();

  // --- organizing collections by tag (coe / course / course/uvss / ...) ---
  let knownTags = $state([]);
  let editingTagsForId = $state(null);
  let newTagInput = $state("");
  let selectedTagPath = $state(null); // e.g. "course" or "course/uvss" — null = show everything

  async function loadKnownTags() {
    try {
      knownTags = await listAllTags();
    } catch (e) {
      // non-critical — freeform typing still works without suggestions
    }
  }

  loadKnownTags();

  const tagTree = $derived(buildTagTree(items ?? []));

  async function saveTags(kb, tags) {
    try {
      const updated = await updateCollectionTags(kb.id, tags);
      items = items.map((i) => (i.id === kb.id ? { ...i, tags: updated.tags } : i));
    } catch (e) {
      error = e.message;
    }
  }

  async function addTag(kb, tag) {
    const trimmed = tag.trim();
    if (!trimmed) return;
    const current = kb.tags ?? [];
    if (current.includes(trimmed)) return;
    await saveTags(kb, [...current, trimmed]);
    if (!knownTags.includes(trimmed)) knownTags = [...knownTags, trimmed].sort();
  }

  async function removeTag(kb, tag) {
    await saveTags(kb, (kb.tags ?? []).filter((t) => t !== tag));
  }

  const filtered = $derived(
    (items ?? [])
      .filter((kb) => !query || kb.name.toLowerCase().includes(query.toLowerCase()))
      .filter((kb) => matchesTagPath(kb, selectedTagPath)),
  );

  async function confirmCreate() {
    if (!newName.trim()) return;
    error = null;
    try {
      const kb = await createKnowledgeBase(newName.trim(), newDescription.trim(), newVersionTag.trim() || "v1.0");
      items = [kb, ...(items ?? [])];
      creating = false;
      newName = "";
      newDescription = "";
      newVersionTag = "v1.0";
      onOpen(kb);
    } catch (e) {
      error = e.message;
    }
  }

  async function handleDelete(event, kb) {
    event.stopPropagation();
    if (!confirm(`Delete knowledge base "${kb.name}"? This cannot be undone.`)) return;
    deletingId = kb.id;
    error = null;
    try {
      await deleteKnowledgeBase(kb.id);
      items = items.filter((i) => i.id !== kb.id);
    } catch (e) {
      error = e.message;
    } finally {
      deletingId = null;
    }
  }

  function relativeTime(epochSeconds) {
    if (!epochSeconds) return "";
    const diffMs = Date.now() - epochSeconds * 1000;
    const minutes = Math.round(diffMs / 60000);
    if (minutes < 1) return "just now";
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.round(hours / 24);
    return `${days}d ago`;
  }
</script>

<div class="flex flex-col gap-1 px-1 mt-1.5 mb-3">
  <div class="flex justify-between items-center">
    <div class="flex items-center md:self-center text-xl font-medium px-0.5 gap-2 shrink-0">
      <div>Knowledge</div>
      <div class="text-lg font-medium text-gray-500 dark:text-gray-500">{items?.length ?? 0}</div>
    </div>

    <div class="flex w-full justify-end gap-1.5">
      <button
        type="button"
        class="px-2 py-1.5 rounded-xl bg-black text-white dark:bg-white dark:text-black transition font-medium text-sm flex items-center"
        onclick={() => (creating = !creating)}
      >
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor" class="size-3">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
        </svg>
        <div class="hidden md:block md:ml-1 text-xs">New Knowledge</div>
      </button>
    </div>
  </div>
</div>

{#if creating}
  <div class="flex gap-1.5 px-1 mb-3">
    <input class="flex-1 text-sm px-3 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden" placeholder="Name" bind:value={newName} />
    <input
      class="flex-1 text-sm px-3 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden"
      placeholder="Description (optional)"
      bind:value={newDescription}
    />
    <input
      class="w-28 text-sm px-3 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden font-mono"
      placeholder="v1.0"
      title="Version tag"
      bind:value={newVersionTag}
    />
    <button
      type="button"
      class="px-3 py-1.5 rounded-xl bg-black text-white dark:bg-white dark:text-black transition font-medium text-sm disabled:opacity-40"
      disabled={!newName.trim()}
      onclick={confirmCreate}
    >
      Create
    </button>
  </div>
{/if}

{#if tagTree.length > 0}
  {@const selectedTopSegment = selectedTagPath ? selectedTagPath.split("/")[0] : null}
  {@const activeTopNode = tagTree.find((n) => n.name === selectedTopSegment) ?? null}
  <div class="flex flex-wrap items-center gap-1.5 px-1 mb-1.5">
    <button
      type="button"
      class="text-xs px-2.5 py-1 rounded-full border transition {selectedTagPath === null
        ? 'bg-black text-white dark:bg-white dark:text-black border-transparent'
        : 'border-gray-200 dark:border-gray-800 hover:bg-gray-100 dark:hover:bg-gray-850'}"
      onclick={() => (selectedTagPath = null)}
    >
      All
    </button>
    {#each tagTree as node (node.path)}
      <button
        type="button"
        class="text-xs px-2.5 py-1 rounded-full border transition {selectedTopSegment === node.name
          ? 'bg-black text-white dark:bg-white dark:text-black border-transparent'
          : 'border-gray-200 dark:border-gray-800 hover:bg-gray-100 dark:hover:bg-gray-850'}"
        onclick={() => (selectedTagPath = node.path)}
      >
        {node.name}
      </button>
    {/each}
  </div>
  {#if activeTopNode?.children?.length > 0}
    <div class="flex flex-wrap items-center gap-1.5 px-1 mb-3 pl-4">
      {#each activeTopNode.children as child (child.path)}
        <button
          type="button"
          class="text-xs px-2 py-0.5 rounded-full border transition {selectedTagPath === child.path
            ? 'bg-black text-white dark:bg-white dark:text-black border-transparent'
            : 'border-gray-200 dark:border-gray-800 hover:bg-gray-100 dark:hover:bg-gray-850'}"
          onclick={() => (selectedTagPath = child.path)}
        >
          {child.name}
        </button>
      {/each}
    </div>
  {/if}
{/if}

<div class="py-2 bg-white dark:bg-gray-900 rounded-3xl border border-gray-100/30 dark:border-gray-850/30">
  <div class="flex w-full space-x-2 py-0.5 px-3.5 pb-2">
    <div class="flex flex-1">
      <div class="self-center ml-1 mr-3">
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-3.5" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
        </svg>
      </div>
      <input
        class="w-full text-sm py-1 rounded-r-xl outline-hidden bg-transparent"
        bind:value={query}
        placeholder="Search Knowledge"
      />
    </div>
  </div>

  {#if items === null}
    <div class="w-full h-full flex justify-center items-center py-10">
      <span class="text-sm text-gray-500 animate-pulse">Loading…</span>
    </div>
  {:else if filtered.length !== 0}
    <div class="my-2 px-3 grid grid-cols-1 lg:grid-cols-2 gap-2">
      {#each filtered as item (item.id)}
        <div
          role="button"
          tabindex="0"
          class="flex space-x-4 cursor-pointer text-left w-full px-3 py-2.5 dark:hover:bg-gray-850/50 hover:bg-gray-50 transition rounded-2xl"
          onclick={() => onOpen(item)}
          onkeydown={(e) => (e.key === "Enter" || e.key === " ") && onOpen(item)}
        >
          <div class="w-full">
            <div class="self-center flex-1 justify-between">
              <div class="flex items-center justify-between -my-1 h-8">
                <div class="flex gap-2 items-center justify-between w-full">
                  <div class="flex items-center gap-1">
                    <div
                      class="text-xs font-medium bg-green-500/20 text-green-700 dark:text-green-200 w-fit px-[5px] rounded-lg uppercase line-clamp-1 mr-0.5"
                    >
                      Collection
                    </div>
                    {#if item.version_tag}
                      <div
                        class="text-xs font-mono bg-gray-500/20 text-gray-700 dark:text-gray-300 w-fit px-[5px] rounded-lg line-clamp-1"
                      >
                        {item.version_tag}
                      </div>
                    {/if}
                  </div>
                  <div class="flex items-center gap-1">
                    {#if !item.write_access}
                      <div
                        class="text-xs font-medium bg-gray-500/20 text-gray-700 dark:text-gray-200 w-fit px-[5px] rounded-lg uppercase line-clamp-1 mr-0.5"
                      >
                        Read Only
                      </div>
                    {/if}
                    <button
                      type="button"
                      aria-label="Delete knowledge base"
                      class="p-1 rounded-full hover:bg-red-500/20 text-gray-400 hover:text-red-600 dark:hover:text-red-400 transition disabled:opacity-40"
                      disabled={deletingId === item.id}
                      onclick={(e) => handleDelete(e, item)}
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
                </div>
              </div>

              <div class="flex items-center gap-1 justify-between px-1.5">
                <div class="flex items-center gap-2">
                  <div class="text-sm font-medium line-clamp-1 capitalize">{item.name}</div>
                </div>

                <div class="flex items-center gap-2 shrink-0">
                  {#if item.updated_at}
                    <div class="text-xs text-gray-500 line-clamp-1 hidden sm:block">
                      Updated {relativeTime(item.updated_at)}
                    </div>
                  {/if}
                  {#if item.user}
                    <div class="text-xs text-gray-500 shrink-0">
                      By {item.user.name ?? item.user.email ?? "Deleted User"}
                    </div>
                  {/if}
                </div>
              </div>

              <div class="flex flex-wrap items-center gap-1.5 px-1.5 pt-1.5">
                {#each item.tags ?? [] as tag}
                  <span class="flex items-center gap-1 text-[0.65rem] leading-normal whitespace-nowrap px-1.5 py-0.5 rounded-full border border-gray-200 dark:border-gray-800">
                    {tag}
                    <button
                      type="button"
                      aria-label="Remove tag"
                      class="opacity-60 hover:opacity-100"
                      onclick={(e) => {
                        e.stopPropagation();
                        removeTag(item, tag);
                      }}
                    >
                      ×
                    </button>
                  </span>
                {/each}
                <button
                  type="button"
                  class="text-[0.65rem] whitespace-nowrap opacity-50 hover:opacity-100"
                  onclick={(e) => {
                    e.stopPropagation();
                    editingTagsForId = editingTagsForId === item.id ? null : item.id;
                    newTagInput = "";
                  }}
                >
                  + tag
                </button>
              </div>

              {#if editingTagsForId === item.id}
                <div class="flex gap-1 px-1.5 pt-1">
                  <input
                    class="flex-1 min-w-0 text-xs px-2 py-1 rounded-lg bg-gray-50 dark:bg-gray-850 outline-hidden"
                    placeholder="tag name (e.g. course/uvss)"
                    list="collection-tag-suggestions-{item.id}"
                    bind:value={newTagInput}
                    onclick={(e) => e.stopPropagation()}
                    onkeydown={(e) => {
                      e.stopPropagation();
                      if (e.key === "Enter") {
                        addTag(item, newTagInput);
                        newTagInput = "";
                      }
                    }}
                  />
                  <datalist id="collection-tag-suggestions-{item.id}">
                    {#each knownTags.filter((t) => !(item.tags ?? []).includes(t)) as suggestion}
                      <option value={suggestion}></option>
                    {/each}
                  </datalist>
                  <button
                    type="button"
                    class="text-xs px-2 py-1 rounded-lg bg-gray-50 dark:bg-gray-850 shrink-0"
                    onclick={(e) => {
                      e.stopPropagation();
                      addTag(item, newTagInput);
                      newTagInput = "";
                    }}
                  >
                    Add
                  </button>
                </div>
              {/if}
            </div>
          </div>
        </div>
      {/each}
    </div>
  {:else}
    <div class="w-full h-full flex flex-col justify-center items-center my-16 mb-24">
      <div class="max-w-md text-center">
        <div class="text-3xl mb-3">😕</div>
        <div class="text-lg font-medium mb-1">No knowledge found</div>
        <div class="text-gray-500 text-center text-xs">
          Try adjusting your search, or create a new knowledge base.
        </div>
      </div>
    </div>
  {/if}
</div>

{#if error}
  <p class="text-red-500 text-sm mt-2">{error}</p>
{/if}
