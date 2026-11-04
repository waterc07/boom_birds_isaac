# -*- coding: utf-8 -*-
"""Combine the single-network identity probe, appearance-feature separability and
saved inner_north prediction evidence into one analysis JSON."""
import json, hashlib, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / "docs/reports/perception/posteval_20261104"

def load(p): return json.loads((ROOT / p).read_text(encoding="utf-8"))
def loadl(p): return [json.loads(l) for l in (ROOT / p).read_text(encoding="utf-8").splitlines() if l.strip()]
def sha(p): return hashlib.sha256((ROOT / p).read_bytes()).hexdigest()

labels = load("outputs/perception/dev_annotations_20261104/labels_identity_dev.json")
by_id = {a["frame_id"]: a for a in labels["annotations"]}
features = load("docs/reports/perception/posteval_20261104/IDENTITY_APPEARANCE_FEATURES_20261104.json")

def iou(a, b):
    if not a or not b: return 0.0
    ax, ay, aw, ah = a; bx, by, bw, bh = b
    x1, y1 = max(ax,bx), max(ay,by); x2, y2 = min(ax+aw,bx+bw), min(ay+ah,by+bh)
    if x2 <= x1 or y2 <= y1: return 0.0
    inter = (x2-x1)*(y2-y1)
    return inter/(aw*ah + bw*bh - inter)

def probe(path):
    rows = loadl(path); cases = collections.defaultdict(lambda: {"n":0,"detected":0,"claimed":0,
        "claim_on_absent":0,"claim_on_gt_unobservable":0,"match_target":0,"match_ms1":0,"multi_candidate":0})
    per_frame = []
    for row in rows:
        a = by_id.get(row["frame_id"]); o = row.get("observation") or {}
        if a is None: continue
        target = a.get("target") or {}; geo = a.get("geometry") or {}
        present = target.get("present") is True; undec = target.get("undecidable") is True
        gt_box = geo.get("bbox_xywh") if present else None
        ms1 = None
        for c in (a.get("confusers") or []):
            if c.get("bbox_xywh"): ms1 = c; break
        pred_box = o.get("bbox_xywh")
        iou_t = iou(pred_box, gt_box) if gt_box and pred_box else None
        iou_m = (iou(pred_box, ms1["bbox_xywh"]) if ms1 and pred_box else None)
        claimed = o.get("landmark_id") is not None
        case = (a.get("source") or {}).get("family","").replace("fam_lmf_devid_","")
        d = cases[case]; d["n"] += 1
        if o.get("status") == "DETECTED": d["detected"] += 1
        if claimed: d["claimed"] += 1
        if claimed and not present and not undec: d["claim_on_absent"] += 1
        if claimed and undec: d["claim_on_gt_unobservable"] += 1
        if iou_t is not None and iou_t >= 0.3: d["match_target"] += 1
        if iou_m is not None and iou_m >= 0.3: d["match_ms1"] += 1
        if (o.get("candidate_count") or 0) >= 2: d["multi_candidate"] += 1
        scores = sorted([c.get("score",0) for c in o.get("candidates") or []], reverse=True)
        per_frame.append({"frame_id": row["frame_id"], "case": case, "status": o.get("status"),
            "identity_claimed": claimed, "candidate_count": o.get("candidate_count"),
            "scores": scores, "iou_target": iou_t, "iou_ms1": iou_m,
            "reject_reason": o.get("reject_reason"),
            "gt_present": present, "gt_unobservable": undec})
    return {"path": path, "sha256": sha(path), "cases": dict(cases), "frames": per_frame}

frozen = probe("docs/reports/perception/posteval_20261104/identity_probe_frozen/predictions.jsonl")
raw = probe("docs/reports/perception/posteval_20261104/identity_probe_raw/predictions.jsonl")
frozen_metrics = load("docs/reports/perception/posteval_20261104/identity_probe_frozen/metrics.json")
raw_metrics = load("docs/reports/perception/posteval_20261104/identity_probe_raw/metrics.json")

