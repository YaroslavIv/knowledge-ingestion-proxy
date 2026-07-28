from pydantic import BaseModel

from app.redaction import Redaction


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


class ModelSummary(BaseModel):
    id: str
    name: str | None = None


class CreateCourseProjectRequest(BaseModel):
    name: str
    product_knowledge_id: str
    competitors_knowledge_id: str | None = None
    instructions_knowledge_id: str
    pedagogy_version: str = "v2"
    language: str = "en"
    target_audience: str = "sales"


class CourseProjectSummary(BaseModel):
    id: str
    name: str
    product_knowledge_id: str
    competitors_knowledge_id: str | None = None
    instructions_knowledge_id: str
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
    # Revising an existing module doesn't always need real product facts
    # (e.g. a style/color change) — opt in when it does (e.g. "add more
    # practice using real product details"). Ignored when generating a
    # brand-new module from scratch, which always consults materials.
    include_materials: bool = False
    # Generating a brand-new module (e.g. a final test) may need to know
    # what the OTHER modules actually cover, not just raw product material —
    # opt in to pull their extracted lecture text into the prompt. Ignored
    # when revising an existing module.
    include_other_modules: bool = False
    # Treat this as a from-scratch generation even though a current version
    # already exists — for when a module came out unusable (e.g. an earlier
    # from-scratch generation invented its own layout/colors instead of
    # matching the rest of the course) and small find/replace edits can't
    # reasonably fix it. The existing version is kept in history as usual;
    # this just supersedes it with a full rewrite.
    regenerate_from_scratch: bool = False


class ModuleOutputContentResponse(BaseModel):
    content: str


class AskRoutedRequest(BaseModel):
    collection_ids: list[str]
    query: str
    model: str
    k: int = 3


class AskJointRequest(BaseModel):
    collection_ids: list[str]
    query: str
    model: str
