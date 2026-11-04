# -*- coding: utf-8 -*-
"""MS1 vs central-tower image-only visual cue measurement (no GT position used
for identity reasoning; capture geometry only selects frames)."""
import json, math, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / "docs/reports/perception/posteval_20261104"
cond = json.loads((ROOT / "docs/reports/perception/capture_dev_20261104/frame_conditions.json").read_text(encoding="utf-8"))
IMG = ROOT / "outputs/sensor_shadow/lm_dev_capture_20261104_sensor/images"
from PIL import Image

def load_px(path):
    with Image.open(path) as im:
        rgb = im.convert("RGB"); w, h = rgb.size; px = list(rgb.getdata())
    return [px[r*w:(r+1)*w] for r in range(h)], w, h

def is_structure(p):
    r, g, b = p; mx, mn = max(p), min(p); mean = (r+g+b)/3.0
    return (mx-mn) <= 30 and 95 <= mean <= 223

def run_span(row, u):
    if not (0 <= u < len(row)) or not is_structure(row[u]):
        return None
    lo = u
    while lo-1 >= 0 and is_structure(row[lo-1]): lo -= 1
    hi = u
    while hi+1 < len(row) and is_structure(row[hi+1]): hi += 1
    return lo, hi

def measure(pixels, w, h, u, v):
    widths = []; centers = []
    for dv in range(5, 15):
        yy = int(round(v)) + dv
        if yy >= h: continue
        span = run_span(pixels[yy], int(round(u)))
        if span:
            widths.append(span[1]-span[0]+1); centers.append((span[0]+span[1])/2.0)
    if not widths: return None
    widths.sort(); width = widths[len(widths)//2]
    center = sum(centers)/len(centers)
    # vertical extent at the measured horizontal center
    cx = int(round(center))
    top = bottom = int(round(v))
    while top-1 >= 0 and run_span(pixels[top-1], cx): top -= 1
    while bottom+1 < h and run_span(pixels[bottom+1], cx): bottom += 1
    height = bottom - top + 1
    return {"width_px": float(width), "center_x": center, "height_px": float(height),
            "aspect_w_over_h": (width/height if height else None),
            "lamp_offset_ratio": (abs(u-center)/width if width else None),
            "top": top, "bottom": bottom}

def green_cluster_for(fr, kind):
    clusters = fr.get("green_clusters") or []
    if not clusters: return None
    proj = (fr.get("tower_projection") or {}).get("light")
    if kind == "target":
        if not proj or fr.get("target_green_pixels", 0) < 1: return None
        return min(clusters, key=lambda c: math.hypot(c["u"]-proj[0], c["v"]-proj[1]))
    # MS1: largest cluster that is not the target light
    if proj and fr.get("target_green_pixels", 0) >= 1:
        clusters = [c for c in clusters if math.hypot(c["u"]-proj[0], c["v"]-proj[1]) > 4.0]
    return max(clusters, key=lambda c: c["area"]) if clusters else None

records = []
for fr in cond:
    if fr.get("run") != "batch1": continue
    fid = fr["frame_id"]
    if not fid.startswith("lmf_dev_inner_north"): continue
    ms1 = green_cluster_for(fr, "ms1")
    tgt = green_cluster_for(fr, "target")
    if not ms1 or fr.get("map_native_pillar_green_pixels", 0) < 10: continue
    path = IMG / fid
    if not path.is_file(): continue
    pixels, w, h = load_px(path)
    m = measure(pixels, w, h, ms1["u"], ms1["v"])
    if not m: continue
    records.append({"frame_id": fid, "kind": "MS1", "green_area": ms1["area"],
                    "green_u": round(ms1["u"],1), "green_v": round(ms1["v"],1),
                    "target_distance_m": fr.get("target_distance_m"), **m})

# central tower measurement on close frames where an image anchor exists
tower_records = []
for fr in cond:
    if fr.get("run") != "batch1": continue
    fid = fr["frame_id"]
    if not fid.startswith("lmf_dev_inner_north"): continue
    tgt = green_cluster_for(fr, "target")
    dist = fr.get("target_distance_m") or 999
    if not tgt or fr.get("target_green_pixels", 0) < 6 or dist > 8: continue
    path = IMG / fid
    if not path.is_file(): continue
    pixels, w, h = load_px(path)
    m = measure(pixels, w, h, tgt["u"], tgt["v"])
    proj = fr.get("tower_projection") or {}
    bar = (proj.get("bar_left"), proj.get("bar_right"), proj.get("bar_top"), proj.get("body_base_left"))
    tower_records.append({"frame_id": fid, "kind": "TOWER", "green_area": tgt["area"],
                          "green_u": round(tgt["u"],1), "green_v": round(tgt["v"],1),
                          "target_distance_m": fr.get("target_distance_m"),
                          "proj_bar_width": (bar[1][0]-bar[0][0]) if bar[0] and bar[1] else None,
                          "proj_v_span": ((bar[3][1] or 0)-(bar[2][1] or 0)) if bar[2] and bar[3] else None, **m})

def summary(rows):
    def agg(key):
        vals = [r[key] for r in rows if r.get(key) is not None]; vals.sort()
        if not vals: return None
        n = len(vals); med = vals[n//2] if n%2 else 0.5*(vals[n//2-1]+vals[n//2])
        return {"n": n, "min": round(vals[0],3), "median": round(med,3), "max": round(vals[-1],3)}
    return {k: agg(k) for k in ("width_px","height_px","aspect_w_over_h","lamp_offset_ratio","green_area","target_distance_m")}

result = {"schema_version": "dsh.landmark_ms1_cues.v1", "created_at": "2026-11-04",
          "scope": "image-only measurements around the strict-green lamp; capture geometry selects frames and is NOT used to reason identity",
          "ms1": {"count": len(records), "summary": summary(records), "frames": records},
          "central_tower": {"count": len(tower_records), "summary": summary(tower_records), "frames": tower_records},
          "note": "MS1 frames are dev inner_north views where the map-native pillar lamp is visible; central-tower frames are inner_north views within 8 m with a visible target lamp. The measurement is a legibility diagnostic, not an identity classifier."}
(OUT / "MS1_VISUAL_CUES_20261104.json").write_text(json.dumps(result, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
print(json.dumps({"ms1_count": len(records), "tower_count": len(tower_records)}, ensure_ascii=False))
print("MS1 summary", json.dumps(result["ms1"]["summary"], ensure_ascii=False))
print("TOWER summary", json.dumps(result["central_tower"]["summary"], ensure_ascii=False))
print("MS1 sample", json.dumps(records[:4], ensure_ascii=False))
print("TOWER sample", json.dumps(tower_records[:4], ensure_ascii=False))
