# City Population API

A containerized REST API for managing city population data, backed by Elasticsearch and deployable on Kubernetes via Helm.

Built with FastAPI (Python 3.12) — chose it over Flask mainly for the async support and the free Swagger docs you get out of the box at `/docs`.

---

## Architecture

```
┌─────────────┐       ┌──────────────────┐       ┌─────────────────────┐
│   Client    │──────▶│  City Pop API     │──────▶│   Elasticsearch     │
│  (curl/UI)  │◀──────│  (FastAPI+Uvicorn)│◀──────│   (single/cluster)  │
└─────────────┘       └──────────────────┘       └─────────────────────┘
                        Port 8000                    Port 9200
```

Uvicorn is the ASGI server that actually listens on port 8000 and forwards requests to FastAPI. Think of uvicorn as the waiter and FastAPI as the chef.

**Why these choices:**
- **FastAPI** — async by default, Pydantic validation catches bad input before it hits ES, and the auto-generated `/docs` endpoint is great for demos.
- **Elasticsearch** — the assignment suggested it, plus it scales horizontally well and gives us full-text search for free if we ever want fuzzy city name matching.
- **12-Factor approach** — all config via env vars so the same image works locally, in Docker, and in K8s without changes.

---

## API Endpoints

| Method | Endpoint             | Description                          |
|--------|----------------------|--------------------------------------|
| GET    | `/health`            | Health check (includes ES status)    |
| PUT    | `/cities`            | Upsert a city and its population     |
| GET    | `/cities/{name}`     | Get population of a specific city    |
| GET    | `/cities`            | List all cities (paginated)          |
| DELETE | `/cities/{name}`     | Delete a city record                 |

Interactive docs available at `/docs` (Swagger UI) once the app is running.

### Example Requests

```bash
# Health check
curl http://localhost:8000/health

# Add a city
curl -X PUT http://localhost:8000/cities \
  -H "Content-Type: application/json" \
  -d '{"city": "Abu Dhabi", "population": 1480000, "country": "UAE"}'

# Query a city
curl http://localhost:8000/cities/Abu%20Dhabi

# List all (paginated)
curl "http://localhost:8000/cities?page=1&size=10"

# Delete
curl -X DELETE http://localhost:8000/cities/Abu%20Dhabi
```

---

## Quick Start — Docker Compose

```bash
git clone <repo-url> && cd sre-city-population

# Bring up ES + API
docker compose up --build

# Wait ~30-60s for ES to be healthy, then:
curl http://localhost:8000/health
```

To tear down:
```bash
docker compose down -v
```

---

## Kubernetes Deployment — Helm

### Prerequisites

- A K8s cluster (minikube, kind, Rancher Desktop, EKS, etc.)
- `kubectl` and `helm` v3
- Container image pushed to a registry the cluster can pull from

### Build & Push the Image

```bash
docker build -t <your-registry>/city-population-api:1.0.0 .
docker push <your-registry>/city-population-api:1.0.0
```

For **minikube/Rancher**: `eval $(minikube/Rancher docker-env)` then build locally.
For **kind**: `kind load docker-image city-population-api:1.0.0`

### Install

```bash
cd helm/city-population-api

helm repo add elastic https://helm.elastic.co
helm repo update
helm dependency build

helm install city-api . \
  --create-namespace \
  --namespace city-api \
  --set image.repository=rsharm49/city-population-api \
  --set image.tag=1.0.0
```

### Verify

```bash
kubectl get pods -n city-api
kubectl rollout status statefulset/city-api-elasticsearch-master -n city-api

# Port-forward and test
kubectl port-forward svc/city-api-city-population-api 8000:80 -n city-api
curl http://localhost:8000/health
```

### Uninstall

```bash
helm uninstall city-api --namespace city-api
kubectl delete namespace city-api
```

---

## Running Tests

