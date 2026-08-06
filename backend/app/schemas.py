from pydantic import BaseModel

from app.redaction import Redaction


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    token: str
    email: str


class DocumentCreatedResponse(BaseModel):
    session_id: str
    filename: str
    text: str
    warnings: list[str]
    status: str


class DocumentStateResponse(BaseModel):
    session_id: str
    filename: str
    text: str
    redactions: list[Redaction]
    target_knowledge_id: str | None
    status: str
    error_message: str | None = None
    owui_file_id: str | None = None


class DocumentPatchRequest(BaseModel):
    text: str | None = None
    redactions: list[Redaction] | None = None
    target_knowledge_id: str | None = None
    replace_file_id: str | None = None


class ConnectRequest(BaseModel):
    label: str = ""
    base_url: str
    email: str
    password: str


class ConnectionSummary(BaseModel):
    id: str
    label: str
    base_url: str
    email: str
    is_active: bool


class KnowledgeUserSummary(BaseModel):
    name: str | None = None
    email: str | None = None


class KnowledgeBaseSummary(BaseModel):
    id: str
    name: str
    description: str | None = None
    updated_at: int | None = None
    write_access: bool = True
    user: KnowledgeUserSummary | None = None
    version_tag: str | None = None
    tags: list[str] = []


class CreateKnowledgeBaseRequest(BaseModel):
    name: str
    description: str = ""
    version_tag: str = "v1.0"


class KnowledgeParentSummary(BaseModel):
    knowledge_id: str
    name: str
    version_tag: str


class KnowledgeBaseDetail(KnowledgeBaseSummary):
    parent: KnowledgeParentSummary | None = None


class KnowledgeLineageNode(BaseModel):
    knowledge_id: str
    name: str
    version_tag: str
    exists: bool = True  # False if the KB was deleted from Open WebUI but we still know its tag
    changed_file_count: int = 0
    total_file_count: int = 0


class KnowledgeLineageResponse(BaseModel):
    ancestors: list[KnowledgeLineageNode]  # root-first, ending just before the current node
    children: list[KnowledgeLineageNode]


class CloneKnowledgeBaseRequest(BaseModel):
    name: str
    version_tag: str


class CloneKnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    version_tag: str
    files_copied: int
    # Files that couldn't be copied (e.g. the source itself has no
    # extracted content in Open WebUI — a binary/unprocessed file, or one
    # whose extraction genuinely failed) — the clone still completes with
    # everything else rather than aborting entirely on the first bad file.
    skipped: list[dict] = []


class FinalizeResponse(BaseModel):
    owui_file_id: str
    knowledge_id: str


class KnowledgeFileSummary(BaseModel):
    id: str
    filename: str
    created_at: int | None = None
    size: int | None = None
    version_tag: str | None = None
    tags: list[str] = []
    cloned_from_file_id: str | None = None
    changed: bool = False
    last_change_method: str | None = None
    # Whether this proxy has a cached original for this file that is
    # specifically a PDF — false for files with no cached original at all,
    # AND for files whose cached original is some other format (.docx,
    # .txt, ...). See original_storage.has_pdf_original.
    has_pdf_original: bool = False


class UpdateFileTagsRequest(BaseModel):
    tags: list[str]


class UpdateCollectionTagsRequest(BaseModel):
    tags: list[str]


class ChunkRangeModel(BaseModel):
    start: int
    end: int


class ChunkPreviewResponse(BaseModel):
    chunks: list[ChunkRangeModel]
    chunk_size: int
    chunk_overlap: int
    text_splitter: str


class KnowledgeFileContentResponse(BaseModel):
    id: str
    content: str
    chunks: list[ChunkRangeModel]
    warnings: list[str] = []


class UpdateFileContentRequest(BaseModel):
    text: str
    redactions: list[Redaction] = []


class ChunkPreviewRequest(BaseModel):
    text: str
    redactions: list[Redaction] = []
    chunk_size: int | None = None
    chunk_overlap: int | None = None


class TaggedCollectionSummary(BaseModel):
    id: str
    name: str
    version_tag: str


class ModelSummary(BaseModel):
    id: str
    name: str | None = None


class CreateCourseProjectRequest(BaseModel):
    name: str
    product_knowledge_ids: list[str]
    competitors_knowledge_ids: list[str] = []
    instructions_knowledge_ids: list[str]
    visual_knowledge_id: str | None = None
    pedagogy_version: str = "v2"
    language: str = "en"
    target_audience: str = "sales"


class AddCourseMaterialRequest(BaseModel):
    knowledge_id: str


class SetCourseVisualRequest(BaseModel):
    knowledge_id: str


class CourseProjectSummary(BaseModel):
    id: str
    name: str
    product_knowledge_ids: list[str]
    competitors_knowledge_ids: list[str]
    instructions_knowledge_ids: list[str]
    visual_knowledge_id: str | None = None
    output_knowledge_id: str | None = None
    pedagogy_version: str
    language: str
    target_audience: str
    created_at: str


