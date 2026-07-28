<script>
  import { buildAnnotatedHtml, detectFlaggedSpans, detectRepeatedLineSpans, rebaseRedactions } from "./annotate.js";

  let { text = $bindable(""), redactions = $bindable([]), disabled = false, chunks = [] } = $props();

  let textareaEl = $state();
  let backdropEl = $state();
  let selection = $state({ start: 0, end: 0 });

  // Figure/table captions left behind where an image used to be — flagged
  // for the user's attention, recomputed live as the text changes. Never
  // auto-redacted; the user decides whether to keep or remove each one.
  const flagged = $derived(detectFlaggedSpans(text));

  // Likely running headers/footers (e.g. a company banner repeated once per
  // page, possibly with a varying page number) — same "flag, don't touch"
  // treatment, rendered in a distinct (yellow) color so the two kinds of
  // review candidates aren't confused with each other.
  const repeated = $derived(detectRepeatedLineSpans(text));

  const backdropHtml = $derived(buildAnnotatedHtml(text, redactions, chunks, flagged, repeated));
  const canRedact = $derived(!disabled && selection.end > selection.start);

  function handleInput(event) {
    const newText = event.target.value;
    redactions = rebaseRedactions(text, newText, redactions);
    text = newText;
  }

  function handleSelect(event) {
    let { selectionStart, selectionEnd } = event.target;

    // A plain click (collapsed selection) landing inside a flagged caption
    // or a likely repeated header/footer auto-expands to the whole span, so
    // one more click on "Redact selection" removes exactly that span.
    if (selectionStart === selectionEnd) {
      const hit = [...flagged, ...repeated].find((f) => f.start <= selectionStart && selectionStart < f.end);
      if (hit) {
        selectionStart = hit.start;
        selectionEnd = hit.end;
        textareaEl.setSelectionRange(hit.start, hit.end);
      }
    }

    selection = { start: selectionStart, end: selectionEnd };
  }

  function handleScroll() {
    backdropEl.scrollTop = textareaEl.scrollTop;
    backdropEl.scrollLeft = textareaEl.scrollLeft;
  }

  function redactSelection() {
    if (!canRedact) return;
    redactions = [...redactions, { start: selection.start, end: selection.end }];
    const collapsedAt = selection.end;
    selection = { start: collapsedAt, end: collapsedAt };
    // Collapse the browser's own native selection too — otherwise its
    // (unstyled, but still visible) highlight lingers over the now-redacted
    // range after focus moves to the button, sitting oddly next to the
    // <mark> highlight in the backdrop.
    textareaEl.setSelectionRange(collapsedAt, collapsedAt);
  }

  function clearAllRedactions() {
    redactions = [];
  }
</script>

<div class="editor">
  <div class="toolbar">
    <button type="button" disabled={!canRedact} onclick={redactSelection}>
      Redact selection
    </button>
    <button type="button" disabled={disabled || redactions.length === 0} onclick={clearAllRedactions}>
      Clear all redactions
    </button>
    <span class="hint">
      {redactions.length} redaction{redactions.length === 1 ? "" : "s"} marked — removed permanently before this
      document is sent to Open WebUI.
      {#if chunks.length > 0}
        · {chunks.length} chunk{chunks.length === 1 ? "" : "s"} (approx.)
      {/if}
      {#if flagged.length > 0}
        · <span class="flagged-hint">{flagged.length} figure caption{flagged.length === 1 ? "" : "s"} flagged</span>
      {/if}
      {#if repeated.length > 0}
        · <span class="repeated-hint">{repeated.length} repeated line{repeated.length === 1 ? "" : "s"} found</span>
        (likely a page header/footer)
      {/if}
      {#if flagged.length > 0 || repeated.length > 0}
        — click one to select it, then Redact if you don't want it kept
      {/if}
    </span>
  </div>

  <div class="editor-surface">
    <div bind:this={backdropEl} class="backdrop" aria-hidden="true">{@html backdropHtml}</div>
    {#if !disabled}
      <textarea
        bind:this={textareaEl}
        class="input"
        spellcheck="false"
        value={text}
        oninput={handleInput}
        onselect={handleSelect}
        onclick={handleSelect}
        onkeyup={handleSelect}
        onscroll={handleScroll}
      ></textarea>
    {/if}
  </div>
</div>

<style>
  .editor {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    height: 100%;
  }

  .toolbar {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .hint {
    font-size: 0.85rem;
    opacity: 0.7;
  }

  .flagged-hint {
    color: var(--owui-danger);
    opacity: 1;
    font-weight: 500;
  }

  .repeated-hint {
    color: var(--owui-warning);
    opacity: 1;
    font-weight: 500;
  }

  .editor-surface {
    position: relative;
    flex: 1;
    min-height: 320px;
    background: var(--owui-bg-secondary);
    border: 1px solid var(--owui-border);
    border-radius: 0.75rem;
    overflow: hidden;
  }

  .backdrop,
  .input {
    position: absolute;
    inset: 0;
    margin: 0;
    padding: 0.85rem 1rem;
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 0.9rem;
    line-height: 1.55;
    white-space: pre-wrap;
    word-wrap: break-word;
    overflow: auto;
    box-sizing: border-box;
  }

  .backdrop {
    color: var(--owui-text);
    pointer-events: none;
  }

  .input {
    background: transparent;
    color: transparent;
    caret-color: var(--owui-text);
    resize: none;
    border: none;
    outline: none;
  }

  :global(.backdrop mark.redacted) {
    background: var(--owui-danger);
    color: transparent;
    border-radius: 0.25rem;
  }

  :global(.backdrop mark.flagged) {
    background: color-mix(in srgb, var(--owui-danger) 20%, transparent);
    border-bottom: 2px solid var(--owui-danger);
    border-radius: 0.15rem;
  }

  :global(.backdrop mark.repeated) {
    background: color-mix(in srgb, var(--owui-warning) 25%, transparent);
    border-bottom: 2px solid var(--owui-warning);
    border-radius: 0.15rem;
  }

  :global(.backdrop .chunk-even) {
    background: color-mix(in srgb, var(--owui-text) 5%, transparent);
  }

  :global(.backdrop .chunk-odd) {
    background: color-mix(in srgb, var(--owui-text) 16%, transparent);
  }

  /* An explicit marker at the start of every chunk after the first — the
     alternating background alone is subtle enough to miss at a glance. */
  :global(.backdrop .chunk-start::before) {
    content: "▏";
    color: var(--owui-accent);
    font-weight: 700;
  }

  :global(.backdrop mark.redacted.chunk-even),
  :global(.backdrop mark.redacted.chunk-odd) {
    background: var(--owui-danger);
  }
</style>
