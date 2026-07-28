from app.chunking.preview import RetrievalChunkingConfig, compute_chunk_preview, with_token_overrides


def test_with_token_overrides_is_noop_without_any_override():
    config = RetrievalChunkingConfig(text_splitter="character", chunk_size=1000, chunk_overlap=100)
    assert with_token_overrides(config, None, None) is config


def test_with_token_overrides_switches_to_token_splitter():
    config = RetrievalChunkingConfig(text_splitter="character", chunk_size=1000, chunk_overlap=100)
    overridden = with_token_overrides(config, 50, 5)
    assert overridden.text_splitter == "token"
    assert overridden.chunk_size == 50
    assert overridden.chunk_overlap == 5


def test_with_token_overrides_falls_back_to_base_for_missing_field():
    config = RetrievalChunkingConfig(text_splitter="character", chunk_size=2000, chunk_overlap=100)
    overridden = with_token_overrides(config, 500, None)
    assert overridden.chunk_size == 500
    assert overridden.chunk_overlap == 100  # base overlap fits comfortably under the new size


def test_with_token_overrides_clamps_overlap_that_would_exceed_the_new_chunk_size():
    # Base config's overlap (100, character-based) would be invalid against a
    # much smaller token-based chunk_size (20) — this used to crash
    # TokenTextSplitter outright; it must now be clamped instead.
    config = RetrievalChunkingConfig(text_splitter="character", chunk_size=1000, chunk_overlap=100)
    overridden = with_token_overrides(config, 20, None)
    assert overridden.chunk_size == 20
    assert overridden.chunk_overlap < overridden.chunk_size

    # And the resulting config must actually be usable, not just internally consistent.
    compute_chunk_preview("word " * 200, overridden)


def test_with_token_overrides_clamps_an_explicit_overlap_too():
    config = RetrievalChunkingConfig(text_splitter="character", chunk_size=1000, chunk_overlap=100)
    overridden = with_token_overrides(config, 10, 50)
    assert overridden.chunk_overlap < overridden.chunk_size


def test_smaller_token_chunk_size_yields_more_chunks():
    text = "word " * 500  # plenty of tokens to split
    base = RetrievalChunkingConfig(text_splitter="character", chunk_size=1000, chunk_overlap=100)

    big_chunks = compute_chunk_preview(text, with_token_overrides(base, 200, 0))
    small_chunks = compute_chunk_preview(text, with_token_overrides(base, 20, 0))

    assert len(small_chunks) > len(big_chunks)
