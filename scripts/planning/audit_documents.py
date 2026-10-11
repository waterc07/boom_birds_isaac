"""Check current planning links, arithmetic anchors and source hashes; no flight acceptance."""
import hashlib
import json
import math
import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
FILES = [ROOT / "README.md", ROOT / "PROJECT_PLAN.md"]
FILES += sorted((ROOT / "docs/design").glob("*.md"))
FILES += sorted((ROOT / "docs/decisions").glob("*.md"))
FILES += [ROOT / p for p in (
    "docs/planning/01_INPUTS_AND_GATES.md",
    "docs/planning/04_RM_FIELD_AND_VISION.md",
    "docs/planning/05_GOAL_MODE_PROMPT.md",
    "docs/planning/06_FEASIBILITY_BUDGETS.md",
    "docs/planning/07_SOURCE_REGISTER.md",
    "docs/planning/08_TASK_ACCEPTANCE_PROTOCOL.md",
    "docs/planning/09_TARGET_TEAM_AND_INTERCEPTION.md",
    "docs/planning/10_CURRENT_FACTS_AND_ANALYSIS_20261011.md",
    "docs/reports/PLANNING_ACCEPTANCE.md",
    "docs/research/04_REPORT_REVIEW_20261009.md",
    "docs/superpowers/plans/2026-10-09-phase0-baseline.md",
    "docs/superpowers/plans/2026-10-11-p0-p1-foundation.md",
)]


if __name__ == "__main__":
    errors, local_links = [], 0
    for file in FILES:
        if not file.exists():
            errors.append(f"missing required file: {file}")
            continue
        content = file.read_text(encoding="utf-8-sig")
        for target in re.findall(r"\[[^\]]*\]\(([^\n]+?)\)", content):
            if re.match(r"(?:https?://|#|app://)", target):
                continue
            target = unquote(target.split("#", 1)[0].strip("<>"))
            local_links += 1
            if not (file.parent / target).resolve().exists():
                errors.append(f"{file.relative_to(ROOT)} -> {target}")
    budget = json.loads((ROOT / "docs/planning/budget_results.json").read_text(encoding="utf-8"))
    checks = {
        "360 scenarios": len(budget["pixel_sweep"]) == 360,
        "120mm mass 175.5g": budget["mass"][1]["max_mass_g"] == 175.5,
        "118mm mass 177.95g": budget["mass"][0]["max_mass_g"] == 177.95,
        "velocity+yaw_rate mask 0x5C7": budget["velocity_yaw_rate_type_mask"] == 0x5C7,
        "one mps roundtrip 41s": budget["flight_time"][1]["round_trip_s"] == 41,
        "two mps roundtrip 27s": budget["flight_time"][3]["round_trip_s"] == 27,
        "14m stereo error approx 1.5844m": math.isclose(budget["stereo"][-1]["first_order_depth_sigma_m"], 1.5844, abs_tol=0.00001),
        "all pixel entries finite positive": all(math.isfinite(x["projected_width_px"]) and x["projected_width_px"] > 0 for x in budget["pixel_sweep"]),
    }
    errors += [f"arithmetic check: {k}" for k, passed in checks.items() if not passed]
    intercept = json.loads((ROOT / "docs/planning/interception_budget.json").read_text(encoding="utf-8"))
    case = next(x for x in intercept["scenarios"] if x["speed_mps_assumed"] == 16.5 and x["distance_m"] == 5)
    additional = {
        "42.5mm at 5m approx 7.769px": math.isclose(case["pixel_diameter_px"], 7.769125, abs_tol=0.00001),
        "5m at 16.5mps approx 303ms": math.isclose(case["constant_speed_remaining_s"], 0.3030303, abs_tol=0.000001),
        "0.5m from rest at assumed 2mps2 approx 707ms": math.isclose(intercept["translation_example"]["from_rest_min_motion_s"], 0.70710678, abs_tol=0.000001),
    }
    checks.update(additional)
    errors += [f"arithmetic check: {k}" for k, passed in additional.items() if not passed]
    source_hashes = {}
    for folder, manifest, key in (
        ("docs/references/field_research_20261009", "sources.json", "sources"),
        ("docs/references/handoff_20261009", "snapshot_sources.json", None),
    ):
        base = ROOT / folder
        entries = json.loads((base / manifest).read_text(encoding="utf-8-sig"))
        if key:
            entries = entries[key]
        for entry in entries:
            file = base / entry.get("file", entry.get("path"))
            observed = hashlib.sha256(file.read_bytes()).hexdigest()
            passed = observed == entry["sha256"].lower()
            source_hashes[str(file.relative_to(ROOT))] = passed
            if not passed:
                errors.append(f"source hash changed: {file}")
    result = {
        "scope": "Current planning links (existence), fixed arithmetic anchors and local source hash integrity. No semantic/source applicability/flight proof.",
        "files_checked": len(FILES), "local_links_checked": local_links,
        "checks": checks, "errors": errors,
        "source_hash_checks": source_hashes,
        "status": "PASS" if not errors else "FAIL",
        "file_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in FILES if p.exists()},
    }
    out = ROOT / "docs/reports/planning_audit.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "file_sha256"}, ensure_ascii=False, indent=2))
    raise SystemExit(1 if errors else 0)
