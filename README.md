# AgentOps — Enterprise AI Orchestration Platform

AgentOps is an autonomous operating system for complex, enterprise-grade multi-agent workflows. It establishes a resilient architecture capable of orchestrating cognitive engines, managing episodic and semantic memory subsystems, enforcing role-based clearances, and executing dynamic tools safely.

---

## Repository Blueprint

```
AgentOps/
├── apps/
│   ├── ui/                  # React + Vite + TS Frontend (Sleek UI dashboard)
│   ├── api-gateway/         # FastAPI Main Gateway entrypoint
│   └── agent-runtime/       # Asynchronous Python execution loop
├── packages/
│   ├── shared-types/        # Pydantic + TypeScript shared schemas
│   ├── memory/              # Memory subsystems adapters (Qdrant, Pinecone, Redis)
│   ├── tools/               # registered actions registry and MCP adapters
│   ├── observability/       # OpenTelemetry traces SDK configurations (Jaeger)
│   └── security/            # Auth, RBAC clearances, and dynamic PII redaction
├── infra/
│   ├── docker/              # Multi-stage production Dockerfiles per service
│   ├── k8s/                 # Kubernetes Deployment, Service, and HPA descriptors
│   └── terraform/           # IaC modules mapping VPC network, RDS database, and ElastiCache
├── scripts/                 # PowerShell and shell environment bootstrapping utilities
├── tests/                   # End-to-end integration and endpoint unit tests
├── .env.example             # Exhaustive templates for third-party keys & database URIs
├── docker-compose.yml       # Local development stack (Postgres, Redis, Kafka, Qdrant, Jaeger, etc.)
└── README.md
```

---

## Local Development Stack

A complete multi-container developer setup is configured via `docker-compose.yml`.

### Services Configured
- **PostgreSQL (`port 5432`)**:Relational config & system audit logs storage.
- **Redis (`port 6379`)**: Episodic sliding memory window & cache store.
- **Qdrant (`port 6333`)**: Semantic long-term vector index memory.
- **Apache Kafka + Zookeeper (`port 9092`)**: Asynchronous distributed event bus.
- **Jaeger (`port 16686`)**: OpenTelemetry distributed traces viewer.
- **MinIO (`ports 9000/9001`)**: Local S3-compatible run artifact file store.
- **Prometheus & Grafana (`ports 9090/3000`)**: Telemetry metrics tracker & visualizer dashboards.

---

## Bootstrapping Environment

### Prerequisites
- Node.js (v20+)
- Python (3.11)
- Poetry dependencies manager
- Docker Desktop

### Quick Start (Windows PowerShell)
1. Initialize the monorepo setups:
   ```powershell
   .\scripts\setup-dev.ps1
   ```
2. Start the local containerized stack:
   ```bash
   docker compose up -d
   ```
3. Run the frontend UI and api servers in watch mode:
   ```bash
   npm run dev
   ```

---

## Quality Gatekeeping

### Pre-commit Hooks
The codebase is guarded with `pre-commit` hooks verifying code format and static types before commits can be completed:
- `black` for Python style formatting guidelines.
- `mypy` for static Python type checks.
- `prettier` for JSON, TS/JS, CSS, and Markdown styling.

Install the git hooks:
```bash
pip install pre-commit
pre-commit install
```

### Continuous Integration
A GitHub Actions workflow is fully configured in `.github/workflows/ci.yml` verifying lint formatting, executing unit tests, and building production containers on pull requests.
