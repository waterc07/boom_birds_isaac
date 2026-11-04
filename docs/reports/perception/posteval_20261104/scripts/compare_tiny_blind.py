# -*- coding: utf-8 -*-
"""Independent comparison of the TINY blind re-annotation with the frozen
development labels (diag side; annot did not compare)."""
import json, math, hashlib, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / "docs/reports/perception/posteval_20261104"
def load(p): return json.loads((ROOT / p).read_text(encoding="utf-8"))
key = load("docs/reports/perception/posteval_20261104/TINY_BLIND_REANNOTATION_KEY_20261104.json")
blind = load("docs/reports/perception/annotation_verify_20261104/labels_tiny_blind.json")
train = load("outputs/perception/dev_annotations_20261104/labels_train.json")
val = load("outputs/perception/dev_annotations_20261104/labels_val.json")
orig = {}
for doc in (train, val):
    for a in doc.get("annotations") or []:
        orig[a["frame_id"]] = a
blind_by = {a["frame_id"]: a for a in blind["annotations"]}

def bbox(a):
    b = ((a.get("target") or {}).get("present") is True) and (a.get("geometry") or {}).get("bbox_xywh")
    return b if b else None

def kpt(a):
    g = (a.get("geometry") or {}).get("keypoint")
    return [float(g["x"]), float(g["y"])] if g else None

def ref(a):
    return (a.get("geometry") or {}).get("reference_status") == "MANUAL_APPROX"

def iou(a, b):
    ax, ay, aw, ah = a; bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by); x2, y2 = min(ax+aw, bx+bw), min(ay+ah, by+bh)
    if x2 <= x1 or y2 <= y1: return 0.0
    inter = (x2-x1)*(y2-y1)
    return inter/(aw*ah + bw*bh - inter)

rows = []
for fr in key["frames"]:
    fid = fr["frame_id"]; role = fr["role"]
    o = orig.get(fid); b = blind_by.get(fid)
    if o is None or b is None:
        rows.append({"frame_id": fid, "role": role, "error": "MISSING"}); continue
    ot = o.get("target") or {}; bt = b.get("target") or {}
    o_present = ot.get("present") is True; b_present = bt.get("present") is True
    b_undec = bt.get("undecidable") is True
    o_bbox, b_bbox = bbox(o), bbox(b)
    o_kpt, b_kpt = kpt(o), kpt(b)
    row = {"frame_id": fid, "role": role, "family": fr.get("family"),
           "original_present": o_present, "blind_present": b_present, "blind_undecidable": b_undec,
           "blind_confidence": b.get("confidence"),
           "original_reference_available": ref(o), "blind_reference_available": ref(b),
           "bbox_iou": (iou(o_bbox, b_bbox) if o_bbox and b_bbox else None),
           "keypoint_distance_px": (math.hypot(o_kpt[0]-b_kpt[0], o_kpt[1]-b_kpt[1]) if o_kpt and b_kpt else None),
           "original_green_pixels": (o.get("geometry") or {}).get("green_pixels"),
           "blind_green_pixels": (b.get("geometry") or {}).get("green_pixels"),
           "truncation": {"original": ot.get("truncated_edges"), "blind": bt.get("truncated_edges")},
           "blind_note": (b.get("notes") or "")[:160]}
    if b_undec:
        row["presence_agreement"] = None
        row["reference_availability_agreement"] = None
        row["truncation_agreement"] = None
    else:
        row["presence_agreement"] = (o_present == b_present)
        row["reference_availability_agreement"] = (ref(o) == ref(b))
        row["truncation_agreement"] = (ot.get("truncated_edges") == bt.get("truncated_edges"))
    rows.append(row)

def rate(num, den): return (round(num/den, 4) if den else None)
decided = [r for r in rows if r.get("blind_undecidable") is False]
agree = [r for r in decided if r.get("presence_agreement") is True]
iou_vals = sorted(r["bbox_iou"] for r in rows if r.get("bbox_iou") is not None)
kpt_vals = sorted(r["keypoint_distance_px"] for r in rows if r.get("keypoint_distance_px") is not None)
def med(v):
    n = len(v); return (v[n//2] if n % 2 else 0.5*(v[n//2-1]+v[n//2])) if v else None
def p90(v): return v[min(len(v)-1, math.ceil(0.9*len(v))-1)] if v else None

def summarise(items):
    d = [r for r in items if r.get("blind_undecidable") is False]
    a = [r for r in d if r.get("presence_agreement") is True]
    ious = sorted(r["bbox_iou"] for r in items if r.get("bbox_iou") is not None)
    kpts = sorted(r["keypoint_distance_px"] for r in items if r.get("keypoint_distance_px") is not None)
    ref_agree = [r for r in d if r.get("reference_availability_agreement") is True]
    trunc_agree = [r for r in d if r.get("truncation_agreement") is True]
    return {"frames": len(items), "blind_undecidable": sum(1 for r in items if r.get("blind_undecidable")),
            "decided": len(d), "presence_agree": len(a),
            "reference_availability_agree": len(ref_agree),
            "reference_availability_agreement_decided": rate(len(ref_agree), len(d)),
            "truncation_agree": len(trunc_agree),
            "truncation_agreement_decided": rate(len(trunc_agree), len(d)),
            "presence_agreement_strict": rate(len(a), len(items)),
            "presence_agreement_decided": rate(len(a), len(d)),
            "bbox_iou": {"n": len(ious), "median": (round(med(ious),4) if ious else None), "p90": (round(p90(ious),4) if ious else None)},
            "keypoint_px": {"n": len(kpts), "median": (round(med(kpts),4) if kpts else None), "p90": (round(p90(kpts),4) if kpts else None), "max": (round(kpts[-1],4) if kpts else None)}}

summary = {"overall": summarise(rows)}
for role in sorted(set(r["role"] for r in rows)):
    summary[role] = summarise([r for r in rows if r["role"] == role])

result = {"schema_version": "dsh.landmark_tiny_blind_disagreement.v1",
          "created_at": "2026-11-04",
          "inputs": {"blind_labels": "docs/reports/perception/annotation_verify_20261104/labels_tiny_blind.json",
                     "blind_labels_sha256": hashlib.sha256((ROOT/"docs/reports/perception/annotation_verify_20261104/labels_tiny_blind.json").read_bytes()).hexdigest(),
                     "blind_frame_list_sha256": "fc3508de23b8d16c593d0e2bad27889de89d3e4ed68a1704e01ba50b37364941",
                     "original_labels": ["labels_train.json", "labels_val.json (current sha 4e8e877e...)"],
                     "comparison_computed_by": "diag (independent of annot)"},
          "pre_registered_gates": {"presence_agreement_min": 0.90, "reference_availability_agreement_min": 0.90, "keypoint_median_px_max": 2.0, "keypoint_p90_px_max": 4.0, "bbox_iou_median_min": 0.50},
          "summary": summary,
          "frames": rows,
          "interpretation": "blind annotator marked 14/22 undecidable; strict presence agreement is computed over all 22 frames, decided-only agreement over the 8 frames the annotator could resolve. The pre-registered annotatability gate uses the strict rate (no silent drop of undecidable frames)."}
(OUT / "TINY_BLIND_DISAGREEMENT_20261104.json").write_text(json.dumps(result, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=1))
print("sha", result["inputs"]["blind_labels_sha256"])
for r in rows:
    print(r["role"], r["frame_id"], "orig_present", r["original_present"], "blind_present", r["blind_present"], "undec", r["blind_undecidable"], "iou", r.get("bbox_iou"), "kpt", r.get("keypoint_distance_px"), "conf", r.get("blind_confidence"))
