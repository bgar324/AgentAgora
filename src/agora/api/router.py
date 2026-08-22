import asyncio
import json
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent

from agora.api.dependencies import (
    InvestigationDep,
    RunnerDep,
    SettingsDep,
    StoreDep,
)
from agora.db.store import (
    create_investigation,
    create_workspace,
    perspective_row,
    workspace,
    workspace_investigations,
    workspaces,
)
from agora.schemas.api import (
    ContributionCreate,
    ContributionPage,
    DeliberationStart,
    DeliberationView,
    DocumentSectionView,
    EvidenceRequestBody,
    InvestigationCreate,
    InvestigationPatch,
    InvestigationState,
    InvestigationView,
    MapPosition,
    PaperView,
    PerspectiveDiscovery,
    PerspectiveSelection,
    PerspectiveSummary,
    PerspectiveUpdateView,
    PerspectiveView,
    ProposalSelectionBody,
    ProposalView,
    ResolutionDecisionBody,
    ResponseView,
    SectionPatch,
    SourcePage,
    SuggestionDecisionBody,
    ThreadCreate,
    ThreadSummary,
    ThreadView,
    CitationView,
    ContributionView,
    ReferenceView,
    WorkingDocumentView,
    WorkspaceCreate,
    WorkspaceView,
    section_view,
)
from agora.schemas.deliberation import Contribution
from agora.schemas.panel import ResearcherProfile
from agora.schemas.research import PaperCorpus, SearchPlan
from agora.core.errors import Conflict, NotFound
from agora.workflow.run import now

router = APIRouter(prefix="/api/v1")


def fail(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"code": code, "message": message},
    )


def attempt(command):
    try:
        return command()
    except Conflict as error:
        raise fail(409, error.code, error.message) from error
    except NotFound as error:
        raise fail(404, "not_found", error.message) from error


async def attempt_async(coroutine):
    try:
        return await coroutine
    except Conflict as error:
        raise fail(409, error.code, error.message) from error
    except NotFound as error:
        raise fail(404, "not_found", error.message) from error


def investigation_of(identifier: str) -> str:
    return identifier.split(":")[0]


def load_plan(settings, investigation_id: str) -> SearchPlan | None:
    path = settings.server.data_dir / investigation_id / "search_plan.json"
    return SearchPlan.model_validate_json(path.read_text()) if path.exists() else None


def load_corpus(request: Request, investigation_id: str) -> PaperCorpus | None:
    cache = request.app.state.corpus_cache

    if investigation_id in cache:
        return cache[investigation_id]

    settings = request.app.state.settings
    path = settings.server.data_dir / investigation_id / "corpus.json"

    if not path.exists():
        return None

    corpus = PaperCorpus.model_validate_json(path.read_text())
    cache[investigation_id] = corpus

    return corpus


def citation_views(observations, corpus) -> list[CitationView]:
    papers = {
        paper.source_id: paper
        for paper in (corpus.papers if corpus else [])
    }
    views: list[CitationView] = []

    for index, observation in enumerate(observations, start=1):
        paper = papers.get(observation.source_id)
        views.append(
            CitationView(
                index=index,
                title=paper.title if paper else "Unknown source",
                authors=list(paper.authors) if paper else [],
                year=paper.year if paper else None,
                venue=paper.venue if paper else None,
                url=paper.url if paper else None,
                text=observation.text,
            )
        )

    return views


def reference_views(document, corpus) -> list[ReferenceView]:
    papers = {
        paper.source_id: paper
        for paper in (corpus.papers if corpus else [])
    }
    views: list[ReferenceView] = []

    for index, source_id in enumerate(document.references, start=1):
        paper = papers.get(source_id)
        views.append(
            ReferenceView(
                index=index,
                source_id=source_id,
                title=paper.title if paper else "Unknown source",
                authors=list(paper.authors) if paper else [],
                year=paper.year if paper else None,
                venue=paper.venue if paper else None,
                url=paper.url if paper else None,
            )
        )

    return views


