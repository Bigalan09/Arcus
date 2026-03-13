"""Tests for the admin blocklist CRUD endpoints."""

import pytest

# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_blocklist_requires_auth(client):
    """GET /admin/blocklist without auth returns 401."""
    resp = await client.get("/admin/blocklist")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_add_requires_auth(client):
    """POST /admin/blocklist without auth returns 401."""
    resp = await client.post("/admin/blocklist", json={"words": ["test"]})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_blocklist_empty(client, admin_headers):
    """GET /admin/blocklist returns an empty list initially."""
    resp = await client.get("/admin/blocklist", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Add – single and batch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_single_word(client, admin_headers):
    """POST with one word adds it and returns the created entry."""
    resp = await client.post("/admin/blocklist", json={"words": ["badword"]}, headers=admin_headers)
    assert resp.status_code == 201
    words = [e["word"] for e in resp.json()]
    assert "badword" in words


@pytest.mark.asyncio
async def test_add_batch_words(client, admin_headers):
    """POST with multiple words adds all of them."""
    resp = await client.post(
        "/admin/blocklist",
        json={"words": ["alpha", "beta", "gamma"]},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    words = [e["word"] for e in resp.json()]
    assert "alpha" in words
    assert "beta" in words
    assert "gamma" in words


@pytest.mark.asyncio
async def test_add_duplicate_word_is_idempotent(client, admin_headers):
    """Adding a word that already exists does not raise an error."""
    await client.post("/admin/blocklist", json={"words": ["dup"]}, headers=admin_headers)
    resp = await client.post("/admin/blocklist", json={"words": ["dup"]}, headers=admin_headers)
    assert resp.status_code == 201

    list_resp = await client.get("/admin/blocklist", headers=admin_headers)
    assert sum(1 for e in list_resp.json() if e["word"] == "dup") == 1


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_word(client, admin_headers):
    """DELETE /admin/blocklist/{word} removes the word and returns 204."""
    await client.post("/admin/blocklist", json={"words": ["toremove"]}, headers=admin_headers)
    resp = await client.delete("/admin/blocklist/toremove", headers=admin_headers)
    assert resp.status_code == 204

    list_resp = await client.get("/admin/blocklist", headers=admin_headers)
    assert all(e["word"] != "toremove" for e in list_resp.json())


@pytest.mark.asyncio
async def test_delete_nonexistent_word_returns_404(client, admin_headers):
    """Deleting a word that is not in the blocklist returns 404."""
    resp = await client.delete("/admin/blocklist/nothere", headers=admin_headers)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_csv_empty(client, admin_headers):
    """GET /admin/blocklist/export returns a valid CSV with just the header."""
    resp = await client.get("/admin/blocklist/export", headers=admin_headers)
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    lines = resp.text.strip().splitlines()
    assert lines[0].lower() == "word"


@pytest.mark.asyncio
async def test_export_csv_with_words(client, admin_headers):
    """CSV export contains all blocklisted words, one per line."""
    await client.post("/admin/blocklist", json={"words": ["export1", "export2"]}, headers=admin_headers)
    resp = await client.get("/admin/blocklist/export", headers=admin_headers)
    assert resp.status_code == 200
    content = resp.text
    assert "export1" in content
    assert "export2" in content
    assert resp.headers.get("content-disposition", "").startswith("attachment")


# ---------------------------------------------------------------------------
# CSV import – append
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_import_csv_append(client, admin_headers):
    """Importing CSV with mode=append adds new words without removing existing ones."""
    await client.post("/admin/blocklist", json={"words": ["existing"]}, headers=admin_headers)

    csv_content = "word\nnewword1\nnewword2\n"
    resp = await client.post(
        "/admin/blocklist/import?mode=append",
        content=csv_content.encode(),
        headers={**admin_headers, "content-type": "text/csv"},
    )
    assert resp.status_code == 200

    list_resp = await client.get("/admin/blocklist", headers=admin_headers)
    words = [e["word"] for e in list_resp.json()]
    assert "existing" in words
    assert "newword1" in words
    assert "newword2" in words


# ---------------------------------------------------------------------------
# CSV import – replace
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_import_csv_replace(client, admin_headers):
    """Importing CSV with mode=replace wipes existing words and inserts new ones."""
    await client.post("/admin/blocklist", json={"words": ["old1", "old2"]}, headers=admin_headers)

    csv_content = "word\nfresh1\nfresh2\n"
    resp = await client.post(
        "/admin/blocklist/import?mode=replace",
        content=csv_content.encode(),
        headers={**admin_headers, "content-type": "text/csv"},
    )
    assert resp.status_code == 200

    list_resp = await client.get("/admin/blocklist", headers=admin_headers)
    words = [e["word"] for e in list_resp.json()]
    assert "old1" not in words
    assert "old2" not in words
    assert "fresh1" in words
    assert "fresh2" in words


@pytest.mark.asyncio
async def test_import_csv_invalid_mode(client, admin_headers):
    """Importing with an unknown mode returns 422."""
    csv_content = "word\nbadmode\n"
    resp = await client.post(
        "/admin/blocklist/import?mode=badvalue",
        content=csv_content.encode(),
        headers={**admin_headers, "content-type": "text/csv"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_import_csv_skips_blank_lines_and_comments(client, admin_headers):
    """Blank lines and lines starting with # are ignored during import."""
    csv_content = "word\n# this is a comment\n\nvalidword\n\n"
    resp = await client.post(
        "/admin/blocklist/import?mode=replace",
        content=csv_content.encode(),
        headers={**admin_headers, "content-type": "text/csv"},
    )
    assert resp.status_code == 200

    list_resp = await client.get("/admin/blocklist", headers=admin_headers)
    words = [e["word"] for e in list_resp.json()]
    assert "validword" in words
    assert len(words) == 1
