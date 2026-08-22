import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from agora.schemas.deliberation import (
    Contribution,
    EvidenceResult,
    PanelReview,
    PerspectiveState,
    Proposal,
    ProposalContext,
    ProposalInput,
    ProposalResult,
    Refinement,
    Reflection,
    Resolution,
    Revision,
    Suggestion,
    Thread,
    WorkingDocument,
)
from agora.schemas.panel import (
    Observation,
    PerspectiveFormationResult,
    ResearcherProfile,
)
from agora.schemas.research import ClusteredLiterature
from agora.workflow.decisions import (
    ProposalSelection,
    SuggestionDecision,
    ThreadDecision,
)
from agora.workflow.events import ProposalsSelected, WorkflowEvent, event_id

SQL_VARIABLE_LIMIT = 900

SCHEMA = """
create table if not exists workspaces(
    workspace_id text primary key,
    name text not null,
    created_at text not null);

create table if not exists investigations(
    investigation_id text primary key,
    corpus_id text,
    question text,
    workspace_id text not null default '',
    idea text not null default '',
    title text,
    status text not null default 'active',
    stage text not null default 'brief',
    waiting_for text,
    active_thread_id text,
    document_version integer,
    version integer not null default 1,
    created_at text not null default '');

create table if not exists workflow_state(
    investigation_id text primary key,
    payload text not null);

create table if not exists perspectives(
    perspective_id text primary key,
    investigation_id text not null,
    version integer not null,
    profile text not null,
    source_ids text not null,
    label text not null default '',
    subthemes text not null default '[]',
    map_position text,
    selected integer not null default 1);

create table if not exists snippets(
    snippet_id text primary key,
    source_id text not null,
    title text not null,
    location text,
    text text not null);

create index if not exists snippet_source on snippets(source_id);

create virtual table if not exists snippets_fts using fts5(
    text, content='snippets', content_rowid='rowid');

create table if not exists snippet_vec(
    snippet_id text primary key,
    dim integer not null,
    vec blob not null);

create table if not exists observations(
    observation_id text primary key,
    source_id text not null,
    location text,
    text text not null,
    snippet_id text);

create table if not exists proposals(
    proposal_id text not null,
    version integer not null,
    investigation_id text not null,
    payload text not null,
    primary key (proposal_id, version));

create table if not exists reviews(
    review_id text primary key,
    investigation_id text not null,
    payload text not null);

create table if not exists refinements(
    refinement_id text primary key,
    investigation_id text not null,
    payload text not null);

create table if not exists reflections(
    reflection_id text primary key,
    investigation_id text not null,
    payload text not null);

create table if not exists decisions(
    decision_id text primary key,
    investigation_id text not null,
    kind text not null,
    payload text not null);

create table if not exists documents(
    document_id text not null,
    version integer not null,
    investigation_id text not null,
    payload text not null,
    primary key (document_id, version));

create table if not exists threads(
    thread_id text not null,
    version integer not null,
    investigation_id text not null,
    payload text not null,
    primary key (thread_id, version));

create table if not exists contributions(
    contribution_id text primary key,
    thread_id text not null,
    investigation_id text not null,
    payload text not null);

create table if not exists resolutions(
    resolution_id text not null,
    version integer not null,
    investigation_id text not null,
    payload text not null,
    primary key (resolution_id, version));

create table if not exists suggestions(
    suggestion_id text not null,
    version integer not null,
    investigation_id text not null,
    payload text not null,
    primary key (suggestion_id, version));

create table if not exists revisions(
    revision_id text primary key,
    investigation_id text not null,
    payload text not null);

create table if not exists events(
    event_id text primary key,
    investigation_id text not null,
    kind text not null,
    payload text not null);

create table if not exists deliberation(
    investigation_id text primary key,
    version integer not null);
"""


MIGRATIONS = {
    "perspectives": {
        "label": "text not null default ''",
        "subthemes": "text not null default '[]'",
        "map_position": "text",
        "selected": "integer not null default 1",
    },
    "investigations": {
        "workspace_id": "text not null default ''",
        "idea": "text not null default ''",
        "title": "text",
        "status": "text not null default 'active'",
        "stage": "text not null default 'brief'",
        "waiting_for": "text",
        "active_thread_id": "text",
        "document_version": "integer",
        "version": "integer not null default 1",
        "created_at": "text not null default ''",
    },
    "events": {
        "created_at": "text not null default ''",
    },
}


def connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)

    with connection:
        for table, additions in MIGRATIONS.items():
            columns = {
                row["name"]
                for row in connection.execute(f"pragma table_info({table})")
            }
            for column, definition in additions.items():
                if column not in columns:
                    connection.execute(
                        f"alter table {table} add column {column} {definition}"
                    )

    return connection


def perspective_id(cluster_id: str) -> str:
    return cluster_id.replace("cluster_", "perspective_", 1)


def proposal_id(perspective: str) -> str:
    return perspective.replace("perspective_", "proposal_", 1)


def register_investigation(
    db: sqlite3.Connection,
    *,
    investigation_id: str,
    corpus_id: str,
    question: str,
) -> None:
    with db:
        db.execute(
            "insert into investigations(investigation_id, corpus_id, question)"
            " values (?,?,?) on conflict(investigation_id) do update set"
            " corpus_id = excluded.corpus_id, question = excluded.question",
            (investigation_id, corpus_id, question),
        )


def create_workspace(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    name: str,
    created_at: str,
) -> None:
    with db:
        db.execute(
            "insert or replace into workspaces values (?,?,?)",
            (workspace_id, name, created_at),
        )


def workspaces(db: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.execute(
        "select * from workspaces order by created_at"
    ).fetchall()


def workspace(
    db: sqlite3.Connection,
    workspace_id: str,
) -> sqlite3.Row | None:
    return db.execute(
        "select * from workspaces where workspace_id = ?",
        (workspace_id,),
    ).fetchone()


def create_investigation(
    db: sqlite3.Connection,
    *,
    investigation_id: str,
    workspace_id: str,
    idea: str,
    created_at: str,
) -> None:
    with db:
        db.execute(
            "insert into investigations"
            " (investigation_id, workspace_id, idea, created_at)"
            " values (?,?,?,?)",
            (investigation_id, workspace_id, idea, created_at),
        )


def investigation(
    db: sqlite3.Connection,
    investigation_id: str,
) -> sqlite3.Row | None:
    return db.execute(
        "select * from investigations where investigation_id = ?",
        (investigation_id,),
    ).fetchone()


def workspace_investigations(
    db: sqlite3.Connection,
    workspace_id: str,
) -> list[sqlite3.Row]:
    return db.execute(
        "select * from investigations where workspace_id = ?"
        " order by created_at",
        (workspace_id,),
    ).fetchall()


def perspective_row(
    db: sqlite3.Connection,
    perspective_id: str,
) -> sqlite3.Row | None:
    return db.execute(
        "select perspective_id, investigation_id, version, profile,"
        " source_ids, label, subthemes, map_position, selected"
        " from perspectives where perspective_id = ?",
        (perspective_id,),
    ).fetchone()


def update_investigation(
    db: sqlite3.Connection,
    investigation_id: str,
    **fields,
) -> None:
    if not fields:
        return

    assignments = ", ".join(f"{name} = ?" for name in fields)

    with db:
        db.execute(
            f"update investigations set {assignments}"
            " where investigation_id = ?",
            (*fields.values(), investigation_id),
        )


def save_workflow_state(
    db: sqlite3.Connection,
    investigation_id: str,
    payload: str,
) -> None:
    with db:
        db.execute(
            "insert or replace into workflow_state values (?,?)",
            (investigation_id, payload),
        )


def load_workflow_state(
    db: sqlite3.Connection,
    investigation_id: str,
) -> str | None:
    row = db.execute(
        "select payload from workflow_state where investigation_id = ?",
        (investigation_id,),
    ).fetchone()
    return row["payload"] if row else None


def register_perspectives(
    db: sqlite3.Connection,
    *,
    investigation_id: str,
    panel: dict[str, PerspectiveFormationResult],
    literature: ClusteredLiterature,
    map_positions: dict[str, tuple[float, float]] | None = None,
) -> list[str]:
    members = {cluster.id: cluster.source_ids for cluster in literature.clusters}
    positions = map_positions or {}
    registered = []

    with db:
        for cluster_id, result in panel.items():
            if result.profile is None:
                continue

            identifier = perspective_id(cluster_id)
            label = result.domain.label if result.domain else ""
            subthemes = (
                result.domain.literature.subthemes if result.domain else []
            )
            position = positions.get(cluster_id)
            db.execute(
                "insert or replace into perspectives"
                " (perspective_id, investigation_id, version, profile,"
                " source_ids, label, subthemes, map_position)"
                " values (?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    investigation_id,
                    1,
                    result.profile.model_dump_json(),
                    json.dumps(members[cluster_id]),
                    label,
                    json.dumps(subthemes),
                    json.dumps(position) if position else None,
                ),
            )
            registered.append(identifier)

    return registered