```bash
pip install -r app/requirements.txt or python -m pip install -r app/requirements.txt
pytest tests/ -v
```
```

Tests mock Elasticsearch entirely — no infra needed. Uses `pytest_asyncio.fixture` for the async HTTP client (ran into issues with plain `@pytest.fixture` on async generators — more on that in the reflection below).

---

## Configuration

All via environment variables:

| Variable               | Default           | Description                     |
|------------------------|-------------------|---------------------------------|
| `ELASTICSEARCH_HOST`   | `elasticsearch`   | ES hostname                     |
| `ELASTICSEARCH_PORT`   | `9200`            | ES port                         |
| `ELASTICSEARCH_SCHEME` | `http`            | `http` or `https`               |
| `ELASTICSEARCH_USER`   | (empty)           | ES basic auth username          |
| `ELASTICSEARCH_PASSWORD`| (empty)          | ES basic auth password          |
| `ELASTICSEARCH_INDEX`  | `cities`          | Index name                      |
| `LOG_LEVEL`            | `INFO`            | Python log level                |

---

## Project Structure

```
sre-city-population/
├── app/
│   ├── main.py              # FastAPI application
│   └── requirements.txt     # Python deps
├── tests/
│   ├── conftest.py          # Path setup
│   └── test_api.py          # Unit tests (mocked ES)
├── helm/
│   └── city-population-api/
│       ├── Chart.yaml
│       ├── values.yaml
│       └── templates/        # Deployment, Service, Ingress, HPA, PDB
├── Dockerfile               # Multi-stage, non-root
├── docker-compose.yml       # Local dev stack
└── README.md
```

---

## Reflection

### Challenges I Ran Into

1. ES 8.x Python client deprecated the `body=` parameter

The `indices.create(index=..., body=...)` pattern that you see in most Stack Overflow answers and tutorials is for the ES 7.x client. The 8.x client wants separate keyword arguments — `mappings=`, `settings=`, etc. I kept getting a cryptic `mapper_parsing_exception` about "Expected map for property [fields]" until I figured this out. In the end I simplified it by dropping the explicit mapping and letting ES auto-detect types from the first indexed document, which is fine for this use case.

2. Sorting on a `text` field breaks in ES

When I let ES auto-detect field types (no explicit mapping), it mapped `city` as a `text` field. My list endpoint tried to `"sort": [{"city": "asc"}]` and ES refused — text fields aren't sortable by default because they go through analysis. The fix was using the auto-generated keyword sub-field: `"sort": [{"city.keyword": "asc"}]`. Small thing but it took me a minute to connect the error message to the actual cause.

3. `pytest-asyncio` fixture gotcha

My test fixtures for the async HTTP client used `@pytest.fixture` but since the fixture was an async generator, pytest couldn't handle it properly — every test failed with `'async_generator' object has no attribute 'get'`. Switching to `@pytest_asyncio.fixture` fixed it. The deprecation warning in the pytest output actually pointed me in the right direction here.

4. During Kubernetes deployment via Helm, the application was unable to connect to Elasticsearch over HTTP. While disabling security worked in a local environment by modifying /etc/elasticsearch/elasticsearch.yml, the official Elasticsearch 8.5.x Helm chart enforces security defaults and automatically enables TLS and authentication.

Attempts to disable security via values.yaml were ineffective because the Helm chart hardcodes several security-related environment variables and startup parameters. Increasing memory allocation did not resolve the issue, confirming the problem was configuration-level rather than resource-related.

After a few failed attempts trying to force-disable security in values.yaml, I switched approach and updated the app to support HTTPS + auth instead.

Key learning: Elasticsearch 8.x treats security as a mandatory default in containerized deployments, and Helm charts may enforce opinionated configurations that override user-supplied values.
### What I'd Do for Production

**High Availability:**
- Run ES as a multi-node cluster (at least 3 master-eligible nodes) with cross-AZ anti-affinity so a single zone failure doesn't take out the cluster.
- Bump API replicas to 3+ and enable the HPA (already templated in the chart, just needs `autoscaling.enabled: true`).
- Set up ES snapshot/restore to S3 or GCS for backups. I've seen too many "we'll set up backups later" situations go sideways.
- The PDB is already in the chart to prevent K8s from killing all pods during a rolling node upgrade.

**Observability:**
- Add Prometheus metrics using something like `prometheus-fastapi-instrumentator` — track request latency (p50/p95/p99), error rates, and ES query times.
- Ship structured JSON logs to Loki or ELK so you can actually search them. Right now the logs are readable but not great for automated alerting.
- Set up Grafana dashboards for the four golden signals: latency, traffic, errors, saturation.
- Would also want ES cluster health monitoring — disk usage, JVM heap, indexing rate. ES can be a black box if you're not watching it.

**Security:**
- Enable ES TLS and authentication (`xpack.security`). Right now security is disabled for dev simplicity — obviously not okay for prod.
- The Helm chart already references secrets via `secretKeyRef` for ES creds — just need to actually create the K8s Secret.
- Add a NetworkPolicy so only the API pods can talk to ES on port 9200.
- API-level auth — probably API keys or JWT depending on who the consumers are.
- Container runs as non-root with dropped Linux capabilities. Didn’t go deep into seccomp/AppArmor here, but that’d be the next step.

**CI/CD:**
- GitHub Actions pipeline: lint → test → build image → push to registry → deploy via Helm.
- Run `helm lint` and `helm template | kubeconform` in CI to catch chart issues before they hit a real cluster.
- For zero-downtime releases, would look at Argo Rollouts for canary deployments — roll out to 10% of traffic, watch error rates, then proceed.
