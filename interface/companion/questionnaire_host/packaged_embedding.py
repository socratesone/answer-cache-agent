"""Load the engine's chosen local embedder from installer assets, without a runtime download."""
from pathlib import Path
from answer_cache_agent.embeddings import FastEmbedEmbedder

class PackagedEmbedder(FastEmbedEmbedder):
    def __init__(self, model_name: str, directory: Path):
        from fastembed import TextEmbedding
        if not directory.is_dir():
            raise RuntimeError("Packaged embedding model missing; repair the installation")
        self._model = TextEmbedding(model_name=model_name, specific_model_path=str(directory), local_files_only=True)
        self.model_id = model_name
        self.dim = len(next(iter(self._model.embed(["dim probe"]))))
