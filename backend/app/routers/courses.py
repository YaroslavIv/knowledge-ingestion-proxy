from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.course_generation.feedback_seed import parse_feedback_file
from app.course_generation.html_extract import extract_html_from_upload, extract_text_from_html
from app.course_generation.module_generate import generate_module_output
from app.course_generation.module_split import build_file_excerpts, propose_modules
from app.course_generation.output_storage import build_kb_content, load_stored_text, save_output_bytes
from app.db import get_db
from app.deps import get_owui_client
from app.original_storage import delete_original_by_file_id
from app.models import (
    CourseFeedbackNote,
    CourseModuleOutputVersion,
    CourseModuleSpec,
    CourseProject,
    TrackedCollection,
    TrackedFile,
)
from app.owui_client import OwuiClient, OwuiError
from app.schemas import (
    AddCourseMaterialRequest,
    BumpOutputVersionRequest,
    CourseFeedbackNoteSummary,
    CourseModuleOutputVersionSummary,
    CourseModuleSpecSummary,
    CourseProjectSummary,
    CreateCourseModuleSpecRequest,
    CreateCourseProjectRequest,
    GenerateModuleOutputRequest,
    GenerationContextSummary,
    ModelSummary,
    ModuleOutputContentResponse,
    ProductCollectionFiles,
    SeedFeedbackRequest,
    SplitModulesRequest,
    UpdateCourseModuleSpecRequest,
)
from app.versioning import bump_file_version, get_or_create_tracked_collection, record_new_file

router = APIRouter(prefix="/api/courses", tags=["courses"])


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _project_summary(row: CourseProject) -> CourseProjectSummary:
    return CourseProjectSummary(
        id=row.id,
        name=row.name,
        product_knowledge_ids=list(row.product_knowledge_ids or []),
        competitors_knowledge_id=row.competitors_knowledge_id,
        instructions_knowledge_id=row.instructions_knowledge_id,
        output_knowledge_id=row.output_knowledge_id,
        pedagogy_version=row.pedagogy_version,
        language=row.language,
        target_audience=row.target_audience,
        created_at=_iso(row.created_at),
    )


def _module_summary(row: CourseModuleSpec, current_output: CourseModuleOutputVersion | None = None) -> CourseModuleSpecSummary:
    return CourseModuleSpecSummary(
        id=row.id,
        project_id=row.project_id,
        order_index=row.order_index,
        title=row.title,
        learning_objectives=list(row.learning_objectives or []),
        source_refs=list(row.source_refs or []),
        status=row.status,
        created_at=_iso(row.created_at),
        approved_at=_iso(row.approved_at),
        current_output_version=current_output.version_tag if current_output else None,
        output_filename=current_output.filename if current_output else None,
        output_published_at=_iso(current_output.created_at) if current_output else None,
    )


def _output_version_summary(row: CourseModuleOutputVersion) -> CourseModuleOutputVersionSummary:
    return CourseModuleOutputVersionSummary(
        id=row.id,
        module_spec_id=row.module_spec_id,
        version_tag=row.version_tag,
        filename=row.filename,
        content_type=row.content_type,
        size=row.size,
        is_current=row.is_current,
        has_html=bool(row.html_stored_path),
        raw_owui_file_id=row.raw_owui_file_id,
        created_at=_iso(row.created_at),
    )


async def _get_current_output(db: AsyncSession, module_spec_id: str) -> CourseModuleOutputVersion | None:
    return (
        await db.execute(
            select(CourseModuleOutputVersion).where(
                CourseModuleOutputVersion.module_spec_id == module_spec_id,
                CourseModuleOutputVersion.is_current.is_(True),
            )
        )
    ).scalar_one_or_none()


def _feedback_summary(row: CourseFeedbackNote) -> CourseFeedbackNoteSummary:
    return CourseFeedbackNoteSummary(
        id=row.id,
        project_id=row.project_id,
        module_spec_id=row.module_spec_id,
        note_text=row.note_text,
        category=row.category,
        status=row.status,
        created_at=_iso(row.created_at),
    )


