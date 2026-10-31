"""Offline fixture preparation. Run from backend, then generate_proposal_audio.ps1."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pydantic import TypeAdapter
from app.providers.proposal_notice import proposal_text
from app.schemas.identity import ChangeProposalWrite
from app.schemas.health import MedicationPlan

directory = Path(__file__).resolve().parent
cases = json.loads((directory / "proposal_cases.json").read_text(encoding="utf-8"))
rows = []
for case in cases:
    body = TypeAdapter(ChangeProposalWrite).validate_python(case["body"])
    plan = MedicationPlan.model_validate(case["plan"]) if "plan" in case else None
    rows.append({"fixture_id": case["fixture_id"], "file": case["fixture_id"] + ".wav",
                 "text": proposal_text(body, plan=plan)})
(directory / "proposal_manifest.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
