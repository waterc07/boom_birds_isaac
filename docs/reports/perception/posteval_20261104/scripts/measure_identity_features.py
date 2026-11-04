# -*- coding: utf-8 -*-
"""Measure image-only appearance features of the central tower vs MS1 on the
62-frame development identity batch, and evaluate an appearance gate.

Identity reasoning uses image features only.  Distance is derived from capture
pose + map-DB positions ONLY to normalise the green-area/range relation; it is
never used as an identity feature because the deployment consumer does not know
the range.
"""
import json, math, statistics, collections, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / "docs/reports/perception/posteval_20261104"
from sys import path as _p
_p.insert(0, str(ROOT / "src"))
from boom_birds.evaluation.landmark_posteval import green_components
from PIL import Image

LABELS = json.loads((ROOT/"outputs/perception/dev_annotations_20261104/labels_identity_dev.json").read_text(encoding="utf-8"))
COND = json.loads((ROOT/"outputs/perception/dev_annotations_20261104/identity/identity_frame_conditions.json").read_text(encoding="utf-8"))
IMAGES = ROOT/"outputs/sensor_shadow/lm_dev_identity_capture_20261104_sensor/images"
TARGET_LIGHT_WORLD = (11.52, -0.01, 1.25)
MS1_LAMP_WORLD = (3.0, 4.0, 1.71)

def load_pixels(path):
    with Image.open(path) as im:
        rgb = im.convert("RGB"); w, h = rgb.size; px = list(rgb.getdata())
    return [px[r*w:(r+1)*w] for r in range(h)], w, h

def is_struct(p):
    r, g, b = p; mx, mn = max(p), min(p); mean = (r+g+b)/3.0
    return (mx-mn) <= 40 and 60 <= mean <= 225

def run_span(row, x):
    if not (0 <= x < len(row)) or not is_struct(row[x]):
        return None
    lo = x
    while lo-1 >= 0 and is_struct(row[lo-1]): lo -= 1
    hi = x
    while hi+1 < len(row) and is_struct(row[hi+1]): hi += 1
    return lo, hi

def median(v): return statistics.median(v) if v else None

def object_features(pixels, w, h, bbox, cue):
    x, y, bw, bh = [float(v) for v in bbox]
    cx = int(round(min(w-1, max(0, x + bw/2.0))))
    out = {"aspect_ratio": bw/bh if bh else None,
           "green_rel_x": ((cue[0]-x)/bw if cue else None),
           "green_rel_y": ((cue[1]-y)/bh if cue else None),
           "green_inside_bbox": (bool(x <= cue[0] <= x+bw and y <= cue[1] <= y+bh) if cue else None),
           "bbox_w": bw, "bbox_h": bh,
           "reference_available": cue is not None}
    comps = green_components(pixels)
    near = ([c for c in comps if math.hypot(c["centroid_x"]-cue[0], c["centroid_y"]-cue[1]) <= 12.0]
            if cue else [])
    near.sort(key=lambda c: math.hypot(c["centroid_x"]-cue[0], c["centroid_y"]-cue[1]))
    out["green_area_px"] = near[0]["area"] if near else None
    out["green_component_width_px"] = (near[0]["u_max"]-near[0]["u_min"]+1) if near else None
    syms, widths_up, widths_mid = [], [], []
    rows_up = range(int(y+0.10*bh), int(y+0.35*bh)+1)
    rows_mid = range(int(y+0.45*bh), int(y+0.65*bh)+1)
    for r in rows_up:
        if not (0 <= r < h): continue
        span = run_span(pixels[r], cx)
        if not span: continue
        lo, hi = span; L = cx-lo; R = hi-cx
        if L+R: syms.append(1.0 - abs(L-R)/(L+R))
        widths_up.append(hi-lo+1)
    for r in rows_mid:
        if not (0 <= r < h): continue
        span = run_span(pixels[r], cx)
        if span: widths_mid.append(span[1]-span[0]+1)
    out["axis_symmetry"] = median(syms)
    out["top_width_px"] = median(widths_up)
    out["body_width_px"] = median(widths_mid)
    out["top_body_width_ratio"] = (median(widths_up)/median(widths_mid)
                                   if widths_up and widths_mid and median(widths_mid) else None)
    out["measurement_ok"] = bool(bh >= 20 and out["top_body_width_ratio"] is not None)
    return out

def dist(cam, world):
    return math.sqrt(sum((cam[i]-world[i])**2 for i in range(3)))

