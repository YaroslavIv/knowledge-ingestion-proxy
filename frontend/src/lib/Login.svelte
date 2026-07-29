<script>
  import { login } from "./api.js";

  let { onLoggedIn = () => {} } = $props();

  let email = $state("");
  let password = $state("");
  let error = $state(null);
  let checking = $state(false);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!email.trim() || !password) return;
    checking = true;
    error = null;
    try {
      await login(email.trim(), password);
      onLoggedIn();
    } catch (e) {
      error = e.message;
    } finally {
      checking = false;
    }
  }
</script>

<div class="max-w-sm mx-auto mt-12 flex flex-col gap-4 bg-white dark:bg-gray-900 rounded-2xl border border-gray-100/30 dark:border-gray-850/30 p-6">
  <div class="flex flex-col gap-1">
    <div class="text-lg font-medium">Sign in</div>
    <div class="text-xs text-gray-500">Use your own Open WebUI account — the same email and password you use there.</div>
  </div>

  <form class="flex flex-col gap-2.5" onsubmit={handleSubmit}>
    <div class="flex flex-col gap-0.5">
      <label for="login-email" class="text-xs text-gray-500">Email</label>
      <input
        id="login-email"
        type="email"
        class="text-sm px-3 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden"
        bind:value={email}
      />
    </div>
    <div class="flex flex-col gap-0.5">
      <label for="login-password" class="text-xs text-gray-500">Password</label>
      <input
        id="login-password"
        type="password"
        class="text-sm px-3 py-2 rounded-xl bg-gray-50 dark:bg-gray-850 outline-hidden"
        bind:value={password}
      />
    </div>

    {#if error}<p class="text-red-500 text-sm">{error}</p>{/if}

    <button type="submit" class="primary self-start px-4" disabled={checking || !email.trim() || !password}>
      {checking ? "Signing in…" : "Sign in"}
    </button>
  </form>
</div>
