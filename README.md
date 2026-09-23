# answer-cache-agent

> Stop answering the same questions from scratch.

> **Experimental.** This is a product of [The Agent Foundry Lab](https://github.com/socratesone), built by SocratesOne Development LLC. It is largely untested outside its own offline test suite and a single live provider run; expect rough edges, breaking changes, and gaps (see the [engine gap list](interface/docs/engine-gaps.md)). Do not rely on it for anything you cannot afford to redo by hand.

A LangGraph agent that turns a questionnaire's questions plus your own approved material into grounded answer *templates* — symbolic text with `{{variable}}` placeholders — ranks them by context, learns from what you pick, and keeps private values and provider keys out of every model request. Local-first: one SQLite file (data, vector index, checkpoints), local ONNX embeddings, your own OpenAI/Anthropic key.

## Repository layout

- `answer_cache_agent/` — the engine: a Python library plus the `answer-cache-agent` CLI. This README covers it.
- `interface/` — **Questionnaire Assistant**, the end-user product built on the engine: a Chrome MV3 extension and a Windows native-messaging companion. In progress; see [`interface/README.md`](interface/README.md) and the [engine gap list](interface/docs/engine-gaps.md) for what it can and cannot do yet.
- `docs/` — PRD, design decisions, architecture, integration guide, and the [interface contract](docs/interface-contract.md) for anyone building a UI or host on the engine.
- `schemas/` — the exported JSON Schema wire contract. `fixtures/` — synthetic demo data (no real people or organisations).

Built for the [Questionnaire Completion Agent PRD](docs/PRD.md). Design decisions: [`docs/design-review.md`](docs/design-review.md). How it works: [`docs/architecture.md`](docs/architecture.md). Integrating a UI or browser extension: [`docs/integration-guide.md`](docs/integration-guide.md). What was generated vs hand-built: [`docs/build-record.md`](docs/build-record.md).

## Install

```bash
pip install -e ".[dev]"
```

Python ≥ 3.10. The first real-embedder run downloads `BAAI/bge-small-en-v1.5` (~65 MB) once.

## Run the offline demo (no keys, no network)

```bash
answer-cache-agent --demo personal_application --db /tmp/demo.db
answer-cache-agent --demo org_questionnaire --db /tmp/demo2.db
```

Each replays a fixture: prepare a form (zero paid calls), generate two variants per question with a scripted model, serve the concise variant from cache, report exposure/selection, reject and regenerate, approve into a reusable template. Success marker: `ANSWER_CACHE_AGENT_DEMO_OK`.

## Run with real providers

```bash
export OPENAI_API_KEY=...            # and/or ANTHROPIC_API_KEY
answer-cache-agent fixtures/personal_application/events.jsonl \
  --db ~/.local/share/answer-cache/answer_cache.db \
  --scope me --ingest fixtures/personal_application/knowledge.jsonl \
  --bindings fixtures/personal_application/bindings.json \
  --routine openai:gpt-4o-mini --advanced anthropic:claude-sonnet-5 --json
```

Keys are read from the environment (a trusted runtime interface), never from event payloads.

## Import your own material

```bash
python -m answer_cache_agent.ingest my_records.jsonl --db answer_cache.db --scope me
```

One JSON record per line: `dimension`, `value`, `variable`, `evidence`, `template` (format in the integration guide §9). Templates and evidence require `approved_by`, `approved_at`, and `disclosure`. Variable *values* never go in this file.

## Verify

```bash
pytest -q                          # offline; no keys or model download
python scripts/spike_retrieval.py  # real embedder sanity check
python scripts/evaluate.py         # writes docs/evaluation-report.md (add --real for the fastembed model)
```

## Tunables

Everything adjustable lives in [`answer_cache_agent/config.yaml`](answer_cache_agent/config.yaml) and is validated on load (unknown keys rejected, ranking weights must sum to 1). Structural invariants — two initial variants, five targeted, zero paid calls on prepare/get/feedback, filters before scoring, generated text never becomes evidence, ledger before send — are in code on purpose.

## License

MIT.
