<script>
  import Backups from "./lib/Backups.svelte";
  import CoE from "./lib/CoE.svelte";
  import Connect from "./lib/Connect.svelte";
  import ConnectionSwitcher from "./lib/ConnectionSwitcher.svelte";
  import CourseDetail from "./lib/CourseDetail.svelte";
  import Courses from "./lib/Courses.svelte";
  import { clearToken, getActiveConnection, getCourseProject, getKnowledgeBaseDetail, getToken } from "./lib/api.js";
  import Knowledge from "./lib/Knowledge.svelte";
  import KnowledgeDetail from "./lib/KnowledgeDetail.svelte";
  import Login from "./lib/Login.svelte";
  import { buildPath, parseRoute } from "./lib/router.js";

  let section = $state("knowledge"); // "knowledge" | "courses"
  let openKnowledge = $state(null); // { id, name, fileId } | null
  let openCourseProjectId = $state(null);
  // Personal login (this browser's own Open WebUI account) gates everything
  // below it — distinct from activeConnection, which is this whole
  // deployment's shared "which Open WebUI instance" admin setting.
  let loggedIn = $state(!!getToken());
  let activeConnection = $state(undefined); // undefined = still loading, null = none, summary = connected
  let checkError = $state(null);

  async function loadActiveConnection() {
    try {
      activeConnection = await getActiveConnection();
    } catch (e) {
      checkError = e.message;
      activeConnection = null;
    }
  }

  if (getToken()) loadActiveConnection();

  function handleLoggedIn() {
    loggedIn = true;
    loadActiveConnection();
  }

  function handleLogout() {
    clearToken();
    window.location.reload();
  }

  function handleSwitched(summary) {
    activeConnection = summary;
    openKnowledge = null; // whatever was open likely doesn't exist on the new instance
    openCourseProjectId = null;
  }

  function switchSection(next) {
    section = next;
    openKnowledge = null;
    openCourseProjectId = null;
  }

  function openKnowledgeCollection(id, name) {
    section = "knowledge";
    openCourseProjectId = null;
    openKnowledge = { id, name, fileId: null };
  }

  // --- URL routing ---
  // No router library here (plain Vite SPA, not SvelteKit) — the browser's
  // own History API is enough for two tabs and one optional id each. A URL
  // only carries an id, never a display name, so a direct/reloaded load of
  // /knowledge/<id> has to fetch the name itself before KnowledgeDetail can
  // show it (confirmed: knowledgeName is a required prop there, with no
  // fallback fetch of its own).
  function applyPathToState(pathname) {
    const { section: s, id } = parseRoute(pathname);
    section = s;
    if (s === "courses") {
      openKnowledge = null;
      openCourseProjectId = id;
    } else if (s === "coe") {
      openKnowledge = null;
      openCourseProjectId = null;
    } else {
      openCourseProjectId = null;
      if (id) {
        if (openKnowledge?.id !== id) {
          openKnowledge = { id, name: "", fileId: null };
          getKnowledgeBaseDetail(id)
            .then((kb) => {
              if (openKnowledge?.id === id) openKnowledge = { ...openKnowledge, name: kb.name };
            })
            .catch(() => {});
        }
      } else {
        openKnowledge = null;
      }
    }
  }

  // Normalize the initial URL (bare "/", an unknown path, etc.) to its
  // canonical form via replaceState, so reloading always restores the right
  // view instead of resetting to the default screen.
  {
    const initial = parseRoute(window.location.pathname);
    applyPathToState(window.location.pathname);
    window.history.replaceState({}, "", buildPath(initial.section, initial.id));
  }

  window.addEventListener("popstate", () => applyPathToState(window.location.pathname));

  $effect(() => {
    const id = section === "knowledge" ? (openKnowledge?.id ?? null) : section === "courses" ? openCourseProjectId : null;
    const path = buildPath(section, id);
    if (window.location.pathname !== path) {
      window.history.pushState({}, "", path);
    }
  });