def investigation_view(settings, row) -> InvestigationView:
    plan = load_plan(settings, row["investigation_id"])

    return InvestigationView(
        id=row["investigation_id"],
        workspace_id=row["workspace_id"],
        title=row["title"],
        idea=row["idea"],
        research_question=row["question"],
        research_directions=plan.research_directions if plan else [],
        status=row["status"],
        stage=row["stage"],
        waiting_for=row["waiting_for"],
        version=row["version"],
    )


def state_view(row) -> InvestigationState:
    return InvestigationState(
        investigation_id=row["investigation_id"],
        status=row["status"],
        stage=row["stage"],
        waiting_for=row["waiting_for"],
        active_thread_id=row["active_thread_id"],
        document_version=row["document_version"],
        version=row["version"],
    )


def summary_of(row) -> PerspectiveSummary:
    profile = ResearcherProfile.model_validate_json(row["profile"])
    position = (
        json.loads(row["map_position"]) if row["map_position"] else None
    )

    return PerspectiveSummary(
        id=row["perspective_id"],
        name=profile.name or profile.focus,
        focus=profile.focus,
        framing=profile.perspective.framing,
        position=profile.perspective.position,
        source_count=len(json.loads(row["source_ids"])),
        selected=bool(row["selected"]),
        map_position=(
            MapPosition(x=position[0], y=position[1]) if position else None
        ),
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/workspaces")
def list_workspaces(runner: RunnerDep) -> list[WorkspaceView]:
    return [
        WorkspaceView(
            id=row["workspace_id"],
            name=row["name"],
            created_at=row["created_at"],
        )
        for row in workspaces(runner.db)
    ]


@router.post("/workspaces", status_code=201)
def add_workspace(body: WorkspaceCreate, runner: RunnerDep) -> WorkspaceView:
    workspace_id = f"workspace_{uuid4().hex[:8]}"
    created_at = now().isoformat()
    create_workspace(
        runner.db,
        workspace_id=workspace_id,
        name=body.name,
        created_at=created_at,
    )

    return WorkspaceView(id=workspace_id, name=body.name, created_at=created_at)


@router.get("/workspaces/{workspace_id}/investigations")
def list_investigations(
    workspace_id: str,
    runner: RunnerDep,
    settings: SettingsDep,
) -> list[InvestigationView]:
    if workspace(runner.db, workspace_id) is None:
        raise fail(404, "not_found", f"Unknown workspace: {workspace_id}")

    return [
        investigation_view(settings, row)
        for row in workspace_investigations(runner.db, workspace_id)
    ]


@router.post("/workspaces/{workspace_id}/investigations", status_code=202)
async def add_investigation(
    workspace_id: str,
    body: InvestigationCreate,
    runner: RunnerDep,
    settings: SettingsDep,
) -> InvestigationView:
    if workspace(runner.db, workspace_id) is None:
        raise fail(404, "not_found", f"Unknown workspace: {workspace_id}")

    investigation_id = f"investigation_{uuid4().hex[:8]}"
    create_investigation(
        runner.db,
        investigation_id=investigation_id,
        workspace_id=workspace_id,
        idea=body.idea,
        created_at=now().isoformat(),
    )
    attempt(
        lambda: runner.start_brief(
            investigation_id,
            idea=body.idea,
            n=body.n,
        )
    )

    return investigation_view(settings, runner.investigation(investigation_id))


@router.get("/investigations/{investigation_id}")
def read_investigation(
    investigation: InvestigationDep,
    settings: SettingsDep,
) -> InvestigationView:
    return investigation_view(settings, investigation)


@router.patch("/investigations/{investigation_id}")
async def patch_investigation(
    investigation: InvestigationDep,
    body: InvestigationPatch,
    runner: RunnerDep,
    settings: SettingsDep,
) -> InvestigationView:
    investigation_id = investigation["investigation_id"]
    attempt(
        lambda: runner.update_brief(
            investigation_id,
            version=body.version,
            title=body.title,
            research_question=body.research_question,
        )
    )

    return investigation_view(settings, runner.investigation(investigation_id))


@router.post("/investigations/{investigation_id}/perspectives", status_code=202)
async def discover_perspectives(
    investigation: InvestigationDep,
    body: PerspectiveDiscovery,
    runner: RunnerDep,
) -> InvestigationState:
    investigation_id = investigation["investigation_id"]

    if body.thread_id is not None:
        raise fail(
            409,
            "not_supported",
            "Thread-scoped Perspective discovery is not available yet",
        )

    attempt(lambda: runner.require_version(investigation_id, body.version))
    attempt(lambda: runner.start_perspectives(investigation_id, n=body.n))

    return state_view(runner.investigation(investigation_id))


@router.get("/investigations/{investigation_id}/perspectives")
def list_perspectives(
    investigation: InvestigationDep,
    store: StoreDep,
) -> list[PerspectiveSummary]:
    return [
        summary_of(row)
        for row in store.perspective_summaries(investigation["investigation_id"])
    ]


@router.put(
    "/investigations/{investigation_id}/perspective-selection",
    status_code=200,
)
async def select_perspectives(
    investigation: InvestigationDep,
    body: PerspectiveSelection,
    runner: RunnerDep,
) -> InvestigationState:
    investigation_id = investigation["investigation_id"]
    attempt(
        lambda: runner.select_perspectives(
            investigation_id,
            perspective_ids=body.perspective_ids,
            version=body.version,
        )
    )

    return state_view(runner.investigation(investigation_id))


@router.get("/perspectives/{perspective_id}")
def read_perspective(
    perspective_id: str,
    runner: RunnerDep,
) -> PerspectiveView:
    row = perspective_row(runner.db, perspective_id)

    if row is None:
        raise fail(404, "not_found", f"Unknown perspective: {perspective_id}")

    profile = ResearcherProfile.model_validate_json(row["profile"])
    position = json.loads(row["map_position"]) if row["map_position"] else None

    return PerspectiveView(
        id=row["perspective_id"],
        name=profile.name or profile.focus,
        focus=profile.focus,
        framing=profile.perspective.framing,
        position=profile.perspective.position,
        facets=profile.facets,
        label=row["label"],
        subthemes=json.loads(row["subthemes"]),
        source_count=len(json.loads(row["source_ids"])),
        selected=bool(row["selected"]),
        map_position=(
            MapPosition(x=position[0], y=position[1]) if position else None
        ),
        version=row["version"],
    )


@router.get("/perspectives/{perspective_id}/sources")
def read_sources(
    perspective_id: str,
    request: Request,
    runner: RunnerDep,
    q: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SourcePage:
    row = perspective_row(runner.db, perspective_id)

    if row is None:
        raise fail(404, "not_found", f"Unknown perspective: {perspective_id}")

    corpus = load_corpus(request, row["investigation_id"])

    if corpus is None:
        raise fail(404, "not_found", "The corpus is not available")

    members = set(json.loads(row["source_ids"]))
    papers = [paper for paper in corpus.papers if paper.source_id in members]

    if q:
        needle = q.casefold()
        papers = [
            paper
            for paper in papers
            if needle in paper.title.casefold()
            or needle in (paper.abstract or "").casefold()
        ]

    return SourcePage(
        items=[PaperView.of(paper) for paper in papers[offset : offset + limit]],
        total=len(papers),
        limit=limit,
        offset=offset,
    )


@router.get("/papers/{paper_id}")
def read_paper(
    paper_id: str,
    request: Request,
    runner: RunnerDep,
) -> PaperView:
    for row in runner.db.execute(
        "select investigation_id from investigations order by rowid"
    ).fetchall():
        corpus = load_corpus(request, row["investigation_id"])

        if corpus is None:
            continue

        for paper in corpus.papers:
            if paper.source_id == paper_id:
                return PaperView.of(paper)

    raise fail(404, "not_found", f"Unknown paper: {paper_id}")


@router.post("/investigations/{investigation_id}/deliberation", status_code=202)
async def start_deliberation(
    investigation: InvestigationDep,
    body: DeliberationStart,
    runner: RunnerDep,
) -> InvestigationState:
    investigation_id = investigation["investigation_id"]
    attempt(
        lambda: runner.start_deliberation(investigation_id, version=body.version)
    )

    return state_view(runner.investigation(investigation_id))


@router.put(
    "/investigations/{investigation_id}/proposal-selection",
    status_code=202,
)
async def select_proposals(
    investigation: InvestigationDep,
    body: ProposalSelectionBody,
    runner: RunnerDep,
) -> InvestigationState:
    investigation_id = investigation["investigation_id"]
    attempt(
        lambda: runner.select_proposals(
            investigation_id,
            proposal_ids=body.proposal_ids,
            version=body.version,
        )
    )

    return state_view(runner.investigation(investigation_id))


async def thread_view(
    store,
    investigation_id: str,
    thread_id: str,
) -> ThreadView:
    thread = await store.thread(investigation_id, thread_id)
    resolution = await store.resolution_for(investigation_id, thread_id)

    return ThreadView(
        id=thread.id,
        version=thread.version,
        status=thread.status,
        title=thread.title,
        question=thread.question,
        context=thread.context,
        section_id=thread.section_id,
        participants=[a.perspective_id for a in thread.assignments],
        resolution=resolution,
    )


def format_report(document, references, *, question: str | None) -> str:
    lines = [f"# {document.title}", ""]

    if question:
        lines += [question, ""]

    if document.objectives:
        lines.append("## Objectives")
        lines += [
            f"{index}. {objective.text}"
            for index, objective in enumerate(document.objectives, start=1)
        ]
        lines.append("")

    for section in document.sections:
        lines += [f"## {section.title}", "", section.text or "", ""]

    if references:
        lines.append("## References")

        for ref in references:
            authors = ", ".join(ref.authors[:3])
            if len(ref.authors) > 3:
                authors += " et al."
            year = f" ({ref.year})" if ref.year else ""
            venue = f" {ref.venue}." if ref.venue else ""
            lines.append(
                f"[{ref.index}] {authors}{year}. {ref.title}.{venue}".strip()
            )

    return "\n".join(lines).strip() + "\n"


@router.get(
    "/investigations/{investigation_id}/report",
    response_class=PlainTextResponse,
)
async def read_report(
    request: Request,
    investigation: InvestigationDep,
    store: StoreDep,
) -> str:
    investigation_id = investigation["investigation_id"]
    document = await store.document(investigation_id)

    if document is None:
        raise fail(404, "not_found", "No Working Document exists yet")

    corpus = load_corpus(request, investigation_id)
    references = reference_views(document, corpus)
    return format_report(
        document,
        references,
        question=investigation["question"],
    )


@router.get("/investigations/{investigation_id}/deliberation")
async def read_deliberation(
    request: Request,
    investigation: InvestigationDep,
    store: StoreDep,
) -> DeliberationView:
    investigation_id = investigation["investigation_id"]
    summaries = [
        summary_of(row)
        for row in store.perspective_summaries(investigation_id)
    ]
    try:
        selected_refinements = await store.selected_refinements(
            investigation_id
        )
    except ValueError:
        selected_refinements = []

    selected_ids = {r.proposal.id for r in selected_refinements}
    corpus = load_corpus(request, investigation_id)
    proposals = []

    for proposal in await store.proposals(investigation_id):
        cited = await store.observations_by_ids(
            [item.observation_id for item in proposal.argument.evidence]
        )
        proposals.append(
            ProposalView(
                id=proposal.id,
                perspective_id=proposal.perspective_id,
                version=proposal.version,
                claim=proposal.claim.text,
                reasoning=proposal.argument.reasoning,
                evidence_count=len(proposal.argument.evidence),
                selected=proposal.id in selected_ids,
                citations=citation_views(cited, corpus),
            )
        )
    responses = [
        ResponseView(
            proposal_id=review.proposal_id,
            reviewer_id=review.reviewer_id,
            response=review.response,
            question=review.question,
        )
        for review in await store.reviews(investigation_id)
    ]
    updates = [
        PerspectiveUpdateView(
            perspective_id=refinement.proposal.perspective_id,
            trigger="response",
            decision=refinement.decision,
            reason=refinement.reason,
            facets_changed=[fr.facet for fr in refinement.facet_revisions],
            open_question=refinement.open_question,
        )
        for refinement in await store.refinements(investigation_id)
    ] + [
        PerspectiveUpdateView(
            perspective_id=reflection.perspective_id,
            trigger="thread",
            decision=reflection.decision,
            reason=reflection.reason,
            facets_changed=[fr.facet for fr in reflection.facet_revisions],
            open_question=reflection.open_question,
        )
        for reflection in await store.reflections(investigation_id)
    ]
    document = await store.document(investigation_id)
    document_view = (
        WorkingDocumentView(
            id=document.id,
            version=document.version,
            title=document.title,
            objectives=document.objectives,
            sections=[section_view(section) for section in document.sections],
            references=reference_views(document, corpus),
        )
        if document
        else None
    )
    threads = await store.threads(investigation_id)
    active_id = investigation["active_thread_id"]
    active = (
        await thread_view(store, investigation_id, active_id)
        if active_id
        else None
    )
    pending_resolution = (
        active.resolution
        if active and active.resolution and active.resolution.status == "pending"
        else None
    )

    return DeliberationView(
        perspectives=summaries,
        proposals=proposals,
        responses=responses,
        perspective_updates=updates,
        objectives=document.objectives if document else [],
        document=document_view,
        threads=[
            ThreadSummary(
                id=thread.id,
                title=thread.title,
                question=thread.question,
                context=thread.context,
                status=thread.status,
                section_id=thread.section_id,
            )
            for thread in threads
        ],
        active_thread=active,
        pending_resolution=pending_resolution,
        pending_suggestions=await store.suggestions(
            investigation_id,
            status="pending",
        ),
    )


@router.post("/investigations/{investigation_id}/threads", status_code=201)
async def add_thread(
    investigation: InvestigationDep,
    body: ThreadCreate,
    runner: RunnerDep,
    store: StoreDep,
) -> ThreadView:
    investigation_id = investigation["investigation_id"]
    if body.thread_id is not None:
        attempt(
            lambda: runner.open_suggested(
                investigation_id,
                body.thread_id or "",
                version=body.version,
            )
        )
        try:
            return await thread_view(store, investigation_id, body.thread_id)
        except ValueError as error:
            raise fail(404, "not_found", str(error)) from error
    else:
        if not body.title.strip() or not body.question.strip():
            raise fail(
                422,
                "validation",
                "A new Thread requires a title and question",
            )
        thread = attempt(
            lambda: runner.create_thread(
                investigation_id,
                title=body.title,
                question=body.question,
                context=body.context,
                version=body.version,
            )
        )

    return ThreadView(
        id=thread.id,
        version=thread.version,
        status=thread.status,
        title=thread.title,
        question=thread.question,
        context=thread.context,
        section_id=thread.section_id,
        participants=[],
        resolution=None,
    )


@router.get("/threads/{thread_id}")
async def read_thread(thread_id: str, store: StoreDep) -> ThreadView:
    investigation_id = investigation_of(thread_id)

    try:
        return await thread_view(store, investigation_id, thread_id)
    except ValueError as error:
        raise fail(404, "not_found", str(error)) from error


@router.get("/threads/{thread_id}/contributions")
async def read_contributions(
    thread_id: str,
    request: Request,
    store: StoreDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ContributionPage:
    investigation_id = investigation_of(thread_id)
    items = await store.contributions(investigation_id, thread_id)
    corpus = load_corpus(request, investigation_id)
    page = []

    for contribution in items[offset : offset + limit]:
        cited = await store.observations_by_ids(contribution.observation_ids)
        page.append(
            ContributionView(
                **contribution.model_dump(),
                citations=citation_views(cited, corpus),
            )
        )

    return ContributionPage(
        items=page,
        total=len(items),
        limit=limit,
        offset=offset,
    )


@router.post("/threads/{thread_id}/contributions", status_code=201)
async def add_contribution(
    thread_id: str,
    body: ContributionCreate,
    runner: RunnerDep,
) -> Contribution:
    supplements = [
        item.value
        for item in body.context
        if item.kind == "text" and item.value
    ]
    text = " ".join([body.text, *supplements]).strip()

    return attempt(
        lambda: runner.add_contribution(
            investigation_of(thread_id),
            thread_id,
            kind=body.kind,
            text=text,
            reply_to=body.reply_to,
        )
    )


@router.post("/threads/{thread_id}/evidence-requests", status_code=202)
async def add_evidence_request(
    thread_id: str,
    body: EvidenceRequestBody,
    runner: RunnerDep,
) -> InvestigationState:
    investigation_id = investigation_of(thread_id)
    attempt(
        lambda: runner.request_evidence(
            investigation_id,
            thread_id,
            need=body.need,
            query=body.query,
        )
    )

    return state_view(runner.investigation(investigation_id))


@router.post("/threads/{thread_id}/resolutions", status_code=202)
async def add_resolution_request(
    thread_id: str,
    runner: RunnerDep,
) -> InvestigationState:
    investigation_id = investigation_of(thread_id)
    attempt(lambda: runner.request_resolution(investigation_id, thread_id))

    return state_view(runner.investigation(investigation_id))


@router.post("/threads/{thread_id}/continuations", status_code=202)
async def continue_thread(
    thread_id: str,
    runner: RunnerDep,
) -> InvestigationState:
    investigation_id = investigation_of(thread_id)
    attempt(lambda: runner.continue_thread(investigation_id, thread_id))

    return state_view(runner.investigation(investigation_id))


@router.post("/resolutions/{resolution_id}/decisions", status_code=202)
async def decide_resolution(
    resolution_id: str,
    body: ResolutionDecisionBody,
    runner: RunnerDep,
    store: StoreDep,
) -> InvestigationState:
    investigation_id = investigation_of(resolution_id)
    resolution = await store.resolution(investigation_id, resolution_id)

    if resolution is None:
        raise fail(404, "not_found", f"Unknown resolution: {resolution_id}")

    attempt(
        lambda: runner.decide_resolution(
            investigation_id,
            resolution,
            action=body.action,
            version=body.version,
            consensus=body.consensus,
            disagreement=body.disagreement,
            open_question=body.open_question,
        )
    )

    return state_view(runner.investigation(investigation_id))


@router.post("/suggestions/{suggestion_id}/decisions", status_code=202)
async def decide_suggestion(
    suggestion_id: str,
    body: SuggestionDecisionBody,
    runner: RunnerDep,
    store: StoreDep,
) -> InvestigationState:
    investigation_id = investigation_of(suggestion_id)
    suggestion = next(
        (
            item
            for item in await store.suggestions(investigation_id)
            if item.id == suggestion_id
        ),
        None,
    )

    if suggestion is None:
        raise fail(404, "not_found", f"Unknown suggestion: {suggestion_id}")

    attempt(
        lambda: runner.decide_suggestion(
            investigation_id,
            suggestion,
            action=body.action,
            version=body.version,
            text=body.text,
        )
    )

    return state_view(runner.investigation(investigation_id))


@router.patch("/document-sections/{section_id}")
async def patch_section(
    section_id: str,
    body: SectionPatch,
    runner: RunnerDep,
) -> DocumentSectionView:
    section = await attempt_async(
        runner.edit_section(
            investigation_of(section_id),
            section_id,
            text=body.text,
            version=body.version,
        )
    )

    return section_view(section)


@router.get(
    "/investigations/{investigation_id}/events",
    response_class=EventSourceResponse,
)
async def stream_events(
    investigation: InvestigationDep,
    runner: RunnerDep,
    last_event_id: Annotated[str | None, Header()] = None,
    after: Annotated[int, Query(ge=0)] = 0,
):
    investigation_id = investigation["investigation_id"]

    if last_event_id and last_event_id.isdigit():
        after = max(after, int(last_event_id))

    for envelope in runner.events_since(investigation_id, after):
        yield ServerSentEvent(data=envelope, event=envelope.type, id=envelope.id)

    queue = runner.open_queue(investigation_id)

    try:
        while True:
            try:
                envelope = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ServerSentEvent(comment="keepalive")
                continue

            yield ServerSentEvent(
                data=envelope,
                event=envelope.type,
                id=envelope.id,
            )
    finally:
        runner.close_queue(investigation_id, queue)
