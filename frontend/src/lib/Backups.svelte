<script>
  import { authHeaders, deleteBackup, getBackupDownloadUrl, listBackups, triggerBackup } from "./api.js";

  let backups = $state(null); // null while loading
  let error = $state(null);
  let creating = $state(false);
  let deletingFilename = $state(null);

  async function load() {
    error = null;
    try {
      backups = await listBackups();
    } catch (e) {
      error = e.message;
    }
  }

  load();

  async function handleCreateBackup() {
    creating = true;
    error = null;
    try {
      const created = await triggerBackup();
      backups = [created, ...(backups ?? []).filter((b) => b.filename !== created.filename)];
    } catch (e) {
      error = e.message;
    } finally {
      creating = false;
    }
  }

  async function handleDownload(backup) {
    try {
      const resp = await fetch(getBackupDownloadUrl(backup.filename), { headers: authHeaders() });
      if (!resp.ok) throw new Error(`Failed to fetch (${resp.status})`);
      const blobUrl = URL.createObjectURL(await resp.blob());
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = backup.filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(blobUrl), 30000);
    } catch (e) {
      error = e.message;
    }
  }

  async function handleDelete(backup) {
    if (!confirm(`Delete backup "${backup.filename}"? This cannot be undone.`)) return;
    deletingFilename = backup.filename;
    error = null;
    try {
      await deleteBackup(backup.filename);
      backups = backups.filter((b) => b.filename !== backup.filename);
    } catch (e) {
      error = e.message;
    } finally {
      deletingFilename = null;
    }
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }

  function formatDate(iso) {
    return new Date(iso).toLocaleString();
  }
</script>

{#snippet spinner()}
  <svg class="animate-spin size-3.5 shrink-0" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V4a8 8 0 00-8 8h0z"></path>
  </svg>
{/snippet}

<div class="flex flex-col gap-3">
  <div class="flex items-center justify-between px-1">
    <div class="flex flex-col gap-0.5">
      <div class="text-xl font-medium">Backups</div>
      <div class="text-xs text-gray-500">
        One zip a day, kept locally, with everything this proxy itself stores — cached original files, published
        course outputs, and its own database (course projects, tracked versions, feedback notes). Does not include
        Open WebUI's own knowledge-base content — that lives in Open WebUI's own storage, not here.
      </div>
    </div>
    <button
      type="button"
      class="primary flex items-center gap-1.5 px-4 shrink-0"
      disabled={creating}
      onclick={handleCreateBackup}
    >
      {#if creating}{@render spinner()}{/if}
      {creating ? "Backing up…" : "Back up now"}
    </button>
  </div>

  {#if error}
    <p class="text-red-500 text-sm px-1">{error}</p>
  {/if}

  <div class="py-2 bg-white dark:bg-gray-900 rounded-3xl border border-gray-100/30 dark:border-gray-850/30">
    {#if backups === null}
      <div class="w-full h-full flex justify-center items-center py-10">
        <span class="text-sm text-gray-500 animate-pulse">Loading…</span>
      </div>
    {:else if backups.length === 0}
      <div class="w-full h-full flex flex-col justify-center items-center my-16 mb-24">
        <div class="max-w-md text-center">
          <div class="text-3xl mb-3">🗄️</div>
          <div class="text-lg font-medium mb-1">No backups yet</div>
          <div class="text-gray-500 text-center text-xs">
            One gets created automatically every day — or click "Back up now" above for an immediate one.
          </div>
        </div>
      </div>
    {:else}
      <div class="flex flex-col gap-0.5 px-3">
        {#each backups as backup (backup.filename)}
          <div class="flex items-center gap-3 px-3 py-2.5 rounded-2xl hover:bg-gray-50 dark:hover:bg-gray-850/50 transition">
            <div class="flex flex-col flex-1 min-w-0">
              <span class="text-sm font-medium truncate">{backup.filename}</span>
              <span class="text-xs text-gray-500">{formatDate(backup.created_at)} · {formatBytes(backup.size_bytes)}</span>
            </div>
            <button
              type="button"
              class="text-xs px-2.5 py-1 rounded-full border border-gray-200 dark:border-gray-800 hover:bg-gray-100 dark:hover:bg-gray-850 transition shrink-0"
              onclick={() => handleDownload(backup)}
            >
              Download
            </button>
            <button
              type="button"
              class="text-xs px-2.5 py-1 rounded-full border border-gray-200 dark:border-gray-800 hover:bg-red-50 hover:text-red-600 hover:border-red-200 dark:hover:bg-red-500/10 dark:hover:text-red-400 dark:hover:border-red-500/30 transition shrink-0 disabled:opacity-40"
              disabled={deletingFilename === backup.filename}
              onclick={() => handleDelete(backup)}
            >
              {deletingFilename === backup.filename ? "Deleting…" : "Delete"}
            </button>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</div>
