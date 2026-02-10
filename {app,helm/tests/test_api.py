"""
Unit tests for City Population API.

Uses FastAPI's TestClient with mocked Elasticsearch.
Run: pytest tests/ -v
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport

# We need to mock ES before importing the app
mock_es = AsyncMock()
mock_es.ping = AsyncMock(return_value=True)
mock_es.indices.exists = AsyncMock(return_value=True)
mock_es.close = AsyncMock()


@pytest.fixture
def app():
    """Create a test app with mocked ES."""
    with patch("app.main._init_es", return_value=mock_es):
        from app.main import app as _app
        import app.main as main_module
        main_module.es = mock_es
        yield _app


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health_check(client):
    """Health endpoint returns OK when ES is reachable."""
    mock_es.ping = AsyncMock(return_value=True)
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "OK"
    assert data["elasticsearch"] == "connected"


@pytest.mark.asyncio
async def test_health_check_es_down(client):
    """Health endpoint returns 503 when ES is unreachable."""
    mock_es.ping = AsyncMock(return_value=False)
    resp = await client.get("/health")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_upsert_city(client):
    """PUT /cities should index a document in ES."""
    mock_es.index = AsyncMock(return_value={"result": "created"})
    resp = await client.put("/cities", json={
        "city": "Abu Dhabi",
        "population": 1480000,
        "country": "UAE",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["city"] == "Abu Dhabi"
    assert data["population"] == 1480000
    mock_es.index.assert_called_once()


@pytest.mark.asyncio
async def test_get_city_found(client):
    """GET /cities/{name} returns the city when it exists."""
    mock_es.get = AsyncMock(return_value={
        "_source": {
            "city": "Dubai",
            "population": 3500000,
            "country": "UAE",
        }
    })
    resp = await client.get("/cities/Dubai")
    assert resp.status_code == 200
    data = resp.json()
    assert data["city"] == "Dubai"
    assert data["population"] == 3500000


@pytest.mark.asyncio
async def test_get_city_not_found(client):
    """GET /cities/{name} returns 404 for unknown cities."""
    from elasticsearch import NotFoundError
    mock_es.get = AsyncMock(side_effect=NotFoundError(404, "not_found", {}))
    resp = await client.get("/cities/Atlantis")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_upsert_invalid_population(client):
    """Negative population should be rejected by validation."""
    resp = await client.put("/cities", json={
        "city": "TestCity",
        "population": -100,
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_cities(client):
    """GET /cities returns paginated list."""
    mock_es.search = AsyncMock(return_value={
        "hits": {
            "total": {"value": 2},
            "hits": [
                {"_source": {"city": "Abu Dhabi", "population": 1480000}},
                {"_source": {"city": "Dubai", "population": 3500000}},
            ],
        }
    })
    resp = await client.get("/cities?page=1&size=10")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["cities"]) == 2
