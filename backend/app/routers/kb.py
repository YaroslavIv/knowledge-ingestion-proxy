from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.chunking import compute_chunk_preview, preview_with_redactions
from app.config_cache import get_chunking_config
from app.db import get_db
from app.deps import get_owui_client
from app.models import CourseModuleOutputVersion, TagDictionary, TrackedCollection, TrackedFile
from app.original_storage import delete_original_by_file_id, get_original, has_pdf_original
from app.owui_client import OwuiClient, OwuiError
from app.parsing.dispatch import parse_document
from app.redaction import apply_redactions
from app.schemas import (
    ChunkRangeModel,
    CloneKnowledgeBaseRequest,
    CloneKnowledgeBaseResponse,
    CreateKnowledgeBaseRequest,
    KnowledgeBaseDetail,
    KnowledgeBaseSummary,
    KnowledgeFileContentResponse,
    KnowledgeFileSummary,
    KnowledgeLineageNode,
    KnowledgeLineageResponse,
    KnowledgeParentSummary,
    KnowledgeUserSummary,
    RenameFileRequest,
    UpdateCollectionTagsRequest,
    UpdateFileContentRequest,
    UpdateFileTagsRequest,
)
from app.versioning import (
    bump_file_version,
    count_changed_files,
    get_or_create_tracked_collection,
    get_or_synthesize_tracked_file,
    get_tracked_collection,
    record_new_file,
)

router = APIRouter(prefix="/api/kb", tags=["knowledge-bases"])


def _to_kb_summary(item: dict, version_tag: str | None = None, tags: list[str] | None = None) -> KnowledgeBaseSummary:
    user = item.get("user")
    return KnowledgeBaseSummary(
        id=item["id"],
        name=item["name"],
        description=item.get("description"),
        updated_at=item.get("updated_at"),
        write_access=item.get("write_access", True),
        user=KnowledgeUserSummary(name=user.get("name"), email=user.get("email")) if user else None,
        version_tag=version_tag,
        tags=tags or [],
    )


@router.get("", response_model=list[KnowledgeBaseSummary])
async def list_knowledge_bases(db: AsyncSession = Depends(get_db), client: OwuiClient = Depends(get_owui_client)):
    try:
        items = await client.list_knowledge_bases()
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e

    ids = [item["id"] for item in items]
    tracked = {}
    if ids:
        rows = (await db.execute(select(TrackedCollection).where(TrackedCollection.knowledge_id.in_(ids)))).scalars()
        tracked = {row.knowledge_id: row for row in rows}

    return [
        _to_kb_summary(
            item,
            tracked[item["id"]].version_tag if item["id"] in tracked else None,
            tracked[item["id"]].tags if item["id"] in tracked else None,
        )
        for item in items
    ]


@router.get("/{knowledge_id}", response_model=KnowledgeBaseDetail)
async def get_knowledge_base(
    knowledge_id: str, db: AsyncSession = Depends(get_db), client: OwuiClient = Depends(get_owui_client)
):
    try:
        items = await client.list_knowledge_bases()
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e

    item = next((i for i in items if i["id"] == knowledge_id), None)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge base not found")

    collection = await get_or_create_tracked_collection(db, knowledge_id)
    await db.commit()

    parent = None
    if collection.parent_knowledge_id:
        parent_item = next((i for i in items if i["id"] == collection.parent_knowledge_id), None)
        if parent_item:
            parent = KnowledgeParentSummary(
                knowledge_id=collection.parent_knowledge_id,
                name=parent_item["name"],
                version_tag=collection.parent_version_tag or "",
            )

    summary = _to_kb_summary(item, collection.version_tag, collection.tags)
    return KnowledgeBaseDetail(**summary.model_dump(), parent=parent)


