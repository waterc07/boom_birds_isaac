# -*- coding: utf-8 -*-
"""Estimate the unlabeled-MS1 risk in the v4.1 single-class training pool.

Read-only projection using the recorded per-frame SW camera pose (sensor
observation extrinsics) and the map-DB positions of MS1 and the central tower.
No image processing, no inference, no GT labels used as an input; single-class
labels are only read to split tower-present vs tower-absent frames.
"""
import json, math, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / "docs/reports/perception/posteval_20261104"

MS1 = {"lamp": (3.0, 4.0, 1.71), "top": (3.0, 4.0, 1.78), "base": (3.0, 4.0, 0.0)}
TARGET_LIGHT = (11.52, -0.01, 1.25)
FX = FY = 160.0; CX = 160.0; CY = 120.0; W = 320; H = 240

def load(p): return json.loads((ROOT / p).read_text(encoding="utf-8"))

def quat_rot(q):
    w, x, y, z = [float(v) for v in q]
    return ((1-2*(y*y+z*z), 2*(x*y-w*z), 2*(x*z+w*y)),
            (2*(x*y+w*z), 1-2*(x*x+z*z), 2*(y*z-w*x)),
            (2*(x*z-w*y), 2*(y*z+w*x), 1-2*(x*x+y*y)))

def world_to_cam(P, cam, quat):
    R = quat_rot(quat)
    d = [P[i]-cam[i] for i in range(3)]
    return [sum(R[j][i]*d[j] for j in range(3)) for i in range(3)]

def project(P, cam, quat):
    x, y, z = world_to_cam(P, cam, quat)
    if x <= 0.3:
        return None
    return (CX - FX*y/x, CY - FY*z/x, x)

def span_valid(u, v, margin_u=32, margin_v=24):
    return (-margin_u <= u <= W+margin_u) and (-margin_v <= v <= H+margin_v)

# --- calibration: dev capture frame_conditions vs formula ------------------
cond = load("docs/reports/perception/capture_dev_20261104/frame_conditions.json")
errors = []
for fr in cond:
    proj = fr.get("tower_projection") or {}
    light = proj.get("light")
    cam = fr.get("camera_position_world_m"); quat = fr.get("camera_quat_wxyz")
    if not light or not cam or not quat: continue
    p = project(TARGET_LIGHT, cam, quat)
    if p is None: continue
    errors.append(math.hypot(p[0]-light[0], p[1]-light[1]))
