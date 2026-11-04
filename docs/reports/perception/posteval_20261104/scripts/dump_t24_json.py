# -*- coding: utf-8 -*-
"""Dump the PROPOSED consumer requirement contract and the old-result usage
register to JSON (lightweight, no inference)."""
import json, hashlib
from pathlib import Path
ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / "docs/reports/perception/posteval_20261104"
from sys import path as _p
_p.insert(0, str(ROOT / "src"))
from boom_birds.evaluation.landmark_posteval import consumer_requirements

req = consumer_requirements()
req["created_at"] = "2026-11-04"
req["evidence_hashes"] = {
    "posteval_report": hashlib.sha256((OUT/"POSTEVAL_DIAGNOSIS_20261104.md").read_bytes()).hexdigest() if (OUT/"POSTEVAL_DIAGNOSIS_20261104.md").is_file() else None,
    "identity_analysis": hashlib.sha256((OUT/"MS1_IDENTITY_ANALYSIS_20261104.json").read_bytes()).hexdigest() if (OUT/"MS1_IDENTITY_ANALYSIS_20261104.json").is_file() else None,
}
(OUT/"CONSUMER_REQUIREMENT_20261104.json").write_text(json.dumps(req, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")

register = {
  "schema_version": "dsh.landmark_old_result_usage_register.v1",
  "created_at": "2026-11-04",
  "status": "REGISTRY_ONLY_NO_OLD_FILE_CHANGED",
  "principle": "old results/protocols/hashes are append-only; this registry records allowed use, forbidden use and errata notes for future citations without rewriting history",
  "entries": [
    {"result": "presence P1.000/R0.916 (final exploratory)", "old_scope": "279 frames, TP218/FP0/FN20/TN41",
     "allowed": ["exploratory evidence", "failure-decomposition entry"], "forbidden": ["certification/final capability", "cross-distribution extrapolation"],
     "errata_note": "cite as exploratory, single-shot, not sealed"},
    {"result": "reference coverage 62/218=0.284", "old_scope": "available-reference denominator",
     "allowed": ["exploratory diagnosis"], "forbidden": ["localization capability", "consumer usability rate"],
     "errata_note": "denominator is available-reference positives 218, not all positives 238"},
    {"result": "joint 71/238=0.298", "old_scope": "legacy composite",
     "allowed": ["historical comparison"], "forbidden": ["localization rate", "consumer metric"],
     "errata_note": "numerators include 9 CORRECT_REFUSAL; split LOCALIZED 62/218 + REFUSAL 9/20"},
    {"result": "anchor correct-subset 1.95px / bearing 0.30deg", "old_scope": "conditional on 62/181 successful emissions",
     "allowed": ["same-source reproducibility evidence"], "forbidden": ["unconditional physical accuracy", "certification"],
     "errata_note": "conditional statistic; GT and model cue are same-source; all-emitted 3.72px/0.546deg"},
    {"result": "identity P1.000 (claims 218)", "old_scope": "single class, no verified similar-structure negative in pool",
     "allowed": ["exploratory diagnosis"], "forbidden": ["identity capability/certification", "unconditional single-class mapping to central tower"],
     "errata_note": "precision denominator claims; recall denominator positives 238; identity only UNKNOWN/appearance-gated"},
    {"result": "TINY coverage 1/15, TINY recall 19/34", "old_scope": "final exploratory",
     "allowed": ["exploratory diagnosis"], "forbidden": ["certification denominator", "TINY as evaluable class"],
     "errata_note": "GT relies on PROJECTION_AID_CALIBRATED; current sample/method unannotatable (posteval section 4)"},
    {"result": "3px 2D pass rate", "old_scope": "historical 2D proxy",
     "allowed": ["legacy diagnosis"], "forbidden": ["consumer bearing capability"],
     "errata_note": "3px approx 1.074deg; 87 emitted frames fail 3px but pass bearing; consumer quantity is image bearing"},
    {"result": "GT_UNOBSERVABLE=0 / model UNKNOWN=0 (final pool)", "old_scope": "branches not exercised",
     "allowed": ["coverage-limitation evidence"], "forbidden": ["claiming the branches are verified"],
     "errata_note": "rules implemented/tested but not exercised by that pool; INCOMPLETE"},
    {"result": "old eval_onnx numbers (joint 4/95 etc.)", "old_scope": "raw/no-NMS ONNX path",
     "allowed": ["historical error case"], "forbidden": ["any model evidence"],
     "errata_note": "already errata: D1 no NMS / D2 rect-square mismatch / D3 predictor not reproduced; numbers invalid"},
    {"result": "candidate A/B improvement (0.453/0.400 vs 0.379)", "old_scope": "matched validation pilot",
     "allowed": ["negative result / STOP evidence"], "forbidden": ["new baseline", "restart tuning basis"],
     "errata_note": "gate not met, holdout NOT_TRIGGERED; do not restart from TINY/MS1 new evidence"},
    {"result": "old exploratory reused in v4.1 train", "old_scope": "DEVELOPMENT_TRAIN",
     "allowed": ["development training evidence chain"], "forbidden": ["final/sealed/independent test"],
     "errata_note": "exposure registry v2 records the reuse; must declare when cited"},
    {"result": "posteval TINY annotatability (0.364/0.434)", "old_scope": "22 development blind frames",
     "allowed": ["applicability-domain / data-strategy basis"], "forbidden": ["extrapolate to 4-8px or final TINY scale"],
     "errata_note": "always cite 'current sample/method' qualifier"},
    {"result": "posteval appearance gate (aspect 0.50 / rel_y 0.18)", "old_scope": "62 development identity frames",
     "allowed": ["PROPOSED basis"], "forbidden": ["freeze/deploy/certify directly"],
     "errata_note": "needs new untouched preregistered data; not tunable on this pool"},
  ],
  "errata_note_suggestions": [
    "cite the old final metrics with denominators + exploratory qualifier",
    "cite TINY/3px old numbers with projection-prior/legacy-proxy notes",
    "identity must not be cited as capability",
    "old eval_onnx numbers remain an invalid error case",
    "aggregate these notes into CURRENT_STATUS or a separate ERRATA file only if lead asks; old files unchanged",
  ],
}
(OUT/"OLD_RESULT_USAGE_REGISTER_20261104.json").write_text(json.dumps(register, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
print(json.dumps({"consumer_status": req["status"], "items": list(req["items"]), "register_entries": len(register["entries"])}, ensure_ascii=False))