@router.patch("/{knowledge_id}/tags", response_model=KnowledgeBaseSummary)
async def update_collection_tags(
    knowledge_id: str,
    body: UpdateCollectionTagsRequest,
    db: AsyncSession = Depends(get_db),
    client: OwuiClient = Depends(get_owui_client),
):
    try:
        items = await client.list_knowledge_bases()
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e
    item = next((i for i in items if i["id"] == knowledge_id), None)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge base not found")

    collection = await get_or_create_tracked_collection(db, knowledge_id)
    collection.tags = body.tags

    for tag in body.tags:
        if await db.get(TagDictionary, tag) is None:
            db.add(TagDictionary(name=tag))
    await db.commit()

    return _to_kb_summary(item, collection.version_tag, collection.tags)


@router.get("/{knowledge_id}/lineage", response_model=KnowledgeLineageResponse)
async def get_knowledge_lineage(
    knowledge_id: str, db: AsyncSession = Depends(get_db), client: OwuiClient = Depends(get_owui_client)
):
    """The full "git branch" chain around one collection: every ancestor it
    was cloned from (root-first), and every direct child cloned from it —
    each annotated with how many of its files have actually changed, purely
    from our own DB (no need to hit Open WebUI just to size a tree).
    """
    try:
        items = await client.list_knowledge_bases()
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e
    items_by_id = {i["id"]: i for i in items}

    async def _node(node_id: str, name: str, version_tag: str, exists: bool) -> KnowledgeLineageNode:
        changed, total = await count_changed_files(db, node_id, version_tag)
        return KnowledgeLineageNode(
            knowledge_id=node_id, name=name, version_tag=version_tag, exists=exists,
            changed_file_count=changed, total_file_count=total,
        )

    ancestors: list[KnowledgeLineageNode] = []
    cursor = await get_or_create_tracked_collection(db, knowledge_id)
    visited = {knowledge_id}
    while cursor.parent_knowledge_id and cursor.parent_knowledge_id not in visited:
        parent_id = cursor.parent_knowledge_id
        parent_item = items_by_id.get(parent_id)
        if parent_item is None:
            ancestors.append(
                await _node(parent_id, "(deleted)", cursor.parent_version_tag or "", exists=False)
            )
            break
        parent_collection = await get_or_create_tracked_collection(db, parent_id)
        ancestors.append(await _node(parent_id, parent_item["name"], parent_collection.version_tag, exists=True))
        visited.add(parent_id)
        cursor = parent_collection
    ancestors.reverse()  # root-first

    child_rows = (
        await db.execute(select(TrackedCollection).where(TrackedCollection.parent_knowledge_id == knowledge_id))
    ).scalars().all()
    children: list[KnowledgeLineageNode] = []
    for row in child_rows:
        child_item = items_by_id.get(row.knowledge_id)
        if child_item is None:
            continue  # child KB was deleted — nothing meaningful to link to
        children.append(await _node(row.knowledge_id, child_item["name"], row.version_tag, exists=True))

    await db.commit()
    return KnowledgeLineageResponse(ancestors=ancestors, children=children)


@router.post("", response_model=KnowledgeBaseSummary)
async def create_knowledge_base(
    body: CreateKnowledgeBaseRequest,
    db: AsyncSession = Depends(get_db),
    client: OwuiClient = Depends(get_owui_client),
):
    try:
        item = await client.create_knowledge_base(body.name, body.description)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e

    if item is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Open WebUI did not return the created knowledge base")

    db.add(TrackedCollection(knowledge_id=item["id"], version_tag=body.version_tag))
    await db.commit()

    return _to_kb_summary(item, body.version_tag)


