"""Dataset connection URI value object (C36).

Parses a connection URI and, crucially, exposes a credential-free `.display()`.
EVERY surface other than a connector's own connect/pull call — API responses,
log lines, stored error messages, the `datasets.source_uri_display` column —
must use `.display()`. The raw URI (with any password) is read ONLY inside a
connector at connect time via `.raw()`.

Forms handled:
- internal: `parquet:///{name}` (scheme `parquet`, empty authority)
- external: `{type}://{user}:{pass}@{host}:{port}/{db}` (e.g.
  `postgresql://u:p@h:5432/sales`)
"""
from __future__ import annotations

from urllib.parse import unquote, urlsplit


class DatasetURI:
    """Credential-aware parse of a connection URI; `.display()` never reveals the password."""

    def __init__(self, raw: str) -> None:
        self._raw = raw or ""
        self._parts = urlsplit(self._raw)

    @property
    def scheme(self) -> str:
        return self._parts.scheme

    @property
    def host(self) -> str | None:
        return self._parts.hostname

    @property
    def port(self) -> int | None:
        return self._parts.port

    @property
    def username(self) -> str | None:
        return self._parts.username

    @property
    def has_password(self) -> bool:
        return self._parts.password is not None

    @property
    def is_internal(self) -> bool:
        """True for the internal `parquet` scheme (no host, no credentials)."""
        return self._parts.scheme == "parquet"

    @property
    def database(self) -> str:
        """The database / logical name (URL-decoded path segment, no leading slash)."""
        return unquote(self._parts.path.lstrip("/"))

    def raw(self) -> str:
        """The raw URI INCLUDING any credentials.

        Use only inside a connector's own connect/introspect/pull calls — never
        in a log line, exception message, or API response.
        """
        return self._raw

    def display(self) -> str:
        """A credential-free rendering safe for logs, templates, errors, and storage."""
        parts = self._parts
        if not parts.hostname and not parts.username:  # internal parquet:///name
            return f"{parts.scheme}:///{parts.path.lstrip('/')}"
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        return f"{parts.scheme}://{host}{port}{parts.path}"

    def __str__(self) -> str:  # never leak credentials via str()
        return self.display()

    def __repr__(self) -> str:  # never leak credentials via repr()
        return f"DatasetURI({self.display()!r})"
