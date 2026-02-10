# City Population API

A production-ready, containerized REST API for managing city population data, backed by **Elasticsearch** and deployable on **Kubernetes** via a **Helm chart**.

Built with **FastAPI** (Python 3.12) for high performance and automatic OpenAPI documentation.

---

## Table of Contents

- [Architecture](#architecture)
- [API Reference](#api-reference)
- [Quick Start — Docker Compose](#quick-start--docker-compose)
- [Kubernetes Deployment — Helm](#kubernetes-deployment--helm)
- [Running Tests](#running-tests)
- [Configuration Reference](#configuration-reference)
- [Project Structure](#project-structure)
- [Reflection](#reflection)

---

## Architecture

```
┌─────────────┐       ┌──────────────────┐       ┌─────────────────────┐
│   Client    │──────▶│  City Pop API     │──────▶│   Elasticsearch     │
│  (curl/UI)  │◀──────│  (FastAPI+Uvicorn)│◀──────│   (single/cluster)  │
└─────────────┘       └──────────────────┘       └─────────────────────┘
                        Port 8000                    Port 9200
                        ┌──────────┐
                        │ /health  │  ← K8s liveness & readiness probes
                        │ /cities  │  ← CRUD operations
                        │ /docs    │  ← Auto-generated Swagger UI
                        └──────────┘
```

**Key Design Decisions:**
- **FastAPI** — Async-native, automatic request validation via Pydantic, built-in OpenAPI docs.
- **Elasticsearch** — Schema-flexible, horizontally scalable, full-text search capable (future-proof for city name fuzzy matching).
- **12-Factor App** — All configuration via environment variables; stateless application tier.
- **Non-root container** — Security best practice baked into the Dockerfile.

---

## API Reference

| Method | Endpoint             | Description                          |
|--------|----------------------|--------------------------------------|
| GET    | `/health`            | Health check (includes ES status)    |
| PUT    | `/cities`            | Upsert a city and its population     |
| GET    | `/cities/{name}`     | Get population of a specific city    |
| GET    | `/cities`            | List all cities (paginated)          |
| DELETE | `/cities/{name}`     | Delete a city record                 |

Full interactive documentation is available at `/docs` (Swagger UI) and `/redoc` once the application is running.

### Example Requests

```bash
# Health check
curl http://localhost:8000/health

# Upsert a city
curl -X PUT http://localhost:8000/cities \
  -H "Content-Type: application/json" \
  -d '{"city": "Abu Dhabi", "population": 1480000, "country": "UAE"}'

# Query a city
curl http://localhost:8000/cities/Abu%20Dhabi

# List all cities (paginated)
curl "http://localhost:8000/cities?page=1&size=10"

# Delete a city
curl -X DELETE http://localhost:8000/cities/Abu%20Dhabi
```

---

## Quick Start — Docker Compose

The fastest way to run everything locally:

```bash
# Clone the repo
git clone <repo-url> && cd sre-city-population

# Start Elasticsearch + API
docker compose up --build

# Wait ~30 seconds for Elasticsearch to be healthy, then test:
curl http://localhost:8000/health
# → {"status":"OK","elasticsearch":"connected"}
```

To stop:
```bash
docker compose down -v   # -v removes the ES data volume
```

---

## Kubernetes Deployment — Helm

### Prerequisites

- A running Kubernetes cluster (minikube, kind, EKS, GKE, AKS, etc.)
- `kubectl` configured to talk to the cluster
- `helm` v3 installed
- Container image pushed to a registry accessible by the cluster

### Step 1 — Build & Push the Container Image

```bash
# Build
docker build -t <your-registry>/city-population-api:1.0.0 .

# Push
docker push <your-registry>/city-population-api:1.0.0
```

For local testing with **minikube**:
```bash
eval $(minikube docker-env)
docker build -t city-population-api:1.0.0 .
```

For local testing with **kind**:
```bash
docker build -t city-population-api:1.0.0 .
kind load docker-image city-population-api:1.0.0
```

### Step 2 — Install the Helm Chart

```bash
cd helm/city-population-api

# Add the Elastic Helm repo (for the Elasticsearch dependency)
helm repo add elastic https://helm.elastic.co
helm repo update

# Download the Elasticsearch sub-chart
helm dependency build

# Install (creates the 'city-api' namespace)
helm install city-api . \
  --create-namespace \
  --namespace city-api \
  --set image.repository=<your-registry>/city-population-api \
  --set image.tag=1.0.0
```

### Step 3 — Verify

```bash
# Check pods
kubectl get pods -n city-api

# Wait for Elasticsearch to be ready (takes ~2 minutes)
kubectl rollout status statefulset/city-api-elasticsearch-master -n city-api

# Port-forward to test
kubectl port-forward svc/city-api-city-population-api 8080:80 -n city-api

# Test
curl http://localhost:8080/health
```

### Upgrading

```bash
helm upgrade city-api . \
  --namespace city-api \
  --set image.tag=1.1.0
```

### Uninstalling

```bash
helm uninstall city-api --namespace city-api
kubectl delete namespace city-api
```

### Customisation

Override values in `values.yaml` or pass `--set` flags. Key options:

| Parameter                         | Default                                            | Description                        |
|-----------------------------------|----------------------------------------------------|------------------------------------|
| `replicaCount`                    | `2`                                                | API pod replicas                   |
| `image.repository`               | `city-population-api`                              | Container image                    |
| `image.tag`                       | `1.0.0`                                            | Image tag                          |
| `config.elasticsearch.host`      | `city-population-api-elasticsearch-master`         | ES hostname                        |
| `autoscaling.enabled`            | `false`                                            | Enable HPA                         |
| `ingress.enabled`                | `false`                                            | Enable Ingress                     |
| `elasticsearch.replicas`         | `1`                                                | ES data node count                 |

---

## Running Tests

```bash
# Install test dependencies
pip install -r app/requirements.txt

# Run tests
pytest tests/ -v
```

Tests use mocked Elasticsearch so they run without any infrastructure.

---

## Configuration Reference

All configuration is via environment variables (12-Factor):

| Variable               | Default           | Description                     |
|------------------------|-------------------|---------------------------------|
| `ELASTICSEARCH_HOST`   | `elasticsearch`   | ES hostname                     |
| `ELASTICSEARCH_PORT`   | `9200`            | ES port                         |
| `ELASTICSEARCH_SCHEME` | `http`            | `http` or `https`               |
| `ELASTICSEARCH_USER`   | (empty)           | ES basic auth username          |
| `ELASTICSEARCH_PASSWORD`| (empty)          | ES basic auth password          |
| `ELASTICSEARCH_INDEX`  | `cities`          | ES index name                   |
| `LOG_LEVEL`            | `INFO`            | Python log level                |

---

## Project Structure

```
sre-city-population/
├── app/
│   ├── main.py              # FastAPI application
│   └── requirements.txt     # Python dependencies
├── tests/
│   └── test_api.py          # Unit tests (mocked ES)
├── helm/
│   └── city-population-api/
│       ├── Chart.yaml        # Helm chart metadata + ES dependency
│       ├── values.yaml       # Default configuration values
│       └── templates/
│           ├── _helpers.tpl      # Template helpers
│           ├── deployment.yaml   # API Deployment
│           ├── service.yaml      # ClusterIP Service
│           ├── ingress.yaml      # Optional Ingress
│           ├── hpa.yaml          # HorizontalPodAutoscaler
│           ├── pdb.yaml          # PodDisruptionBudget
│           ├── serviceaccount.yaml
│           └── NOTES.txt         # Post-install instructions
├── Dockerfile               # Multi-stage build (non-root)
├── docker-compose.yml       # Local dev stack
├── .dockerignore
├── .gitignore
└── README.md                # This file
```

---

## Reflection

### Challenges Faced

1. **Elasticsearch startup timing** — ES takes 30–60 seconds to initialize, so the application needs retry logic and health-check-based dependency ordering. In Docker Compose this is handled with `depends_on: condition: service_healthy`. In Kubernetes, the readiness probe on the API naturally handles this: pods won't receive traffic until ES is reachable via `/health`.

2. **Index creation race condition** — With multiple API replicas starting simultaneously, concurrent index creation calls could conflict. This was mitigated by using `indices.exists()` checks and relying on Elasticsearch's idempotent index creation behavior (409 conflicts are safe to ignore in production; for this assignment, a single check suffices).

3. **Helm dependency management** — Integrating the official Elastic Helm chart as a sub-chart required careful value mapping (`elasticsearch.*` in `values.yaml`) to ensure the ES cluster name, resource limits, and security settings aligned with the application's expectations.

### Suggestions for Production Readiness

**High Availability & Resilience:**
- Deploy Elasticsearch as a multi-node cluster (3+ master-eligible nodes, dedicated data nodes) with cross-AZ pod anti-affinity rules.
- Increase API replicas to 3+ with a PodDisruptionBudget (already templated) and enable the HPA for traffic-based autoscaling.
- Configure Elasticsearch snapshot/restore to S3 or GCS for backup/disaster recovery.

**Observability:**
- Integrate **Prometheus** metrics via `prometheus-fastapi-instrumentator` (request latency, error rates, ES query duration).
- Deploy the **Elastic APM agent** for distributed tracing across the API and Elasticsearch.
- Ship structured JSON logs to a centralized stack (EFK/ELK or Loki+Grafana) for correlation and alerting.
- Create Grafana dashboards covering the four golden signals: latency, traffic, errors, and saturation.

**Security Hardening:**
- Enable Elasticsearch TLS (transport + HTTP) and authentication via `xpack.security`.
- Store ES credentials in a Kubernetes Secret (already templated via `secretKeyRef` in the deployment).
- Add a **NetworkPolicy** to restrict traffic: only the API pods should reach ES on port 9200.
- Implement API authentication (e.g., API keys or OAuth2/JWT) at the application or Ingress level.
- Run regular container image vulnerability scans (Trivy, Snyk).
- Enable Pod Security Standards (`restricted` profile) at the namespace level.

**CI/CD:**
- Automate builds and tests in a CI pipeline (GitHub Actions, GitLab CI, etc.).
- Use `helm lint`, `helm template`, and `kubeval` / `kubeconform` in CI to validate chart correctness before deployment.
- Implement canary or blue-green deployments via Argo Rollouts or Flagger for zero-downtime releases.

**Data Management:**
- Implement index lifecycle management (ILM) policies if city data grows or includes historical snapshots.
- Add rate limiting at the Ingress or application level to protect against abuse.
- Consider read replicas or caching (Redis) if query volume grows significantly.
