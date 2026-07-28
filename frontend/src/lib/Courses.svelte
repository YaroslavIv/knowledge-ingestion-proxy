<script>
  import { createCourseProject, deleteCourseProject, listCourseProjects, listKnowledgeBases } from "./api.js";

  let { onOpen = (_project) => {} } = $props();

  let items = $state(null);
  let knowledgeBases = $state([]);
  let error = $state(null);
  let deletingId = $state(null);

  let creating = $state(false);
  let newName = $state("");
  let newProductKb = $state("");
  let newCompetitorsKb = $state("");
  let newInstructionsKb = $state("");
  let newLanguage = $state("en");
  let newAudience = $state("sales");

  async function load() {
    error = null;
    try {
      [items, knowledgeBases] = await Promise.all([listCourseProjects(), listKnowledgeBases()]);
    } catch (e) {
      error = e.message;
    }
  }

  load();

  function kbName(id) {
    return knowledgeBases.find((k) => k.id === id)?.name ?? id;
  }

  async function confirmCreate() {
    if (!newName.trim() || !newProductKb || !newInstructionsKb) return;
    error = null;
    try {
      const project = await createCourseProject({
        name: newName.trim(),
        product_knowledge_id: newProductKb,
        competitors_knowledge_id: newCompetitorsKb || null,
        instructions_knowledge_id: newInstructionsKb,
        language: newLanguage,
        target_audience: newAudience,
      });
      items = [project, ...(items ?? [])];
      creating = false;
      newName = "";
      newProductKb = "";
      newCompetitorsKb = "";
      newInstructionsKb = "";
      onOpen(project);
    } catch (e) {
      error = e.message;
    }
  }

  async function handleDelete(event, project) {
    event.stopPropagation();
    if (!confirm(`Delete course project "${project.name}"? This cannot be undone.`)) return;
    deletingId = project.id;
    error = null;
    try {
      await deleteCourseProject(project.id);
      items = items.filter((i) => i.id !== project.id);
    } catch (e) {
      error = e.message;
    } finally {
      deletingId = null;
    }
  }
</script>

<div class="flex flex-col gap-1 px-1 mt-1.5 mb-3">
  <div class="flex justify-between items-center">
    <div class="flex items-center md:self-center text-xl font-medium px-0.5 gap-2 shrink-0">
      <div>Courses</div>
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
        <div class="hidden md:block md:ml-1 text-xs">New Course Project</div>
      </button>
    </div>
  </div>
</div>

{#if creating}
  <div class="flex flex-col gap-2 px-1 mb-3 bg-white dark:bg-gray-900 rounded-2xl border border-gray-100/30 dark:border-gray-850/30 p-3">
    <input class="text-sm px-3 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden" placeholder="Project name (e.g. UVSS Sales Onboarding)" bind:value={newName} />
    <div class="grid grid-cols-1 md:grid-cols-3 gap-2">
      <div class="flex flex-col gap-0.5">
        <label for="product-kb" class="text-xs text-gray-500">Product material (required)</label>
        <select id="product-kb" class="text-sm px-2 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden" bind:value={newProductKb}>
          <option value="">Select a knowledge base…</option>
          {#each knowledgeBases as kb}<option value={kb.id}>{kb.name}</option>{/each}
        </select>
      </div>
      <div class="flex flex-col gap-0.5">
        <label for="competitors-kb" class="text-xs text-gray-500">Competitive intel (optional)</label>
        <select id="competitors-kb" class="text-sm px-2 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden" bind:value={newCompetitorsKb}>
          <option value="">None</option>
          {#each knowledgeBases as kb}<option value={kb.id}>{kb.name}</option>{/each}
        </select>
      </div>
      <div class="flex flex-col gap-0.5">
        <label for="instructions-kb" class="text-xs text-gray-500">Instructions / playbook (required)</label>
        <select id="instructions-kb" class="text-sm px-2 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden" bind:value={newInstructionsKb}>
          <option value="">Select a knowledge base…</option>
          {#each knowledgeBases as kb}<option value={kb.id}>{kb.name}</option>{/each}
        </select>
      </div>
    </div>
    <div class="grid grid-cols-2 gap-2">
      <div class="flex flex-col gap-0.5">
        <label for="new-language" class="text-xs text-gray-500">Language</label>
        <input id="new-language" class="text-sm px-2 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden" bind:value={newLanguage} />
      </div>
      <div class="flex flex-col gap-0.5">
        <label for="new-audience" class="text-xs text-gray-500">Target audience</label>
        <input id="new-audience" class="text-sm px-2 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden" bind:value={newAudience} />
      </div>
    </div>
    <button
      type="button"
      class="primary self-start px-4"
      disabled={!newName.trim() || !newProductKb || !newInstructionsKb}
      onclick={confirmCreate}
    >
      Create
    </button>
  </div>
{/if}

<div class="py-2 bg-white dark:bg-gray-900 rounded-3xl border border-gray-100/30 dark:border-gray-850/30">
  {#if items === null}
    <div class="w-full h-full flex justify-center items-center py-10">
      <span class="text-sm text-gray-500 animate-pulse">Loading…</span>
    </div>
  {:else if items.length !== 0}
    <div class="my-2 px-3 grid grid-cols-1 lg:grid-cols-2 gap-2">
      {#each items as item (item.id)}
        <div
          role="button"
          tabindex="0"
          class="flex space-x-4 cursor-pointer text-left w-full px-3 py-2.5 dark:hover:bg-gray-850/50 hover:bg-gray-50 transition rounded-2xl"
          onclick={() => onOpen(item)}
          onkeydown={(e) => (e.key === "Enter" || e.key === " ") && onOpen(item)}
        >
          <div class="w-full">
            <div class="flex items-center justify-between -my-1 h-8">
              <div class="flex items-center gap-1">
                <div class="text-xs font-medium bg-blue-500/20 text-blue-700 dark:text-blue-200 w-fit px-[5px] rounded-lg uppercase line-clamp-1 mr-0.5">
                  Course Project
                </div>
                <div class="text-xs font-mono bg-gray-500/20 text-gray-700 dark:text-gray-300 w-fit px-[5px] rounded-lg line-clamp-1">
                  {item.pedagogy_version} · {item.language}
                </div>
              </div>
              <button
                type="button"
                aria-label="Delete course project"
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
            <div class="flex items-center gap-1 justify-between px-1.5">
              <div class="text-sm font-medium line-clamp-1">{item.name}</div>
              <div class="text-xs text-gray-500 shrink-0">Product: {kbName(item.product_knowledge_id)}</div>
            </div>
          </div>
        </div>
      {/each}
    </div>
  {:else}
    <div class="w-full h-full flex flex-col justify-center items-center my-16 mb-24">
      <div class="max-w-md text-center">
        <div class="text-3xl mb-3">📚</div>
        <div class="text-lg font-medium mb-1">No course projects yet</div>
        <div class="text-gray-500 text-center text-xs">
          Create one, pointing at a product-material and an instructions knowledge base.
        </div>
      </div>
    </div>
  {/if}
</div>

{#if error}
  <p class="text-red-500 text-sm mt-2">{error}</p>
{/if}
