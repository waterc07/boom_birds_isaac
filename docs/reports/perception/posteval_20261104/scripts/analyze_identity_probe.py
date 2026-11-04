# -*- coding: utf-8 -*-
"""Analyze the single-network identity probe on the 62 development identity frames."""
import json, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parents[5]
def load(p): return json.loads((ROOT / p).read_text(encoding="utf-8"))
labels = load("outputs/perception/dev_annotations_20261104/labels_identity_dev.json")
by_id = {a["frame_id"]: a for a in labels["annotations"]}

def iou(a, b):
    if not a or not b: return 0.0
    ax, ay, aw, ah = a; bx, by, bw, bh = b
    x1, y1 = max(ax,bx), max(ay,by); x2, y2 = min(ax+aw,bx+bw), min(ay+ah,by+bh)
    if x2 <= x1 or y2 <= y1: return 0.0
    inter = (x2-x1)*(y2-y1)
    return inter/(aw*ah + bw*bh - inter)

def analyze(path, tag):
    rows = [json.loads(l) for l in (ROOT/path).read_text(encoding="utf-8").splitlines() if l.strip()]
    out = []
    for row in rows:
        a = by_id.get(row["frame_id"]); o = row.get("observation") or {}
        if a is None: continue
        target = a.get("target") or {}; geo = a.get("geometry") or {}
        present = target.get("present") is True; undec = target.get("undecidable") is True
        gt_box = geo.get("bbox_xywh") if present else None
        confs = (a.get("confusers") or [])
        ms1 = None
        for c in confs:
            if "MS1" in (c.get("confuser_id") or "") or "PILLAR" in (c.get("confuser_id") or "").upper():
                ms1 = c; break
        if ms1 is None and confs: ms1 = confs[0]
        pred_box = o.get("bbox_xywh")
        iou_target = iou(pred_box, gt_box) if gt_box and pred_box else None
        iou_ms1 = (iou(pred_box, ms1.get("bbox_xywh")) if ms1 and ms1.get("bbox_xywh") and pred_box else None)
        scores = [c.get("score") for c in (o.get("candidates") or [])]
        scores.sort(reverse=True)
        margin = (scores[0]-scores[1]) if len(scores) >= 2 else None
        kind = (a.get("source") or {}).get("family","").replace("fam_lmf_devid_","")
        out.append({
            "frame_id": row["frame_id"], "kind": kind, "present": present, "gt_unobservable": undec,
            "has_ms1": ms1 is not None, "ms1_box": (ms1.get("bbox_xywh") if ms1 else None),
            "status": o.get("status"), "claimed": o.get("landmark_id") is not None,
            "landmark_id": o.get("landmark_id"), "candidate_count": o.get("candidate_count"),
            "scores": scores, "margin": margin, "reject": o.get("reject_reason"),
            "pred_box": pred_box, "iou_target": iou_target, "iou_ms1": iou_ms1,
            "kpt": o.get("keypoint_px"), "kpt_conf": o.get("keypoint_confidence"),
            "matches_target": bool(iou_target is not None and iou_target >= 0.3),
            "matches_ms1": bool(iou_ms1 is not None and iou_ms1 >= 0.3),
        })
    print("===", tag, len(out))
    for kind in sorted(set(r["kind"] for r in out)):
        g = [r for r in out if r["kind"] == kind]
        det = [r for r in g if r["status"] == "DETECTED"]
        claims = [r for r in g if r["claimed"]]
        print(" ", kind, "n", len(g), "det", len(det), "claims", len(claims),
              "match_target", sum(1 for r in g if r["matches_target"]),
              "match_ms1", sum(1 for r in g if r["matches_ms1"]),
              "false_identity(claim on absent)", sum(1 for r in claims if not r["present"] and not r["gt_unobservable"]),
              "claims_on_gt_unobs", sum(1 for r in claims if r["gt_unobservable"]))
        for r in g:
            print("    ", r["frame_id"], "status", r["status"], "claim", r["claimed"], "cand", r["candidate_count"],
                  "scores", [round(s,3) for s in r["scores"]], "iouT", (round(r["iou_target"],2) if r["iou_target"] is not None else None),
                  "iouM", (round(r["iou_ms1"],2) if r["iou_ms1"] is not None else None), "reject", r["reject"])
    return out

frozen = analyze("docs/reports/perception/posteval_20261104/identity_probe_frozen/predictions.jsonl", "FROZEN 0.605476")
raw = analyze("docs/reports/perception/posteval_20261104/identity_probe_raw/predictions.jsonl", "RAW 0.25")

# inner_north saved predictions: old frozen vs improvement v4 baseline
def inner(path, tag):
    rows = [json.loads(l) for l in (ROOT/path).read_text(encoding="utf-8").splitlines() if l.strip()]
    inner = [r for r in rows if "inner_north" in r["frame_id"]]
    print("===", tag, "inner_north", len(inner))
    print("  status", collections.Counter((r.get("observation") or {}).get("status") for r in inner),
          "cand", collections.Counter((r.get("observation") or {}).get("candidate_count") for r in inner),
          "claims", sum(1 for r in inner if (r.get("observation") or {}).get("landmark_id")),
          "reject", collections.Counter((r.get("observation") or {}).get("reject_reason") for r in inner))
    for r in inner:
        o = r.get("observation") or {}
        if (o.get("candidate_count") or 0) >= 2:
            print("  MULTI", r["frame_id"], "scores", [round(c.get("score",0),3) for c in o.get("candidates") or []],
                  "bboxes", [c.get("bbox_xywh") for c in o.get("candidates") or []], "reject", o.get("reject_reason"),
                  "claimed", o.get("landmark_id") is not None)
inner("outputs/landmark_train/runs/bounded_v2/seed1/eval_last/predictions.jsonl", "OLD FROZEN seed1 eval_last (tau 0.25)")
inner("outputs/landmark_train/runs/improvement_v4/baseline_seed0/eval_last/predictions.jsonl", "IMPROVEMENT v4 baseline eval_last (tau 0.25)")