@router.post("/{knowledge_id}/clone", response_model=CloneKnowledgeBaseResponse)
async def clone_knowledge_base(
    knowledge_id: str,
    body: CloneKnowledgeBaseRequest,
    db: AsyncSession = Depends(get_db),
    client: OwuiClient = Depends(get_owui_client),
):
    """Fully duplicate a knowledge base into a new one with a new version tag.

    Every file is re-uploaded (new Open WebUI file_id, freshly re-embedded)
    rather than shared with the source — this is a real, independent copy,
    not a lazy reference, so N files means N re-embeddings. Each copy starts
    out tagged with the *source* file's existing version_tag (nothing has
    changed yet); editing or replacing a specific file later is what bumps
    just that file to this new collection's tag.
    """
    source_collection = await get_or_create_tracked_collection(db, knowledge_id)

    try:
        source_files_raw = await client.list_knowledge_files(knowledge_id, include_content=False)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e
    source_files = source_files_raw.get("items", source_files_raw) if isinstance(source_files_raw, dict) else source_files_raw

    try:
        new_kb = await client.create_knowledge_base(body.name, "")
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e
    new_knowledge_id = new_kb["id"]

    db.add(
        TrackedCollection(
            knowledge_id=new_knowledge_id,
            version_tag=body.version_tag,
            parent_knowledge_id=knowledge_id,
            parent_version_tag=source_collection.version_tag,
        )
    )

    copied = 0
    skipped: list[dict] = []
    for item in source_files:
        source_file_id = item["id"]
        filename = item.get("filename") or item.get("meta", {}).get("name", "untitled")
        try:
            content = await client.get_file_content(source_file_id)

            source_tracked = await get_or_synthesize_tracked_file(db, source_file_id, knowledge_id)

            # We're re-uploading EXTRACTED TEXT, not the original file's raw
            # bytes — Open WebUI picks its processing pipeline from the
            # filename's extension, not the declared content-type. Confirmed
            # live: keeping a source file's original extension (e.g. a real
            # ".pdf") made it try to parse plain text as an actual PDF and
            # fail with "Extracted content is not available", even though
            # the content itself was perfectly good — renaming to ".md"
            # (matching course-generation's own manifest uploads) fixed it
            # outright, for every file that failed this way.
            stem = filename.rsplit(".", 1)[0] if "." in filename else filename
            upload_filename = f"{stem}.md"

            result = await client.upload_file_to_knowledge(
                filename=upload_filename, content=content, knowledge_id=new_knowledge_id
            )
            new_file_id = result.get("id")
            # Restore the source file's real display name (see
            # OwuiClient.rename_file / finalize_document for why the .md
            # extension is required on upload but purely cosmetic afterward).
            # Best-effort: a rename failure shouldn't fail an otherwise-
            # successful clone.
            try:
                await client.rename_file(new_file_id, filename)
            except OwuiError:
                pass

            db.add(
                TrackedFile(
                    file_id=new_file_id,
                    knowledge_id=new_knowledge_id,
                    version_tag=source_tracked.version_tag,
                    tags=list(source_tracked.tags or []),
                    cloned_from_file_id=source_file_id,
                )
            )
            copied += 1
        except OwuiError as e:
            # Some files can still fail for other reasons (Open WebUI's own
            # duplicate-content detection, a transient error, etc.) — one
            # bad file must not nuke the whole clone; skip it and continue.
            skipped.append({"filename": filename, "reason": e.detail})

    if copied == 0 and source_files:
        # Every single file failed to copy — an empty "clone" of a
        # non-empty collection isn't a real clone, just clutter. Undo the
        # destination KB (never committed yet, so rollback discards the
        # TrackedCollection row too) instead of leaving it behind as an
        # orphan the way this used to.
        await db.rollback()
        try:
            await client.delete_knowledge_base(new_knowledge_id)
        except OwuiError:
            pass
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not clone any files: " + "; ".join(f"{s['filename']}: {s['reason']}" for s in skipped),
        )

    await db.commit()

    return CloneKnowledgeBaseResponse(
        id=new_knowledge_id, name=body.name, version_tag=body.version_tag, files_copied=copied, skipped=skipped
    )


@router.post("/{knowledge_id}/files/{file_id}/reembed", response_model=bool)
async def reembed_file(knowledge_id: str, file_id: str, client: OwuiClient = Depends(get_owui_client)):
    """Re-push this one file's already-extracted text unchanged, forcing
    Open WebUI to recompute its embedding under whatever embedding model /
    chunk size+overlap it currently has configured in its own Admin
    Settings — changing those settings there never retroactively re-embeds
    already-processed files on its own; only a real content push does (see
    update_file_content's own docstring).

    Deliberately one file per call rather than one endpoint looping over
    the whole collection: the frontend calls this once per file, in its own
    loop, so it can show live per-file progress (a real progress bar, not
    one opaque all-or-nothing wait) while re-embedding a large collection.
    """
    try:
        content = await client.get_file_content(file_id)
        await client.update_file_content(file_id, content)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e
    return True


