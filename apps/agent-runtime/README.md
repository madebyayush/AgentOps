# AgentOps Agent Runtime Service
Asynchronous execution engine for AgentOps multi-agent networks.

---

## Phase 2 — Agent Execution Engine (LangGraph)

### Architecture
- **State machine**: LangGraph `StateGraph` with `AgentState` TypedDict
- **Nodes**: `memory_retrieval → planner → tool_executor → reflection → [advance_step | hitl_checkpoint | output]`
- **Conditional routing**: `reflection_router` implements `continue | retry | escalate_hitl | abort`
- **Checkpointing**: `AsyncSqliteSaver` (dev) / `AsyncPostgresSaver` (prod)

### Key files
| File | Purpose |
|------|---------|
| `agent/state.py` | `AgentState` TypedDict — shared graph state |
| `agent/nodes.py` | All LangGraph node functions |
| `agent/graph.py` | Graph builder + checkpointer factory |
| `agent/base.py` | `BaseAgent` abstract class |
| `agent/tools/` | `BaseTool`, `ToolRegistry`, and built-in tools |

### Phase 2 Test Results (80 tests)
- ReAct loop execution — ✅
- Reflection retries (MAX_RETRIES=3) — ✅
- State transitions for all nodes — ✅
- LangGraph edge routing — ✅
- Checkpoint recovery (SQLite) — ✅
- Failure handling / abort paths — ✅

---

## Phase 3 — Memory Subsystem

### Architecture
Four-tier memory system, all tiers activate via environment variables:

| Tier | Backend | Env var | Key Pattern |
|------|---------|---------|-------------|
| **Semantic** (long-term) | Pinecone + OpenAI embeddings | `PINECONE_API_KEY`, `OPENAI_API_KEY` | `nexus-{agent_name}` (namespace) |
| **Episodic** (short-term) | Redis Lists + Streams | `REDIS_URL` | `nexus:episodic:{agent_id}:{session_id}` |
| **Working** (run state) | Redis + orjson | `REDIS_URL` | `nexus:state:{run_id}` |
| **Procedural** (tool stats) | PostgreSQL + asyncpg | `POSTGRES_URL` | `tool_registry` table |

### New files (Phase 3)
| File | Purpose |
|------|---------|
| `agent/memory/embeddings.py` | `EmbeddingModel` — OpenAI `text-embedding-3-small` + deterministic stub |
| `agent/memory/semantic.py` | `SemanticMemory` — Pinecone real client + cosine-similarity InMemory stub |
| `agent/memory/reranker.py` | `CrossEncoderReranker` — Cohere real + score-aware passthrough stub |
| `agent/memory/episodic.py` | `EpisodicMemory` — Redis LPUSH/LTRIM + Redis Streams |
| `agent/memory/working.py` | `WorkingMemory` — orjson AgentState snapshots in Redis |
| `agent/memory/procedural.py` | `ProceduralMemory` — asyncpg PostgreSQL + in-memory fallback |
| `agent/memory/__init__.py` | Sub-package re-exports + `MemoryClient` backward-compat shim |

### RAG Pipeline (Step 3.1)
1. `SemanticMemory.recall()` → top-10 chunks by cosine similarity
2. `CrossEncoderReranker.rerank()` → top-5 by relevance (Cohere / score-passthrough)
3. Injected into `state["memory_context"]` as `=== RELEVANT CONTEXT ===` block
4. Citation chunk IDs stored in `state["memory_citations"]` for auditability

### Auto-disable Policy (Step 3.4)
`ProceduralMemory.auto_disable_check()` runs after every agent cycle:
- Minimum sample: **10 calls** required before evaluation
- Threshold: **error_rate > 30%** → `tool_registry.enabled = FALSE`
- Operator alert logged with tool name, error rate, call counts

### Stub / Real client pattern
All four tiers use the same interface for stub and real clients. Activation:
```bash
export OPENAI_API_KEY=sk-...        # enables real embeddings
export PINECONE_API_KEY=...         # enables Pinecone vector store
export COHERE_API_KEY=...           # enables Cohere reranking
export POSTGRES_URL=postgresql://...# enables PostgreSQL tool registry
export REDIS_URL=redis://...        # enables episodic + working memory
```
Without any keys, all stubs engage — the full RAG pipeline still executes offline.

### Phase 3 Test Results (150 tests, 3 Postgres skipped locally)
- EmbeddingModel: unit vector dim, determinism, batch — ✅
- InMemoryVectorStore: cosine similarity, ranking, filter, namespace isolation — ✅
- SemanticMemory: remember/recall/forget, metadata, citations, RAG context — ✅
- CrossEncoderReranker: score-order, top_k, empty input — ✅
- Full RAG pipeline: end-to-end remember → recall → rerank → context — ✅
- EpisodicMemory: push/load, LTRIM, session isolation, Streams — ✅
- WorkingMemory: save/load, TTL, delete, run isolation — ✅
- ProceduralMemory: register, record_call, auto_disable_check — ✅
- PostgreSQL integration tests: run in CI with real Postgres 16 service — ✅ (CI only)

### Running tests locally
```bash
cd apps/agent-runtime
python -m pytest tests/ --asyncio-mode=auto -v
# 150 passed, 3 skipped (Postgres — run with POSTGRES_URL to include)
```
