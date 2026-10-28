"""Read-only product facts for the evaluation adapter; never migrate a database.

Fixture digests are logical SQLite snapshots, not hashes of a live main/WAL file.
The manifest is an explicit provenance assertion, not proof of model quality.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .eval_support import isolated_database, readonly
from .storage import Database, encode


TABLES = (
    "courses", "runs", "command_receipts", "model_calls", "lesson_scripts",
    "lesson_states", "lesson_interactions", "activity_progress", "quizzes",
    "quiz_states", "quiz_attempts", "assistance_conversations", "assistance_artifacts",
)
RESOURCE_TABLES = set(TABLES) - {"command_receipts"}


def sha256(value) -> str:
    """Use precisely the product's JSON encoding for command fingerprints."""
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def records(conn) -> dict:
    """One transaction includes all committed WAL facts and receipt columns."""
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if tables != set(TABLES) or conn.execute("PRAGMA user_version").fetchone()[0] != 3:
        raise ValueError("unsupported product SQLite schema/table inventory; no migration is performed")
    return {table: [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")]
            for table in TABLES}


def snapshot_digest(conn) -> str:
    return sha256({"user_version": conn.execute("PRAGMA user_version").fetchone()[0],
                   "tables": records(conn)})


def verify_fixture_source(conn, table: str, identity: str, producer_id: str) -> dict:
    """Verify actual persisted producer/owner fields, not just an asserted ID."""
    data = row_data(conn, table, identity)
    run = row_data(conn, "runs", producer_id)
    if run.get("status") not in {"ready", "failed", "cancelled", "interrupted"} or not run.get("model"):
        raise ValueError("fixture producer must be a terminal saved business run")
    if table == "runs":
        matches = identity == producer_id
    elif table == "courses":
        matches = run.get("course_id") == identity
    elif table == "assistance_conversations":
        matches = run.get("conversation_id") == identity and any(
            turn["turn_id"] == run.get("turn_id") for turn in data["turns"])
    elif table == "assistance_artifacts":
        matches = (run.get("status") == "ready" and run.get("turn_id") == data.get("turn_id")
                   and run.get("conversation_id") == data.get("conversation_id"))
    elif table == "lesson_scripts":
        matches = run.get("script_id") == identity and run.get("session_id") == data.get("session_id")
    elif table == "lesson_states":
        matches = run.get("session_id") == identity
    elif table == "lesson_interactions":
        matches = run.get("interaction_id") == identity and data.get("run_id") == producer_id
    elif table == "quizzes":
        matches = run.get("quiz_id") == identity and run.get("target_id") == data.get("target_id")
    elif table == "quiz_states":
        matches = f"{run.get('target_type')}:{run.get('target_id')}" == identity
    elif table == "quiz_attempts":
        matches = run.get("quiz_id") == data.get("quiz_id")
    elif table == "activity_progress":
        matches = (run.get("session_id") == identity or run.get("target_id") == identity) and run.get("course_id") == data.get("course_id")
    elif table == "model_calls":
        matches = conn.execute("SELECT run_id FROM model_calls WHERE id=?", (identity,)).fetchone()[0] == producer_id
    else:
        matches = False
    if not matches:
        raise ValueError(f"fixture producer ownership mismatch: {table}/{identity}")
    return data


def export_fixture_manifest(data_dir: Path, *, origin: str, bindings: dict,
                            resource_sources: dict[str, str]) -> dict:
    """Export only a consistent read, never invent resources or copy a live DB.

    ``origin`` is a non-secret opaque source/backup identifier (not a path).
    ``resource_sources`` maps every ``table/id`` to its actual producer run ID;
    callers must supply this provenance explicitly, not infer model execution
    from stored text. Write the returned JSON only to a private output location.
    The helper does not create a backup: snapshot.source.kind explicitly records
    sqlite-consistent-read, not a claimed backup file. No paths/configuration are
    exported. Callers preparing copies must use the real SQLite backup API.
    """
    if not origin or any(char in origin for char in ("/", "\\", "@", "\n")):
        raise ValueError("origin must be an opaque non-secret identifier, not a path/URL")
    database = isolated_database(Path(data_dir))
    with readonly(database) as conn:
        data = records(conn)
        resources = []
        for table, rows in data.items():
            if table == "command_receipts":
                continue
            for row in rows:
                key = f"{table}/{row['id']}"
                producer_id = resource_sources.get(key)
                if not producer_id:
                    raise ValueError(f"explicit real producer required for {key}")
                verify_fixture_source(conn, table, row["id"], producer_id)
                resources.append({"table": table, "id": row["id"], "sha256": sha256(json.loads(row["data"])),
                                  "source": {"kind": "business-generated", "run_id": producer_id, "origin": origin}})
        expected = {f"{r['table']}/{r['id']}" for r in resources}
        if set(resource_sources) != expected:
            raise ValueError("resource_sources must exactly inventory existing data rows")
        for ref in bindings.values():
            resource_path(ref["kind"], ref["id"])
            product_snapshot(conn, ref["kind"], ref["id"])
        return {"schema_version": 1, "snapshot": {"method": "sqlite-logical-v1",
                "sha256": snapshot_digest(conn), "source": {"kind": "sqlite-consistent-read", "origin": origin}},
                "resources": resources, "bindings": deepcopy(bindings)}


def database_instance(path: Path) -> dict:
    stat = path.stat()
    return {"device": stat.st_dev, "inode": stat.st_ino}


def row_data(conn, table: str, identity: str) -> dict:
    if table not in RESOURCE_TABLES:
        raise ValueError("unsupported evidence table")
    row = conn.execute(f"SELECT data FROM {table} WHERE id=?", (identity,)).fetchone()
    if row is None:
        raise ValueError(f"missing evidence: {table}/{identity}")
    return json.loads(row["data"])


def product_snapshot(conn, kind: str, identity: str) -> dict:
    """Reuse only read methods, without constructing/migrating a Database."""
    if kind == "exam":
        kind, identity = "quiz_target", "exam:" + identity
    db = Database.__new__(Database)
    readers = {"run": lambda: row_data(conn, "runs", identity),
               "course": lambda: db._course(conn, identity),
               "session": lambda: db._lesson(conn, identity),
               "conversation": lambda: db._conversation(conn, identity),
               "artifact": lambda: row_data(conn, "assistance_artifacts", identity),
               "quiz_target": lambda: db._quiz_target(conn, *identity.split(":", 1))}
    if kind not in readers:
        raise ValueError("unsupported snapshot kind")
    return deepcopy(readers[kind]())


def resource_path(kind: str, identity: str) -> str:
    # IDs originate in checked bindings, never user-controlled URL paths.
    import re
    if kind == "exam":
        kind, identity = "quiz_target", "exam:" + identity
    if kind == "quiz_target":
        target_type, target_id = identity.split(":", 1)
        if target_type not in {"practice", "exam"}:
            raise ValueError("invalid quiz target")
        checked_id(target_id)
        return (f"/api/sessions/{target_id}/practice" if target_type == "practice"
                else f"/api/exams/{target_id}")
    if kind not in {"run", "course", "session", "conversation", "artifact"}:
        raise ValueError("unsupported resource kind")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", identity):
        raise ValueError("invalid resource identity")
    prefixes = {"run": "/api/runs", "course": "/api/courses", "session": "/api/sessions",
                "conversation": "/api/assistance/conversations",
                "artifact": "/api/assistance/artifacts"}
    return f"{prefixes[kind]}/{identity}"


def checked_id(identity: str) -> str:
    import re
    if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", identity):
        raise ValueError("invalid resource identity")
    return identity


def verified_receipt(conn, command_id: str, payload: dict, resource_type: str) -> dict | None:
    row = conn.execute("SELECT * FROM command_receipts WHERE id=?", (command_id,)).fetchone()
    if row is None:
        return None
    receipt = dict(row)
    if receipt["fingerprint"] != sha256(payload) or receipt["resource_type"] != resource_type:
        raise ValueError("protocol error: command receipt fingerprint/type mismatch")
    return receipt


def crosscheck(client, database: Path, refs: dict, *, base_url: str) -> dict:
    """HTTP first, then one SQLite read transaction: differing versions are gaps.

    Do not silently retry a racing checkpoint and present a newer view as the old
    one. The caller may observe again; the already returned observation is fixed.
    """
    http = {}
    for alias, ref in refs.items():
        response = client.get(base_url + resource_path(ref["kind"], ref["id"]), follow_redirects=False)
        response.raise_for_status()
        http[alias] = response.json()
    with readonly(database) as conn:
        saved = {alias: product_snapshot(conn, ref["kind"], ref["id"])
                 for alias, ref in refs.items()}
    if saved != http:
        raise ValueError("evidence gap: HTTP and SQLite do not describe the same resource version")
    return deepcopy(saved)