@router.delete("/{knowledge_id}", response_model=bool)
async def delete_knowledge_base(
    knowledge_id: str, db: AsyncSession = Depends(get_db), client: OwuiClient = Depends(get_owui_client)
):
    try:
        await client.delete_knowledge_base(knowledge_id)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e

    tracked_file_ids = (
        await db.execute(select(TrackedFile.file_id).where(TrackedFile.knowledge_id == knowledge_id))
    ).scalars().all()
    for file_id in tracked_file_ids:
        await delete_original_by_file_id(db, file_id)

    if tracked_file_ids:
        # A course module's published output is an ordinary file inside its
        # project's output KB — if this whole KB (or one of its files, see
        # delete_knowledge_file below) gets deleted this way, the course
        # generator must stop thinking that file still exists: otherwise the
        # next publish tries to update a file Open WebUI no longer has
        # (502), and /original keeps serving a "deleted" file's content.
        await db.execute(
            update(CourseModuleOutputVersion)
            .where(CourseModuleOutputVersion.owui_file_id.in_(tracked_file_ids))
            .values(owui_file_id=None)
        )

    await db.execute(delete(TrackedFile).where(TrackedFile.knowledge_id == knowledge_id))
    await db.execute(delete(TrackedCollection).where(TrackedCollection.knowledge_id == knowledge_id))
    await db.commit()
    return True


@router.get("/{knowledge_id}/files", response_model=list[KnowledgeFileSummary])
async def list_knowledge_files(
    knowledge_id: str, db: AsyncSession = Depends(get_db), client: OwuiClient = Depends(get_owui_client)
):
    try:
        result = await client.list_knowledge_files(knowledge_id, include_content=False)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e

    items = result.get("items", result) if isinstance(result, dict) else result
    collection = await get_or_create_tracked_collection(db, knowledge_id)

    summaries = []
    for item in items:
        tracked = await get_or_synthesize_tracked_file(db, item["id"], knowledge_id)
        filename = item.get("filename") or item.get("meta", {}).get("name", "untitled")
        summaries.append(
            KnowledgeFileSummary(
                id=item["id"],
                filename=filename,
                created_at=item.get("created_at"),
                size=item.get("meta", {}).get("size"),
                version_tag=tracked.version_tag,
                tags=list(tracked.tags or []),
                cloned_from_file_id=tracked.cloned_from_file_id,
                changed=tracked.version_tag == collection.version_tag,
                last_change_method=tracked.last_change_method,
                # Two independent ways a file's original can genuinely be a
                # PDF: (a) this proxy ingested it itself and cached the real
                # bytes (see original_storage.has_pdf_original) — Open WebUI
                # then only ever sees the cleaned text, renamed to .md, so
                # the filename itself tells us nothing for these; or (b) it
                # entered the collection some other way (uploaded straight
                # into Open WebUI), in which case Open WebUI's own /original
                # fallback serves ITS real stored bytes — for those, the
                # filename Open WebUI reports is the genuine original one,
                # so a plain ".pdf" extension is already a reliable signal
                # with no extra network round-trip needed.
                has_pdf_original=filename.lower().endswith(".pdf") or await has_pdf_original(db, item["id"]),
            )
        )
    await db.commit()
    return summaries


