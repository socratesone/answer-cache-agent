"""Release-build step: download once into isolated build assets and preserve model license."""
from pathlib import Path
import shutil
from fastembed import TextEmbedding
from answer_cache_agent.config import load_config

root = Path(__file__).resolve().parents[1]
model = TextEmbedding(load_config().retrieval.embedding_model, cache_dir=str(root / "artifacts" / "model-cache"))
# FastEmbed exposes the concrete local model directory on its selected implementation.
source = Path(model.model._model_dir)
target = root / "artifacts" / "embedding-model"
shutil.copytree(source, target, dirs_exist_ok=True)
assert any(target.rglob("*.onnx")), "Embedding assets missing"
# Verify the bundled path works without download access before allowing packaging.
offline = TextEmbedding(load_config().retrieval.embedding_model, specific_model_path=str(target), local_files_only=True)
assert len(next(iter(offline.embed(["synthetic packaging verification"])))) > 0

# Preserve the model publisher's license; fail the release build if it cannot be retrieved.
# Review this source again if the engine changes the configured embedding model.
from urllib.request import urlopen
import hashlib
import json
if load_config().retrieval.embedding_model != "BAAI/bge-small-en-v1.5":
    raise RuntimeError("Review model license provenance for the newly configured model")
license_url = "https://raw.githubusercontent.com/FlagOpen/FlagEmbedding/master/LICENSE"
with urlopen(license_url, timeout=30) as response:
    license_text = response.read()
if b"MIT License" not in license_text:
    raise RuntimeError("Unexpected model license: review before release")
(target / "LICENSE.FlagEmbedding").write_bytes(license_text)
(root / "artifacts" / "model-provenance.json").write_text(json.dumps({
    "model": load_config().retrieval.embedding_model,
    "license_source": license_url,
    "files": {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest() for p in target.rglob("*") if p.is_file()}
}, indent=2))
