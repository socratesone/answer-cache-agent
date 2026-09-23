"""Narrow JSONL importer (Q10): validated records only, index updated in the same transaction as each insert."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from answer_cache_agent.repository import Repository


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DimensionRecord(_Strict):
    kind: Literal["dimension"]
    id: str
    label: str


class ValueRecord(_Strict):
    kind: Literal["value"]
    id: str
    dimension_id: str
    label: str


class VariableRecord(_Strict):
    kind: Literal["variable"]
    id: str
    safe_description: str
    value_type: str = "text"
    permitted_use: str = "verbatim"


class EvidenceRecord(_Strict):
    kind: Literal["evidence"]
    id: str
    locator: str
    version: str
    excerpt: str
    disclosure: Literal["model_visible", "local_only"]
    approved_by: str
    approved_at: str


class ContextAssignment(_Strict):
    dimension: str
    value: str
    mode: Literal["applies", "requires"] = "applies"


class TemplateRecord(_Strict):
    kind: Literal["template"]
    id: str
    intent: str
    aliases: list[str] = []
    body: str
    variables: list[str] = []
    evidence: list[str] = []
    context: list[ContextAssignment] = []
    disclosure: Literal["model_visible", "local_only"]
    approved_by: str
    approved_at: str


Record = Annotated[Union[DimensionRecord, ValueRecord, VariableRecord, EvidenceRecord, TemplateRecord], Field(discriminator="kind")]
_adapter = TypeAdapter(Record)


def ingest(repo: Repository, lines: Iterable[str]) -> Counter:
    """Apply records in file order; a bad line raises with its line number and nothing after it is applied."""
    counts: Counter = Counter()
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            rec = _adapter.validate_python(json.loads(line))
        except Exception as exc:
            raise ValueError(f"line {n}: {exc}") from exc
        if isinstance(rec, DimensionRecord):
            repo.add_dimension(rec.id, rec.label)
        elif isinstance(rec, ValueRecord):
            repo.add_value(rec.id, rec.dimension_id, rec.label)
        elif isinstance(rec, VariableRecord):
            repo.add_variable(rec.id, rec.safe_description, rec.value_type, rec.permitted_use)
        elif isinstance(rec, EvidenceRecord):
            repo.add_evidence(rec.id, rec.locator, rec.version, rec.excerpt, rec.disclosure, rec.approved_by, rec.approved_at)
        else:
            for a in rec.aliases:
                repo.add_intent_alias(rec.intent, a)
            repo.add_template(rec.id, rec.intent, rec.body, rec.variables, rec.evidence, rec.disclosure, rec.approved_by, rec.approved_at)
            repo.clear_assignments("template", rec.id)
            for cx in rec.context:
                repo.assign("template", rec.id, cx.value, cx.mode, "user")
        counts[rec.kind] += 1
    return counts


def main(argv=None) -> int:
    from answer_cache_agent.harness import open_repository

    p = argparse.ArgumentParser(description="Import knowledge records (JSONL) into the agent database.")
    p.add_argument("file")
    p.add_argument("--db", required=True)
    p.add_argument("--scope", default="default")
    p.add_argument("--hash-embedder", action="store_true", help="offline lexical embedder (tests/demo only)")
    a = p.parse_args(argv)
    repo = open_repository(a.db, a.scope, a.hash_embedder)
    with open(a.file, encoding="utf-8") as fh:
        counts = ingest(repo, fh)
    print(json.dumps(dict(counts)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
