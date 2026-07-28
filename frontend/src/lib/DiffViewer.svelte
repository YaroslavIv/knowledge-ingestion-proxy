<script>
  import { buildDiffRows } from "./diffRows.js";

  let { oldText = "", newText = "", oldLabel = "previous", newLabel = "current" } = $props();

  const rows = $derived(buildDiffRows(oldText, newText));
  const addCount = $derived(rows.filter((r) => r.type === "add").length);
  const removeCount = $derived(rows.filter((r) => r.type === "remove").length);

  function rowClass(type) {
    if (type === "add") return "bg-green-500/10 text-green-800 dark:text-green-300";
    if (type === "remove") return "bg-red-500/10 text-red-800 dark:text-red-300";
    return "text-gray-600 dark:text-gray-400";
  }

  function rowPrefix(type) {
    if (type === "add") return "+";
    if (type === "remove") return "−";
    return " ";
  }
</script>

<div class="flex flex-col gap-1.5">
  <div class="flex items-center gap-2 text-xs text-gray-500">
    <span class="font-mono">{oldLabel}</span>
    <span>→</span>
    <span class="font-mono">{newLabel}</span>
    <span class="ml-auto text-green-700 dark:text-green-400">+{addCount}</span>
    <span class="text-red-700 dark:text-red-400">−{removeCount}</span>
  </div>
  <div class="rounded-lg border border-gray-100 dark:border-gray-850 max-h-[60vh] overflow-auto font-mono text-xs">
    {#each rows as row, i (i)}
      <div class="flex gap-2 px-2 py-0.5 whitespace-pre-wrap break-all {rowClass(row.type)}">
        <span class="select-none opacity-50 shrink-0">{rowPrefix(row.type)}</span>
        <span class="flex-1">{row.text}</span>
      </div>
    {/each}
    {#if rows.length === 0}
      <div class="px-2 py-3 text-gray-500">No differences.</div>
    {/if}
  </div>
</div>