def inner_summary(path):
    rows = [r for r in loadl(path) if "inner_north" in r["frame_id"]]
    out = {"path": path, "sha256": sha(path), "frames": len(rows),
           "status": dict(collections.Counter((r.get("observation") or {}).get("status") for r in rows)),
           "candidate_count": dict(collections.Counter((r.get("observation") or {}).get("candidate_count") for r in rows)),
           "claims": sum(1 for r in rows if (r.get("observation") or {}).get("landmark_id")),
           "reject_reason": {str(k): v for k, v in collections.Counter((r.get("observation") or {}).get("reject_reason") for r in rows).items()},
           "multi_candidate_frames": []}
    for r in rows:
        o = r.get("observation") or {}
        if (o.get("candidate_count") or 0) >= 2:
            scores = sorted([c.get("score",0) for c in o.get("candidates") or []], reverse=True)
            out["multi_candidate_frames"].append({"frame_id": r["frame_id"], "scores": scores,
                "margin": (scores[0]-scores[1]) if len(scores)>=2 else None,
                "bboxes": [c.get("bbox_xywh") for c in o.get("candidates") or []],
                "reject_reason": o.get("reject_reason"), "identity_claimed": o.get("landmark_id") is not None})
    return out

inner_old = inner_summary("outputs/landmark_train/runs/bounded_v2/seed1/eval_last/predictions.jsonl")
inner_v4 = inner_summary("outputs/landmark_train/runs/improvement_v4/baseline_seed0/eval_last/predictions.jsonl")

