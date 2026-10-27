"""An in-memory stand-in for the Supabase client, for the job-layer suites.

The older suites each carry a few-line FakeClient covering only what their
module calls. The job layer touches enough tables and query shapes (insert,
update, delete, in_, order, column lists, count) that one fuller fake is
clearer than five partial ones. Still no database, no network.

Two things it can do that matter for these tests:

  - `schema`: the columns each table has. A write naming a column the table
    doesn't have raises, the way PostgREST does — so "a database that hasn't
    had the migration yet" is testable, and so is "the current version's
    insert is unchanged".
  - `fail`: table names whose every query raises. That's how the best-effort
    suite forces the job bookkeeping to fail.
"""

import itertools

_ids = itertools.count(1)


class FakeAPIError(Exception):
    pass


DEFAULTS = {
    "jobs": lambda: {"crew_dates": {}, "client_name": None, "production_company": None,
                     "payroll_provider": None, "created_at": "2026-09-28T00:00:00"},
    "job_hires": lambda: {"dates_override": {}, "sort_order": 0, "roster_id": None,
                          "email": None, "phone": None, "role": None, "department": None},
    "projects": lambda: {"job_id": None, "shoot_date": None, "general_call_time": None, "notes": None,
                         "created_at": "2026-09-28T00:00:00", "client_name": None,
                         "production_company": None, "payroll_provider": None},
    "crew_members": lambda: {"hire_id": None, "confirmed_at": None, "call_time": None, "call_time_note": None,
                             "department": None, "phone": None, "sort_order": 0,
                             "hide_contact": False, "wants_pdf": False, "roster_id": None,
                             "deal_memo_dates": None, "last_sent_at": None},
    "roster": lambda: {"email": None, "phone": None, "role": None, "department": None},
}

# Columns added by supabase/jobs_migration.sql, per table.
MIGRATION_COLUMNS = {"projects": {"job_id"}, "crew_members": {"hire_id"}}


class Result:
    def __init__(self, data, count=None):
        self.data, self.count = data, count


class Query:
    def __init__(self, client, name):
        self.c, self.name = client, name
        self.filters, self.cols, self.op, self.payload = [], None, "select", None
        self._order, self._limit, self._count = [], None, None

    # ── building ─────────────────────────────────────────────────────────────
    def select(self, cols="*", count=None):
        self.cols = None if cols.strip() == "*" else [c.strip() for c in cols.split(",")]
        self._count = count
        return self

    def eq(self, k, v): self.filters.append((k, "eq", v)); return self
    def neq(self, k, v): self.filters.append((k, "neq", v)); return self
    def in_(self, k, vs): self.filters.append((k, "in", list(vs))); return self
    def is_(self, k, v): self.filters.append((k, "is", v)); return self
    def order(self, col, desc=False): self._order.append((col, desc)); return self
    def limit(self, n): self._limit = n; return self

    def insert(self, rows): self.op, self.payload = "insert", rows; return self
    def update(self, changes): self.op, self.payload = "update", changes; return self
    def delete(self): self.op = "delete"; return self

    def upsert(self, row, on_conflict=None):
        self.op, self.payload, self._conflict = "upsert", row, on_conflict
        return self

    # ── running ──────────────────────────────────────────────────────────────
    def _check_columns(self, row):
        cols = self.c.schema.get(self.name)
        if cols is None:
            return
        unknown = set(row) - cols
        if unknown:
            raise FakeAPIError(f"column {sorted(unknown)} of relation {self.name} does not exist")

    def _match(self, row):
        for k, op, v in self.filters:
            val = row.get(k)
            if op == "eq" and str(val) != str(v):
                return False
            if op == "neq" and str(val) == str(v):
                return False
            if op == "in" and str(val) not in {str(x) for x in v}:
                return False
            if op == "is" and val is not None:
                return False
        return True

    def _project(self, row):
        if self.cols is None:
            return dict(row)
        return {k: row.get(k) for k in self.cols}

    def execute(self):
        self.c.calls.append((self.name, self.op))
        if self.name in self.c.fail:
            raise FakeAPIError(f"forced failure on {self.name}")
        if self.name not in self.c.db:
            if self.c.schema and self.name not in self.c.schema:
                raise FakeAPIError(f'relation "public.{self.name}" does not exist')
            self.c.db[self.name] = []
        table = self.c.db[self.name]

        if self.op in ("insert", "upsert"):
            rows = self.payload if isinstance(self.payload, list) else [self.payload]
            out = []
            known = self.c.schema.get(self.name)
            for r in rows:
                self._check_columns(r)
                defaults = {k: v for k, v in DEFAULTS.get(self.name, dict)().items()
                            if known is None or k in known}
                new = {**defaults, "id": f"{self.name[:4]}{next(_ids)}", **r}
                table.append(new)
                out.append(dict(new))
            return Result(out)

        hits = [r for r in table if self._match(r)]
        if self.op == "update":
            self._check_columns(self.payload)
            for r in hits:
                r.update(self.payload)
            return Result([dict(r) for r in hits])
        if self.op == "delete":
            for r in hits:
                table.remove(r)
            return Result([dict(r) for r in hits])

        for col, desc in reversed(self._order):
            hits.sort(key=lambda r: (r.get(col) is None, r.get(col) if r.get(col) is not None else ""),
                      reverse=desc)
        if self._limit is not None:
            hits = hits[: self._limit]
        return Result([self._project(r) for r in hits], count=len(hits) if self._count else None)


