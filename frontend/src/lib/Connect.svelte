<script>
  import ConnectForm from "./ConnectForm.svelte";

  let { onConnected = (_summary) => {} } = $props();
</script>

<div class="max-w-sm mx-auto mt-12 flex flex-col gap-4 bg-white dark:bg-gray-900 rounded-2xl border border-gray-100/30 dark:border-gray-850/30 p-6">
  <div class="flex flex-col gap-1">
    <div class="text-lg font-medium">Connect to Open WebUI</div>
    <div class="text-xs text-gray-500">
      Sign in with an admin account on the Open WebUI instance you want to manage — local, in Docker, or remote.
      You can add more instances and switch between them later.
    </div>
  </div>

  <ConnectForm onConnected={onConnected} />
</div>
