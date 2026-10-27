"""The Supabase client, with one retry for reads that hit a dead pooled connection.

Every set-ready-backend Sentry issue from 2026-09-25 on was the same thing:
`httpx.RemoteProtocolError: Server disconnected` on a plain select, clustered
after quiet periods, fine on retry. httpx keeps idle keep-alive connections in a
pool; Supabase's edge closes them first; the next request goes out on one that's
already dead. The pool drops that connection, so a second attempt opens a fresh
one and succeeds.

So the PostgREST client gets a transport that retries ONCE — and only for GET
and HEAD, which is every select (count/head included). Inserts, upserts,
updates, deletes and RPCs go out as POST/PATCH/DELETE and are never retried:
the server may have applied a write before the connection died, and an insert
replayed is a duplicate row. Those still fail the way they always did.

Only PostgREST is wrapped. Storage keeps the library's own client — uploads are
writes. Auth's get_user is retried once for the same two errors in auth.py
itself (its client isn't built here); a failure after that is still a 503.

(The *other* Supabase blip — "JSON could not be generated", a 5xx with an
unparseable body — is retried in the browser, by frontend/src/lib/api.ts's
api.get. That's a response, not a dropped connection, and doesn't come here.)
"""

import logging

import httpx
from postgrest import SyncPostgrestClient
from supabase import Client

from config import settings

logger = logging.getLogger(__name__)

_client: Client | None = None

RETRY_METHODS = frozenset({"GET", "HEAD"})
RETRY_ERRORS = (httpx.RemoteProtocolError, httpx.ReadError)


class RetryReadsTransport(httpx.BaseTransport):
    """Retries a GET/HEAD once if the connection drops under it. Nothing else."""

    def __init__(self, inner: httpx.BaseTransport):
        self._inner = inner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        try:
            return self._inner.handle_request(request)
        except RETRY_ERRORS as e:
            if request.method not in RETRY_METHODS:
                raise
            logger.warning("Supabase %s %s: %s; retrying once on a fresh connection",
                           request.method, request.url.path, type(e).__name__)
            return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


class _Client(Client):
    # Used in place of the default HTTPTransport; tests hand in a fake.
    inner_transport: httpx.BaseTransport | None = None

    def _init_postgrest_client(self, rest_url, headers, schema, timeout=None,
                               verify=True, proxy=None, http_client=None):
        # The same httpx.Client postgrest builds for itself (SyncPostgrestClient
        # .__init__), plus the retrying transport. Re-run whenever the library
        # resets its postgrest client, so the retry can't silently fall away.
        transport = self.inner_transport or httpx.HTTPTransport(http2=True, verify=verify)
        session = httpx.Client(
            base_url=rest_url,
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
            transport=RetryReadsTransport(transport),
        )
        return SyncPostgrestClient(rest_url, headers=headers, schema=schema, http_client=session)


def new_client(url: str, key: str, inner_transport: httpx.BaseTransport | None = None) -> Client:
    client = _Client(url, key)
    client.inner_transport = inner_transport
    return client


def get_client() -> Client:
    global _client
    if _client is None:
        _client = new_client(settings.supabase_url, settings.supabase_service_role_key)
    return _client