class _User:
    def __init__(self, uid, meta, app_meta=None, email=None):
        self.id, self.user_metadata, self.email = uid, meta, email or f"{uid}@example.com"
        self.app_metadata = dict(app_meta or {})


class _Admin:
    def __init__(self, client): self.c = client

    def get_user_by_id(self, uid):
        return type("R", (), {"user": _User(uid, dict(self.c.users.setdefault(uid, {})),
                                            self.c.app_metadata.get(uid))})

    def update_user_by_id(self, uid, attrs):
        # Replaces rather than merges — the stricter of the two behaviours,
        # so a caller that forgets to send the whole dict is caught.
        self.c.users[uid] = dict(attrs.get("user_metadata") or {})

    def delete_user(self, uid): self.c.users.pop(uid, None)

    # The two the first-run owner setup uses (routers/setup.py). list_users
    # pages like the real one so a caller that forgets to page is caught.
    def list_users(self, page=None, per_page=None):
        page, per_page = page or 1, per_page or 50
        users = [_User(uid, dict(meta), self.c.app_metadata.get(uid), self.c.emails.get(uid))
                 for uid, meta in self.c.users.items()]
        return users[(page - 1) * per_page: page * per_page]

    def create_user(self, attrs):
        uid = f"u{len(self.c.users) + 1}"
        self.c.users[uid] = dict(attrs.get("user_metadata") or {})
        self.c.app_metadata[uid] = dict(attrs.get("app_metadata") or {})
        self.c.emails[uid] = attrs.get("email")
        self.c.calls.append(("create_user", attrs))
        return type("R", (), {"user": _User(uid, self.c.users[uid], self.c.app_metadata[uid], attrs.get("email"))})


class _Storage:
    def from_(self, _b): return self
    def remove(self, _paths): return None


class FakeClient:
    def __init__(self, db=None, schema=None, fail=()):
        self.db = db if db is not None else {}
        self.schema = schema or {}
        self.fail = set(fail)
        self.calls = []
        self.users = {}
        self.app_metadata = {}
        self.emails = {}
        self.auth = type("Auth", (), {})()
        self.auth.admin = _Admin(self)
        self.storage = _Storage()

    def table(self, name):
        return Query(self, name)


def pre_migration_schema(db: dict) -> dict:
    """Columns per table as they are BEFORE jobs_migration.sql: whatever the
    seed rows use plus the defaults, minus the migration's columns, and no job
    tables at all."""
    schema = {}
    for name, rows in db.items():
        cols = set(DEFAULTS.get(name, dict)()) | {"id"}
        for r in rows:
            cols |= set(r)
        cols |= {"project_id", "name", "email", "role", "owner_id", "type", "storage_path"}
        schema[name] = cols - MIGRATION_COLUMNS.get(name, set())
    return schema
