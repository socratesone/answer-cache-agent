"""Write JSON Schema for every public contract into schemas/ so the surrounding app can generate types."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from answer_cache_agent import contracts

OUT = Path(__file__).resolve().parents[1] / "schemas"
PUBLIC = ["Event", "PrepareFormPayload", "GenerateInitialPayload", "GetCandidatePayload", "RegenerateQuestionPayload",
          "RecordFeedbackPayload", "Result", "CandidateOut", "GenerationOutput", "DiagnosisOutput"]

OUT.mkdir(exist_ok=True)
for name in PUBLIC:
    model = getattr(contracts, name)
    (OUT / f"{name}.schema.json").write_text(json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n")
print(f"wrote {len(PUBLIC)} schemas to {OUT}")