async def _get_project_or_404(db: AsyncSession, project_id: str) -> CourseProject:
    project = await db.get(CourseProject, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course project not found")
    return project


async def _load_kb_files_with_content(client: OwuiClient, knowledge_id: str) -> list[tuple[str, str]]:
    """List every file in a knowledge base and fetch its content — the
    "give me this collection's material as (filename, text) pairs" shape
    both the module-splitting stage and the module-generation stage need.
    """
    try:
        raw = await client.list_knowledge_files(knowledge_id, include_content=False)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e
    items = raw.get("items", raw) if isinstance(raw, dict) else raw

    files: list[tuple[str, str]] = []
    for item in items:
        filename = item.get("filename") or item.get("meta", {}).get("name", "untitled")
        try:
            content = await client.get_file_content(item["id"])
        except OwuiError as e:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e
        files.append((filename, content))
    return files


async def _load_product_files(client: OwuiClient, project: CourseProject) -> list[tuple[str, str]]:
    """Product material can span several collections — flattens all of
    them into one (filename, text) list, same shape a single collection's
    _load_kb_files_with_content would have returned."""
    files: list[tuple[str, str]] = []
    for knowledge_id in project.product_knowledge_ids or []:
        files.extend(await _load_kb_files_with_content(client, knowledge_id))
    return files


async def _list_kb_filenames(client: OwuiClient, knowledge_id: str) -> list[str]:
    """Just the filenames, for a cheap pre-generation preview — unlike
    _load_kb_files_with_content, doesn't fetch every file's full text.
    """
    try:
        raw = await client.list_knowledge_files(knowledge_id, include_content=False)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e
    items = raw.get("items", raw) if isinstance(raw, dict) else raw
    return [item.get("filename") or item.get("meta", {}).get("name", "untitled") for item in items]


async def _load_open_feedback_notes(db: AsyncSession, project_id: str) -> list[str]:
    rows = (
        await db.execute(
            select(CourseFeedbackNote).where(
                or_(CourseFeedbackNote.project_id == project_id, CourseFeedbackNote.project_id.is_(None)),
                CourseFeedbackNote.status == "open",
            )
        )
    ).scalars().all()
    return [r.note_text for r in rows]


@router.get("/available-models", response_model=list[ModelSummary])
async def list_available_models(client: OwuiClient = Depends(get_owui_client)):
    try:
        models = await client.list_models()
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e
    return [ModelSummary(id=m["id"], name=m.get("name")) for m in models]


@router.get("", response_model=list[CourseProjectSummary])
async def list_course_projects(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(CourseProject).order_by(CourseProject.created_at.desc()))).scalars().all()
    return [_project_summary(r) for r in rows]


@router.post("", response_model=CourseProjectSummary)
async def create_course_project(body: CreateCourseProjectRequest, db: AsyncSession = Depends(get_db)):
    if not body.product_knowledge_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one product knowledge base is required")
    row = CourseProject(
        name=body.name,
        product_knowledge_ids=body.product_knowledge_ids,
        competitors_knowledge_id=body.competitors_knowledge_id,
        instructions_knowledge_id=body.instructions_knowledge_id,
        pedagogy_version=body.pedagogy_version,
        language=body.language,
        target_audience=body.target_audience,
    )
    db.add(row)
    await db.commit()
    return _project_summary(row)


@router.post("/{project_id}/materials", response_model=CourseProjectSummary)
async def add_course_material(project_id: str, body: AddCourseMaterialRequest, db: AsyncSession = Depends(get_db)):
    """Add another product-material collection to this project — product
    material is often split across several collections (e.g. a datasheet
    collection plus a separate one per sub-product), and generation pulls
    files from all of them (see _load_kb_files_with_content usage below)."""
    project = await _get_project_or_404(db, project_id)
    ids = list(project.product_knowledge_ids or [])
    if body.knowledge_id not in ids:
        ids.append(body.knowledge_id)
        project.product_knowledge_ids = ids
        await db.commit()
    return _project_summary(project)


@router.delete("/{project_id}/materials/{knowledge_id}", response_model=CourseProjectSummary)
async def remove_course_material(project_id: str, knowledge_id: str, db: AsyncSession = Depends(get_db)):
    project = await _get_project_or_404(db, project_id)
    ids = [i for i in (project.product_knowledge_ids or []) if i != knowledge_id]
    if not ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="A course project needs at least one product material collection"
        )
    project.product_knowledge_ids = ids
    await db.commit()
    return _project_summary(project)


