"""Persistent local memory architecture for Sophyane.

The system keeps raw sources, evergreen Markdown knowledge, generated output,
interaction context and identity memory outside the language model.

It is intentionally provider-free and deterministic. SQLite FTS5 is used when
available; a bounded LIKE-based fallback remains available on minimal builds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
MAX_TEXT_BYTES = 2_000_000
MAX_RESULT_CHARS = 1_200

TEXT_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".kt",
    ".kts",
    ".cpp",
    ".cc",
    ".c",
    ".h",
    ".hpp",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".ini",
    ".cfg",
    ".csv",
    ".log",
    ".html",
    ".css",
    ".xml",
    ".sql",
    ".sh",
    ".bash",
    ".zsh",
}


@dataclass(frozen=True)
class MemoryPaths:
    root: Path
    raw: Path
    wiki: Path
    output: Path
    ctx: Path
    mem: Path
    database: Path
    events: Path
    identity: Path
    preferences: Path
    goals: Path
    projects: Path
    people: Path
    history: Path


def memory_root() -> Path:
    configured = os.environ.get("SOPHYANE_MEMORY_HOME", "").strip()

    if configured:
        return Path(configured).expanduser().resolve()

    return (
        Path.home()
        / ".local"
        / "share"
        / "sophyane"
        / "memory"
    ).resolve()


def paths() -> MemoryPaths:
    root = memory_root()

    return MemoryPaths(
        root=root,
        raw=root / "raw",
        wiki=root / "wiki",
        output=root / "output",
        ctx=root / "ctx",
        mem=root / "mem",
        database=root / "memory.sqlite3",
        events=root / "ctx" / "memory-events.jsonl",
        identity=root / "mem" / "sophyane.md",
        preferences=root / "mem" / "preferences",
        goals=root / "mem" / "goals",
        projects=root / "mem" / "projects",
        people=root / "mem" / "people",
        history=root / "mem" / "history",
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def slugify(value: str, fallback: str = "note") -> str:
    clean = re.sub(
        r"[^a-z0-9]+",
        "-",
        str(value or "").casefold(),
    ).strip("-")

    return clean[:90] or fallback


def title_from_text(text: str, fallback: str = "Memory note") -> str:
    for line in str(text or "").splitlines():
        candidate = re.sub(r"^#+\s*", "", line).strip()

        if candidate:
            return candidate[:100]

    words = re.findall(r"\S+", str(text or ""))

    if words:
        return " ".join(words[:10])[:100]

    return fallback


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def normalized_text(text: str) -> str:
    return "\n".join(
        line.rstrip()
        for line in str(text or "").replace("\r\n", "\n").split("\n")
    ).strip()


def keywords(text: str, limit: int = 12) -> list[str]:
    stop = {
        "about", "after", "again", "also", "among", "and", "are", "because",
        "been", "before", "being", "between", "both", "but", "can", "could",
        "does", "each", "from", "have", "into", "just", "more", "most", "not",
        "only", "other", "our", "over", "same", "should", "some", "such",
        "than", "that", "the", "their", "them", "then", "there", "these",
        "they", "this", "through", "under", "very", "was", "were", "what",
        "when", "where", "which", "while", "with", "would", "your",
    }

    counts: dict[str, int] = {}

    for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text.casefold()):
        if token in stop:
            continue

        counts[token] = counts.get(token, 0) + 1

    ranked = sorted(
        counts.items(),
        key=lambda item: (-item[1], item[0]),
    )

    return [token for token, _ in ranked[:limit]]


def extractive_summary(text: str, max_sentences: int = 4) -> str:
    clean = re.sub(r"\s+", " ", normalized_text(text)).strip()

    if not clean:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", clean)

    if len(sentences) == 1:
        return sentences[0][:700]

    terms = keywords(clean, limit=20)
    term_set = set(terms)

    scored: list[tuple[float, int, str]] = []

    for index, sentence in enumerate(sentences[:80]):
        words = set(
            re.findall(
                r"[a-zA-Z][a-zA-Z0-9_-]{2,}",
                sentence.casefold(),
            )
        )

        score = float(len(words.intersection(term_set)))

        if index == 0:
            score += 1.5

        if 35 <= len(sentence) <= 260:
            score += 0.5

        scored.append((score, index, sentence.strip()))

    selected = sorted(
        sorted(scored, reverse=True)[:max_sentences],
        key=lambda item: item[1],
    )

    summary = " ".join(
        sentence
        for _, _, sentence in selected
        if sentence
    )

    return summary[:1_000]


def open_database() -> sqlite3.Connection:
    initialize()
    connection = sqlite3.connect(paths().database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    return connection


def initialize() -> MemoryPaths:
    target = paths()

    directories = (
        target.raw / "articles",
        target.raw / "pdfs",
        target.raw / "screenshots",
        target.raw / "voice",
        target.raw / "transcripts",
        target.raw / "notes",
        target.raw / "other",
        target.wiki / "concepts",
        target.wiki / "entities",
        target.wiki / "topics",
        target.wiki / "literature",
        target.wiki / "permanent-notes",
        target.wiki / "references",
        target.output / "reports",
        target.output / "presentations",
        target.output / "posts",
        target.output / "documents",
        target.output / "summaries",
        target.output / "visuals",
        target.output / "other",
        target.ctx / "sessions",
        target.ctx / "prompts",
        target.ctx / "templates",
        target.ctx / "rules",
        target.ctx / "snippets",
        target.preferences,
        target.goals,
        target.projects,
        target.people,
        target.history,
    )

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

    if not target.identity.exists():
        target.identity.write_text(
            """# Sophyane Memory

