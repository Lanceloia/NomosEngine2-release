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
    for repo in ("NomosEngine2-release", "nomos-m1-web"):
        assert f"https://github.com/Lanceloia/{repo}/tree/showcase-2026-10-11" in parsed.links
    assert "showcase/introduction/film-v6/index.html" in parsed.links
    assert parsed.assets
    for asset in parsed.assets:
        assert (page.parent / asset).is_file()
    assert (page.parent / "showcase/introduction/film-v6/font/site-chinese.woff").is_file()
    assert any(link.endswith("NOMOS_PRODUCT_PROPOSITION.md") for link in parsed.links)


def test_homepage_and_verification_link_the_same_successful_ci_run():
    target = "https://github.com/Lanceloia/NomosEngine2-release/actions/runs/38135299619"
    for path in ("docs/index.html", "docs/VERIFICATION.md", "README.md"):
        assert target in (ROOT / path).read_text(encoding="utf-8")
    assert "ce190292c75d8e36da2e692c7b5dfaf08323ebde" in (
        ROOT / "docs/VERIFICATION.md"
    ).read_text(encoding="utf-8")


def test_course_reading_paths_are_pinned_in_homepage_and_contribution_guide():
    revisions = {
        "cp2020": "1cf28947cc4beef5d9bd2f87274e036b8fb15766",
        "os2019": "b86451574242d3eaded3baae354c1102d710ac72",
        "ics2018": "fd881ab8ef2b87dd55030a07bc69479d07feddff",
    }
    homepage = (ROOT / "docs/index.html").read_text(encoding="utf-8")
    guide = (ROOT / "docs/PERSONAL_CONTRIBUTION.md").read_text(encoding="utf-8")
    for repo, revision in revisions.items():
        assert f"https://github.com/Lanceloia/{repo}/tree/{revision}" in homepage
        assert f"https://github.com/Lanceloia/{repo}/blob/{revision}/docs/CODE_TOUR.md" in guide


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