class DeliberationStore(Protocol):
    async def proposal_context(
        self,
        investigation_id: str,
    ) -> ProposalContext:
        ...

    async def save_proposals(
        self,
        investigation_id: str,
        *,
        proposals: list[ProposalResult],
        events: list[WorkflowEvent],
        expected_version: int,
    ) -> int:
        ...

    async def perspectives(
        self,
        investigation_id: str,
    ) -> list[PerspectiveState]:
        ...

    async def proposals(
        self,
        investigation_id: str,
    ) -> list[Proposal]:
        ...

    async def reviews(
        self,
        investigation_id: str,
    ) -> list[PanelReview]:
        ...

    async def save_reviews(
        self,
        investigation_id: str,
        *,
        reviews: list[PanelReview],
        events: list[WorkflowEvent],
        expected_version: int,
    ) -> int:
        ...

    async def save_refinements(
        self,
        investigation_id: str,
        *,
        refinements: list[Refinement],
        events: list[WorkflowEvent],
        expected_version: int,
    ) -> int:
        ...

    async def select_proposals(
        self,
        investigation_id: str,
        decision: ProposalSelection,
    ) -> ProposalsSelected:
        ...

    async def append_events(
        self,
        investigation_id: str,
        *,
        events: list[WorkflowEvent],
        expected_version: int,
    ) -> int:
        ...

    def deliberation_version(self, investigation_id: str) -> int:
        ...

    async def selected_refinements(
        self,
        investigation_id: str,
    ) -> list[Refinement]:
        ...

    async def save_document(
        self,
        investigation_id: str,
        *,
        document: WorkingDocument,
        threads: list[Thread],
        events: list[WorkflowEvent],
        expected_version: int,
    ) -> int:
        ...

    async def thread(
        self,
        investigation_id: str,
        thread_id: str,
    ) -> Thread:
        ...

    async def contributions(
        self,
        investigation_id: str,
        thread_id: str,
    ) -> list[Contribution]:
        ...

    async def save_contributions(
        self,
        investigation_id: str,
        *,
        contributions: list[Contribution],
        evidence: EvidenceResult | None,
        events: list[WorkflowEvent],
        expected_version: int,
    ) -> int:
        ...

    async def save_thread(
        self,
        investigation_id: str,
        *,
        thread: Thread,
        events: list[WorkflowEvent],
        expected_version: int,
    ) -> int:
        ...

    async def save_resolution(
        self,
        investigation_id: str,
        *,
        thread: Thread,
        resolution: Resolution,
        decision: ThreadDecision | None,
        events: list[WorkflowEvent],
        expected_version: int,
    ) -> int:
        ...

    async def save_completion(
        self,
        investigation_id: str,
        *,
        reflections: list[Reflection],
        suggestion: Suggestion | None,
        threads: list[Thread] | None = None,
        events: list[WorkflowEvent],
        expected_version: int,
    ) -> int:
        ...

    async def save_revision(
        self,
        investigation_id: str,
        *,
        document: WorkingDocument,
        suggestion: Suggestion,
        revision: Revision | None,
        decision: SuggestionDecision,
        events: list[WorkflowEvent],
        expected_version: int,
    ) -> int:
        ...