## Identity

- Name: Sophyane
- Memory architecture: persistent local knowledge system
- Privacy: local by default
- Retrieval: SQLite full-text search with deterministic fallback
- Updated: {updated}

## Preferences

Add durable user preferences through:

    sophyane-memory preference "Preference text"

## Goals

Add durable goals through:

    sophyane-memory goal "Goal text"

## Projects

Project memories are stored under `mem/projects/`.
""".format(updated=now_iso()),
            encoding="utf-8",
        )

    connection = sqlite3.connect(target.database)

    try:
        connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                source_path TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL,
                body TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_accessed_at TEXT NOT NULL DEFAULT '',
                access_count INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_documents_kind
                ON documents(kind);

            CREATE INDEX IF NOT EXISTS idx_documents_hash
                ON documents(content_hash);

            CREATE INDEX IF NOT EXISTS idx_documents_updated
                ON documents(updated_at);

            CREATE TABLE IF NOT EXISTS links (
                source_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                relation TEXT NOT NULL DEFAULT 'related',
                weight REAL NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL,
                PRIMARY KEY(source_id, target_id, relation),
                FOREIGN KEY(source_id) REFERENCES documents(id)
                    ON DELETE CASCADE,
                FOREIGN KEY(target_id) REFERENCES documents(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

        try:
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts
                USING fts5(
                    title,
                    summary,
                    body,
                    tags,
                    content='documents',
                    content_rowid='id'
                )
                """
            )

            connection.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS documents_ai
                AFTER INSERT ON documents BEGIN
                    INSERT INTO documents_fts(
                        rowid, title, summary, body, tags
                    )
                    VALUES(
                        new.id, new.title, new.summary,
                        new.body, new.tags
                    );
                END;

                CREATE TRIGGER IF NOT EXISTS documents_ad
                AFTER DELETE ON documents BEGIN
                    INSERT INTO documents_fts(
                        documents_fts, rowid,
                        title, summary, body, tags
                    )
                    VALUES(
                        'delete', old.id, old.title,
                        old.summary, old.body, old.tags
                    );
                END;

                CREATE TRIGGER IF NOT EXISTS documents_au
                AFTER UPDATE ON documents BEGIN
                    INSERT INTO documents_fts(
                        documents_fts, rowid,
                        title, summary, body, tags
                    )
                    VALUES(
                        'delete', old.id, old.title,
                        old.summary, old.body, old.tags
                    );

                    INSERT INTO documents_fts(
                        rowid, title, summary, body, tags
                    )
                    VALUES(
                        new.id, new.title, new.summary,
                        new.body, new.tags
                    );
                END;
                """
            )

            fts_enabled = "1"
        except sqlite3.OperationalError:
            fts_enabled = "0"

        connection.execute(
            """
            INSERT INTO metadata(key, value)
            VALUES('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (str(SCHEMA_VERSION),),
        )

        connection.execute(
            """
            INSERT INTO metadata(key, value)
            VALUES('fts_enabled', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (fts_enabled,),
        )

        connection.commit()
    finally:
        connection.close()

    return target


def record_event(event_type: str, payload: dict[str, Any]) -> None:
    target = initialize()
    event = {
        "timestamp": now_iso(),
        "type": event_type,
        **payload,
    }

    try:
        with target.events.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(event, ensure_ascii=False) + "\n"
            )
    except OSError:
        pass

    try:
        connection = sqlite3.connect(target.database)
        connection.execute(
            """
            INSERT INTO events(event_type, payload, created_at)
            VALUES(?, ?, ?)
            """,
            (
                event_type,
                json.dumps(payload, ensure_ascii=False),
                event["timestamp"],
            ),
        )
        connection.commit()
        connection.close()
    except sqlite3.Error:
        pass


def classify_raw_destination(source: Path) -> Path:
    target = paths()
    suffix = source.suffix.casefold()

    if suffix == ".pdf":
        return target.raw / "pdfs"

    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return target.raw / "screenshots"

    if suffix in {".wav", ".mp3", ".m4a", ".ogg", ".flac"}:
        return target.raw / "voice"

    if "transcript" in source.name.casefold():
        return target.raw / "transcripts"

    if suffix in TEXT_SUFFIXES:
        return target.raw / "notes"

    return target.raw / "other"


def read_source_text(source: Path) -> str:
    try:
        size = source.stat().st_size
    except OSError:
        return ""

    if size > MAX_TEXT_BYTES:
        return ""

    if source.suffix.casefold() not in TEXT_SUFFIXES:
        return ""

    try:
        return source.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return ""


def insert_document(
    *,
    kind: str,
    title: str,
    path: Path,
    source_path: str,
    body: str,
    summary: str,
    tags: Iterable[str],
) -> int:
    content = normalized_text(body)
    digest = sha256_bytes(content.encode("utf-8"))
    timestamp = now_iso()
    tags_json = json.dumps(
        sorted(set(str(tag).casefold() for tag in tags if str(tag).strip())),
        ensure_ascii=False,
    )

    connection = open_database()

    try:
        existing = connection.execute(
            """
            SELECT id FROM documents
            WHERE path=?
            """,
            (str(path),),
        ).fetchone()

        if existing:
            document_id = int(existing["id"])
            connection.execute(
                """
                UPDATE documents
                SET kind=?,
                    title=?,
                    source_path=?,
                    content_hash=?,
                    body=?,
                    summary=?,
                    tags=?,
                    updated_at=?,
                    active=1
                WHERE id=?
                """,
                (
                    kind,
                    title,
                    source_path,
                    digest,
                    content,
                    summary,
                    tags_json,
                    timestamp,
                    document_id,
                ),
            )
        else:
            duplicate = connection.execute(
                """
                SELECT id, path FROM documents
                WHERE content_hash=? AND active=1
                ORDER BY id
                LIMIT 1
                """,
                (digest,),
            ).fetchone()

            if duplicate:
                return int(duplicate["id"])

            cursor = connection.execute(
                """
                INSERT INTO documents(
                    kind, title, path, source_path,
                    content_hash, body, summary, tags,
                    created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    kind,
                    title,
                    str(path),
                    source_path,
                    digest,
                    content,
                    summary,
                    tags_json,
                    timestamp,
                    timestamp,
                ),
            )
            document_id = int(cursor.lastrowid)

        connection.commit()
        return document_id
    finally:
        connection.close()


