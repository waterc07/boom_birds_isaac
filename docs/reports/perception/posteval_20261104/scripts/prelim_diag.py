# -*- coding: utf-8 -*-
"""Preliminary post-eval decomposition (urgent intermediate; superseded by
landmark_posteval.py when the module lands)."""
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
metrics_json = load("outputs/perception/final_exploratory_eval_20261104/metrics.json")
TAU_PX, TAU_IOU, TAU_CONF, TAU_KPT, FX, CX = 3.0, 0.3, 0.605476, 0.5, 160.0, 160.0
rows = []
for ann in labels["annotations"]:
    o = obs.get(ann["frame_id"])
    gt, ref_px, strata = yolo.ground_truth_from_annotation(ann)
    pred = yolo.observation_to_metric_prediction(o)
    base = metrics.evaluate_frame(gt, pred, tau_iou=TAU_IOU, reference_px=ref_px, tau_px=TAU_PX, tau_conf=TAU_CONF, fx_px=FX, cx_px=CX, strata=strata)
    geo = ann.get("geometry") or {}
    kpt, kc = o.get("keypoint_px"), o.get("keypoint_confidence")
    present = gt["present"]
    ref_avail = (gt["reference"] == "VISIBLE") if present else None
    suppressed = bool(kpt is None and kc is not None and float(kc) < TAU_KPT)
    dx = dy = None
    if ref_avail and kpt is not None and ref_px is not None:
        dx = float(kpt[0]) - float(ref_px[0]); dy = float(kpt[1]) - float(ref_px[1])
    row = dict(base); row.update({"family": strata["family"], "scale": strata["scale"],
        "truncation": strata["truncation"], "visibility": strata["visibility"],
        "ref_avail": ref_avail, "dx": dx, "dy": dy, "suppressed": suppressed,
        "kpt_conf": kc, "gt_bbox": gt["bbox_xywh"], "pred_bbox": o.get("bbox_xywh"),
        "ref_source": geo.get("reference_source")})
    rows.append(row)

print("=== presence (recomputed vs frozen) ===")
sum_dev = metrics.summarize(rows)
frozen = metrics_json["overall"]
for k in ("tp","fp","fn","tn"): print("presence.%s recomputed=%s frozen=%s" % (k, sum_dev["presence"][k], frozen["presence"][k]))
print("joint recomputed", sum_dev["joint"]["narrow_tp"], "/", sum_dev["joint"]["narrow_denominator"], "frozen", frozen["joint"]["narrow_tp"], "/", frozen["joint"]["narrow_denominator"])

avail = [r for r in rows if r["gt_observable"] and r["gt_present"] and r["ref_avail"] is True]
unavail = [r for r in rows if r["gt_observable"] and r["gt_present"] and r["ref_avail"] is False]
emitted = [r for r in avail if r["dx"] is not None]
correct = [r for r in emitted if r["anchor_error_px"] is not None and r["anchor_error_px"] <= TAU_PX]
wrong = [r for r in emitted if r["anchor_error_px"] is not None and r["anchor_error_px"] > TAU_PX]
nokpt = [r for r in avail if r["presence_class"] == "TP" and r["dx"] is None]
pmiss = [r for r in avail if r["presence_class"] != "TP"]
declared = [r for r in unavail if r["dx"] is None]
false_ref = [r for r in unavail if r["dx"] is not None]
print("=== reference stages ===")
print("available", len(avail), "correct", len(correct), "wrong", len(wrong), "no_kpt", len(nokpt), "presence_miss", len(pmiss), "unavailable", len(unavail), "declared", len(declared), "false_ref", len(false_ref))
print("no_kpt suppressed by conf", sum(1 for r in nokpt if r["suppressed"]), "no kpt output", sum(1 for r in nokpt if not r["suppressed"]))

