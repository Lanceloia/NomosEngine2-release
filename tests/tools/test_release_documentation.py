"""Keep the public reading paths local, present, and independent of work notes."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]


def test_public_markdown_local_links_point_to_existing_files():
    documents = [ROOT / "README.md", ROOT / "RIGHTS.md", ROOT / "engine/kernel/README.md"]
    documents.extend((ROOT / "docs").rglob("*.md"))
    documents.extend((ROOT / "src").rglob("*.md"))
    missing = []
    for document in documents:
        for target in re.findall(r"\[[^\]\n]*\]\(<?([^\s)>]+)>?\)",
                                 document.read_text(encoding="utf-8")):
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            path = (document.parent / unquote(parsed.path)).resolve()
            if not path.is_relative_to(ROOT) or not path.exists():
                missing.append(f"{document.relative_to(ROOT)} -> {target}")
    assert not missing, "Missing or external local targets:\n" + "\n".join(missing)