def related_documents(
    document_id: int,
    terms: Iterable[str],
    limit: int = 6,
) -> list[sqlite3.Row]:
    term_list = [
        term for term in terms
        if len(term) >= 3
    ]

    if not term_list:
        return []

    connection = open_database()

    try:
        rows = connection.execute(
            """
            SELECT id, title, path, summary, tags
            FROM documents
            WHERE active=1 AND id<>?
            ORDER BY updated_at DESC
            LIMIT 250
            """,
            (document_id,),
        ).fetchall()

        scored: list[tuple[int, sqlite3.Row]] = []

        for row in rows:
            haystack = " ".join(
                (
                    str(row["title"]),
                    str(row["summary"]),
                    str(row["tags"]),
                )
            ).casefold()

            score = sum(
                1 for term in term_list
                if term.casefold() in haystack
            )

            if score:
                scored.append((score, row))

        return [
            row
            for _, row in sorted(
                scored,
                key=lambda item: (
                    -item[0],
                    str(item[1]["title"]).casefold(),
                ),
            )[:limit]
        ]
    finally:
        connection.close()


def link_document(document_id: int, terms: Iterable[str]) -> int:
    related = related_documents(document_id, terms)
    timestamp = now_iso()
    connection = open_database()
    count = 0

    try:
        for row in related:
            target_id = int(row["id"])

            if target_id == document_id:
                continue

            connection.execute(
                """
                INSERT INTO links(
                    source_id, target_id,
                    relation, weight, created_at
                )
                VALUES(?, ?, 'related', 1.0, ?)
                ON CONFLICT(source_id, target_id, relation)
                DO UPDATE SET weight=excluded.weight
                """,
                (document_id, target_id, timestamp),
            )

            connection.execute(
                """
                INSERT INTO links(
                    source_id, target_id,
                    relation, weight, created_at
                )
                VALUES(?, ?, 'related', 1.0, ?)
                ON CONFLICT(source_id, target_id, relation)
                DO UPDATE SET weight=excluded.weight
                """,
                (target_id, document_id, timestamp),
            )

            count += 1

        connection.commit()
    finally:
        connection.close()

    return count


