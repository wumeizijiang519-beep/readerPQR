from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Block:
    id: str
    page: int
    bbox: tuple[float, float, float, float]
    text: str
    kind: str = "text"


@dataclass
class Paper:
    path: str
    fingerprint: str
    title: str
    page_count: int
    pages: list[list[Block]] = field(default_factory=list)
    image_only_pages: list[int] = field(default_factory=list)

    @property
    def blocks(self) -> list[Block]:
        return [block for page in self.pages for block in page]
