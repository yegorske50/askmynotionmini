"""End-to-end API tests against the seeded demo (mock providers)."""



def test_health_ok(app_client):
    r = app_client.get("/health")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] in ("ok", "degraded")


def test_workspace_get_returns_seeded(app_client):
    r = app_client.get("/api/workspace")
    assert r.status_code == 200
    j = r.json()
    assert j["notion_page_id"] == "mock-page-0001"
    assert j["counts"]["videos"] >= 3
    assert j["counts"]["chunks"] > 0


def test_list_sources_has_three_reels(app_client):
    r = app_client.get("/api/sources")
    assert r.status_code == 200
    j = r.json()
    assert len(j["videos"]) == 3
    assert len(j["pages"]) == 1


def test_post_message_stream(app_client):
    r = app_client.post("/api/ingest", json={})  # idempotent on seeded
    assert r.status_code == 200
    # Ask a question through the streaming endpoint and accumulate events.
    with app_client.stream(
        "POST",
        "/api/conversations/1/messages",
        json={"content": "How much water should I drink each day?"},
    ) as resp:
        assert resp.status_code == 200
        chunks = []
        for line in resp.iter_lines():
            if not line:
                continue
            chunks.append(line)
    text = "\n".join(chunks)
    assert "data:" in text
    # final event should include sources
    assert '"type": "final"' in text or '"type":"final"' in text