objects = []
per_frame = []
for a in LABELS["annotations"]:
    fid = a["frame_id"]; cond = COND.get(fid, {}); cam = cond.get("camera_position_world_m")
    path = ROOT / a["image"]
    if not path.is_file(): print("MISSING", fid); continue
    pixels, w, h = load_pixels(path)
    target = a.get("target") or {}; geo = a.get("geometry") or {}
    rec = {"frame_id": fid, "case": (a.get("source") or {}).get("family","").replace("fam_lmf_devid_",""),
           "camera": cam, "objects": []}
    if target.get("present") is True and geo.get("bbox_xywh"):
        cue = ([float(geo["keypoint"]["x"]), float(geo["keypoint"]["y"])]
               if geo.get("keypoint") else None)
        f = object_features(pixels, w, h, geo["bbox_xywh"], cue)
        f.update({"kind": "TARGET", "frame_id": fid, "case": rec["case"],
                  "distance_m": (dist(cam, TARGET_LIGHT_WORLD) if cam else None),
                  "label_green_pixels": geo.get("green_pixels"),
                  "reference_status": geo.get("reference_status")})
        rec["objects"].append(f); objects.append(f)
    for c in (a.get("confusers") or []):
        if not c.get("bbox_xywh"): continue
        cue = ([float(c["green_cue"]["x"]), float(c["green_cue"]["y"])]
               if c.get("green_cue") else None)
        f = object_features(pixels, w, h, c["bbox_xywh"], cue)
        f.update({"kind": "MS1", "frame_id": fid, "case": rec["case"],
                  "distance_m": (dist(cam, MS1_LAMP_WORLD) if cam else None),
                  "verification_source": c.get("verification_source")})
        rec["objects"].append(f); objects.append(f)
    per_frame.append(rec)