def write_evergreen_note(
    *,
    title: str,
    source_text: str,
    source_reference: str,
    category: str = "permanent-notes",
    tags: Iterable[str] = (),
) -> tuple[Path, int]:
    target = initialize()
    clean_title = title.strip() or "Memory note"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = slugify(clean_title)
    note_path = target.wiki / category / f"{slug}-{timestamp}.md"
    summary = extractive_summary(source_text)
    generated_tags = sorted(
        set(tags).union(keywords(source_text))
    )

    body = f"""# {clean_title}

## Summary

{summary or "No summary available."}

## Knowledge

{normalized_text(source_text)}

## Metadata

- Created: {now_iso()}
- Source: {source_reference}
- Type: evergreen-note
- Tags: {", ".join(generated_tags) if generated_tags else "none"}

## Related

Related notes are maintained in the SQLite knowledge graph.
"""

    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(body, encoding="utf-8")

    document_id = insert_document(
        kind="wiki",
        title=clean_title,
        path=note_path,
        source_path=source_reference,
        body=body,
        summary=summary,
        tags=generated_tags,
    )

    link_count = link_document(document_id, generated_tags)

    record_event(
        "evergreen_note_created",
        {
            "document_id": document_id,
            "path": str(note_path),
            "title": clean_title,
            "links_created": link_count,
        },
    )

    return note_path, document_id


def remember(
    text: str,
    *,
    title: str = "",
    category: str = "permanent-notes",
    tags: Iterable[str] = (),
) -> dict[str, Any]:
    clean = normalized_text(text)

    if not clean:
        raise ValueError("Memory text is empty.")

    resolved_title = title.strip() or title_from_text(clean)
    note_path, document_id = write_evergreen_note(
        title=resolved_title,
        source_text=clean,
        source_reference="direct-memory",
        category=category,
        tags=tags,
    )

    return {
        "ok": True,
        "document_id": document_id,
        "title": resolved_title,
        "path": str(note_path),
    }


def ingest(source_value: str) -> dict[str, Any]:
    source = Path(source_value).expanduser().resolve()

    if not source.is_file():
        raise FileNotFoundError(f"Source file not found: {source}")

    initialize()
    destination_directory = classify_raw_destination(source)
    destination_directory.mkdir(parents=True, exist_ok=True)
    digest = sha256_bytes(source.read_bytes())
    destination = (
        destination_directory
        / f"{source.stem}-{digest[:12]}{source.suffix.casefold()}"
    )

    if not destination.exists():
        shutil.copy2(source, destination)

    text = read_source_text(source)
    title = title_from_text(text, fallback=source.stem)

    raw_document_id = insert_document(
        kind="raw",
        title=title,
        path=destination,
        source_path=str(source),
        body=text or f"Binary source: {source.name}",
        summary=extractive_summary(text),
        tags=keywords(text or source.stem),
    )

    wiki_path = ""
    wiki_document_id = 0

    if text.strip():
        note_path, wiki_document_id = write_evergreen_note(
            title=title,
            source_text=text,
            source_reference=str(destination),
            category="literature",
            tags=keywords(text),
        )
        wiki_path = str(note_path)

    record_event(
        "source_ingested",
        {
            "source": str(source),
            "raw_copy": str(destination),
            "raw_document_id": raw_document_id,
            "wiki_document_id": wiki_document_id,
        },
    )

    return {
        "ok": True,
        "source": str(source),
        "raw_copy": str(destination),
        "raw_document_id": raw_document_id,
        "wiki_path": wiki_path,
        "wiki_document_id": wiki_document_id,
        "text_extracted": bool(text.strip()),
    }