</script>

<main>
  <header class="flex items-start justify-between gap-3">
    <div>
      <h1>Knowledge Ingestion Proxy</h1>
      <p class="subtitle">
        A document intake tool in front of Open WebUI — parse, redact secrets, preview chunking, then push into a
        knowledge base.
      </p>
    </div>
    {#if loggedIn}
      <div class="flex items-center gap-2">
        {#if activeConnection}
          <ConnectionSwitcher active={activeConnection} onSwitched={handleSwitched} />
        {/if}
        <button
          type="button"
          class="text-xs px-3 py-1.5 rounded-xl border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-850"
          onclick={handleLogout}
        >
          Log out
        </button>
      </div>
    {/if}
  </header>

  {#if !loggedIn}
    <Login onLoggedIn={handleLoggedIn} />
  {:else if activeConnection === undefined}
    <div class="text-sm text-gray-500 text-center mt-12">Loading…</div>
  {:else if activeConnection === null}
    <Connect onConnected={(summary) => (activeConnection = summary)} />
  {:else}
    {#key activeConnection.id}
      <nav class="flex gap-1.5 px-1">
        <button
          type="button"
          class="text-xs px-3 py-1.5 rounded-xl border transition {section === 'knowledge'
            ? 'bg-black text-white dark:bg-white dark:text-black border-transparent'
            : 'border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-850'}"
          onclick={() => switchSection("knowledge")}
        >
          Knowledge
        </button>
        <button
          type="button"
          class="text-xs px-3 py-1.5 rounded-xl border transition {section === 'courses'
            ? 'bg-black text-white dark:bg-white dark:text-black border-transparent'
            : 'border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-850'}"
          onclick={() => switchSection("courses")}
        >
          Courses
        </button>
        <button
          type="button"
          class="text-xs px-3 py-1.5 rounded-xl border transition {section === 'coe'
            ? 'bg-black text-white dark:bg-white dark:text-black border-transparent'
            : 'border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-850'}"
          onclick={() => switchSection("coe")}
        >
          CoE
        </button>
        <button
          type="button"
          class="text-xs px-3 py-1.5 rounded-xl border transition {section === 'backups'
            ? 'bg-black text-white dark:bg-white dark:text-black border-transparent'
            : 'border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-850'}"
          onclick={() => switchSection("backups")}
        >
          Backups
        </button>
      </nav>

      {#if section === "knowledge"}
        {#if openKnowledge}
          {#key openKnowledge.id}
            <KnowledgeDetail
              knowledgeId={openKnowledge.id}
              knowledgeName={openKnowledge.name}
              initialFileId={openKnowledge.fileId}
              onBack={() => (openKnowledge = null)}
              onOpenKnowledge={(id, name, fileId = null) => (openKnowledge = { id, name, fileId })}
            />
          {/key}
        {:else}
          <Knowledge onOpen={(kb) => (openKnowledge = { id: kb.id, name: kb.name })} />
        {/if}
      {:else if section === "coe"}
        <CoE onOpenKnowledge={openKnowledgeCollection} />
      {:else if section === "backups"}
        <Backups />
      {:else if openCourseProjectId}
        {#key openCourseProjectId}
          <CourseDetail projectId={openCourseProjectId} onBack={() => (openCourseProjectId = null)} onOpenKnowledgeCollection={openKnowledgeCollection} />
        {/key}
      {:else}
        <Courses onOpen={(project) => (openCourseProjectId = project.id)} />
      {/if}
    {/key}
  {/if}
</main>

<style>
  main {
    max-width: 1600px;
    margin: 0 auto;
    padding: 2rem 1.5rem 4rem;
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
  }

  header h1 {
    font-size: 1.4rem;
    font-weight: 600;
    margin: 0 0 0.3rem;
    letter-spacing: -0.01em;
  }

  .subtitle {
    color: var(--owui-text-muted);
    margin: 0;
    font-size: 0.9rem;
  }
</style>
