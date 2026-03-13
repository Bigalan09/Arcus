"""RED tests for the admin blacklist CRUD endpoints."""

import io
import os

import pytest

API_KEY = os.environ.get("API_SECRET_KEY", "changeme")
HEADERS = {"X-Api-Key": API_KEY}


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_blacklist_requires_api_key(client):
    """GET /admin/blacklist without API key returns 401."""
    resp = await client.get("/admin/blacklist")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_add_requires_api_key(client):
    """POST /admin/blacklist without API key returns 401."""
    resp = await client.post("/admin/blacklist", json={"words": ["test"]})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_blacklist_empty(client):
    """GET /admin/blacklist returns an empty list initially."""
    resp = await client.get("/admin/blacklist", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Add – single and batch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_single_word(client):
    """POST with one word adds it and returns the created entry."""
    resp = await client.post("/admin/blacklist", json={"words": ["badword"]}, headers=HEADERS)
    assert resp.status_code == 201
    words = [e["word"] for e in resp.json()]
    assert "badword" in words


@pytest.mark.asyncio
async def test_add_batch_words(client):
    """POST with multiple words adds all of them."""
    resp = await client.post(
        "/admin/blacklist",
        json={"words": ["alpha", "beta", "gamma"]},
        headers=HEADERS,
    )
    assert resp.status_code == 201
    words = [e["word"] for e in resp.json()]
    assert "alpha" in words
    assert "beta" in words
    assert "gamma" in words


@pytest.mark.asyncio
async def test_add_duplicate_word_is_idempotent(client):
    """Adding a word that already exists does not raise an error."""
    await client.post("/admin/blacklist", json={"words": ["dup"]}, headers=HEADERS)
    resp = await client.post("/admin/blacklist", json={"words": ["dup"]}, headers=HEADERS)
    assert resp.status_code == 201

    list_resp = await client.get("/admin/blacklist", headers=HEADERS)
    assert sum(1 for e in list_resp.json() if e["word"] == "dup") == 1


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_word(client):
    """DELETE /admin/blacklist/{word} removes the word and returns 204."""
    await client.post("/admin/blacklist", json={"words": ["toremove"]}, headers=HEADERS)
    resp = await client.delete("/admin/blacklist/toremove", headers=HEADERS)
    assert resp.status_code == 204

    list_resp = await client.get("/admin/blacklist", headers=HEADERS)
    assert all(e["word"] != "toremove" for e in list_resp.json())


@pytest.mark.asyncio
async def test_delete_nonexistent_word_returns_404(client):
    """Deleting a word that is not in the blacklist returns 404."""
    resp = await client.delete("/admin/blacklist/nothere", headers=HEADERS)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_csv_empty(client):
    """GET /admin/blacklist/export returns a valid CSV with just the header."""
    resp = await client.get("/admin/blacklist/export", headers=HEADERS)
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    lines = resp.text.strip().splitlines()
    assert lines[0].lower() == "word"


@pytest.mark.asyncio
async def test_export_csv_with_words(client):
    """CSV export contains all blacklisted words, one per line."""
    await client.post("/admin/blacklist", json={"words": ["export1", "export2"]}, headers=HEADERS)
    resp = await client.get("/admin/blacklist/export", headers=HEADERS)
    assert resp.status_code == 200
    content = resp.text
    assert "export1" in content
    assert "export2" in content
    assert resp.headers.get("content-disposition", "").startswith("attachment")


# ---------------------------------------------------------------------------
# CSV import – append
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_import_csv_append(client):
    """Importing CSV with mode=append adds new words without removing existing ones."""
    await client.post("/admin/blacklist", json={"words": ["existing"]}, headers=HEADERS)

    csv_content = "word\nnewword1\nnewword2\n"
    resp = await client.post(
        "/admin/blacklist/import?mode=append",
        content=csv_content.encode(),
        headers={**HEADERS, "content-type": "text/csv"},
    )
    assert resp.status_code == 200

    list_resp = await client.get("/admin/blacklist", headers=HEADERS)
    words = [e["word"] for e in list_resp.json()]
    assert "existing" in words
    assert "newword1" in words
    assert "newword2" in words


# ---------------------------------------------------------------------------
# CSV import – replace
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_import_csv_replace(client):
    """Importing CSV with mode=replace wipes existing words and inserts new ones."""
    await client.post("/admin/blacklist", json={"words": ["old1", "old2"]}, headers=HEADERS)

    csv_content = "word\nfresh1\nfresh2\n"
    resp = await client.post(
        "/admin/blacklist/import?mode=replace",
        content=csv_content.encode(),
        headers={**HEADERS, "content-type": "text/csv"},
    )
    assert resp.status_code == 200

    list_resp = await client.get("/admin/blacklist", headers=HEADERS)
    words = [e["word"] for e in list_resp.json()]
    assert "old1" not in words
    assert "old2" not in words
    assert "fresh1" in words
    assert "fresh2" in words


@pytest.mark.asyncio
async def test_import_csv_invalid_mode(client):
    """Importing with an unknown mode returns 422."""
    csv_content = "word\nbadmode\n"
    resp = await client.post(
        "/admin/blacklist/import?mode=badvalue",
        content=csv_content.encode(),
        headers={**HEADERS, "content-type": "text/csv"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_import_csv_skips_blank_lines_and_comments(client):
    """Blank lines and lines starting with # are ignored during import."""
    csv_content = "word\n# this is a comment\n\nvalidword\n\n"
    resp = await client.post(
        "/admin/blacklist/import?mode=replace",
        content=csv_content.encode(),
        headers={**HEADERS, "content-type": "text/csv"},
    )
    assert resp.status_code == 200

    list_resp = await client.get("/admin/blacklist", headers=HEADERS)
    words = [e["word"] for e in list_resp.json()]
    assert "validword" in words
    assert len(words) == 1