def stat(vs, unit="px"):
    vs = [float(v) for v in vs if v is not None]; vs.sort(); n = len(vs)
    if not n: return {"n":0}
    med = vs[n//2] if n%2 else 0.5*(vs[n//2-1]+vs[n//2])
    p90 = vs[max(0,min(n-1,math.ceil(0.9*n)-1))]
    return {"n":n,"median":round(med,3),"p90":round(p90,3),"max":round(vs[-1],3)}

tau_px_eff = [r["anchor_error_px"] for r in correct]
print("anchor all", stat([r["anchor_error_px"] for r in emitted]))
print("anchor correct-only", stat(tau_px_eff))
print("anchor wrong-only", stat([r["anchor_error_px"] for r in wrong]))
bearing_all = [abs(metrics.image_bearing_deg((r["dx"] or 0)+0, fx_px=FX, cx_px=CX)) for r in emitted]
# recompute bearing error from kpt dx is not correct; use stored gt/pred bearings
def bearing_err(r):
    if r["dx"] is None: return None
    gx = float(r["dx"]); return None
print("wrong: lateral", sum(1 for r in wrong if abs(r["dx"]) > abs(r["dy"])), "vertical|tie", sum(1 for r in wrong if abs(r["dy"]) >= abs(r["dx"])))
print("signed dx", stat([r["dx"] for r in emitted]), "signed dy", stat([r["dy"] for r in emitted]))
print("correct signed dx", stat([r["dx"] for r in correct]), "signed dy", stat([r["dy"] for r in correct]))
print("wrong signed dx", stat([r["dx"] for r in wrong]), "signed dy", stat([r["dy"] for r in wrong]))

print("=== groups ===")
def group_report(rows_in, keyfn, label):
    g = collections.defaultdict(lambda: {"n":0,"avail":0,"correct":0,"wrong":0,"no_kpt":0,"pmiss":0})
    for r in rows_in:
        k = keyfn(r); d = g[k]; d["n"] += 1
        if r["ref_avail"] is True:
            d["avail"] += 1
            if r["presence_class"] != "TP": d["pmiss"] += 1
            elif r["dx"] is None: d["no_kpt"] += 1
            elif r["anchor_error_px"] <= TAU_PX: d["correct"] += 1
            else: d["wrong"] += 1
    print("--", label)
    for k in sorted(g):
        d = g[k]; cov = (d["correct"]/d["avail"]) if d["avail"] else None
        print("  ", k, "n", d["n"], "avail", d["avail"], "correct", d["correct"], "wrong", d["wrong"], "no_kpt", d["no_kpt"], "pmiss", d["pmiss"], "cov", (round(cov,3) if cov is not None else None))
group_report(rows, lambda r: r["scale"], "scale")
group_report(rows, lambda r: r["truncation"], "truncation")
group_report(rows, lambda r: r["family"], "family")
group_report(rows, lambda r: r["visibility"], "visibility")

def bearing_abs(r):
    if r["dx"] is None: return None
    gt_b = metrics.image_bearing_deg((r["dx"] and 0) or 0, fx_px=FX, cx_px=CX)
    return None
ans = {"overall": {"available": len(avail), "correct": len(correct), "wrong": len(wrong),
    "no_keypoint": len(nokpt), "presence_miss": len(pmiss), "unavailable": len(unavail),
    "correct_refusal": len(declared), "false_reference": len(false_ref)},
    "anchor": {"all": stat([r["anchor_error_px"] for r in emitted]),
               "correct_only": stat([r["anchor_error_px"] for r in correct]),
               "wrong_only": stat([r["anchor_error_px"] for r in wrong])},
    "signed_dx_emitted": stat([r["dx"] for r in emitted]),
    "signed_dy_emitted": stat([r["dy"] for r in emitted]),
    "recomputed_presence": {k: sum_dev["presence"][k] for k in ("tp","fp","fn","tn")},
    "recomputed_joint": sum_dev["joint"]}
(ROOT / "docs/reports/perception/posteval_20261104/_prelim_stats.json").write_text(json.dumps(ans, indent=2), encoding="utf-8")
print("WROTE _prelim_stats.json")
