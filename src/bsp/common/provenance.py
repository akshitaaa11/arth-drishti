from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Provenance:
    """Metadata for any source-backed dataset row."""

    source_doc: str | None = None
    source_page: str | int | None = None
    source_url: str | None = None
    fetched_at: str | None = None

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "source_doc": self.source_doc,
            "source_page": self.source_page,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at,
        }