combined = features["combined_gate"]
aspect = features["feature_distributions"]["aspect_ratio"]
rely = features["feature_distributions"]["green_rel_y"]
result = {
  "schema_version": "dsh.landmark_ms1_identity_analysis.v1",
  "created_at": "2026-11-04",
  "status": "DEVELOPMENT_DIAGNOSIS_PROPOSED_NOT_FROZEN",
  "scope": "val_identity 62-frame development batch + saved inner_north predictions; image evidence only for identity reasoning",
  "inputs": {
    "identity_labels": {"path": "outputs/perception/dev_annotations_20261104/labels_identity_dev.json",
                        "sha256": sha("outputs/perception/dev_annotations_20261104/labels_identity_dev.json")},
    "frozen_model": {"path": "outputs/landmark_train/runs/bounded_v2/seed1/bounded_1/weights/last.pt",
                     "sha256": sha("outputs/landmark_train/runs/bounded_v2/seed1/bounded_1/weights/last.pt")},
    "appearance_features": "docs/reports/perception/posteval_20261104/IDENTITY_APPEARANCE_FEATURES_20261104.json",
  },
  "single_network_probe": {
    "description": "frozen single-class model run once over the 62 development identity frames; no training/retuning; results are dev evidence only",
    "frozen_thresholds": {"tau_det": 0.605476, "tau_conf": 0.605476, "tau_px": 3.0, "tau_iou": 0.3, "tau_margin": 0.1, "tau_kpt": 0.5},
    "raw_sensitivity": {"tau_det": 0.25, "tau_conf": 0.25, "note": "threshold-sensitivity probe, not the frozen operating point"},
    "frozen": {"metrics": frozen_metrics["overall"], "cases": frozen["cases"], "frames": frozen["frames"]},
    "raw": {"metrics": raw_metrics["overall"], "cases": raw["cases"], "frames": raw["frames"]},
    "inner_north_saved_predictions": {"old_frozen_seed1": inner_old, "improvement_v4_baseline": inner_v4},
  },
  "appearance_features": {
    "denominators": features["denominators"],
    "aspect_ratio": aspect,
    "green_rel_y": rely,
    "green_rel_x": features["feature_distributions"]["green_rel_x"],
    "axis_symmetry": features["feature_distributions"]["axis_symmetry"],
    "top_body_width_ratio": features["feature_distributions"]["top_body_width_ratio"],
    "green_area_px": features["feature_distributions"]["green_area_px"],
    "green_area_vs_distance_loglog": features["green_area_vs_distance_loglog"],
    "per_case_aspect_and_rel_y": features["per_case_aspect_and_rel_y"],
    "combined_gate": combined,
    "gate_tables": {"aspect_ratio": features["single_feature_gates"]["aspect_ratio"],
                    "green_rel_y": features["single_feature_gates"]["green_rel_y"]},
    "zero_false_identity_upper_bound_95": features["zero_false_identity_upper_bound_95"],
    "feature_compute_benchmark": features["feature_compute_benchmark"],
  },
  "verdicts": {
    "single_network_sufficient_for_identity": "NO / UNPROVEN",
    "single_network_reasons": [
      "the network output is class tower + one keypoint; it has no identity channel, appearance_check=NOT_EVALUATED and landmark_id is claimed from single-candidate score/margin only",
      "frozen model produced 0 false identity claims on 9 MS1-alone frames (0/9; 95% one-sided upper bound 28.3%) and 0 claims on 9 GT-unobservable frames; this bounds the observed dev error, it does not establish identity capability",
      "the retrained v4 baseline detected MS1 as a second candidate in 1/30 inner_north frames (scores 0.792/0.411, margin 0.381 > tau_margin 0.1, target top1) - the network can represent MS1; suppression relies on score margin and view distribution, not identity reasoning",
      "in matched-scale both-visible frames the frozen model detected only the target (candidate_count=1) and never the MS1 object, while under-detecting the target in 9/9 same-bearing frames at the frozen threshold - behaviour is threshold/view dependent",
    ],
    "appearance_gate_feasible": "YES on this development sample (PROPOSED_NOT_FROZEN)",
    "appearance_gate_rule": "identity ACCEPT only if bbox aspect_ratio >= 0.50; if a reference keypoint is emitted also require green_rel_y >= 0.18; otherwise UNKNOWN (never silently map to the central tower)",
    "appearance_gate_denominators": {"target_objects": 44, "ms1_objects": 35, "target_objects_with_reference": 18, "ms1_objects_with_reference": 26},
    "appearance_gate_cost_on_dev": combined,
    "carrying_cues": {
      "bbox_aspect_ratio": "target 0.632-1.778 (median 1.461) vs MS1 0.201-0.438 (median 0.326); AUC 1.0; threshold 0.50 gives 0 false-block / 0 miss-block on 44/35 objects",
      "green_rel_y": "target 0.212-0.396 (median 0.242) vs MS1 0.062-0.122 (median 0.093); AUC 1.0; threshold 0.18 separates; only measurable when the reference keypoint is emitted (44 objects -> 18 target / 26 MS1)",
      "green_rel_x": "overlapping (target/reference vs MS1) -> NOT a gate cue",
      "axis_symmetry": "overlapping (target median 0.65 vs MS1 0.43, ranges 0.17-1.0 vs 0.0-0.95) -> weak, not a gate cue alone",
      "top_body_width_ratio": "overlapping and segmentation-sensitive (AUC 0.56) -> not recommended until a verified measurement exists",
      "green_area_px": "overlapping and range-confounded (target slope -2.46 vs MS1 -1.81 in log-log, R2 0.94/0.78); cannot be used without range, and the consumer has no range",
    },
    "compute_cost": "gate needs the bbox only (aspect) plus the reference keypoint plus the already-computed strict-green component; host pure-python feature extraction 0.072-0.185 s/frame for 320x240 (cached green components lower this); RK3576 board cost UNKNOWN (no board test)",
    "cost_of_errors": {
      "false_block (target rejected)": "identity becomes UNKNOWN; landmark relay loses one visibility fix (availability cost, recoverable by the next frame; no safety violation)",
      "miss_block (MS1 accepted)": "false landmark/region hypothesis; violates the V2.2 consumer guardrail (identity false match worse than miss); safety-relevant",
      "design choice": "prefer false-block over miss-block; gate must never claim identity when the reference point is unavailable",
    },
    "applicability_domain": [
      "development identity batch only: 320x240 synthetic RGB, one Isaac asset/session, 7 cases, 62 annotated frames, agent-proxy labels",
      "not valid below ~20 px bbox height (the TINY blind test showed 9-14 px targets are not reliably annotatable) -> identity UNKNOWN there",
      "MS1 verification is map-native (WORLD_POSE_OR_MAP_DB); MS2 symmetric candidate appearance UNKNOWN; real-arena confuser distribution UNKNOWN",
      "no certification, no holdout, no board/real-camera claim; gate thresholds are PROPOSED and need new untouched data to freeze",
    ],
  },
  "boundaries": ["internal bounded research only", "no control/PPO/Gate promotion", "old results unchanged",
                 "image evidence only for identity; map positions used only to normalise the green-area/range relation"],
}
(OUT/"MS1_IDENTITY_ANALYSIS_20261104.json").write_text(json.dumps(result, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
print(json.dumps({"wrote": "MS1_IDENTITY_ANALYSIS_20261104.json",
                  "frozen_metrics": {k: frozen_metrics["overall"]["presence"][k] for k in ("tp","fp","fn","tn")},
                  "frozen_joint": frozen_metrics["overall"]["joint"]["narrow_rate"],
                  "raw_joint": raw_metrics["overall"]["joint"]["narrow_rate"],
                  "gate": combined}, ensure_ascii=False))
