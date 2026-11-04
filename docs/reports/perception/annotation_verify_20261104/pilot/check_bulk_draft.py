"""Consistency self-check for the rebuilt 279-frame draft."""
import json
from pathlib import Path

REPO = Path(r"E:\isaac\proj_boom_birds")
OUT = REPO / "outputs/perception/final_exploratory_20261104"
BASE = REPO / "docs/reports/perception/annotation_verify_20261104"
draft = json.loads((OUT / "labels_draft.json").read_text(encoding="utf-8"))
pilot = json.loads((REPO / "outputs/perception/landmark_final_annotations_20261104/labels_v1.json").read_text(encoding="utf-8"))
pilot_by = {a["frame_id"]: a for a in pilot["annotations"]}

def iou(a,b):
    ax,ay,aw,ah = a; bx,by,bw,bh = b
    ix0,iy0 = max(ax,bx), max(ay,by); ix1,iy1 = min(ax+aw,bx+bw), min(ay+ah,by+bh)
    iw,ih = max(0.0,ix1-ix0), max(0.0,iy1-iy0)
    inter = iw*ih; union = aw*ah+bw*bh-inter
    return inter/union if union>0 else 0

issues = []
for a in draft["annotations"]:
    fid = a["frame_id"]; t = a["target"]; g = a["geometry"]
    if t["present"]:
        b = g["bbox_xywh"]
        if not b:
            issues.append((fid, "missing bbox")); continue
        x,y,w,h = b
        if w <= 2 or h <= 2: issues.append((fid, "degenerate bbox"))
        if x < -0.01 or y < -0.01 or x+w > 320.01 or y+h > 240.01:
            issues.append((fid, "bbox out of bounds"))
        kp = g["keypoint"]
        if kp and not (x-2 <= kp["x"] <= x+w+2 and y-2 <= kp["y"] <= y+h+2):
            issues.append((fid, "keypoint outside bbox"))
        if t["truncated"] != any(t["truncated_edges"].values()):
            issues.append((fid, "truncated/edges mismatch"))

# pilot-frame IoU after calibration
pilot_ious = []
for fid, a in pilot_by.items():
    if not a["target"]["present"]: continue
    d = next(x for x in draft["annotations"] if x["frame_id"] == fid)
    pilot_ious.append(iou(a["geometry"]["bbox_xywh"], d["geometry"]["bbox_xywh"]))
pilot_ious.sort()
print("pilot IoU after calibration: n=%d mean=%.4f median=%.4f min=%.4f max=%.4f" % (
    len(pilot_ious), sum(pilot_ious)/len(pilot_ious), pilot_ious[len(pilot_ious)//2], pilot_ious[0], pilot_ious[-1]))

# sequence smoothness per family (centres and sizes)
def mad_stats(vals):
    vals = sorted(vals)
    med = vals[len(vals)//2]
    dev = sorted(abs(v-med) for v in vals)
    mad = dev[len(dev)//2] if dev else 0.0
    return med, mad

families = {}
for a in draft["annotations"]:
    families.setdefault(a["source"]["family"], []).append(a)
outliers = []
for fam, anns in families.items():
    anns.sort(key=lambda a: a["source"]["sequence"])
    for key, getter in (
        ("cx", lambda b: b[0]+b[2]/2), ("cy", lambda b: b[1]+b[3]/2),
        ("w", lambda b: b[2]), ("h", lambda b: b[3])):
        deltas = []
        for prev, cur in zip(anns, anns[1:]):
            bp, bc = prev["geometry"]["bbox_xywh"], cur["geometry"]["bbox_xywh"]
            if not bp or not bc: continue
            deltas.append((cur["frame_id"], abs(getter(bc)-getter(bp))))
        if len(deltas) < 5: continue
        med, mad = mad_stats([d for _, d in deltas])
        for fid, d in deltas:
            if mad > 0 and d > med + 6*mad and d > 6:
                outliers.append((fid, key, round(d,2), round(med,2), round(mad,2)))
print("consistency issues:", len(issues))
for i in issues[:20]: print("  ", i)
print("sequence outliers (delta > median+6*MAD and >6px):", len(outliers))
for o in outliers[:30]: print("  ", o)