@router.get("/{project_id}", response_model=CourseProjectSummary)
async def get_course_project(project_id: str, db: AsyncSession = Depends(get_db)):
    project = await _get_project_or_404(db, project_id)
    return _project_summary(project)


async def _delete_module_output_artifacts(
    db: AsyncSession,
    client: OwuiClient,
    project: CourseProject,
    module_id: str,
    unlink_manifest_files: bool,
) -> None:
    """Delete every stored artifact for one module's entire output history —
    local disk blobs, raw published files in Open WebUI (never linked into
    any KB, so nothing else ever cleans these up — see upload_raw_file), and
    (when the KB itself isn't also about to be deleted right after this)
    the manifest files linked into the project's output KB.

    Best-effort against Open WebUI: a remote call failing (already gone,
    instance hiccup) must not block the user from actually deleting the
    module/project locally — that's the whole point of clicking delete.
    """
    versions = (
        await db.execute(
            select(CourseModuleOutputVersion).where(CourseModuleOutputVersion.module_spec_id == module_id)
        )
    ).scalars().all()

    if unlink_manifest_files and project.output_knowledge_id:
        manifest_ids = {v.owui_file_id for v in versions if v.owui_file_id}
        for file_id in manifest_ids:
            try:
                await client.remove_file_from_knowledge(project.output_knowledge_id, file_id)
            except OwuiError:
                pass
            await db.execute(delete(TrackedFile).where(TrackedFile.file_id == file_id))
            await delete_original_by_file_id(db, file_id)

    raw_ids = {v.raw_owui_file_id for v in versions if v.raw_owui_file_id}
    for file_id in raw_ids:
        try:
            await client.delete_file(file_id)
        except OwuiError:
            pass

    for v in versions:
        for path_str in (v.stored_path, v.html_stored_path):
            if path_str:
                Path(path_str).unlink(missing_ok=True)

    await db.execute(delete(CourseModuleOutputVersion).where(CourseModuleOutputVersion.module_spec_id == module_id))


@router.delete("/{project_id}", response_model=bool)
async def delete_course_project(
    project_id: str, db: AsyncSession = Depends(get_db), client: OwuiClient = Depends(get_owui_client)
):
    project = await _get_project_or_404(db, project_id)
    module_ids = (
        await db.execute(select(CourseModuleSpec.id).where(CourseModuleSpec.project_id == project_id))
    ).scalars().all()

    for module_id in module_ids:
        # the whole output KB is deleted below in one shot — no need to
        # unlink each manifest file individually first, just clean up raw
        # files (which live outside any KB either way) and local rows.
        await _delete_module_output_artifacts(db, client, project, module_id, unlink_manifest_files=False)

    if project.output_knowledge_id:
        try:
            await client.delete_knowledge_base(project.output_knowledge_id)
        except OwuiError:
            pass
        await db.execute(delete(TrackedFile).where(TrackedFile.knowledge_id == project.output_knowledge_id))
        await db.execute(delete(TrackedCollection).where(TrackedCollection.knowledge_id == project.output_knowledge_id))

    await db.execute(delete(CourseModuleSpec).where(CourseModuleSpec.project_id == project_id))
    await db.execute(delete(CourseFeedbackNote).where(CourseFeedbackNote.project_id == project_id))
    await db.execute(delete(CourseProject).where(CourseProject.id == project_id))
    await db.commit()
    return True


@router.post("/{project_id}/feedback/seed", response_model=list[CourseFeedbackNoteSummary])
async def seed_feedback(project_id: str, body: SeedFeedbackRequest, db: AsyncSession = Depends(get_db)):
    await _get_project_or_404(db, project_id)
    parsed = parse_feedback_file(body.text)
    rows = []
    for note in parsed:
        row = CourseFeedbackNote(
            project_id=project_id,
            note_text=note.note_text if note.module_label is None else f"[{note.module_label}] {note.note_text}",
            category=note.category,
        )
        db.add(row)
        rows.append(row)
    await db.commit()
    return [_feedback_summary(r) for r in rows]