def search(query: str, limit: int = 8) -> list[dict[str, Any]]:
    clean = " ".join(str(query or "").strip().split())

    if not clean:
        return []

    limit = min(max(int(limit), 1), 30)
    connection = open_database()

    try:
        metadata = connection.execute(
            """
            SELECT value FROM metadata
            WHERE key='fts_enabled'
            """
        ).fetchone()

        fts_enabled = bool(
            metadata and metadata["value"] == "1"
        )

        rows: list[sqlite3.Row]

        if fts_enabled:
            tokens = re.findall(
                r"[a-zA-Z0-9_-]+",
                clean,
            )

            match_query = " OR ".join(
                f'"{token}"'
                for token in tokens[:12]
            )

            try:
                rows = connection.execute(
                    """
                    SELECT
                        d.id,
                        d.kind,
                        d.title,
                        d.path,
                        d.summary,
                        d.tags,
                        d.updated_at,
                        bm25(documents_fts) AS rank
                    FROM documents_fts
                    JOIN documents AS d
                      ON d.id=documents_fts.rowid
                    WHERE documents_fts MATCH ?
                      AND d.active=1
                    ORDER BY rank, d.updated_at DESC
                    LIMIT ?
                    """,
                    (match_query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        else:
            rows = []

        if not rows:
            pattern = f"%{clean.casefold()}%"
            rows = connection.execute(
                """
                SELECT
                    id, kind, title, path,
                    summary, tags, updated_at,
                    0.0 AS rank
                FROM documents
                WHERE active=1
                  AND (
                    lower(title) LIKE ?
                    OR lower(summary) LIKE ?
                    OR lower(body) LIKE ?
                    OR lower(tags) LIKE ?
                  )
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (
                    pattern,
                    pattern,
                    pattern,
                    pattern,
                    limit,
                ),
            ).fetchall()

        timestamp = now_iso()

        for row in rows:
            connection.execute(
                """
                UPDATE documents
                SET access_count=access_count+1,
                    last_accessed_at=?
                WHERE id=?
                """,
                (timestamp, int(row["id"])),
            )

        connection.commit()

        return [
            {
                "id": int(row["id"]),
                "kind": str(row["kind"]),
                "title": str(row["title"]),
                "path": str(row["path"]),
                "summary": str(row["summary"]),
                "tags": json.loads(row["tags"] or "[]"),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]
    finally:
        connection.close()


def retrieve_context(query: str, limit: int = 5) -> str:
    results = search(query, limit=limit)

    if not results:
        return "No relevant persistent memory was found."

    sections = ["Relevant persistent memory:"]

    for index, item in enumerate(results, start=1):
        summary = item["summary"].strip()

        if not summary:
            try:
                content = Path(item["path"]).read_text(
                    encoding="utf-8",
                    errors="replace",
                )
                summary = extractive_summary(content, max_sentences=2)
            except OSError:
                summary = ""

        sections.append(
            f"\n{index}. {item['title']}\n"
            f"   Type: {item['kind']}\n"
            f"   Summary: {summary[:500] or 'No summary.'}\n"
            f"   Path: {item['path']}"
        )

    return "\n".join(sections)[:6_000]


def add_identity_memory(kind: str, text: str) -> Path:
    target = initialize()
    clean = normalized_text(text)

    if not clean:
        raise ValueError(f"{kind} text is empty.")

    mapping = {
        "preference": target.preferences,
        "goal": target.goals,
        "project": target.projects,
        "person": target.people,
        "history": target.history,
    }

    directory = mapping[kind]
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    title = title_from_text(clean, fallback=kind.title())
    note = directory / f"{slugify(title, kind)}-{timestamp}.md"

    note.write_text(
        f"""# {title}

- Type: {kind}
- Created: {now_iso()}

{clean}
""",
        encoding="utf-8",
    )

    document_id = insert_document(
        kind=f"memory:{kind}",
        title=title,
        path=note,
        source_path="identity-memory",
        body=note.read_text(encoding="utf-8"),
        summary=extractive_summary(clean),
        tags=[kind, *keywords(clean)],
    )

    link_document(document_id, [kind, *keywords(clean)])

    record_event(
        "identity_memory_added",
        {
            "kind": kind,
            "document_id": document_id,
            "path": str(note),
        },
    )

    return note


def write_session(
    user_message: str,
    assistant_message: str,
    *,
    session_id: str = "",
) -> Path:
    target = initialize()
    resolved_session = (
        slugify(session_id, "")
        or datetime.now().strftime("%Y%m%d")
    )
    session_file = (
        target.ctx
        / "sessions"
        / f"{resolved_session}.jsonl"
    )

    event = {
        "timestamp": now_iso(),
        "user": str(user_message),
        "assistant": str(assistant_message),
    }

    with session_file.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(event, ensure_ascii=False) + "\n"
        )

    return session_file


def maintain() -> dict[str, Any]:
    target = initialize()
    connection = open_database()
    missing = 0
    duplicates = 0
    links_removed = 0
    notes_reindexed = 0

    try:
        rows = connection.execute(
            """
            SELECT id, path, content_hash
            FROM documents
            WHERE active=1
            ORDER BY id
            """
        ).fetchall()

        hashes: dict[str, int] = {}

        for row in rows:
            document_id = int(row["id"])
            path = Path(str(row["path"]))
            digest = str(row["content_hash"])

            if not path.exists():
                connection.execute(
                    """
                    UPDATE documents
                    SET active=0, updated_at=?
                    WHERE id=?
                    """,
                    (now_iso(), document_id),
                )
                missing += 1
                continue

            if digest in hashes:
                connection.execute(
                    """
                    UPDATE documents
                    SET active=0, updated_at=?
                    WHERE id=?
                    """,
                    (now_iso(), document_id),
                )
                duplicates += 1
                continue

            hashes[digest] = document_id

            if path.suffix.casefold() in TEXT_SUFFIXES:
                try:
                    body = path.read_text(
                        encoding="utf-8",
                        errors="replace",
                    )

                    current_hash = sha256_bytes(
                        normalized_text(body).encode("utf-8")
                    )

                    if current_hash != digest:
                        connection.execute(
                            """
                            UPDATE documents
                            SET body=?,
                                content_hash=?,
                                summary=?,
                                updated_at=?
                            WHERE id=?
                            """,
                            (
                                normalized_text(body),
                                current_hash,
                                extractive_summary(body),
                                now_iso(),
                                document_id,
                            ),
                        )
                        notes_reindexed += 1
                except OSError:
                    pass

        cursor = connection.execute(
            """
            DELETE FROM links
            WHERE source_id NOT IN (
                SELECT id FROM documents WHERE active=1
            )
            OR target_id NOT IN (
                SELECT id FROM documents WHERE active=1
            )
            """
        )
        links_removed = max(cursor.rowcount, 0)

        try:
            connection.execute(
                """
                INSERT INTO documents_fts(documents_fts)
                VALUES('rebuild')
                """
            )
        except sqlite3.OperationalError:
            pass

        connection.commit()
    finally:
        connection.close()

    report = {
        "missing_deactivated": missing,
        "duplicates_deactivated": duplicates,
        "links_removed": links_removed,
        "notes_reindexed": notes_reindexed,
        "completed_at": now_iso(),
    }

    report_path = (
        target.output
        / "reports"
        / f"memory-maintenance-{datetime.now():%Y%m%d-%H%M%S}.json"
    )

    report_path.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    record_event("maintenance_completed", report)
    return {**report, "report_path": str(report_path)}


def status() -> dict[str, Any]:
    target = initialize()
    connection = open_database()

    try:
        counts = {
            str(row["kind"]): int(row["count"])
            for row in connection.execute(
                """
                SELECT kind, COUNT(*) AS count
                FROM documents
                WHERE active=1
                GROUP BY kind
                ORDER BY kind
                """
            ).fetchall()
        }

        total = sum(counts.values())

        link_count = int(
            connection.execute(
                "SELECT COUNT(*) AS count FROM links"
            ).fetchone()["count"]
        )

        event_count = int(
            connection.execute(
                "SELECT COUNT(*) AS count FROM events"
            ).fetchone()["count"]
        )

        fts_row = connection.execute(
            """
            SELECT value FROM metadata
            WHERE key='fts_enabled'
            """
        ).fetchone()

        return {
            "root": str(target.root),
            "database": str(target.database),
            "schema_version": SCHEMA_VERSION,
            "documents": total,
            "documents_by_kind": counts,
            "links": link_count,
            "events": event_count,
            "fts_enabled": bool(
                fts_row and fts_row["value"] == "1"
            ),
            "identity": str(target.identity),
        }
    finally:
        connection.close()


def review() -> dict[str, Any]:
    target = initialize()
    current = status()
    connection = open_database()

    try:
        recent = connection.execute(
            """
            SELECT title, kind, path, updated_at
            FROM documents
            WHERE active=1
            ORDER BY updated_at DESC
            LIMIT 12
            """
        ).fetchall()

        unused = connection.execute(
            """
            SELECT title, kind, path, access_count
            FROM documents
            WHERE active=1
            ORDER BY access_count ASC, updated_at ASC
            LIMIT 12
            """
        ).fetchall()
    finally:
        connection.close()

    report_path = (
        target.output
        / "reports"
        / f"memory-review-{datetime.now():%Y%m%d-%H%M%S}.md"
    )

    lines = [
        "# Sophyane Memory Review",
        "",
        f"- Generated: {now_iso()}",
        f"- Documents: {current['documents']}",
        f"- Links: {current['links']}",
        f"- Events: {current['events']}",
        f"- FTS enabled: {current['fts_enabled']}",
        "",
        "## Recent knowledge",
        "",
    ]

    for row in recent:
        lines.append(
            f"- **{row['title']}** "
            f"({row['kind']}) — `{row['path']}`"
        )

    lines.extend(
        [
            "",
            "## Least-used knowledge",
            "",
        ]
    )

    for row in unused:
        lines.append(
            f"- **{row['title']}** "
            f"({row['kind']}, accesses={row['access_count']}) "
            f"— `{row['path']}`"
        )

    lines.extend(
        [
            "",
            "## Recommended maintenance",
            "",
            "- Run `sophyane-memory maintain` daily.",
            "- Add durable preferences with `sophyane-memory preference`.",
            "- Add long-term goals with `sophyane-memory goal`.",
            "- Ingest important documents with `sophyane-memory ingest`.",
        ]
    )

    report_path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    record_event(
        "memory_review_created",
        {"path": str(report_path)},
    )

    return {
        "ok": True,
        "path": str(report_path),
        **current,
    }


def format_search_results(results: list[dict[str, Any]]) -> str:
    if not results:
        return "No matching persistent memory was found."

    lines = [
        f"Found {len(results)} persistent memory result"
        f"{'s' if len(results) != 1 else ''}:"
    ]

    for index, item in enumerate(results, start=1):
        summary = item["summary"].strip()

        lines.append(
            f"\n{index}. {item['title']}\n"
            f"   Type: {item['kind']}\n"
            f"   {summary[:280] or 'No summary available.'}\n"
            f"   {item['path']}"
        )

    return "\n".join(lines)[:5_000]


def try_memory_reply(message: str) -> str | None:
    """Handle explicit memory requests before any LLM provider is called."""
    raw = str(message or "").strip()
    text = " ".join(raw.casefold().split())

    if not text:
        return None

    if text in {
        "memory status",
        "show memory status",
        "memory architecture status",
        "how much memory do you have",
    }:
        data = status()
        kinds = ", ".join(
            f"{key}={value}"
            for key, value in data["documents_by_kind"].items()
        ) or "none"

        return (
            "Sophyane persistent memory:\n"
            f"Root: {data['root']}\n"
            f"Documents: {data['documents']}\n"
            f"Links: {data['links']}\n"
            f"Events: {data['events']}\n"
            f"Full-text search: "
            f"{'enabled' if data['fts_enabled'] else 'fallback mode'}\n"
            f"Types: {kinds}"
        )

    remember_match = re.match(
        r"^(?:please\s+)?remember(?:\s+that)?\s+(.+)$",
        raw,
        flags=re.I | re.S,
    )

    if remember_match:
        content = remember_match.group(1).strip()
        result = remember(content)

        return (
            f"Remembered permanently: {result['title']}\n"
            f"Stored at: {result['path']}"
        )

    forgetless_match = re.match(
        r"^(?:save|store)\s+(?:this\s+)?"
        r"(?:in\s+)?memory\s*[:\-]?\s*(.+)$",
        raw,
        flags=re.I | re.S,
    )

    if forgetless_match:
        content = forgetless_match.group(1).strip()
        result = remember(content)

        return (
            f"Saved to persistent memory: {result['title']}\n"
            f"Stored at: {result['path']}"
        )

    preference_match = re.match(
        r"^(?:remember\s+)?my\s+preference(?:\s+is)?\s*[:\-]?\s*(.+)$",
        raw,
        flags=re.I | re.S,
    )

    if preference_match:
        note = add_identity_memory(
            "preference",
            preference_match.group(1),
        )
        return f"Preference saved permanently: {note}"

    goal_match = re.match(
        r"^(?:remember\s+)?my\s+goal(?:\s+is)?\s*[:\-]?\s*(.+)$",
        raw,
        flags=re.I | re.S,
    )

    if goal_match:
        note = add_identity_memory(
            "goal",
            goal_match.group(1),
        )
        return f"Goal saved permanently: {note}"

    queries = (
        r"^what do you remember about\s+(.+)$",
        r"^search (?:your )?memory for\s+(.+)$",
        r"^memory search\s+(.+)$",
        r"^retrieve memory(?: about)?\s+(.+)$",
        r"^find in memory\s+(.+)$",
    )

    for pattern in queries:
        match = re.match(
            pattern,
            raw,
            flags=re.I | re.S,
        )

        if match:
            query = match.group(1).strip()
            return format_search_results(
                search(query, limit=8)
            )

    if text in {
        "review memory",
        "memory review",
        "review persistent memory",
    }:
        result = review()

        return (
            "Memory review completed.\n"
            f"Documents: {result['documents']}\n"
            f"Links: {result['links']}\n"
            f"Report: {result['path']}"
        )

    if text in {
        "maintain memory",
        "memory maintenance",
        "clean memory",
        "deduplicate memory",
    }:
        result = maintain()

        return (
            "Memory maintenance completed.\n"
            f"Missing deactivated: "
            f"{result['missing_deactivated']}\n"
            f"Duplicates deactivated: "
            f"{result['duplicates_deactivated']}\n"
            f"Notes reindexed: "
            f"{result['notes_reindexed']}\n"
            f"Report: {result['report_path']}"
        )

    return None


def _json_default(value: Any) -> Any:
    """Convert filesystem and other common values to JSON-safe forms."""
    if isinstance(value, Path):
        return str(value)

    if isinstance(value, set):
        return sorted(value)

    if isinstance(value, tuple):
        return list(value)

    if isinstance(value, datetime):
        return value.isoformat()

    raise TypeError(
        f"Object of type {type(value).__name__} "
        "is not JSON serializable"
    )


def print_json(value: Any) -> None:
    print(
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
            default=_json_default,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sophyane-memory",
        description="Sophyane persistent local memory architecture",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    subparsers.add_parser("init")
    subparsers.add_parser("status")
    subparsers.add_parser("review")
    subparsers.add_parser("maintain")

    remember_parser = subparsers.add_parser("remember")
    remember_parser.add_argument("text")
    remember_parser.add_argument("--title", default="")
    remember_parser.add_argument(
        "--tag",
        action="append",
        default=[],
    )

    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("path")

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=8)

    retrieve_parser = subparsers.add_parser("retrieve")
    retrieve_parser.add_argument("query")
    retrieve_parser.add_argument("--limit", type=int, default=5)

    for command in (
        "preference",
        "goal",
        "project",
        "person",
        "history",
    ):
        child = subparsers.add_parser(command)
        child.add_argument("text")

    session_parser = subparsers.add_parser("session")
    session_parser.add_argument("user")
    session_parser.add_argument("assistant")
    session_parser.add_argument("--id", default="")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            print_json(asdict(initialize()))
            return 0

        if args.command == "status":
            print_json(status())
            return 0

        if args.command == "remember":
            print_json(
                remember(
                    args.text,
                    title=args.title,
                    tags=args.tag,
                )
            )
            return 0

        if args.command == "ingest":
            print_json(ingest(args.path))
            return 0

        if args.command == "search":
            print(
                format_search_results(
                    search(args.query, limit=args.limit)
                )
            )
            return 0

        if args.command == "retrieve":
            print(
                retrieve_context(
                    args.query,
                    limit=args.limit,
                )
            )
            return 0

        if args.command in {
            "preference",
            "goal",
            "project",
            "person",
            "history",
        }:
            path = add_identity_memory(
                args.command,
                args.text,
            )
            print(path)
            return 0

        if args.command == "session":
            print(
                write_session(
                    args.user,
                    args.assistant,
                    session_id=args.id,
                )
            )
            return 0

        if args.command == "review":
            print_json(review())
            return 0

        if args.command == "maintain":
            print_json(maintain())
            return 0

        parser.error(f"Unsupported command: {args.command}")
        return 2
    except Exception as error:
        print(
            f"sophyane-memory: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
