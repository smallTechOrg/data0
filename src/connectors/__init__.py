"""Pluggable `DatasetConnector` seam (C36, Phase 9).

A one-time snapshot-pull data-LOADING mechanism — the agent never talks to an
external database directly and never runs live SQL. `parquet` (internal,
wraps the existing upload store) and `postgresql` (external, BETA/flag-gated)
are wired via `connectors.base.get_connector`. See
`spec/capabilities/external-db-connectors.md`.
"""
