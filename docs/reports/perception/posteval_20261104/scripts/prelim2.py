# -*- coding: utf-8 -*-
"""Preliminary 2: flips, kpt-confidence, near-family detail."""
import json, math, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parents[5]
from sys import path as _p
_p.insert(0, str(ROOT / "src"))
from boom_birds.evaluation import landmark_metrics as metrics
from boom_birds.evaluation import landmark_yolo as yolo
def load(p): return json.loads((ROOT / p).read_text(encoding="utf-8"))
labels = load("outputs/perception/final_exploratory_20261104/labels_v1.json")
preds = [json.loads(l) for l in (ROOT / "outputs/perception/final_exploratory_eval_20261104/predictions.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
obs = {r["frame_id"]: r.get("observation") for r in preds}
TAU_PX, TAU_IOU, TAU_CONF, TAU_KPT, FX, CX = 3.0, 0.3, 0.605476, 0.5, 160.0, 160.0
rows = []
for ann in labels["annotations"]:
    o = obs.get(ann["frame_id"]); gt, ref_px, strata = yolo.ground_truth_from_annotation(ann)
    pred = yolo.observation_to_metric_prediction(o)
    base = metrics.evaluate_frame(gt, pred, tau_iou=TAU_IOU, reference_px=ref_px, tau_px=TAU_PX, tau_conf=TAU_CONF, fx_px=FX, cx_px=CX, strata=strata)
    kpt, kc = o.get("keypoint_px"), o.get("keypoint_confidence")
    present = gt["present"]; ref_avail = (gt["reference"] == "VISIBLE") if present else None
    dx = dy = None
    if ref_avail and kpt is not None and ref_px is not None:
        dx = float(kpt[0]) - float(ref_px[0]); dy = float(kpt[1]) - float(ref_px[1])
    row = dict(base); row.update({"family": strata["family"], "scale": strata["scale"], "ref_avail": ref_avail, "dx": dx, "dy": dy, "kpt_conf": kc, "suppressed": bool(kpt is None and kc is not None and float(kc) < TAU_KPT)})
    rows.append(row)
avail = [r for r in rows if r["gt_observable"] and r["gt_present"] and r["ref_avail"] is True]
emitted = [r for r in avail if r["dx"] is not None]
wrong = [r for r in emitted if r["anchor_error_px"] > TAU_PX]
correct = [r for r in emitted if r["anchor_error_px"] <= TAU_PX]
nokpt = [r for r in avail if r["dx"] is None and r["presence_class"] == "TP"]
unavail = [r for r in rows if r["gt_observable"] and r["gt_present"] and r["ref_avail"] is False]

print("== flips (denominator emitted=%d)" % len(emitted))
for th in (0.414, 1.074, 3.0, 5.0):
    b = [r for r in emitted if r["bearing_error_deg"] is not None and r["bearing_error_deg"] <= th]
    bp = set(id(r) for r in b)
    pp = set(id(r) for r in correct)
    both = len(bp & pp); pf = len(pp - bp); bf = len(bp - pp); neither = len(emitted) - both - pf - bf
    print(" threshold %.3f deg: both_pass %d | 2D_pass_bearing_fail %d | 2D_fail_bearing_pass %d | both_fail %d | flips %d" % (th, both, pf, bf, neither, pf + bf))

def dist(vals):
    vals = [float(v) for v in vals if v is not None]; vals.sort()
    if not vals: return "n=0"
    n = len(vals); med = vals[n//2] if n%2 else 0.5*(vals[n//2-1]+vals[n//2])
    return "n=%d min=%.4f median=%.4f p90=%.4f max=%.4f" % (n, vals[0], med, vals[min(n-1, math.ceil(0.9*n)-1)], vals[-1])
print("== kpt confidence")
print(" suppressed(28):", dist([r["kpt_conf"] for r in nokpt]))
print(" available emitted correct:", dist([r["kpt_conf"] for r in correct]))
print(" available emitted wrong:", dist([r["kpt_conf"] for r in wrong]))
print(" GT-unavailable declared(20):", dist([r["kpt_conf"] for r in unavail]))
print(" suppressed kpt conf >0.3:", sum(1 for r in nokpt if r["kpt_conf"] > 0.3), ">0.4:", sum(1 for r in nokpt if r["kpt_conf"] > 0.4))

print("== family: 2D vs bearing")
for fam in sorted(set(r["family"] for r in avail)):
    g = [r for r in avail if r["family"] == fam]; e = [r for r in g if r["dx"] is not None]
    b = [r for r in e if r["bearing_error_deg"] is not None and r["bearing_error_deg"] <= 1.074]
    c = [r for r in e if r["anchor_error_px"] <= TAU_PX]
    berr = [r["bearing_error_deg"] for r in e if r["bearing_error_deg"] is not None]
    med = sorted(berr)[len(berr)//2] if berr else None
    print("  %-18s avail %3d emitted %3d 2D<=3 %3d bearing<=1.074 %3d bearing_med %s" % (fam, len(g), len(e), len(c), len(b), ("%.3f" % med) if med is not None else None))

print("== near family wrong-anchor detail")
near = [r for r in wrong if r["family"] == "lmf_near"]
for r in near[:25]:
    print("  ", r["frame_id"], "err %.2f dx %.2f dy %.2f bearing %.3f kptconf %.3f" % (r["anchor_error_px"], r["dx"], r["dy"], r["bearing_error_deg"], r["kpt_conf"]))
print(" near median err", sorted(r["anchor_error_px"] for r in near)[len(near)//2] if near else None)
print(" near dy median", sorted(r["dy"] for r in near)[len(near)//2] if near else None)
print(" near bbox sample", [(r["frame_id"], r["gt_bbox"]) for r in near[:3]])
