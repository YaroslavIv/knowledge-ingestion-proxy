import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import JSON, Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _default_expiry() -> datetime:
    return _now() + timedelta(hours=settings.session_ttl_hours)


class OwuiConnection(Base):
    """One saved Open WebUI instance this proxy can talk to.

    Signing in (email + password, against that instance's own
    `/api/v1/auths/signin`) gets us a JWT session token, which we store here
    instead of the password — Open WebUI's auth layer accepts either an API
    key or a JWT as a bearer token identically (see get_current_user), so
    this token works everywhere `settings.owui_api_key` used to. Exactly one
    row is `is_active` at a time; that's the instance every OwuiClient call
    talks to. Lets one person hop between several separately-administered
    Open WebUI deployments (local, Docker, remote) without editing env vars.
    """

    __tablename__ = "owui_connection"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    label: Mapped[str] = mapped_column(String)
    base_url: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String)
    token: Mapped[str] = mapped_column(String)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class IngestionSession(Base):
    """Transient state for one in-progress document, from parse to submit.

    The original file bytes are never stored here or anywhere else — only the
    already-parsed text lives in `current_text`, and only until the session is
    finalized or expires (see routers/documents.py cleanup logic).
    """

    __tablename__ = "ingestion_session"

    session_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_default_expiry)

    original_filename: Mapped[str] = mapped_column(Text)
    original_content_type: Mapped[str | None] = mapped_column(Text, nullable=True)

    current_text: Mapped[str] = mapped_column(Text, default="")
    redactions: Mapped[list] = mapped_column(JSON, default=list)

    target_knowledge_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Set to switch finalize() from "add a new file" to "replace this file's
    # content in place" (same OWUI file_id, re-embedded) — see
    # routers/documents.py finalize_document.
    replace_file_id: Mapped[str | None] = mapped_column(String, nullable=True)

    status: Mapped[str] = mapped_column(String, default="editing")
    # one of: editing | submitting | done | failed

    owui_file_id: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class TrackedCollection(Base):
    """Proxy-local version metadata for an Open WebUI knowledge base.

    Open WebUI has no versioning concept of its own — this table plus
    `TrackedFile` implement a lightweight "git branch" model entirely on our
    side: cloning a collection creates a new row here pointing at the old one
    as `parent_knowledge_id`, and every file starts out tagged with the
    parent's version until it's actually edited/replaced (see TrackedFile).
    """

    __tablename__ = "tracked_collection"

    knowledge_id: Mapped[str] = mapped_column(String, primary_key=True)  # == Open WebUI knowledge.id
    version_tag: Mapped[str] = mapped_column(String)
    parent_knowledge_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Denormalized so the parent's tag is still displayable after the parent
    # itself is deleted.
    parent_version_tag: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Freeform, user-managed organizational tags for the collection itself —
    # independent of version_tag. Hierarchy is expressed by convention only
    # (e.g. "course/uvss" is a child of "course"); no separate tree table.
    tags: Mapped[list] = mapped_column(JSON, default=list)


class TrackedFile(Base):
    """Proxy-local version/tag metadata for a single Open WebUI file.

    `version_tag` tracks which collection version this file's *content*
    currently matches — it starts out equal to whatever version it was
    cloned from (or created in), and only advances when the file is actually
    edited or replaced. A file is "changed in this version" precisely when
    its version_tag equals its collection's current version_tag.
    """

    __tablename__ = "tracked_file"

    file_id: Mapped[str] = mapped_column(String, primary_key=True)  # == Open WebUI file.id
    knowledge_id: Mapped[str] = mapped_column(String, index=True)
    version_tag: Mapped[str] = mapped_column(String)
    tags: Mapped[list] = mapped_column(JSON, default=list)  # freeform, user-managed, independent of version_tag
    cloned_from_file_id: Mapped[str | None] = mapped_column(String, nullable=True)
    last_change_method: Mapped[str | None] = mapped_column(String, nullable=True)  # "text_edit" | "file_replace" | None
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class OriginalFileBlob(Base):
    """A local-disk cache of the true original file bytes for one document.

    Open WebUI never receives these — this proxy always uploads cleaned,
    already-redacted text to Open WebUI (see finalize_document). Kept here,
    on the proxy's own machine, purely so the "existing file" split-pane can
    show the real original (e.g. an actual PDF) instead of just the extracted
    text again. Written at upload time keyed by the ingestion session (before
    an Open WebUI file_id exists yet), then re-keyed to `file_id` once
    finalize() succeeds; anything still unattached once its session is gone
    is orphaned and gets purged (see main.py's periodic cleanup job).
    """

    __tablename__ = "original_file_blob"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    file_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True, unique=True)
    content_type: Mapped[str] = mapped_column(String)
    filename: Mapped[str] = mapped_column(String)
    stored_path: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TagDictionary(Base):
    """Every freeform tag name ever used, kept around after removal from any
    one file so it still shows up as a suggestion later (the point of a
    shared vocabulary — reusing "reviewed" shouldn't depend on some other
    file still wearing it).
    """

    __tablename__ = "tag_dictionary"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CourseProject(Base):
    """One lecture-generation project — a product, its source collections,
    and the pedagogy/language it should be taught in.

    product_knowledge_id / competitors_knowledge_id / instructions_knowledge_id
    point at Open WebUI knowledge bases (competitors is optional — not every
    product has documented competitors). Kept separate on purpose: product
    material is reusable for other tasks (plain Q&A, support, etc.), while
    the instructions collection (methodology + accumulated feedback) is
    specific to "how do we build a lecture" and shouldn't pollute the
    product material with generation-only guidance.
    """

    __tablename__ = "course_project"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String)
    product_knowledge_id: Mapped[str] = mapped_column(String)
    competitors_knowledge_id: Mapped[str | None] = mapped_column(String, nullable=True)
    instructions_knowledge_id: Mapped[str] = mapped_column(String)
    pedagogy_version: Mapped[str] = mapped_column(String, default="v2")
    language: Mapped[str] = mapped_column(String, default="en")
    target_audience: Mapped[str] = mapped_column(String, default="sales")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Lazily created (on the first published module output) Open WebUI
    # knowledge base that holds this project's *generated deliverables*
    # (e.g. per-module SCORM packages) — a completely ordinary
    # TrackedCollection, so the existing Knowledge UI's git-branch-like
    # version badges ("Changed in vX.Y" / "Since vX.Y") work on it
    # unmodified. Distinct from product_knowledge_id etc., which hold
    # *source* material, not generated output.
    output_knowledge_id: Mapped[str | None] = mapped_column(String, nullable=True)