class CourseModuleSpecSummary(BaseModel):
    id: str
    project_id: str
    order_index: int
    title: str
    learning_objectives: list[str]
    source_refs: list[str]
    status: str
    created_at: str
    approved_at: str | None = None
    current_output_version: str | None = None
    output_filename: str | None = None
    output_published_at: str | None = None
    last_generation_settings: dict | None = None


class UpdateCourseModuleSpecRequest(BaseModel):
    title: str | None = None
    learning_objectives: list[str] | None = None
    source_refs: list[str] | None = None
    order_index: int | None = None


class CreateCourseModuleSpecRequest(BaseModel):
    title: str
    learning_objectives: list[str] = []
    source_refs: list[str] = []


class SplitModulesRequest(BaseModel):
    model: str


class SeedFeedbackRequest(BaseModel):
    text: str


class CourseFeedbackNoteSummary(BaseModel):
    id: str
    project_id: str | None = None
    module_spec_id: str | None = None
    note_text: str
    category: str
    status: str
    created_at: str


class CourseModuleOutputVersionSummary(BaseModel):
    id: str
    module_spec_id: str
    version_tag: str
    filename: str
    content_type: str
    size: int
    is_current: bool
    has_html: bool = False
    raw_owui_file_id: str | None = None
    created_at: str


class BumpOutputVersionRequest(BaseModel):
    version_tag: str


class GenerateModuleOutputRequest(BaseModel):
    model: str
    instruction: str
    # Which collections of each role to actually draw from for this call —
    # None means "every collection the project currently has in that role"
    # (the safe default for any caller that doesn't scope explicitly); an
    # explicit list (including []) is honored exactly as given, so a caller
    # can deliberately exclude a noisy/outdated collection for one run.
    product_knowledge_ids: list[str] | None = None
    competitor_knowledge_ids: list[str] | None = None
    instructions_knowledge_ids: list[str] | None = None
    # Whether to pull in the project's visual-style collection, if it has one.
    include_visual: bool = True
    # Which sibling modules' actual generated content to ground this call in
    # — e.g. a final-test module that must only quiz material the course
    # really covers. Every sibling's title+objectives are always visible
    # regardless of this list (cheap, and prevents accidental repeats); this
    # only controls whether their full lecture text is also included. Applies
    # identically whether this call generates from scratch or revises.
    other_module_ids: list[str] = []
    # An explicit sibling module whose HTML to use as a "match this look"
    # visual template, regardless of whether it's also in other_module_ids
    # (content-visibility and style-borrowing are independent choices). None
    # falls back to the project's visual collection, then (only for a
    # from-scratch generation with neither available) the first sibling
    # module found with a published page.
    style_reference_module_id: str | None = None
    # Treat this as a from-scratch generation even though a current version
    # already exists — for when a module came out unusable (e.g. an earlier
    # from-scratch generation invented its own layout/colors instead of
    # matching the rest of the course) and small find/replace edits can't
    # reasonably fix it. The existing version is kept in history as usual;
    # this just supersedes it with a full rewrite.
    regenerate_from_scratch: bool = False


class ProductCollectionFiles(BaseModel):
    knowledge_id: str
    knowledge_name: str
    filenames: list[str]


class GenerationContextSummary(BaseModel):
    """What a Generate/Revise call for one module will actually pull in —
    fetched fresh from the collections every time (see generate_output),
    never cached — so this always reflects their current real content, not
    whatever they held the last time this module was generated. Drives the
    scoping checkboxes in the generate/revise form: one entry per collection
    the caller could choose to include or exclude for this specific call."""

    product_files: list[ProductCollectionFiles]
    competitor_files: list[ProductCollectionFiles]
    instructions_files: list[ProductCollectionFiles]
    visual_present: bool
    feedback_notes_count: int
    has_current_version: bool


class ModuleOutputContentResponse(BaseModel):
    content: str


class ChatMessage(BaseModel):
    role: str
    content: str


class AskRoutedRequest(BaseModel):
    # Exactly one of these two must be given — either an explicit list, or a
    # tag name whose latest-per-lineage collections get resolved server-side
    # (see app/versioning.py's resolve_collection_ids_by_tag).
    collection_ids: list[str] = []
    tag: str | None = None
    query: str
    model: str
    k: int = 3
    # Prior turns, oldest first — same shape as Open WebUI's own /api/chat/
    # completions `messages` array, minus the current question (that's
    # `query` above). Only feeds the actual answer, not the collection-
    # routing/scoring step — see ask_with_routing.
    history: list[ChatMessage] = []


class AskJointRequest(BaseModel):
    collection_ids: list[str] = []
    tag: str | None = None
    query: str
    model: str
    history: list[ChatMessage] = []