class SqliteDeliberationStore:
    def __init__(self, connection: sqlite3.Connection):
        self.db = connection

    def deliberation_version(self, investigation_id: str) -> int:
        row = self.db.execute(
            "select version from deliberation where investigation_id = ?",
            (investigation_id,),
        ).fetchone()
        return row["version"] if row else 0

    def _advance_version(self, investigation_id: str, expected: int) -> int:
        current = self.deliberation_version(investigation_id)

        if current != expected:
            raise ValueError(
                f"Stale deliberation version: expected {expected}, "
                f"found {current}"
            )

        return current + 1

    def _set_version(self, investigation_id: str, version: int) -> None:
        self.db.execute(
            "insert or replace into deliberation values (?,?)",
            (investigation_id, version),
        )

    def _record_events(self, events: Sequence[WorkflowEvent]) -> None:
        for event in events:
            self.db.execute(
                "insert or ignore into events"
                " (event_id, investigation_id, kind, payload, created_at)"
                " values (?,?,?,?,?)",
                (
                    event.id,
                    event.investigation_id,
                    event.kind,
                    event.model_dump_json(),
                    event.created_at.isoformat(),
                ),
            )

    def _record_decision(
        self,
        investigation_id: str,
        kind: str,
        decision_id: str,
        payload: str,
    ) -> None:
        self.db.execute(
            "insert or replace into decisions values (?,?,?,?)",
            (decision_id, investigation_id, kind, payload),
        )

    def _perspective_rows(self, investigation_id: str) -> list[sqlite3.Row]:
        return self.db.execute(
            "select perspective_id, version, profile, source_ids, label, "
            "subthemes from perspectives where investigation_id = ? "
            "and selected = 1 order by rowid",
            (investigation_id,),
        ).fetchall()

    def perspective_summaries(
        self,
        investigation_id: str,
    ) -> list[sqlite3.Row]:
        return self.db.execute(
            "select perspective_id, version, profile, source_ids, label, "
            "subthemes, map_position, selected from perspectives "
            "where investigation_id = ? order by rowid",
            (investigation_id,),
        ).fetchall()

    def set_perspective_selection(
        self,
        investigation_id: str,
        perspective_ids: Sequence[str],
    ) -> None:
        chosen = set(perspective_ids)

        with self.db:
            for row in self.db.execute(
                "select perspective_id from perspectives "
                "where investigation_id = ?",
                (investigation_id,),
            ).fetchall():
                self.db.execute(
                    "update perspectives set selected = ? "
                    "where perspective_id = ?",
                    (
                        1 if row["perspective_id"] in chosen else 0,
                        row["perspective_id"],
                    ),
                )

    def _observations_for(
        self,
        source_ids: Sequence[str],
    ) -> list[Observation]:
        observations: list[Observation] = []

        for start in range(0, len(source_ids), SQL_VARIABLE_LIMIT):
            chunk = source_ids[start : start + SQL_VARIABLE_LIMIT]
            placeholders = ",".join("?" * len(chunk))
            rows = self.db.execute(
                "select observation_id, source_id, location, text "
                f"from observations where source_id in ({placeholders}) "
                "order by rowid",
                tuple(chunk),
            ).fetchall()
            observations += [
                Observation(
                    id=row["observation_id"],
                    text=row["text"],
                    source_id=row["source_id"],
                    location=row["location"],
                )
                for row in rows
            ]

        return observations

    async def observations_by_ids(
        self,
        observation_ids: Sequence[str],
    ) -> list[Observation]:
        ordered_ids = list(dict.fromkeys(observation_ids))
        by_id: dict[str, Observation] = {}

        for start in range(0, len(ordered_ids), SQL_VARIABLE_LIMIT):
            chunk = ordered_ids[start : start + SQL_VARIABLE_LIMIT]
            placeholders = ",".join("?" * len(chunk))
            rows = self.db.execute(
                "select observation_id, source_id, location, text "
                f"from observations where observation_id in ({placeholders})",
                tuple(chunk),
            ).fetchall()

            for row in rows:
                by_id[row["observation_id"]] = Observation(
                    id=row["observation_id"],
                    text=row["text"],
                    source_id=row["source_id"],
                    location=row["location"],
                )

        return [
            by_id[observation_id]
            for observation_id in ordered_ids
            if observation_id in by_id
        ]

    def _latest_refinements(
        self,
        investigation_id: str,
    ) -> dict[str, Refinement]:
        latest: dict[str, Refinement] = {}

        for row in self.db.execute(
            "select payload from refinements where investigation_id = ? "
            "order by rowid",
            (investigation_id,),
        ):
            refinement = Refinement.model_validate_json(row["payload"])
            key = refinement.proposal.perspective_id
            current = latest.get(key)

            if (
                current is None
                or refinement.proposal.version >= current.proposal.version
            ):
                latest[key] = refinement

        return latest

    def _latest_reflections(
        self,
        investigation_id: str,
    ) -> dict[str, Reflection]:
        latest: dict[str, Reflection] = {}

        for row in self.db.execute(
            "select payload from reflections where investigation_id = ? "
            "order by rowid",
            (investigation_id,),
        ):
            reflection = Reflection.model_validate_json(row["payload"])
            current = latest.get(reflection.perspective_id)

            if (
                current is None
                or reflection.perspective_version
                >= current.perspective_version
            ):
                latest[reflection.perspective_id] = reflection

        return latest

    async def proposal_context(
        self,
        investigation_id: str,
    ) -> ProposalContext:
        investigation = self.db.execute(
            "select corpus_id, question from investigations "
            "where investigation_id = ?",
            (investigation_id,),
        ).fetchone()

        if investigation is None:
            raise ValueError(f"Unknown investigation: {investigation_id}")

        perspectives = [
            ProposalInput(
                proposal_id=proposal_id(row["perspective_id"]),
                perspective_id=row["perspective_id"],
                perspective_version=row["version"],
                profile=ResearcherProfile.model_validate_json(row["profile"]),
                observations=self._observations_for(
                    json.loads(row["source_ids"])
                ),
                source_ids=json.loads(row["source_ids"]),
            )
            for row in self._perspective_rows(investigation_id)
        ]

        return ProposalContext(
            question=investigation["question"],
            corpus_id=investigation["corpus_id"],
            deliberation_version=self.deliberation_version(investigation_id),
            perspectives=perspectives,
        )

    async def perspectives(
        self,
        investigation_id: str,
    ) -> list[PerspectiveState]:
        latest = self._latest_refinements(investigation_id)
        reflected = self._latest_reflections(investigation_id)
        states: list[PerspectiveState] = []

        for row in self._perspective_rows(investigation_id):
            source_ids = json.loads(row["source_ids"])
            refinement = latest.get(row["perspective_id"])
            profile = (
                refinement.profile
                if refinement
                else ResearcherProfile.model_validate_json(row["profile"])
            )
            version = (
                refinement.proposal.perspective_version
                if refinement
                else row["version"]
            )
            reflection = reflected.get(row["perspective_id"])

            if reflection is not None and (
                reflection.perspective_version >= version
            ):
                profile = reflection.profile
                version = reflection.perspective_version

            states.append(
                PerspectiveState(
                    id=row["perspective_id"],
                    version=version,
                    profile=profile,
                    observations=self._observations_for(source_ids),
                    source_ids=source_ids,
                    label=row["label"],
                    subthemes=json.loads(row["subthemes"]),
                )
            )

        return states

    async def proposals(
        self,
        investigation_id: str,
    ) -> list[Proposal]:
        latest = self._latest_refinements(investigation_id)
        opening: dict[str, Proposal] = {}

        for row in self.db.execute(
            "select payload from proposals "
            "where investigation_id = ? and version = 1",
            (investigation_id,),
        ):
            result = ProposalResult.model_validate_json(row["payload"])
            opening[result.proposal.perspective_id] = result.proposal

        proposals: list[Proposal] = []

        for row in self._perspective_rows(investigation_id):
            refinement = latest.get(row["perspective_id"])
            proposal = (
                refinement.proposal
                if refinement
                else opening.get(row["perspective_id"])
            )

            if proposal is not None:
                proposals.append(proposal)

        return proposals

    async def reviews(
        self,
        investigation_id: str,
    ) -> list[PanelReview]:
        return [
            PanelReview.model_validate_json(row["payload"])
            for row in self.db.execute(
                "select payload from reviews where investigation_id = ? "
                "order by rowid",
                (investigation_id,),
            )
        ]

    async def selected_refinements(
        self,
        investigation_id: str,
    ) -> list[Refinement]:
        row = self.db.execute(
            "select payload from decisions where investigation_id = ? "
            "and kind = 'proposal_selection' order by rowid desc limit 1",
            (investigation_id,),
        ).fetchone()

        if row is None:
            raise ValueError("No Proposal selection has been recorded")

        selection = ProposalSelection.model_validate_json(row["payload"])
        refinements = [
            Refinement.model_validate_json(item["payload"])
            for item in self.db.execute(
                "select payload from refinements where investigation_id = ? "
                "order by rowid",
                (investigation_id,),
            )
        ]
        selected: list[Refinement] = []

        for ref in selection.proposals:
            match = next(
                (
                    refinement
                    for refinement in refinements
                    if refinement.proposal.id == ref.id
                    and refinement.proposal.version == ref.version
                ),
                None,
            )

            if match is None:
                raise ValueError(
                    f"No Refinement matches the selection {ref.id} "
                    f"v{ref.version}"
                )

            selected.append(match)

        return selected

    async def thread(
        self,
        investigation_id: str,
        thread_id: str,
    ) -> Thread:
        row = self.db.execute(
            "select payload from threads where thread_id = ? "
            "order by version desc limit 1",
            (thread_id,),
        ).fetchone()

        if row is None:
            raise ValueError(f"Unknown Thread: {thread_id}")

        return Thread.model_validate_json(row["payload"])

    async def contributions(
        self,
        investigation_id: str,
        thread_id: str,
    ) -> list[Contribution]:
        return [
            Contribution.model_validate_json(row["payload"])
            for row in self.db.execute(
                "select payload from contributions where thread_id = ? "
                "order by rowid",
                (thread_id,),
            )
        ]

    async def document(
        self,
        investigation_id: str,
    ) -> WorkingDocument | None:
        row = self.db.execute(
            "select payload from documents where investigation_id = ? "
            "order by version desc limit 1",
            (investigation_id,),
        ).fetchone()
        return WorkingDocument.model_validate_json(row["payload"]) if row else None

    async def threads(self, investigation_id: str) -> list[Thread]:
        rows = self.db.execute(
            "select payload from threads where investigation_id = ? "
            "and (thread_id, version) in ("
            "select thread_id, max(version) from threads "
            "where investigation_id = ? group by thread_id) "
            "order by rowid",
            (investigation_id, investigation_id),
        ).fetchall()
        return [Thread.model_validate_json(row["payload"]) for row in rows]

    async def resolution_for(
        self,
        investigation_id: str,
        thread_id: str,
    ) -> Resolution | None:
        latest: Resolution | None = None

        for row in self.db.execute(
            "select payload from resolutions where investigation_id = ? "
            "order by rowid",
            (investigation_id,),
        ):
            resolution = Resolution.model_validate_json(row["payload"])
            if resolution.thread_id == thread_id:
                latest = resolution

        return latest

    async def resolution(
        self,
        investigation_id: str,
        resolution_id: str,
    ) -> Resolution | None:
        latest: Resolution | None = None

        for row in self.db.execute(
            "select payload from resolutions where investigation_id = ? "
            "order by rowid",
            (investigation_id,),
        ):
            candidate = Resolution.model_validate_json(row["payload"])
            if candidate.id == resolution_id:
                latest = candidate

        return latest

    async def suggestions(
        self,
        investigation_id: str,
        status: str | None = None,
    ) -> list[Suggestion]:
        items = [
            Suggestion.model_validate_json(row["payload"])
            for row in self.db.execute(
                "select payload from suggestions where investigation_id = ? "
                "order by rowid",
                (investigation_id,),
            )
        ]
        if status is None:
            return items
        return [item for item in items if item.status == status]

    async def opening_proposals(
        self,
        investigation_id: str,
    ) -> list[ProposalResult]:
        return [
            ProposalResult.model_validate_json(row["payload"])
            for row in self.db.execute(
                "select payload from proposals "
                "where investigation_id = ? and version = 1 order by rowid",
                (investigation_id,),
            )
        ]

    async def refinements(self, investigation_id: str) -> list[Refinement]:
        return [
            Refinement.model_validate_json(row["payload"])
            for row in self.db.execute(
                "select payload from refinements where investigation_id = ? "
                "order by rowid",
                (investigation_id,),
            )
        ]

    async def reflections(self, investigation_id: str) -> list[Reflection]:
        return [
            Reflection.model_validate_json(row["payload"])
            for row in self.db.execute(
                "select payload from reflections where investigation_id = ? "
                "order by rowid",
                (investigation_id,),
            )
        ]

    def events_after(
        self,
        investigation_id: str,
        after: int = 0,
        limit: int = 500,
    ) -> list[sqlite3.Row]:
        return self.db.execute(
            "select rowid, event_id, kind, payload, created_at from events "
            "where investigation_id = ? and rowid > ? order by rowid limit ?",
            (investigation_id, after, limit),
        ).fetchall()

    async def save_proposals(
        self,
        investigation_id: str,
        *,
        proposals: list[ProposalResult],
        events: list[WorkflowEvent],
        expected_version: int,
    ) -> int:
        with self.db:
            version = self._advance_version(investigation_id, expected_version)

            for result in proposals:
                self.db.execute(
                    "insert or replace into proposals values (?,?,?,?)",
                    (
                        result.proposal.id,
                        result.proposal.version,
                        investigation_id,
                        result.model_dump_json(),
                    ),
                )
                self._record_observations(
                    result.new_observations,
                    result.observation_snippets,
                )

            self._record_events(events)
            self._set_version(investigation_id, version)

        return version

    def _record_observations(
        self,
        observations: Sequence[Observation],
        observation_snippets: dict[str, str],
    ) -> None:
        for observation in observations:
            self.db.execute(
                "insert or replace into observations values (?,?,?,?,?)",
                (
                    observation.id,
                    observation.source_id,
                    observation.location,
                    observation.text,
                    observation_snippets.get(observation.id),
                ),
            )

    async def save_reviews(
        self,
        investigation_id: str,
        *,
        reviews: list[PanelReview],
        events: list[WorkflowEvent],
        expected_version: int,
    ) -> int:
        with self.db:
            version = self._advance_version(investigation_id, expected_version)

            for review in reviews:
                self.db.execute(
                    "insert or replace into reviews values (?,?,?)",
                    (review.id, investigation_id, review.model_dump_json()),
                )

            self._record_events(events)
            self._set_version(investigation_id, version)

        return version

    def _record_refinements(
        self,
        investigation_id: str,
        refinements: Sequence[Refinement],
    ) -> None:
        for refinement in refinements:
            self.db.execute(
                "insert or replace into refinements values (?,?,?)",
                (
                    refinement.id,
                    investigation_id,
                    refinement.model_dump_json(),
                ),
            )

    def _record_reflections(
        self,
        investigation_id: str,
        reflections: Sequence[Reflection],
    ) -> None:
        for reflection in reflections:
            self.db.execute(
                "insert or replace into reflections values (?,?,?)",
                (
                    reflection.id,
                    investigation_id,
                    reflection.model_dump_json(),
                ),
            )

    async def save_refinements(
        self,
        investigation_id: str,
        *,
        refinements: list[Refinement],
        events: list[WorkflowEvent],
        expected_version: int,
    ) -> int:
        with self.db:
            version = self._advance_version(investigation_id, expected_version)
            self._record_refinements(investigation_id, refinements)
            self._record_events(events)
            self._set_version(investigation_id, version)

        return version

    async def select_proposals(
        self,
        investigation_id: str,
        decision: ProposalSelection,
    ) -> ProposalsSelected:
        selected = ProposalsSelected(
            id=event_id(
                decision.run_id,
                "proposals_selected",
                investigation_id,
            ),
            run_id=decision.run_id,
            investigation_id=investigation_id,
            created_at=decision.submitted_at,
            caused_by=decision.id,
            proposal_ids=[ref.id for ref in decision.proposals],
        )

        with self.db:
            version = self._advance_version(
                investigation_id,
                decision.expected_version,
            )
            self._record_decision(
                investigation_id,
                "proposal_selection",
                decision.id,
                decision.model_dump_json(),
            )
            self._record_events([selected])
            self._set_version(investigation_id, version)

        return selected

    async def append_events(
        self,
        investigation_id: str,
        *,
        events: list[WorkflowEvent],
        expected_version: int,
    ) -> int:
        with self.db:
            version = self._advance_version(investigation_id, expected_version)
            self._record_events(events)
            self._set_version(investigation_id, version)

        return version

    def _record_document(
        self,
        investigation_id: str,
        document: WorkingDocument,
    ) -> None:
        self.db.execute(
            "insert or replace into documents values (?,?,?,?)",
            (
                document.id,
                document.version,
                investigation_id,
                document.model_dump_json(),
            ),
        )

    def _record_threads(
        self,
        investigation_id: str,
        threads: Sequence[Thread],
    ) -> None:
        for thread in threads:
            self.db.execute(
                "insert or replace into threads values (?,?,?,?)",
                (
                    thread.id,
                    thread.version,
                    investigation_id,
                    thread.model_dump_json(),
                ),
            )

    async def save_document(
        self,
        investigation_id: str,
        *,
        document: WorkingDocument,
        threads: list[Thread],
        events: list[WorkflowEvent],
        expected_version: int,
    ) -> int:
        with self.db:
            version = self._advance_version(investigation_id, expected_version)
            self._record_document(investigation_id, document)
            self._record_threads(investigation_id, threads)
            self._record_events(events)
            self._set_version(investigation_id, version)

        return version

    async def save_contributions(
        self,
        investigation_id: str,
        *,
        contributions: list[Contribution],
        evidence: EvidenceResult | None,
        events: list[WorkflowEvent],
        expected_version: int,
    ) -> int:
        with self.db:
            version = self._advance_version(investigation_id, expected_version)

            for contribution in contributions:
                self.db.execute(
                    "insert or replace into contributions values (?,?,?,?)",
                    (
                        contribution.id,
                        contribution.thread_id,
                        investigation_id,
                        contribution.model_dump_json(),
                    ),
                )

            if evidence is not None:
                self._record_observations(
                    evidence.new_observations,
                    evidence.observation_snippets,
                )

            self._record_events(events)
            self._set_version(investigation_id, version)

        return version

    async def save_thread(
        self,
        investigation_id: str,
        *,
        thread: Thread,
        events: list[WorkflowEvent],
        expected_version: int,
    ) -> int:
        with self.db:
            version = self._advance_version(investigation_id, expected_version)
            self._record_threads(investigation_id, [thread])
            self._record_events(events)
            self._set_version(investigation_id, version)

        return version

    async def save_resolution(
        self,
        investigation_id: str,
        *,
        thread: Thread,
        resolution: Resolution,
        decision: ThreadDecision | None,
        events: list[WorkflowEvent],
        expected_version: int,
    ) -> int:
        with self.db:
            version = self._advance_version(investigation_id, expected_version)
            self._record_threads(investigation_id, [thread])
            self.db.execute(
                "insert or replace into resolutions values (?,?,?,?)",
                (
                    resolution.id,
                    resolution.version,
                    investigation_id,
                    resolution.model_dump_json(),
                ),
            )

            if decision is not None:
                self._record_decision(
                    investigation_id,
                    "thread_decision",
                    decision.id,
                    decision.model_dump_json(),
                )

            self._record_events(events)
            self._set_version(investigation_id, version)

        return version

    async def save_completion(
        self,
        investigation_id: str,
        *,
        reflections: list[Reflection],
        suggestion: Suggestion | None,
        threads: list[Thread] | None = None,
        events: list[WorkflowEvent],
        expected_version: int,
    ) -> int:
        with self.db:
            version = self._advance_version(investigation_id, expected_version)
            self._record_reflections(investigation_id, reflections)

            if suggestion is not None:
                self._record_suggestion(investigation_id, suggestion)

            if threads:
                self._record_threads(investigation_id, threads)

            self._record_events(events)
            self._set_version(investigation_id, version)

        return version

    def _record_suggestion(
        self,
        investigation_id: str,
        suggestion: Suggestion,
    ) -> None:
        self.db.execute(
            "insert or replace into suggestions values (?,?,?,?)",
            (
                suggestion.id,
                suggestion.version,
                investigation_id,
                suggestion.model_dump_json(),
            ),
        )

    async def save_revision(
        self,
        investigation_id: str,
        *,
        document: WorkingDocument,
        suggestion: Suggestion,
        revision: Revision | None,
        decision: SuggestionDecision,
        events: list[WorkflowEvent],
        expected_version: int,
    ) -> int:
        with self.db:
            version = self._advance_version(investigation_id, expected_version)
            self._record_document(investigation_id, document)
            self._record_suggestion(investigation_id, suggestion)

            if revision is not None:
                self.db.execute(
                    "insert or replace into revisions values (?,?,?)",
                    (
                        revision.id,
                        investigation_id,
                        revision.model_dump_json(),
                    ),
                )

            self._record_decision(
                investigation_id,
                "suggestion_decision",
                decision.id,
                decision.model_dump_json(),
            )
            self._record_events(events)
            self._set_version(investigation_id, version)

        return version
