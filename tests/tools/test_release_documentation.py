"""Keep the public reading paths local, present, and independent of work notes."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]


class HomepageLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.assets = []
        self.refresh = False

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a":
            self.links.append(attributes.get("href", ""))
        if tag in {"video", "script", "img"}:
            self.assets.extend(attributes[key] for key in ("src", "poster") if key in attributes)
        if tag == "meta" and attributes.get("http-equiv", "").lower() == "refresh":
            self.refresh = True


def test_homepage_has_direct_reading_paths_and_current_media():
    page = ROOT / "docs/index.html"
    parsed = HomepageLinks()
    parsed.feed(page.read_text(encoding="utf-8"))
    assert not parsed.refresh
    for name in ("PROJECT_TOUR.md", "CODE_MAP.md", "PERSONAL_CONTRIBUTION.md"):
        assert any(link.endswith(name) for link in parsed.links)
    assert "https://github.com/Lanceloia/nomos-m1-web" in parsed.links
    assert "showcase/introduction/film-v3/index.html" in parsed.links
    assert parsed.assets
    for asset in parsed.assets:
        assert (page.parent / asset).is_file()
    assert (page.parent / "showcase/introduction/film-v3/font/site-chinese.woff").is_file()


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