class CourseModuleSpec(Base):
    """One proposed (then human-validated) module in a course's breakdown.

    This is the addressable, editable entity the module-splitting stage
    writes to and the review UI edits/approves — replacing the old
    prototype's implicit module list buried inside a single lecture JSON
    blob. `source_refs` names which product-collection file(s)/sections
    feed this module; `learning_objectives` mirrors the old prototype's
    per-module objectives (see LectureModule.learning_objectives).
    Content generation (a later phase) only runs against `approved` rows.
    """

    __tablename__ = "course_module_spec"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str] = mapped_column(String, index=True)
    order_index: Mapped[int] = mapped_column(default=0)
    title: Mapped[str] = mapped_column(String)
    learning_objectives: Mapped[list] = mapped_column(JSON, default=list)
    source_refs: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String, default="proposed")
    # one of: proposed | approved | rejected
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CourseFeedbackNote(Base):
    """One discrete, reusable piece of generation guidance — either seeded
    from a past reviewer's feedback (parsed into standalone notes, see
    app/course_generation/feedback_seed.py) or added directly by a user.

    project_id=None means the note applies to every future project (e.g.
    "Knowledge Check blocks must look visually distinct from body text" —
    a UI rule, not something specific to one product); module_spec_id=None
    means it's a project-wide note rather than tied to one module. This is
    the standing "don't repeat past mistakes" memory the generation stage
    consults on every run, for this product or a different one.
    """

    __tablename__ = "course_feedback_note"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    module_spec_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    note_text: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String, default="structure")
    # one of: ui | content_repetition | factual_error | structure | packaging
    status: Mapped[str] = mapped_column(String, default="open")
    # one of: open | applied
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CourseModuleOutputVersion(Base):
    """One version of one module's *generated deliverable* (e.g. a SCORM
    package) — an append-only history, so nothing is ever lost even though
    Open WebUI itself can only hold the current version (it has no
    in-place binary-content-replace endpoint, unlike our text-file update
    flow — publishing a new version deletes the previous version's Open
    WebUI file and uploads a fresh one, getting a new file_id each time).

    `owui_file_id` is only meaningful while `is_current` is true; once
    superseded it's set to None (the Open WebUI file is gone) but the
    bytes remain on disk at `stored_path` forever, so an older version can
    still be inspected or restored. `version_tag` is a snapshot of the
    project's output-collection version_tag at publish time — the *live*
    "did this module change in the current version" answer still comes
    from the ordinary TrackedFile row for the current `owui_file_id`
    (same git-branch-like logic as any other knowledge-base file).
    """

    __tablename__ = "course_module_output_version"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    module_spec_id: Mapped[str] = mapped_column(String, index=True)
    version_tag: Mapped[str] = mapped_column(String)
    filename: Mapped[str] = mapped_column(String)
    content_type: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(default=0)
    stored_path: Mapped[str] = mapped_column(String)
    owui_file_id: Mapped[str | None] = mapped_column(String, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # The plain HTML found in this upload (extracted from inside a SCORM
    # zip, or the raw bytes if the upload was already .html) — cached
    # separately so it can be opened directly in a browser (see the
    # `/view` endpoint) instead of only being downloadable as a zip. None
    # when no HTML could be found (a non-HTML, non-zip upload, or a zip
    # with no .html member).
    html_stored_path: Mapped[str | None] = mapped_column(String, nullable=True)

    # The published artifact's OWN file id in Open WebUI (uploaded with
    # process=false — it's a finished deliverable, not something to
    # extract/embed text from; that's the separate manifest-text flow
    # tracked by owui_file_id above, which stays the thing actually linked
    # into the knowledge base). Zips can never be linked into a knowledge
    # base's own file list on Open WebUI (it requires extractable content),
    # but they can still be stored and downloaded through it — this is what
    # makes that true. Kept forever, like stored_path, never cleared on
    # republish.
    raw_owui_file_id: Mapped[str | None] = mapped_column(String, nullable=True)