@router.patch("/{knowledge_id}/files/{file_id}/tags", response_model=KnowledgeFileSummary)
async def update_file_tags(
    knowledge_id: str, file_id: str, body: UpdateFileTagsRequest, db: AsyncSession = Depends(get_db)
):
    tracked = await get_or_synthesize_tracked_file(db, file_id, knowledge_id)
    tracked.tags = body.tags
    tracked.updated_at = datetime.now(timezone.utc)

    for tag in body.tags:
        if await db.get(TagDictionary, tag) is None:
            db.add(TagDictionary(name=tag))
    await db.commit()

    collection = await get_or_create_tracked_collection(db, knowledge_id)
    return KnowledgeFileSummary(
        id=file_id,
        filename="",
        version_tag=tracked.version_tag,
        tags=list(tracked.tags or []),
        cloned_from_file_id=tracked.cloned_from_file_id,
        changed=tracked.version_tag == collection.version_tag,
        last_change_method=tracked.last_change_method,
        has_pdf_original=await has_pdf_original(db, file_id),
    )


@router.patch("/{knowledge_id}/files/{file_id}/name", response_model=KnowledgeFileSummary)
async def rename_knowledge_file(
    knowledge_id: str,
    file_id: str,
    body: RenameFileRequest,
    db: AsyncSession = Depends(get_db),
    client: OwuiClient = Depends(get_owui_client),
):
    filename = body.filename.strip()
    if not filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filename must not be empty")

    try:
        await client.rename_file(file_id, filename)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e

    tracked = await get_or_synthesize_tracked_file(db, file_id, knowledge_id)
    collection = await get_or_create_tracked_collection(db, knowledge_id)
    await db.commit()

    return KnowledgeFileSummary(
        id=file_id,
        filename=filename,
        version_tag=tracked.version_tag,
        tags=list(tracked.tags or []),
        cloned_from_file_id=tracked.cloned_from_file_id,
        changed=tracked.version_tag == collection.version_tag,
        last_change_method=tracked.last_change_method,
        has_pdf_original=filename.lower().endswith(".pdf") or await has_pdf_original(db, file_id),
    )


@router.get("/{knowledge_id}/files/{file_id}", response_model=KnowledgeFileContentResponse)
async def get_knowledge_file(knowledge_id: str, file_id: str, client: OwuiClient = Depends(get_owui_client)):
    try:
        content = await client.get_file_content(file_id)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e

    config = await get_chunking_config(client)
    chunks = compute_chunk_preview(content, config)

    return KnowledgeFileContentResponse(
        id=file_id,
        content=content,
        chunks=[ChunkRangeModel(start=c.start, end=c.end) for c in chunks],
    )


@router.get("/{knowledge_id}/files/{file_id}/original")
async def get_knowledge_file_original(
    knowledge_id: str,
    file_id: str,
    db: AsyncSession = Depends(get_db),
    client: OwuiClient = Depends(get_owui_client),
):
    """The real original file, if this proxy has one cached locally (see
    original_storage.py) — falling back to whatever Open WebUI itself has
    stored (the same cleaned text again, for files this proxy uploaded; a
    genuine original for files that entered the collection some other way).
    """
    cached = await get_original(db, file_id)
    if cached is not None:
        content, content_type, filename = cached
        return Response(
            content=content,
            media_type=content_type,
            headers={"X-Original-Filename": quote(filename), "X-Original-Source": "proxy-cache"},
        )

    # A course-generator output file gets its knowledge-base content REPLACED
    # in place on every republish/revision (update_file_content posts to Open
    # WebUI's .../data/content/update) — but Open WebUI's raw .../content
    # endpoint (what get_file_raw below hits) keeps serving whatever bytes
    # were FIRST uploaded for that file_id, forever. For an ordinary ingested
    # document that's the correct "true original", but for a course module it
    # would show a stale, possibly many-versions-old deliverable. So for
    # these files, "original" means this module's own currently-cached HTML,
    # not Open WebUI's frozen blob.
    course_version = (
        await db.execute(
            select(CourseModuleOutputVersion).where(
                CourseModuleOutputVersion.owui_file_id == file_id,
                CourseModuleOutputVersion.is_current.is_(True),
            )
        )
    ).scalar_one_or_none()
    if course_version is not None and course_version.html_stored_path:
        html_path = Path(course_version.html_stored_path)
        if html_path.is_file():
            return Response(
                content=html_path.read_bytes(),
                media_type="text/html",
                headers={
                    "X-Original-Filename": quote(course_version.filename),
                    "X-Original-Source": "course-generator-current-version",
                },
            )

    try:
        content, content_type, filename = await client.get_file_raw(file_id)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e

    return Response(
        content=content,
        media_type=content_type,
        # HTTP header values must be latin-1 — filenames routinely aren't
        # (em dashes, non-Latin scripts), so this is percent-encoded; the
        # frontend decodeURIComponent()s it back (see KnowledgeDetail.svelte).
        headers={"X-Original-Filename": quote(filename), "X-Original-Source": "open-webui"},
    )