def stats(vals):
    vals = sorted(float(v) for v in vals if v is not None)
    if not vals: return {"n": 0}
    n = len(vals); med = vals[n//2] if n%2 else 0.5*(vals[n//2-1]+vals[n//2])
    return {"n": n, "min": round(vals[0],4), "median": round(med,4), "p90": round(vals[min(n-1, math.ceil(0.9*n)-1)],4), "max": round(vals[-1],4)}

FEATURES = ["aspect_ratio","green_rel_x","green_rel_y","green_area_px","green_component_width_px",
            "axis_symmetry","top_width_px","body_width_px","top_body_width_ratio","distance_m"]
print("objects", len(objects), collections.Counter(o["kind"] for o in objects))
print("cases", collections.Counter(o["case"] for o in objects))
for k in FEATURES:
    t = stats([o.get(k) for o in objects if o["kind"]=="TARGET"])
    m = stats([o.get(k) for o in objects if o["kind"]=="MS1"])
    print(k)
    print("   TARGET", t)
    print("   MS1   ", m)

def fit(kind):
    pts = [(o["distance_m"], o["green_area_px"]) for o in objects if o["kind"]==kind and o.get("distance_m") and o.get("green_area_px")]
    if len(pts) < 3: return None
    xs = [math.log(d) for d,_ in pts]; ys = [math.log(a) for _,a in pts]
    mx = sum(xs)/len(xs); my = sum(ys)/len(ys)
    sxx = sum((v-mx)**2 for v in xs); sxy = sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    slope = sxy/sxx if sxx else None; intercept = my - slope*mx if slope else None
    ss_tot = sum((y-my)**2 for y in ys); ss_res = sum((y-(intercept+slope*x))**2 for x,y in zip(xs,ys))
    return {"n": len(pts), "slope": slope, "intercept": intercept,
            "r2": (1-ss_res/ss_tot if ss_tot else None),
            "note": "green area ~ distance^slope; slope about -2 means inverse-square apparent size"}
green_distance = {"TARGET": fit("TARGET"), "MS1": fit("MS1")}
print("green area vs distance", json.dumps(green_distance, indent=1))

def auc(values_pos, values_neg):
    pos = [v for v in values_pos if v is not None]; neg = [v for v in values_neg if v is not None]
    if not pos or not neg: return None
    wins = 0.0
    for p in pos:
        for n in neg:
            wins += 1.0 if p > n else (0.5 if p == n else 0.0)
    return wins/(len(pos)*len(neg))

def gate_table(values, higher_is_target, thresholds):
    rows = []
    for t in thresholds:
        def accept(v):
            if v is None: return None
            return (v >= t) if higher_is_target else (v <= t)
        tgt = [o for o in objects if o["kind"]=="TARGET" and o.get("measurement_ok", True)]
        ms1 = [o for o in objects if o["kind"]=="MS1" and o.get("measurement_ok", True)]
        fb = sum(1 for o in tgt if accept(o.get(values)) is False)
        mb = sum(1 for o in ms1 if accept(o.get(values)) is True)
        rows.append({"threshold": t, "false_block_target": fb, "target_n": len(tgt),
                     "miss_block_ms1": mb, "ms1_n": len(ms1),
                     "cost_5x": 5*mb + fb})
    return rows

candidates = {
  "aspect_ratio": (True, [0.5,0.6,0.7,0.8,0.9,1.0,1.1]),
  "green_rel_y": (True, [0.13,0.15,0.18,0.20,0.22,0.25]),
  "top_body_width_ratio": (True, [0.7,0.85,1.0,1.15,1.3]),
  "green_component_width_px": (True, [2,3,4,5,6,8,10]),
}
gate_grid = {}
for name, (higher, thr) in candidates.items():
    tvals = [o.get(name) for o in objects if o["kind"]=="TARGET"]
    mvals = [o.get(name) for o in objects if o["kind"]=="MS1"]
    gate_grid[name] = {"auc_target_higher": auc(tvals, mvals), "higher_is_target": higher,
                       "table": gate_table(name, higher, thr)}
    print("GATE", name, "auc", gate_grid[name]["auc_target_higher"])
    for row in gate_grid[name]["table"]: print("   ", row)

def combined(o, aspect_min=0.50, rel_y_min=0.18):
    a = o.get("aspect_ratio")
    if a is None: return "UNKNOWN"
    if a < aspect_min: return "REJECT"
    ry = o.get("green_rel_y")
    if ry is not None and ry < rel_y_min: return "REJECT"
    return "ACCEPT"
comb_t = [o for o in objects if o["kind"]=="TARGET"]
comb_m = [o for o in objects if o["kind"]=="MS1"]
comb = {"rule": "identity ACCEPT only if aspect_ratio>=0.50; if a reference keypoint is emitted also require green_rel_y>=0.18; otherwise UNKNOWN/REJECT",
        "accept_target": sum(1 for o in comb_t if combined(o)=="ACCEPT"), "target_n": len(comb_t),
        "reject_target_false_block": sum(1 for o in comb_t if combined(o)=="REJECT"),
        "accept_ms1_miss_block": sum(1 for o in comb_m if combined(o)=="ACCEPT"), "ms1_n": len(comb_m),
        "reject_ms1": sum(1 for o in comb_m if combined(o)=="REJECT"),
        "unknown_target": sum(1 for o in comb_t if combined(o)=="UNKNOWN"),
        "unknown_ms1": sum(1 for o in comb_m if combined(o)=="UNKNOWN")}
per_case = {}
for case in sorted(set(o["case"] for o in objects)):
    grp = [o for o in objects if o["case"]==case]
    per_case[case] = {k: {"TARGET": stats([o.get(k) for o in grp if o["kind"]=="TARGET"]),
                          "MS1": stats([o.get(k) for o in grp if o["kind"]=="MS1"])}
                     for k in ("aspect_ratio","green_rel_y")}
print("COMBINED", json.dumps(comb, ensure_ascii=False))
print("PER_CASE", json.dumps(per_case, ensure_ascii=False, indent=1))

def upper_bound(k, n):
    if n == 0: return None
    if k == 0: return 1 - 0.05**(1.0/n)
    return None

bench_pixels, bw, bh = load_pixels(ROOT / LABELS["annotations"][0]["image"])
t0 = time.perf_counter(); reps = 50
for _ in range(reps):
    green_components(bench_pixels)
    run_span(bench_pixels[80], 160)
dt = (time.perf_counter()-t0)/reps
bench = {"reps": reps, "image": "320x240", "seconds_per_frame_host_cpu": dt,
         "note": "host CPU only, pure-python; RK3576 board cost UNKNOWN (no board test)"}
print("BENCH", json.dumps(bench))

result = {"schema_version": "dsh.landmark_identity_appearance_features.v1", "created_at": "2026-11-04",
          "scope": "62 development identity frames; identity decisions use image features only; distance from capture pose+map DB only normalises the green-area/range relation and is NOT an identity feature",
          "world_positions": {"target_light": TARGET_LIGHT_WORLD, "ms1_lamp": MS1_LAMP_WORLD},
          "denominators": {"objects": len(objects), "target_objects": sum(1 for o in objects if o["kind"]=="TARGET"),
                           "ms1_objects": sum(1 for o in objects if o["kind"]=="MS1"), "frames": len(per_frame)},
          "feature_distributions": {k: {"TARGET": stats([o.get(k) for o in objects if o["kind"]=="TARGET"]),
                                        "MS1": stats([o.get(k) for o in objects if o["kind"]=="MS1"])} for k in FEATURES},
          "green_area_vs_distance_loglog": green_distance,
          "single_feature_gates": gate_grid,
          "combined_gate": comb,
          "per_case_aspect_and_rel_y": per_case,
          "zero_false_identity_upper_bound_95": upper_bound(0, sum(1 for o in objects if o["kind"]=="MS1")),
          "feature_compute_benchmark": bench,
          "frames": per_frame}
(OUT/"IDENTITY_APPEARANCE_FEATURES_20261104.json").write_text(json.dumps(result, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
print("WROTE IDENTITY_APPEARANCE_FEATURES_20261104.json")
