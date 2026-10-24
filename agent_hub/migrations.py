"""Atomic, additive migrations for the hub's own database only."""
SCHEMA_VERSION = 3
LEGACY_SCHEMA = (
    'CREATE TABLE IF NOT EXISTS agents (id TEXT PRIMARY KEY, name TEXT, available INT, synced INT, error TEXT)',
    'CREATE TABLE IF NOT EXISTS agent_sources (agent TEXT PRIMARY KEY, reader TEXT, home TEXT, container TEXT)',
    'CREATE TABLE IF NOT EXISTS projects (agent TEXT, id TEXT, name TEXT, roots TEXT, source TEXT, PRIMARY KEY(agent,id))',
    'CREATE TABLE IF NOT EXISTS conversations (agent TEXT, id TEXT, title TEXT, cwd TEXT, updated INT, archived INT, project_id TEXT, PRIMARY KEY(agent,id))',
    'CREATE TABLE IF NOT EXISTS messages (agent TEXT, conversation TEXT, ordinal INT, role TEXT, text TEXT, PRIMARY KEY(agent,conversation,ordinal), FOREIGN KEY(agent,conversation) REFERENCES conversations(agent,id) ON DELETE CASCADE)',
    'CREATE TABLE IF NOT EXISTS transfers (id TEXT PRIMARY KEY, source_agent TEXT, source_chat TEXT, target_agent TEXT, project_id TEXT, project_name TEXT, cwd TEXT, title TEXT, context_path TEXT, native_id TEXT, status TEXT, created INT)',
)
TASK_SCHEMA = (
    """CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT,
        contract TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','ready','blocked','running','verifying','reviewing',
        'changes_requested','waiting_human','failed','done','cancelled')),
        created INTEGER NOT NULL, updated INTEGER NOT NULL, revision INTEGER NOT NULL DEFAULT 1)""",
    """CREATE TABLE task_dependencies (task INTEGER NOT NULL REFERENCES tasks(id),
        dependency INTEGER NOT NULL REFERENCES tasks(id), PRIMARY KEY(task,dependency), CHECK(task<>dependency))""",
    """CREATE TABLE task_events (id INTEGER PRIMARY KEY AUTOINCREMENT,
        task INTEGER NOT NULL REFERENCES tasks(id), type TEXT NOT NULL,
        payload TEXT NOT NULL, created INTEGER NOT NULL)""",
    'CREATE INDEX tasks_status ON tasks(status,id)',
    'CREATE INDEX task_events_task ON task_events(task,id)',
    'CREATE INDEX task_dependents ON task_dependencies(dependency,task)',
)


def migrate(conn):
    # executescript implicitly commits: run individual statements so schema and
    # user_version roll back together, including concurrent initializers.
    conn.execute('BEGIN IMMEDIATE')
    try:
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version > SCHEMA_VERSION:
            raise ValueError('La base de Agent Hub pertenece a una versión más nueva.')
        if version == 0:
            for statement in LEGACY_SCHEMA:
                conn.execute(statement)
            conn.execute('PRAGMA user_version=1')
            version = 1
        if version == 1:
            for statement in TASK_SCHEMA:
                conn.execute(statement)
            conn.execute('PRAGMA user_version=2')
            version = 2
        if version == 2:
            from .engine.schema import ENGINE_SCHEMA
            for statement in ENGINE_SCHEMA:
                conn.execute(statement)
            conn.execute('PRAGMA user_version=3')
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
