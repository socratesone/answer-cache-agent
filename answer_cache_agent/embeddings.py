"""Embedder protocol plus the deterministic test embedder and the v1 local ONNX embedder."""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, runtime_checkable

_TOKEN = re.compile(r"[a-z0-9]+")


@runtime_checkable
class Embedder(Protocol):
    model_id: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Offline bag-of-hashed-tokens embedder for tests. Lexical overlap only, no semantics."""

    def __init__(self, dim: int = 1024) -> None:
        self.model_id = f"hash-{dim}"
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dim
            for tok in _TOKEN.findall(text.lower()):
                h = int(hashlib.blake2b(tok.encode(), digest_size=4).hexdigest(), 16)
                vec[h % self.dim] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class FastEmbedEmbedder:
    """Local ONNX embeddings via fastembed; the model downloads once and runs offline after."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name)
        self.model_id = model_name
        self.dim = len(next(iter(self._model.embed(["dim probe"]))))

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.embed(texts)]
