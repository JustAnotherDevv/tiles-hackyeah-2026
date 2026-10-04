"""Built-dashboard smoke test: the real gateway serves `web/dist` and every referenced asset exists.

Skipped when the bundle has not been built (`make web`). Catches a broken or partial build (index.html
pointing at missing hashed chunks, a lazy route chunk that was never emitted) before a judge opens
`/ui/`. Route-agnostic on purpose: deep links are served by the SPA fallback, so this does not depend
on the dashboard's page list. The dist is copied to a temp dir first so a concurrent `make web` cannot
change it mid-test.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
DIST = ROOT / "web" / "dist"

pytestmark = pytest.mark.skipif(
    not (DIST / "index.html").is_file(), reason="web/dist not built (run `make web`)"
)

#: absolute /ui/ references in index.html (script src, modulepreload, stylesheet, icon)
INDEX_REF = re.compile(r"""(?:src|href)=["'](/ui/[^"'?#]+)["']""")
#: sibling chunk references inside built JS (static + dynamic imports, CSS deps)
CHUNK_REF = re.compile(r"""["'`](?:\./|/ui/assets/)([\w.-]+\.(?:js|css))["'`]""")
DEEP_LINKS = ("/ui/", "/ui/security/live", "/ui/governance/approvals", "/ui/does/not/exist")


@pytest.fixture(scope="module")
def dist_copy(tmp_path_factory: pytest.TempPathFactory) -> Path:
    dst = tmp_path_factory.mktemp("ui") / "dist"
    try:
        shutil.copytree(DIST, dst)
    except (OSError, shutil.Error) as exc:  # a concurrent rebuild removed files mid-copy
        pytest.skip(f"web/dist changed while copying: {exc}")
    if not (dst / "index.html").is_file():
        pytest.skip("web/dist/index.html vanished (rebuild in progress)")
    return dst


@pytest.fixture(scope="module")
def client(dist_copy: Path, tmp_path_factory: pytest.TempPathFactory) -> Iterator[object]:
    from fastapi.testclient import TestClient

    from aegis.app import create_app
    from aegis.settings import Settings

    mp = pytest.MonkeyPatch()
    mp.setenv("AEGIS_TEST_MODE", "1")
    mp.setenv("AEGIS_SEMANTIC", "off")
    mp.setenv("AEGIS_FEED_URL", "disabled")
    data = tmp_path_factory.mktemp("data")
    try:
        app = create_app(Settings(data_dir=data, ui_dist=dist_copy, test_mode=True, semantic="off", feed_url="disabled"))
        with TestClient(app, follow_redirects=False) as c:
            yield c
    finally:
        mp.undo()


def _index_refs(html: str) -> list[str]:
    return sorted(set(INDEX_REF.findall(html)))


def test_root_redirects_to_ui(client) -> None:
    r = client.get("/")
    assert r.status_code in (302, 307), r.status_code
    assert r.headers["location"].endswith("/ui/")


@pytest.mark.parametrize("path", DEEP_LINKS)
def test_deep_links_serve_the_built_index(client, dist_copy: Path, path: str) -> None:
    r = client.get(path)
    assert r.status_code == 200, f"{path}: {r.status_code}"
    assert r.headers["content-type"].startswith("text/html")
    assert r.text == (dist_copy / "index.html").read_text(encoding="utf-8"), f"{path}: not the built index"
    assert "make web" not in r.text, "placeholder page served although dist exists"


def test_index_references_existing_assets(client, dist_copy: Path) -> None:
    html = (dist_copy / "index.html").read_text(encoding="utf-8")
    refs = _index_refs(html)
    scripts = [u for u in refs if u.startswith("/ui/assets/") and u.endswith(".js")]
    assert scripts, "index.html references no /ui/assets/*.js entry chunk"
    for url in refs:
        r = client.get(url)
        assert r.status_code == 200, f"{url}: {r.status_code} (index.html references a missing file)"
        if url.startswith("/ui/assets/"):
            assert "immutable" in r.headers.get("cache-control", ""), url
        if url.endswith(".js"):
            assert "javascript" in r.headers["content-type"], url


def test_every_chunk_import_resolves(client, dist_copy: Path) -> None:
    assets = dist_copy / "assets"
    js = sorted(assets.glob("*.js"))
    assert js, "no JS chunks in web/dist/assets"
    missing: dict[str, list[str]] = {}
    seen = 0
    for f in js:
        for name in set(CHUNK_REF.findall(f.read_text(encoding="utf-8", errors="replace"))):
            seen += 1
            if not (assets / name).is_file():
                missing.setdefault(f.name, []).append(name)
    assert seen, "no chunk imports found (CHUNK_REF no longer matches the bundler output)"
    assert not missing, f"chunks import files that were not emitted: {missing}"
    # spot-check that the server serves a lazily imported chunk too
    for f in js[:3]:
        assert client.get(f"/ui/assets/{f.name}").status_code == 200, f.name


def test_missing_asset_is_404_not_index(client) -> None:
    r = client.get("/ui/assets/definitely-not-built-0000.js")
    assert r.status_code == 404


def test_path_traversal_is_not_served(client) -> None:
    for path in ("/ui/../pyproject.toml", "/ui/%2e%2e/pyproject.toml", "/ui/..%2fpyproject.toml"):
        r = client.get(path)
        assert "[tool.pytest" not in r.text, f"{path} escaped ui_dist"
