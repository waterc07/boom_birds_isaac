"""Calibrate the bulk bbox prior on the 25 pilot positive frames."""
import json
from pathlib import Path

REPO = Path(r"E:\isaac\proj_boom_birds")
BASE = REPO / "docs/reports/perception/annotation_verify_20261104"
cond = {r["frame_id"]: r for r in json.loads((REPO / "docs/reports/perception/capture_20261104/frame_conditions.json").read_text(encoding="utf-8"))}
pilot = json.loads((REPO / "outputs/perception/landmark_final_annotations_20261104/labels_v1.json").read_text(encoding="utf-8"))
pos = [a for a in pilot["annotations"] if a["target"]["present"]]
strict = {}
import numpy as np
from PIL import Image
IMG = REPO / "outputs/sensor_shadow/lm_final_candidate_20261104_sensor/images"
def centroid(path):
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    r, g, b = rgb[...,0], rgb[...,1], rgb[...,2]
    mask = (g >= 90) & (g - r >= 25) & (g - b >= 25)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0: return None
    return [float(xs.mean()), float(ys.mean())]
def iou(a,b):
    ax,ay,aw,ah = a; bx,by,bw,bh = b
    ix0,iy0 = max(ax,bx), max(ay,by); ix1,iy1 = min(ax+aw,bx+bw), min(ay+ah,by+bh)
    iw,ih = max(0.0,ix1-ix0), max(0.0,iy1-iy0)
    inter = iw*ih; union = aw*ah+bw*bh-inter
    return inter/union if union>0 else 0

def make_bbox(fid, hf, yoff, wf):
    c = cond[fid]; s0,s1 = c["predicted_tower_span_u_px"]; span = s1-s0
    cen = centroid(IMG/fid)
    ay = cen[1] if cen else 120.0
    x0 = s0 + (1-wf)*span/2.0; x1 = x0 + wf*span
    y0 = ay + yoff
    y1 = y0 + hf*0.9*span/0.9*1.0  # hf multiplies height
    y1 = y0 + hf*span
    bx0,by0 = max(0,min(320,x0)), max(0,min(240,y0))
    bx1,by1 = max(0,min(320,x1)), max(0,min(240,y1))
    return [bx0,by0,bx1-bx0,by1-by0]

best = None
for hf in [0.75,0.8,0.85,0.9,0.95,1.0,1.05,1.1]:
    for yoff in [-20,-18,-16,-14,-12,-10,-8,-6,-4]:
        for wf in [0.85,0.9,0.95,1.0,1.05,1.1]:
            ious = [iou(a["geometry"]["bbox_xywh"], make_bbox(a["frame_id"], hf, yoff, wf)) for a in pos]
            mean = sum(ious)/len(ious); med = sorted(ious)[len(ious)//2]
            if best is None or mean > best[0]:
                best = (mean, med, min(ious), hf, yoff, wf)
print("best mean=%.4f median=%.4f min=%.4f hf=%.2f yoff=%d wf=%.2f" % best)
# compare current draft (hf 0.9, yoff -8, wf 1.0)
ious = [iou(a["geometry"]["bbox_xywh"], make_bbox(a["frame_id"], 0.9, -8, 1.0)) for a in pos]
print("current: mean=%.4f median=%.4f min=%.4f" % (sum(ious)/len(ious), sorted(ious)[len(ious)//2], min(ious)))
# keypoint check
kpd = []
for a in pos:
    if a["geometry"]["keypoint"] is None: continue
    cen = centroid(IMG/a["frame_id"])
    if cen is None: continue
    kp = a["geometry"]["keypoint"]
    kpd.append(((kp["x"]-cen[0])**2 + (kp["y"]-cen[1])**2)**0.5)
print("keypoint dist to strict centroid: n=%d mean=%.3f max=%.3f" % (len(kpd), sum(kpd)/len(kpd), max(kpd)))
