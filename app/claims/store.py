"""Small local SQLite repository. Original evidence is immutable; reviews append."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from app.claims.checks import RULES_VERSION, run_checks, validate_corrections
from app.claims.extraction import parse_pdf
from app.claims.models import CaseView, Document, ReviewRequest, ReviewSnapshot


class RevisionConflict(Exception):
    pass


class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS cases (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, fictional INTEGER NOT NULL,
                    created_at TEXT NOT NULL, documents TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS documents (
                    case_id TEXT NOT NULL REFERENCES cases(id), role TEXT NOT NULL, content BLOB NOT NULL,
                    PRIMARY KEY(case_id, role));
                CREATE TABLE IF NOT EXISTS reviews (
                    case_id TEXT NOT NULL REFERENCES cases(id), revision INTEGER NOT NULL,
                    payload TEXT NOT NULL, rules_version TEXT NOT NULL, PRIMARY KEY(case_id, revision));
            ''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, title: str, files: dict[str, tuple[str, bytes]], fictional: bool = False) -> CaseView:
        documents = [parse_pdf(role, files[role][0] if role in files else '', files[role][1] if role in files else None)
                     for role in ('policy', 'claim', 'invoice')]
        case_id, created = str(uuid4()), datetime.now(timezone.utc).isoformat()
        with self.connection() as db:
            db.execute('INSERT INTO cases VALUES (?, ?, ?, ?, ?, 0)',
                       (case_id, title, int(fictional), created, json.dumps([d.model_dump() for d in documents])))
            for role, (_, content) in files.items():
                db.execute('INSERT INTO documents VALUES (?, ?, ?)', (case_id, role, content))
        return self.get(case_id)

    def list_cases(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT id,title,fictional,created_at,revision FROM cases ORDER BY created_at DESC LIMIT 100')]

    def get(self, case_id: str) -> CaseView:
        with self.connection() as db:
            row = db.execute('SELECT * FROM cases WHERE id=?', (case_id,)).fetchone()
            if row is None:
                raise KeyError(case_id)
            documents = [Document.model_validate(d) for d in json.loads(row['documents'])]
            review_row = db.execute('SELECT payload FROM reviews WHERE case_id=? AND revision=?', (case_id, row['revision'])).fetchone()
            review = ReviewSnapshot.model_validate_json(review_row['payload']) if review_row else None
            return CaseView(id=case_id, title=row['title'], fictional=bool(row['fictional']), created_at=row['created_at'],
                            revision=row['revision'], documents=documents,
                            findings=review.findings if review else run_checks(documents), review=review)

    def history(self, case_id: str) -> list[ReviewSnapshot]:
        self.get(case_id)
        with self.connection() as db:
            return [ReviewSnapshot.model_validate_json(row['payload']) for row in
                    db.execute('SELECT payload FROM reviews WHERE case_id=? ORDER BY revision DESC', (case_id,))]

    def save_review(self, case_id: str, request: ReviewRequest) -> CaseView:
        if not request.reviewer.strip():
            raise ValueError('Reviewer name is required')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT documents,revision FROM cases WHERE id=?', (case_id,)).fetchone()
            if row is None:
                raise KeyError(case_id)
            if row['revision'] != request.expected_revision:
                raise RevisionConflict('This case changed. Reload before saving; your edit was not applied.')
            documents = [Document.model_validate(d) for d in json.loads(row['documents'])]
            validate_corrections(documents, request.corrections)
            # Request is the full correction set, not a patch. Original evidence remains unchanged.
            review = ReviewSnapshot(rules_version=RULES_VERSION, revision=row['revision'] + 1, created_at=datetime.now(timezone.utc).isoformat(),
                                    reviewer=request.reviewer.strip(), notes=request.notes, status=request.status,
                                    corrections=request.corrections, findings=run_checks(documents, request.corrections))
            db.execute('INSERT INTO reviews VALUES (?,?,?,?)', (case_id, review.revision, review.model_dump_json(), RULES_VERSION))
            db.execute('UPDATE cases SET revision=? WHERE id=?', (review.revision, case_id))
        return self.get(case_id)

    def document_bytes(self, case_id: str, role: str) -> bytes:
        with self.connection() as db:
            row = db.execute('SELECT content FROM documents WHERE case_id=? AND role=?', (case_id, role)).fetchone()
            if row is None:
                raise KeyError(case_id)
            return bytes(row['content'])
