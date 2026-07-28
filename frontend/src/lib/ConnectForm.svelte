<script>
  import { connect } from "./api.js";

  let { onConnected = (_summary) => {}, submitLabel = "Connect" } = $props();

  let label = $state("");
  let baseUrl = $state("http://localhost:8080");
  let email = $state("");
  let password = $state("");
  let error = $state(null);
  let connecting = $state(false);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!baseUrl.trim() || !email.trim() || !password) return;
    connecting = true;
    error = null;
    try {
      const summary = await connect(label.trim(), baseUrl.trim(), email.trim(), password);
      onConnected(summary);
    } catch (e) {
      error = e.message;
    } finally {
      connecting = false;
    }
  }
</script>

<form class="flex flex-col gap-2.5" onsubmit={handleSubmit}>
  <div class="flex flex-col gap-0.5">
    <label for="connect-base-url" class="text-xs text-gray-500">Open WebUI URL</label>
    <input
      id="connect-base-url"
      class="text-sm px-3 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden"
      placeholder="http://localhost:8080 or http://my-server:3000"
      bind:value={baseUrl}
    />
  </div>
  <div class="flex flex-col gap-0.5">
    <label for="connect-label" class="text-xs text-gray-500">Label (optional)</label>
    <input
      id="connect-label"
      class="text-sm px-3 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden"
      placeholder="e.g. Production, Docker, Alex's instance"
      bind:value={label}
    />
  </div>
  <div class="flex flex-col gap-0.5">
    <label for="connect-email" class="text-xs text-gray-500">Admin email</label>
    <input
      id="connect-email"
      type="email"
      class="text-sm px-3 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden"
      placeholder="admin@admin.com"
      bind:value={email}
    />
  </div>
  <div class="flex flex-col gap-0.5">
    <label for="connect-password" class="text-xs text-gray-500">Password</label>
    <input
      id="connect-password"
      type="password"
      class="text-sm px-3 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden"
      bind:value={password}
    />
  </div>

  {#if error}<p class="text-red-500 text-sm">{error}</p>{/if}

  <button
    type="submit"
    class="primary self-start px-4"
    disabled={connecting || !baseUrl.trim() || !email.trim() || !password}
  >
    {connecting ? "Connecting…" : submitLabel}
  </button>
</form>