errors.sort()
cal = {"n": len(errors), "median_px": (errors[len(errors)//2] if errors else None),
       "max_px": (errors[-1] if errors else None), "note": "formula u=cx-fx*y/x, v=cy-fy*z/x with FLU camera axes"}
print("CALIBRATION", json.dumps(cal))

freeze = load("configs/perception/landmark_split_freeze_v4_1.json")
groups = {g["group_id"]: g for g in freeze["groups"]}
datasets = freeze["datasets"]

# index sensor observations by payload ref for the datasets used by train groups
train_groups = freeze["splits"]["train"]
needed = sorted(set(groups[g]["dataset"] for g in train_groups))
pose_by_ref = {}
obs_missing = 0
for ds in needed:
    path = datasets[ds]["observations"]
    rows = [json.loads(l) for l in (ROOT/path).read_text(encoding="utf-8").splitlines() if l.strip()]
    for row in rows:
        ex = (row.get("sensor") or {}).get("extrinsics") or {}
        ref = (row.get("payload") or {}).get("ref")
        accepted = (row.get("gate") or {}).get("accepted")
        valid = (row.get("validity") or {}).get("valid")
        if not ref or not accepted or not ex.get("position_world_m") or not ex.get("quat_w_world"):
            continue
        pose_by_ref[ref.replace("\\", "/")] = {"cam": ex["position_world_m"], "quat": ex["quat_w_world"],
                                                "valid": valid}
    print(ds, "obs rows", len(rows), "accepted poses", sum(1 for k in pose_by_ref if ds in k))

# single-class label presence maps (diagnostic split only)
label_present = {}
for p in ["outputs/perception/dev_annotations_20261104/labels_train.json",
          "outputs/perception/final_exploratory_20261104/labels_v1.json"]:
    try:
        doc = load(p)
        for a in doc.get("annotations") or []:
            label_present[a["frame_id"]] = (a.get("target") or {}).get("present") is True
    except Exception as e:
        print("label load err", p, e)

frames = []
for gid in train_groups:
    g = groups[gid]; ds = g["dataset"]
    for f in g["frames"]:
        if not f.get("accepted"):
            continue
        fid = f["frame_id"]
        ref = "outputs/sensor_shadow/%s/images/%s" % (ds, fid)
        pose = pose_by_ref.get(ref)
        rec = {"frame_id": fid, "group_id": gid, "dataset": ds, "tower_label_present": label_present.get(fid)}
        if pose is None:
            rec["ms1_visible"] = None; rec["ms1_clearly_visible"] = None
            rec["reason"] = "NO_POSE"; frames.append(rec); obs_missing += 1; continue
        lamp = project(MS1["lamp"], pose["cam"], pose["quat"])
        top = project(MS1["top"], pose["cam"], pose["quat"])
        base = project(MS1["base"], pose["cam"], pose["quat"])
        rec["distance_m"] = math.dist(pose["cam"], MS1["lamp"])
        if lamp is None or top is None or base is None:
            rec["ms1_visible"] = False; rec["ms1_clearly_visible"] = False
            rec["in_frame"] = False; rec["reason"] = "BEHIND_OR_INVALID"; frames.append(rec); continue
        height_px = abs(base[1]-top[1])
        in_frame = span_valid(lamp[0], lamp[1])
        rec.update({"lamp_uv": [round(lamp[0],1), round(lamp[1],1)], "height_px": round(height_px,2),
                    "in_frame": in_frame, "ms1_visible": bool(in_frame and height_px >= 8.0),
                    "ms1_clearly_visible": bool(in_frame and height_px >= 20.0)})
        frames.append(rec)

valid = [r for r in frames if r.get("ms1_visible") is not None]
vis8 = [r for r in valid if r["ms1_visible"]]
vis20 = [r for r in valid if r["ms1_clearly_visible"]]
print("FRAMES", len(frames), "pose_missing", obs_missing, "valid", len(valid),
      "ms1_visible>=8px", len(vis8), ">=20px", len(vis20))

def group_summary():
    out = {}
    for gid in train_groups:
        g = [r for r in valid if r["group_id"] == gid]
        v8 = [r for r in g if r["ms1_visible"]]
        v20 = [r for r in g if r["ms1_clearly_visible"]]
        out[gid] = {"usable": len(g), "ms1_visible_8px": len(v8), "ratio_8px": (len(v8)/len(g) if g else None),
                    "ms1_visible_20px": len(v20), "ratio_20px": (len(v20)/len(g) if g else None),
                    "tower_label_present_true": sum(1 for r in v8 if r["tower_label_present"] is True),
                    "tower_label_present_false": sum(1 for r in v8 if r["tower_label_present"] is False),
                    "tower_label_unknown": sum(1 for r in v8 if r["tower_label_present"] is None)}
    return out

dist = sorted(r["distance_m"] for r in vis8 if r.get("distance_m"))
heights = sorted(r["height_px"] for r in vis8 if r.get("height_px"))
def stats(vals):
    if not vals: return {"n": 0}
    n = len(vals); med = vals[n//2] if n%2 else 0.5*(vals[n//2-1]+vals[n//2])
    return {"n": n, "min": round(vals[0],2), "median": round(med,2), "p90": round(vals[min(n-1, math.ceil(0.9*n)-1)],2), "max": round(vals[-1],2)}

result = {"schema_version": "dsh.landmark_v41_unlabeled_ms1_risk.v1", "created_at": "2026-11-05",
          "scope": "read-only projection estimate over the v4.1 single-class train pool; no images/inference/labels-as-input",
          "method": {"camera_pose": "sensor observation extrinsics (world position + quat_w_world)", "camera_projection": "u=cx-fx*y_cam/x_cam, v=cy-fy*z_cam/x_cam, FLU camera axes", "calibration": cal,
                     "ms1_points": MS1, "visibility_thresholds_px": {"decidable": 8.0, "clearly_visible": 20.0},
                     "limitations": ["no occlusion/terrain test", "MS1 width approximated by its axis", "runs may contain dynamic obstacles", "upper bound because occlusion would reduce visibility"]},
          "denominators": {"train_groups": len(train_groups), "accepted_frames": len(frames), "frames_with_pose": len(valid), "pose_missing": obs_missing},
          "overall": {"ms1_visible_8px": len(vis8), "ratio_8px": (len(vis8)/len(valid) if valid else None),
                      "ms1_visible_20px": len(vis20), "ratio_20px": (len(vis20)/len(valid) if valid else None),
                      "distance_m": stats(dist), "apparent_height_px": stats(heights),
                      "tower_label_present_true_among_visible": sum(1 for r in vis8 if r["tower_label_present"] is True),
                      "tower_label_present_false_among_visible": sum(1 for r in vis8 if r["tower_label_present"] is False),
                      "tower_label_unknown_among_visible": sum(1 for r in vis8 if r["tower_label_present"] is None)},
          "per_group": group_summary(),
          "consequence_if_reused_as_is": {
              "same_frame_omission": "frames where MS1 is projected visible and a tower bbox is also labelled: class1 exists but is unlabelled -> the two-class trainer treats it as background, directly suppressing the same-frame disambiguation case the gate needs",
              "background_penalty": "frames where MS1 is projected visible without any instance label: class1 gradient pushes 'no MS1 here' on exactly the MS1 views; class1 recall/photometric invariance risk",
              "quantified_risk": "see overall.ratio_8px / ratio_20px; any frame used in two-class training with single-class labels is an unlabelled-MS1 frame",
              "not_measured": "occlusion by terrain/robots and annotation-source mismatch are UNKNOWN; estimate is an upper bound of visible frames"},
          "mitigations": [
              "pre-register a v4.1 inclusion rule: exclude frames where projected MS1 height >= 20 px (or 8 px if more conservative) from the two-class train pass; report the excluded fraction before training",
              "or annotate class1 in the affected v4.1 frames (same-frame completeness rule) before training; this is the only option that keeps the vulnerable views",
              "do not rely on a pixel/loss ignore mask: ultralytics 8.2.0 pose loss has no per-region ignore mechanism; adding one is a code change with its own risk",
              "keep the new two-class-only families as the primary class1 supervision and report class1 recall on the excluded views separately as a generalization probe (not train signal)"],
          "frames": frames}
(OUT/"V41_UNLABELED_MS1_RISK_20261105.json").write_text(json.dumps(result, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
print("WROTE V41_UNLABELED_MS1_RISK_20261105.json")
print("OVERALL", json.dumps(result["overall"], ensure_ascii=False))
print("PER GROUP", json.dumps(result["per_group"], ensure_ascii=False, indent=1)[:4000])