@router.get("/{project_id}/feedback", response_model=list[CourseFeedbackNoteSummary])
async def list_feedback(project_id: str, db: AsyncSession = Depends(get_db)):
    await _get_project_or_404(db, project_id)
    rows = (
        await db.execute(
            select(CourseFeedbackNote)
            .where(or_(CourseFeedbackNote.project_id == project_id, CourseFeedbackNote.project_id.is_(None)))
            .order_by(CourseFeedbackNote.created_at)
        )
    ).scalars().all()
    return [_feedback_summary(r) for r in rows]


@router.get("/{project_id}/modules", response_model=list[CourseModuleSpecSummary])
async def list_modules(project_id: str, db: AsyncSession = Depends(get_db)):
    await _get_project_or_404(db, project_id)
    rows = (
        await db.execute(
            select(CourseModuleSpec)
            .where(CourseModuleSpec.project_id == project_id)
            .order_by(CourseModuleSpec.order_index)
        )
    ).scalars().all()
    if not rows:
        return []
    current_outputs = (
        await db.execute(
            select(CourseModuleOutputVersion).where(
                CourseModuleOutputVersion.module_spec_id.in_([r.id for r in rows]),
                CourseModuleOutputVersion.is_current.is_(True),
            )
        )
    ).scalars().all()
    by_module = {o.module_spec_id: o for o in current_outputs}
    return [_module_summary(r, by_module.get(r.id)) for r in rows]


@router.post("/{project_id}/modules", response_model=CourseModuleSpecSummary)
async def create_module(project_id: str, body: CreateCourseModuleSpecRequest, db: AsyncSession = Depends(get_db)):
    await _get_project_or_404(db, project_id)
    existing = (
        await db.execute(select(CourseModuleSpec).where(CourseModuleSpec.project_id == project_id))
    ).scalars().all()
    row = CourseModuleSpec(
        project_id=project_id,
        order_index=len(existing),
        title=body.title,
        learning_objectives=body.learning_objectives,
        source_refs=body.source_refs,
        status="proposed",
    )
    db.add(row)
    await db.commit()
    return _module_summary(row)