@router.post("/{knowledge_id}/files/{file_id}/reparse", response_model=KnowledgeFileContentResponse)
async def reparse_knowledge_file(
    knowledge_id: str,
    file_id: str,
    db: AsyncSession = Depends(get_db),
    client: OwuiClient = Depends(get_owui_client),
):
    """Re-run our own parser (app/parsing/dispatch.py) against the true
    original — same source `/original` serves — and return the freshly
    extracted text WITHOUT saving it. Lets a user pull a fresh extraction
    (e.g. after a parser improvement, or to discard prior manual edits) back
    into the editor; they still have to press Update to actually push it,
    exactly like any other edit.
    """
    cached = await get_original(db, file_id)
    if cached is not None:
        data, content_type, filename = cached
    else:
        try:
            data, content_type, filename = await client.get_file_raw(file_id)
        except OwuiError as e:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e

    result = parse_document(filename, content_type, data)
    config = await get_chunking_config(client)
    chunks = compute_chunk_preview(result.text, config)

    return KnowledgeFileContentResponse(
        id=file_id,
        content=result.text,
        chunks=[ChunkRangeModel(start=c.start, end=c.end) for c in chunks],
        warnings=result.warnings,
    )


@router.delete("/{knowledge_id}/files/{file_id}", response_model=bool)
async def delete_knowledge_file(
    knowledge_id: str, file_id: str, db: AsyncSession = Depends(get_db), client: OwuiClient = Depends(get_owui_client)
):
    try:
        await client.remove_file_from_knowledge(knowledge_id, file_id)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e

    await db.execute(delete(TrackedFile).where(TrackedFile.file_id == file_id))
    await delete_original_by_file_id(db, file_id)
    # See the matching comment in delete_knowledge_base — a course module's
    # output file can be deleted through this exact generic endpoint too.
    await db.execute(
        update(CourseModuleOutputVersion)
        .where(CourseModuleOutputVersion.owui_file_id == file_id)
        .values(owui_file_id=None)
    )
    await db.commit()
    return True


@router.post("/{knowledge_id}/files/{file_id}/content", response_model=KnowledgeFileContentResponse)
async def update_knowledge_file(
    knowledge_id: str,
    file_id: str,
    body: UpdateFileContentRequest,
    db: AsyncSession = Depends(get_db),
    client: OwuiClient = Depends(get_owui_client),
):
    """Edit an already-committed file's content in place.

    Applies any newly-marked redactions the same way the initial ingestion does
    (permanent cut, no trace), then calls Open WebUI's own content-update
    endpoint, which re-embeds the new text into every knowledge base collection
    referencing the file (see docs/mas-baseline/INTEGRATION_NOTES.md in the
    open-webui repo) — so this re-syncs the vector DB, not just the display text.
    """
    final_text = apply_redactions(body.text, body.redactions)
    if not final_text.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Resulting document is empty")

    try:
        await client.update_file_content(file_id, final_text)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e

    await bump_file_version(db, file_id, knowledge_id, method="text_edit")
    await db.commit()

    config = await get_chunking_config(client)
    chunks = compute_chunk_preview(final_text, config)

    return KnowledgeFileContentResponse(
        id=file_id,
        content=final_text,
        chunks=[ChunkRangeModel(start=c.start, end=c.end) for c in chunks],
    )
