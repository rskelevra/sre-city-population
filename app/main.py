"""
City Population API — A FastAPI service backed by Elasticsearch.

Provides endpoints to upsert, query, and manage city population data.
Designed for containerized deployment on Kubernetes.
"""

import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from elasticsearch import AsyncElasticsearch, NotFoundError, ConnectionError as ESConnectionError

# ---------------------------------------------------------------------------
# Configuration (12‑factor: all config via environment variables)
# ---------------------------------------------------------------------------
ES_HOST = os.getenv("ELASTICSEARCH_HOST", "elasticsearch")
ES_PORT = int(os.getenv("ELASTICSEARCH_PORT", "9200"))
ES_SCHEME = os.getenv("ELASTICSEARCH_SCHEME", "http")
ES_USER = os.getenv("ELASTICSEARCH_USER", "")
ES_PASSWORD = os.getenv("ELASTICSEARCH_PASSWORD", "")
ES_INDEX = os.getenv("ELASTICSEARCH_INDEX", "cities")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("city-api")

# ---------------------------------------------------------------------------
# Elasticsearch client (module‑level, managed by lifespan)
# ---------------------------------------------------------------------------
es: Optional[AsyncElasticsearch] = None

INDEX_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 1,
    },
}


async def _init_es() -> AsyncElasticsearch:
    """Create the ES client and ensure the index exists."""
    kwargs: dict = {
        "hosts": [f"{ES_SCHEME}://{ES_HOST}:{ES_PORT}"],
        "retry_on_timeout": True,
        "max_retries": 5,
    }
    if ES_USER and ES_PASSWORD:
        kwargs["basic_auth"] = (ES_USER, ES_PASSWORD)

    client = AsyncElasticsearch(**kwargs)

    # Wait for cluster to be reachable
    if not await client.ping():
        raise RuntimeError("Cannot reach Elasticsearch cluster")

    # Create index if it doesn't already exist
    if not await client.indices.exists(index=ES_INDEX):
        await client.indices.create(index=ES_INDEX, settings=INDEX_MAPPING["settings"])
        logger.info("Created index '%s'", ES_INDEX)
    else:
        logger.info("Index '%s' already exists", ES_INDEX)

    return client


# ---------------------------------------------------------------------------
# Application lifespan (startup / shutdown)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(_app: FastAPI):
    global es
    logger.info("Connecting to Elasticsearch at %s://%s:%s …", ES_SCHEME, ES_HOST, ES_PORT)
    es = await _init_es()
    logger.info("Elasticsearch connection established ✓")
    yield
    await es.close()
    logger.info("Elasticsearch connection closed")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="City Population API",
    description="Manage city population data, backed by Elasticsearch.",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class CityPayload(BaseModel):
    """Request body for upserting a city."""
    city: str = Field(..., min_length=1, examples=["Abu Dhabi"])
    population: int = Field(..., ge=0, examples=[1480000])
    country: Optional[str] = Field(None, examples=["UAE"])


class CityResponse(BaseModel):
    """Response model for city data."""
    city: str
    population: int
    country: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    elasticsearch: str


class MessageResponse(BaseModel):
    message: str
    city: str
    population: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _city_id(name: str) -> str:
    """Deterministic document ID from city name (lowercased, trimmed)."""
    return name.strip().lower().replace(" ", "_")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["ops"])
async def health_check():
    """
    Health check — returns OK and verifies Elasticsearch connectivity.
    Suitable as a Kubernetes liveness / readiness probe target.
    """
    try:
        es_healthy = await es.ping()
    except Exception:
        es_healthy = False

    if not es_healthy:
        raise HTTPException(status_code=503, detail="Elasticsearch unreachable")

    return HealthResponse(status="OK", elasticsearch="connected")


@app.put("/cities", response_model=MessageResponse, tags=["cities"])
async def upsert_city(payload: CityPayload):
    """
    Insert or update a city and its population.

    - If the city already exists its population (and optional country) are updated.
    - City matching is **case‑insensitive**.
    """
    doc_id = _city_id(payload.city)
    doc = {
        "city": payload.city.strip(),
        "population": payload.population,
        "updated_at": "now",
    }
    if payload.country:
        doc["country"] = payload.country.strip()

    try:
        await es.index(index=ES_INDEX, id=doc_id, document=doc, refresh="wait_for")
    except ESConnectionError as exc:
        logger.error("ES connection error during upsert: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable")

    logger.info("Upserted city=%s population=%d", payload.city, payload.population)
    return MessageResponse(
        message="City upserted successfully",
        city=payload.city.strip(),
        population=payload.population,
    )


@app.get("/cities/{city_name}", response_model=CityResponse, tags=["cities"])
async def get_city(city_name: str):
    """
    Retrieve the population of a specified city (case‑insensitive lookup).
    """
    doc_id = _city_id(city_name)
    try:
        result = await es.get(index=ES_INDEX, id=doc_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"City '{city_name}' not found")
    except ESConnectionError as exc:
        logger.error("ES connection error during query: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable")

    src = result["_source"]
    return CityResponse(
        city=src["city"],
        population=src["population"],
        country=src.get("country"),
    )


@app.get("/cities", tags=["cities"])
async def list_cities(
    page: int = Query(1, ge=1, description="Page number"),
    size: int = Query(20, ge=1, le=100, description="Results per page"),
):
    """
    List all cities with pagination support.
    """
    body = {
        "query": {"match_all": {}},
        "sort": [{"city.keyword": "asc"}],
        "from": (page - 1) * size,
        "size": size,
    }
    try:
        result = await es.search(index=ES_INDEX, body=body)
    except ESConnectionError as exc:
        logger.error("ES connection error during list: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable")

    hits = result["hits"]
    return {
        "total": hits["total"]["value"],
        "page": page,
        "size": size,
        "cities": [h["_source"] for h in hits["hits"]],
    }


@app.delete("/cities/{city_name}", tags=["cities"])
async def delete_city(city_name: str):
    """Delete a city record."""
    doc_id = _city_id(city_name)
    try:
        await es.delete(index=ES_INDEX, id=doc_id, refresh="wait_for")
    except NotFoundError:
        raise HTTPException(status_code=404, detail=f"City '{city_name}' not found")

    return {"message": f"City '{city_name}' deleted"}