@router.patch("/{project_id}/modules/{module_id}", response_model=CourseModuleSpecSummary)
async def update_module(
    project_id: str, module_id: str, body: UpdateCourseModuleSpecRequest, db: AsyncSession = Depends(get_db)
):
    row = await db.get(CourseModuleSpec, module_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")
    if body.title is not None:
        row.title = body.title
    if body.learning_objectives is not None:
        row.learning_objectives = body.learning_objectives
    if body.source_refs is not None:
        row.source_refs = body.source_refs
    if body.order_index is not None:
        row.order_index = body.order_index
    await db.commit()
    return _module_summary(row)


@router.delete("/{project_id}/modules/{module_id}", response_model=bool)
async def delete_module(
    project_id: str,
    module_id: str,
    db: AsyncSession = Depends(get_db),
    client: OwuiClient = Depends(get_owui_client),
):
    project = await _get_project_or_404(db, project_id)
    row = await db.get(CourseModuleSpec, module_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")
    await _delete_module_output_artifacts(db, client, project, module_id, unlink_manifest_files=True)
    await db.execute(delete(CourseModuleSpec).where(CourseModuleSpec.id == module_id))
    await db.commit()
    return True


@router.post("/{project_id}/modules/{module_id}/approve", response_model=CourseModuleSpecSummary)
async def approve_module(project_id: str, module_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(CourseModuleSpec, module_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")
    row.status = "approved"
    row.approved_at = datetime.now(timezone.utc)
    await db.commit()
    return _module_summary(row)


@router.post("/{project_id}/modules/{module_id}/reject", response_model=CourseModuleSpecSummary)
async def reject_module(project_id: str, module_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(CourseModuleSpec, module_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")
    row.status = "rejected"
    await db.commit()
    return _module_summary(row)


@router.post("/{project_id}/split", response_model=list[CourseModuleSpecSummary])
async def split_into_modules(
    project_id: str,
    body: SplitModulesRequest,
    db: AsyncSession = Depends(get_db),
    client: OwuiClient = Depends(get_owui_client),
):
    """Runs the module-splitting stage and writes the result as `proposed`
    CourseModuleSpec rows — additive: existing rows (already reviewed) are
    left alone, so re-running the split after adding new source material
    doesn't clobber modules a human already approved.
    """
    project = await _get_project_or_404(db, project_id)

    product_files = await _load_product_files(client, project)
    instructions_files = await _load_kb_files_with_content(client, project.instructions_knowledge_id)
    methodology_text = "\n\n---\n\n".join(content for _, content in instructions_files)
    feedback_notes = await _load_open_feedback_notes(db, project_id)

    try:
        proposed = await propose_modules(
            client,
            model=body.model,
            product_files=build_file_excerpts(product_files),
            methodology_text=methodology_text,
            feedback_notes=feedback_notes,
            target_audience=project.target_audience,
            language=project.language,
        )
    except (OwuiError, ValueError) as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e

    existing_count = (
        await db.execute(select(CourseModuleSpec).where(CourseModuleSpec.project_id == project_id))
    ).scalars().all()
    start_index = len(existing_count)

    rows = []
    for i, m in enumerate(proposed):
        row = CourseModuleSpec(
            project_id=project_id,
            order_index=start_index + i,
            title=m.get("title", f"Module {start_index + i + 1}"),
            learning_objectives=m.get("learning_objectives", []),
            source_refs=m.get("source_refs", []),
            status="proposed",
        )
        db.add(row)
        rows.append(row)
    await db.commit()
    return [_module_summary(r) for r in rows]


async def _get_module_or_404(db: AsyncSession, project_id: str, module_id: str) -> CourseModuleSpec:
    row = await db.get(CourseModuleSpec, module_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Module not found")
    return row


async def _ensure_output_knowledge_base(
    db: AsyncSession, client: OwuiClient, project: CourseProject
) -> str:
    """Lazily create the project's output knowledge base on first publish —
    an ordinary knowledge base (TrackedCollection, version_tag "v1.0"), so
    the existing Knowledge UI's version badges work on it unmodified.
    """
    if project.output_knowledge_id:
        return project.output_knowledge_id

    try:
        kb = await client.create_knowledge_base(f"{project.name} — Output", "")
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e

    db.add(TrackedCollection(knowledge_id=kb["id"], version_tag="v1.0"))
    project.output_knowledge_id = kb["id"]
    await db.flush()
    return kb["id"]


async def _persist_new_output_version(
    db: AsyncSession,
    client: OwuiClient,
    project: CourseProject,
    module: CourseModuleSpec,
    filename: str,
    content_type: str,
    data: bytes,
    notes: str,
    method: str,
) -> CourseModuleOutputVersion:
    """Persist a new output version for a module — the tail shared by every
    way of creating one (manual upload, AI generate/revise): cache the raw
    bytes locally forever, extract HTML/text if there is any, push real
    lecture text into the project's output knowledge base, and advance the
    existing TrackedFile/TrackedCollection versioning machinery exactly like
    any other knowledge-base file change.
    """
    output_knowledge_id = await _ensure_output_knowledge_base(db, client, project)
    collection = await get_or_create_tracked_collection(db, output_knowledge_id)

    previous = await _get_current_output(db, module.id)

    stored_path = save_output_bytes(data)
    raw_html = extract_html_from_upload(filename, content_type, data)
    html_stored_path = save_output_bytes(raw_html.encode("utf-8")) if raw_html else None
    lecture_text = extract_text_from_html(raw_html) if raw_html else None

    new_version = CourseModuleOutputVersion(
        module_spec_id=module.id,
        version_tag=collection.version_tag,
        filename=filename,
        content_type=content_type,
        size=len(data),
        stored_path=stored_path,
        html_stored_path=html_stored_path,
        is_current=True,
    )

    kb_content = build_kb_content(
        module_title=module.title,
        version_tag=collection.version_tag,
        filename=new_version.filename,
        content_type=new_version.content_type,
        size=new_version.size,
        published_at=_iso(datetime.now(timezone.utc)),
        notes=notes,
        lecture_text=lecture_text,
    )
    kb_filename = f"{module.title}.md"

    try:
        # The actual published artifact must genuinely live inside Open WebUI
        # too, not just our local disk cache — even a zip, which can never be
        # linked into a knowledge base's own file list (see upload_raw_file).
        raw_result = await client.upload_raw_file(filename, data, content_type, output_knowledge_id)
        new_version.raw_owui_file_id = raw_result.get("id")

        if previous is None or not previous.owui_file_id:
            result = await client.upload_file_to_knowledge(kb_filename, kb_content, output_knowledge_id)
            new_version.owui_file_id = result.get("id")
            await record_new_file(db, new_version.owui_file_id, output_knowledge_id)
        else:
            await client.update_file_content(previous.owui_file_id, kb_content)
            new_version.owui_file_id = previous.owui_file_id
            await bump_file_version(db, previous.owui_file_id, output_knowledge_id, method=method)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e

    if previous is not None:
        previous.is_current = False

    db.add(new_version)
    await db.commit()
    return new_version


@router.post("/{project_id}/modules/{module_id}/output", response_model=CourseModuleOutputVersionSummary)
async def publish_module_output(
    project_id: str,
    module_id: str,
    file: UploadFile,
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
    client: OwuiClient = Depends(get_owui_client),
):
    """Publish a new version of one module's generated deliverable.

    The real uploaded bytes are cached locally forever (every version, not
    just the current one — Open WebUI cannot reliably hold an opaque binary
    file, so it never receives the raw upload). If the upload is (or
    contains) HTML — a SCORM zip's index.html, or a plain .html file — its
    lecture text is extracted and pushed into the project's output
    knowledge base for real, so it's genuinely askable, not just a pointer
    to a download. That push is what the existing TrackedFile/
    TrackedCollection machinery tracks — this module's entry shows "Changed
    in vX.Y" exactly like any other knowledge-base file.
    """
    project = await _get_project_or_404(db, project_id)
    module = await _get_module_or_404(db, project_id, module_id)

    data = await file.read()
    new_version = await _persist_new_output_version(
        db,
        client,
        project,
        module,
        filename=file.filename or "output",
        content_type=file.content_type or "application/octet-stream",
        data=data,
        notes=notes,
        method="output_republish",
    )
    return _output_version_summary(new_version)


@router.get(
    "/{project_id}/modules/{module_id}/generation-context",
    response_model=GenerationContextSummary,
)
async def get_generation_context(
    project_id: str,
    module_id: str,
    db: AsyncSession = Depends(get_db),
    client: OwuiClient = Depends(get_owui_client),
):
    """What a Generate/Revise call for this module will actually pull in —
    shown on the frontend before generating, so it's never a silent guess
    (e.g. confirm here that a cleaned-up collection's file list is now
    actually empty/updated before generating against it)."""
    project = await _get_project_or_404(db, project_id)
    await _get_module_or_404(db, project_id, module_id)

    try:
        kb_items = await client.list_knowledge_bases()
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e
    names_by_id = {item["id"]: item["name"] for item in kb_items}

    product_files = [
        ProductCollectionFiles(
            knowledge_id=knowledge_id,
            knowledge_name=names_by_id.get(knowledge_id, knowledge_id),
            filenames=await _list_kb_filenames(client, knowledge_id),
        )
        for knowledge_id in project.product_knowledge_ids or []
    ]
    instructions_files = await _list_kb_filenames(client, project.instructions_knowledge_id)
    feedback_notes = await _load_open_feedback_notes(db, project_id)
    current = await _get_current_output(db, module_id)

    return GenerationContextSummary(
        product_files=product_files,
        instructions_files=instructions_files,
        feedback_notes_count=len(feedback_notes),
        has_current_version=current is not None,
    )


@router.post(
    "/{project_id}/modules/{module_id}/output/generate",
    response_model=CourseModuleOutputVersionSummary,
)
async def generate_output(
    project_id: str,
    module_id: str,
    body: GenerateModuleOutputRequest,
    db: AsyncSession = Depends(get_db),
    client: OwuiClient = Depends(get_owui_client),
):
    """AI-driven counterpart to the manual-upload publish endpoint: calls
    Open WebUI to write (no prior version) or revise (an existing version)
    this module's interactive HTML page, then persists the result exactly
    like a manual publish — same versioning, same knowledge-base push — so
    the two ways of creating an output version are indistinguishable to
    everything downstream (history, diffing, viewing).
    """
    project = await _get_project_or_404(db, project_id)
    module = await _get_module_or_404(db, project_id, module_id)

    current = await _get_current_output(db, module_id)
    current_html = None
    if not body.regenerate_from_scratch and current is not None and current.html_stored_path and Path(current.html_stored_path).is_file():
        current_html = load_stored_text(current.html_stored_path)

    # Always pulled fresh from the collections — for both a from-scratch
    # write and a revise. A revise that skipped this would only ever see
    # its own previous version's already-baked-in HTML, so it could keep
    # citing facts the source material no longer has (e.g. after cleaning
    # up the product collection) with nothing to ever correct that.
    product_files = await _load_product_files(client, project)
    product_excerpts = build_file_excerpts(product_files)
    instructions_files = await _load_kb_files_with_content(client, project.instructions_knowledge_id)
    methodology_text = "\n\n---\n\n".join(content for _, content in instructions_files)

    # A brand-new module (e.g. a final test) may need to know what the course
    # already covers — the other modules' specs always, their actual
    # generated content only when explicitly requested (it can be large).
    other_modules: list[dict] = []
    other_modules_content: list[dict] = []
    style_reference_html: str | None = None
    if current_html is None:
        other_specs = (
            await db.execute(
                select(CourseModuleSpec)
                .where(
                    CourseModuleSpec.project_id == project_id,
                    CourseModuleSpec.id != module_id,
                )
                .order_by(CourseModuleSpec.order_index)
            )
        ).scalars().all()
        other_modules = [
            {"title": m.title, "learning_objectives": list(m.learning_objectives or [])} for m in other_specs
        ]
        if body.include_other_modules:
            for m in other_specs:
                other_current = await _get_current_output(db, m.id)
                if other_current and other_current.html_stored_path and Path(other_current.html_stored_path).is_file():
                    other_text = extract_text_from_html(load_stored_text(other_current.html_stored_path))
                    if other_text.strip():
                        other_modules_content.append({"title": m.title, "text": other_text})

        # A brand-new module has no page of its own to inherit CSS/layout
        # from, and describing "the other modules" as stripped text (above)
        # carries zero visual information — the model was inventing its own
        # look from scratch, which is why a from-scratch module (e.g. a
        # final-test module) could end up styled nothing like the rest of
        # the course. Give it one real module's actual HTML, in order, as an
        # explicit template to visually match.
        for m in other_specs:
            ref_current = await _get_current_output(db, m.id)
            if ref_current and ref_current.html_stored_path and Path(ref_current.html_stored_path).is_file():
                style_reference_html = load_stored_text(ref_current.html_stored_path)
                break

    feedback_notes = await _load_open_feedback_notes(db, project_id)

    try:
        html = await generate_module_output(
            client,
            model=body.model,
            title=module.title,
            learning_objectives=list(module.learning_objectives or []),
            current_html=current_html,
            instruction=body.instruction,
            product_excerpts=product_excerpts,
            methodology_text=methodology_text,
            feedback_notes=feedback_notes,
            other_modules=other_modules,
            other_modules_content=other_modules_content,
            style_reference_html=style_reference_html,
        )
    except (OwuiError, ValueError) as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e

    new_version = await _persist_new_output_version(
        db,
        client,
        project,
        module,
        filename=f"{module.title}.html",
        content_type="text/html",
        data=html.encode("utf-8"),
        notes=body.instruction,
        method="ai_generate" if current_html is None else "ai_revise",
    )
    return _output_version_summary(new_version)


@router.get(
    "/{project_id}/modules/{module_id}/output/versions",
    response_model=list[CourseModuleOutputVersionSummary],
)
async def list_output_versions(project_id: str, module_id: str, db: AsyncSession = Depends(get_db)):
    await _get_module_or_404(db, project_id, module_id)
    rows = (
        await db.execute(
            select(CourseModuleOutputVersion)
            .where(CourseModuleOutputVersion.module_spec_id == module_id)
            .order_by(CourseModuleOutputVersion.created_at.desc())
        )
    ).scalars().all()
    return [_output_version_summary(r) for r in rows]


@router.get("/{project_id}/modules/{module_id}/output/versions/{version_id}/download")
async def download_output_version(
    project_id: str, module_id: str, version_id: str, db: AsyncSession = Depends(get_db)
):
    await _get_module_or_404(db, project_id, module_id)
    row = await db.get(CourseModuleOutputVersion, version_id)
    if row is None or row.module_spec_id != module_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Output version not found")

    path = Path(row.stored_path)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored file is missing on disk")

    return Response(
        content=path.read_bytes(),
        media_type=row.content_type,
        headers={"Content-Disposition": f'attachment; filename="{row.filename}"'},
    )


@router.get("/{project_id}/modules/{module_id}/output/versions/{version_id}/view")
async def view_output_version_html(
    project_id: str, module_id: str, version_id: str, db: AsyncSession = Depends(get_db)
):
    """Serve the extracted HTML inline (Content-Disposition omitted, so the
    browser renders it directly) — this is how you actually look at the
    finished course, not just download the packaged deliverable.
    """
    await _get_module_or_404(db, project_id, module_id)
    row = await db.get(CourseModuleOutputVersion, version_id)
    if row is None or row.module_spec_id != module_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Output version not found")
    if not row.html_stored_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No HTML was found in this upload")

    path = Path(row.html_stored_path)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored HTML is missing on disk")

    return Response(content=path.read_bytes(), media_type="text/html")


@router.get(
    "/{project_id}/modules/{module_id}/output/versions/{version_id}/content",
    response_model=ModuleOutputContentResponse,
)
async def get_output_version_content(
    project_id: str, module_id: str, version_id: str, db: AsyncSession = Depends(get_db)
):
    """Plain-text-fetchable counterpart to /view (renders inline, no CORS-safe
    way for JS to read it) and /download (forces a browser save) — lets the
    frontend pull a version's cached HTML into JS, e.g. to diff two versions.
    """
    await _get_module_or_404(db, project_id, module_id)
    row = await db.get(CourseModuleOutputVersion, version_id)
    if row is None or row.module_spec_id != module_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Output version not found")
    if not row.html_stored_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No HTML was found in this upload")

    path = Path(row.html_stored_path)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored HTML is missing on disk")

    return ModuleOutputContentResponse(content=load_stored_text(row.html_stored_path))


@router.post(
    "/{project_id}/modules/{module_id}/output/resync",
    response_model=CourseModuleOutputVersionSummary,
)
async def resync_output_content(
    project_id: str,
    module_id: str,
    db: AsyncSession = Depends(get_db),
    client: OwuiClient = Depends(get_owui_client),
):
    """Re-extract and re-push the current version's knowledge-base content
    from its already-cached bytes — no new version, no file_id change, just
    fixes/improves what's searchable (e.g. after an extractor improvement,
    or to backfill entries published before real-text extraction existed).
    """
    await _get_project_or_404(db, project_id)
    module = await _get_module_or_404(db, project_id, module_id)
    current = await _get_current_output(db, module_id)
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No output published yet for this module")

    data = Path(current.stored_path).read_bytes()
    raw_html = extract_html_from_upload(current.filename, current.content_type, data)
    if raw_html and not current.html_stored_path:
        current.html_stored_path = save_output_bytes(raw_html.encode("utf-8"))
    lecture_text = extract_text_from_html(raw_html) if raw_html else None

    kb_content = build_kb_content(
        module_title=module.title,
        version_tag=current.version_tag,
        filename=current.filename,
        content_type=current.content_type,
        size=current.size,
        published_at=_iso(current.created_at),
        lecture_text=lecture_text,
    )

    if not current.owui_file_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This version has no linked knowledge-base file")
    try:
        await client.update_file_content(current.owui_file_id, kb_content)
    except OwuiError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=e.detail) from e

    await db.commit()
    return _output_version_summary(current)


@router.post("/{project_id}/bump-output-version", response_model=CourseProjectSummary)
async def bump_output_version(
    project_id: str, body: BumpOutputVersionRequest, db: AsyncSession = Depends(get_db)
):
    """Cut a new release: advances the output collection's version_tag with
    no file changes. Whichever module gets republished next will be the one
    whose entry flips to "Changed in {new tag}" — siblings keep showing
    "Since {old tag}" until they, too, get a new version — the same diff
    visualization already built for ordinary knowledge-base files.
    """
    project = await _get_project_or_404(db, project_id)
    if not project.output_knowledge_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No output has been published yet for this project.",
        )
    collection = await get_or_create_tracked_collection(db, project.output_knowledge_id)
    collection.version_tag = body.version_tag
    await db.commit()
    return _project_summary(project)
