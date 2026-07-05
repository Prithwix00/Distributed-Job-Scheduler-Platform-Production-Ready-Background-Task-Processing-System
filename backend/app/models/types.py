"""Portable column types (JSONB on Postgres, JSON elsewhere)."""
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

# Use JSONB on Postgres for indexing and operator support, plain JSON on SQLite.
JSONType = JSON().with_variant(JSONB, "postgresql")
