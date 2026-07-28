<script>
  import { activateConnection, deleteConnection, listConnections } from "./api.js";
  import ConnectForm from "./ConnectForm.svelte";

  let { active, onSwitched = (_summary) => {} } = $props();

  let open = $state(false);
  let connections = $state([]);
  let loading = $state(false);
  let error = $state(null);
  let addingNew = $state(false);

  async function loadConnections() {
    loading = true;
    error = null;
    try {
      connections = await listConnections();
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  function toggleOpen() {
    open = !open;
    addingNew = false;
    if (open) loadConnections();
  }

  async function handleActivate(id) {
    if (id === active?.id) return;
    error = null;
    try {
      const summary = await activateConnection(id);
      open = false;
      onSwitched(summary);
    } catch (e) {
      error = e.message;
    }
  }

  async function handleDelete(event, id) {
    event.stopPropagation();
    if (!confirm("Remove this saved connection?")) return;
    try {
      await deleteConnection(id);
      const wasActive = id === active?.id;
      await loadConnections();
      if (wasActive) {
        onSwitched(connections.find((c) => c.is_active) ?? null);
      }
    } catch (e) {
      error = e.message;
    }
  }

  function handleConnected(summary) {
    addingNew = false;
    open = false;
    onSwitched(summary);
  }
</script>

<div class="relative">
  <button
    type="button"
    class="text-xs px-2.5 py-1.5 rounded-xl border border-gray-200 dark:border-gray-800 hover:bg-gray-100 dark:hover:bg-gray-850 transition flex items-center gap-1.5"
    onclick={toggleOpen}
  >
    <span class="size-1.5 rounded-full bg-green-500 shrink-0"></span>
    <span class="max-w-40 truncate">{active?.label || active?.base_url || "Not connected"}</span>
    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="size-3">
      <path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
    </svg>
  </button>

  {#if open}
    <div class="absolute right-0 mt-1 w-80 z-10 bg-white dark:bg-gray-900 rounded-2xl border border-gray-100/30 dark:border-gray-850/30 shadow-lg p-2 flex flex-col gap-1">
      {#if loading}
        <div class="text-xs text-gray-500 px-2 py-2">Loading…</div>
      {:else}
        {#each connections as c (c.id)}
          <div
            class="flex items-center gap-2 w-full rounded-xl hover:bg-gray-100 dark:hover:bg-gray-850 transition {c.is_active
              ? 'bg-gray-100 dark:bg-gray-850'
              : ''}"
          >
            <button
              type="button"
              class="flex items-center gap-2 flex-1 min-w-0 text-left px-2.5 py-2"
              onclick={() => handleActivate(c.id)}
            >
              <span class="size-1.5 rounded-full shrink-0 {c.is_active ? 'bg-green-500' : 'bg-gray-300 dark:bg-gray-700'}"></span>
              <span class="flex-1 min-w-0">
                <span class="block text-sm truncate">{c.label}</span>
                <span class="block text-xs text-gray-500 truncate">{c.base_url} · {c.email}</span>
              </span>
            </button>
            <button
              type="button"
              aria-label="Remove connection"
              class="p-1 mr-1.5 rounded-full hover:bg-red-500/20 text-gray-400 hover:text-red-600 dark:hover:text-red-400 transition shrink-0"
              onclick={(e) => handleDelete(e, c.id)}
            >
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-3.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        {/each}

        {#if error}<p class="text-red-500 text-xs px-2">{error}</p>{/if}

        {#if addingNew}
          <div class="px-2.5 py-2 border-t border-gray-100 dark:border-gray-850 mt-1">
            <ConnectForm onConnected={handleConnected} submitLabel="Add & switch" />
          </div>
        {:else}
          <button
            type="button"
            class="text-xs text-left px-2.5 py-2 rounded-xl hover:bg-gray-100 dark:hover:bg-gray-850 transition text-gray-500"
            onclick={() => (addingNew = true)}
          >
            + Connect another instance
          </button>
        {/if}
      {/if}
    </div>
  {/if}
</div>
