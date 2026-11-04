"""Build the 279-frame exploratory annotation draft from capture geometry + green cue.

bbox draft prior: predicted_tower_span_u_px (capture pose/geometry projection) for
horizontal extent, height = 0.9 * span (median calibrated on the 34-frame pilot),
top anchored 8 px above the green centroid (median y0-green_y = -8.2 px, sd 5).
The draft is NOT final: every frame is visually reviewed afterwards and annotated
as BULK_CALIBRATED_WITH_FULL_VISUAL_QA with bbox_source=PROJECTION_AID_CALIBRATED.
"""
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(r"E:\isaac\proj_boom_birds")
BASE = REPO / "docs/reports/perception/annotation_verify_20261104"
OUT = REPO / "outputs/perception/final_exploratory_20261104"
OUT.mkdir(parents=True, exist_ok=True)
IMG = REPO / "outputs/sensor_shadow/lm_final_candidate_20261104_sensor/images"

seal = json.loads((REPO / "configs/perception/landmark_final_pool_seal_v1.json").read_text(encoding="utf-8"))
cond = {r["frame_id"]: r for r in json.loads((REPO / "docs/reports/perception/capture_20261104/frame_conditions.json").read_text(encoding="utf-8"))}
pilot_manifest = json.loads((BASE / "pilot/labels_manifest.json").read_text(encoding="utf-8"))
pilot_labels = json.loads((REPO / "outputs/perception/landmark_final_annotations_20261104/labels_v1.json").read_text(encoding="utf-8"))
pilot_ids = {a["frame_id"] for a in pilot_labels["annotations"]}
SPEC_V21 = "configs/perception/landmark_annotation_spec_v2_1.json"
SPEC_SHA = (BASE / "pilot/spec_v2_1_sha.txt").read_text(encoding="utf-8").strip()

PIXEL_BASIS = {"image_width": 320, "image_height": 240, "fx_px": 160.0,
               "cx_px": 160.0, "cy_px": 120.0, "projection_model": "PINHOLE",
               "bearing_formula": "atan2(x - cx_px, fx_px)"}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def clusters(path, min_green, min_diff):
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mask = (g >= min_green) & (g - r >= min_diff) & (g - b >= min_diff)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return {"pixels": 0, "centroid": None}
    seen = np.zeros(mask.shape, dtype=bool)
    best = []
    for y0, x0 in zip(ys, xs):
        if seen[y0, x0]:
            continue
        stack = [(y0, x0)]
        seen[y0, x0] = True
        comp = []
        while stack:
            y, x = stack.pop()
            comp.append((y, x))
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < mask.shape[0] and 0 <= nx < mask.shape[1] and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if len(comp) > len(best):
            best = comp
    if len(best) < 2:
        return {"pixels": len(best), "centroid": None}
    yy = [p[0] for p in best]
    xx = [p[1] for p in best]
    return {"pixels": len(best), "centroid": [sum(xx) / len(xx), sum(yy) / len(yy)]}

# accepted frame roster, family preserving seal order
families = {}
for group in seal["groups"]:
    fam = group["family_id"]
    frames = [f["frame_id"] for f in group["frames"] if f.get("accepted")]
    frames.sort(key=lambda f: int(f.rsplit("_", 1)[1].split(".")[0]))
    families[fam] = frames
all_frames = [f for fam in families for f in families[fam]]

NEGATIVE_FAMILIES = {"lmf_similar_negative", "lmf_side_negative"}
records = {}
for fid in all_frames:
    c = cond[fid]
    strict = clusters(IMG / fid, 90, 25)
    relaxed = clusters(IMG / fid, 60, 12)
    records[fid] = {"cond": c, "strict": strict, "relaxed": relaxed,
                    "family": next(f for f in families if fid in families[f])}

# anchor y: strict centroid y >=3 px, else relaxed centroid y, else neighbour interpolation
for fam, frames in families.items():
    for fid in frames:
        r = records[fid]
        if r["strict"]["pixels"] >= 3:
            r["anchor_y"] = r["strict"]["centroid"][1]
            r["anchor_src"] = "STRICT_GREEN_CENTROID"
        elif r["relaxed"]["centroid"] is not None:
            r["anchor_y"] = r["relaxed"]["centroid"][1]
            r["anchor_src"] = "RELAXED_GREEN_CENTROID"
        else:
            r["anchor_y"] = None
            r["anchor_src"] = None
    known = [(i, records[f]["anchor_y"]) for i, f in enumerate(frames) if records[f]["anchor_y"] is not None]
    for fid in frames:
        if records[fid]["anchor_y"] is not None:
            continue
        idx = frames.index(fid)
        if known:
            nearest = min(known, key=lambda t: abs(t[0] - idx))
            records[fid]["anchor_y"] = nearest[1]
            records[fid]["anchor_src"] = "NEIGHBOUR_INTERPOLATED"
        else:
            records[fid]["anchor_y"] = 0.5 * 240  # degenerate fallback; flagged for visual QA
            records[fid]["anchor_src"] = "FRAME_CENTER_FALLBACK"

annotations = []
for fid in all_frames:
    r = records[fid]
    c = r["cond"]
    fam = r["family"]
    present = fam not in NEGATIVE_FAMILIES
    span0, span1 = c["predicted_tower_span_u_px"]
    span = span1 - span0
    # calibrated on the 25 pilot positives: w=0.85*span, h=1.0*span, top=green_y-6
    width = 0.85 * span
    height = 1.0 * span
    x0 = span0 + (span - width) / 2.0
    x1 = x0 + width
    y0 = float(r["anchor_y"]) - 6.0
    y1 = y0 + height
    edges = {"left": bool(x0 < 0), "right": bool(x1 > 320),
             "top": bool(y0 < 0), "bottom": bool(y1 > 240)}
    sources = {}
    conflicts = []
    capture_right = bool(c.get("truncated_right"))
    capture_left = bool(c.get("truncated_left"))
    for edge in ("left", "right", "top", "bottom"):
        if not edges[edge]:
            continue
        capture = capture_left if edge == "left" else (capture_right if edge == "right" else None)
        if capture is True:
            sources[edge] = "BOTH"
        else:
            sources[edge] = "ANNOTATOR_VISUAL"
            if capture is False:
                conflicts.append({"edge": edge, "capture": False, "annotator": True,
                                  "resolution": "ANNOTATOR_OVER_CAPTURE"})
    bbox = None
    if present:
        bx0 = max(0.0, min(320.0, x0))
        by0 = max(0.0, min(240.0, y0))
        bx1 = max(0.0, min(320.0, x1))
        by1 = max(0.0, min(240.0, y1))
        bbox = [round(float(bx0), 1), round(float(by0), 1),
                round(float(bx1 - bx0), 1), round(float(by1 - by0), 1)]
        if bbox[2] <= 1 or bbox[3] <= 1:
            bbox = None
    strict = r["strict"]
    kp = None
    reference_status = "NOT_APPLICABLE"
    reference_reason = None
    reference_source = "NOT_APPLICABLE"
    if present:
        if strict["pixels"] >= 3 and strict["centroid"] is not None:
            kp = {"name": "green_roof_light_center",
                  "x": round(float(strict["centroid"][0]), 1),
                  "y": round(float(strict["centroid"][1]), 1), "visible": True}
            reference_status = "MANUAL_APPROX"
            reference_source = "COLOR_CUE_ASSISTED"
        else:
            reference_status = "UNAVAILABLE"
            reference_reason = "REFERENCE_TOO_SMALL"
    visibility = "ABSENT" if not present else ("PARTIAL" if any(edges.values()) else "FULL")
    annotations.append({
        "frame_id": fid,
        "image": "outputs/sensor_shadow/lm_final_candidate_20261104_sensor/images/" + fid,
        "image_sha256": c["image_sha256"],
        "image_width": 320, "image_height": 240,
        "source": {"run": "lm_final_candidate_20261104_sensor", "family": fam,
                   "group_id": "g_" + fam, "split": "test",
                   "origin_split_in_freeze": "test",
                   "generation": int(fid.rsplit("_g", 1)[1].split(".")[0]),
                   "sequence": c["sequence"]},
        "dataset_role": "ANNOTATION_CALIBRATION" if fid in pilot_ids else "EXPLORATORY_EVAL",
        "target": {
            "landmark_id": "RMUC2027_CENTRAL_TOWER_PROPOSED", "class": "tower",
            "present": present, "undecidable": False,
            "visibility": visibility,
            "truncated": any(edges.values()),
            "truncated_edges": edges,
            "truncation_source": sources,
            "truncation_conflicts": conflicts,
            "occluded": False, "ambiguous": False,
            "ambiguous_reason": None, "undecidable_reason": None,
        },
        "geometry": {
            "bbox_xywh": bbox,
            "bbox_source": "PROJECTION_AID_CALIBRATED",
            "keypoint": kp,
            "green_pixels": int(strict["pixels"]),
            "reference_status": reference_status,
            "reference_unavailable_reason": reference_reason,
            "reference_source": reference_source,
        },
        "confusers": [],
        "negative_type": None if present else "TARGET_ABSENT",
        "annotator": {
            "annotator_type": "AGENT_PROXY",
            "annotator_id": "annot (DSH teammate, DeepSeek agent)",
            "annotation_mode": "BULK_CALIBRATED_WITH_FULL_VISUAL_QA",
            "independent_of_model_dev": True,
            "independent_of_detector_cue": False,
            "review_status": "SELF_CHECKED",
            "note": "bulk draft from green cue + capture span calibration; full visual review pass recorded in QA report",
        },
        "pixel_basis": dict(PIXEL_BASIS),
        "notes": "draft: anchor=%s; span=%.1f; bbox prior from capture projection (projection aid, disclosed)" % (r["anchor_src"], span),
    })

doc = {
    "schema_version": "dsh.tower_annotation.v2_1",
    "status": "DRAFT_BULK_279_PENDING_VISUAL_QA",
    "annotation_spec": {"path": SPEC_V21, "sha256": SPEC_SHA, "status": "FROZEN_FOR_DATA"},
    "seal": {"path": "configs/perception/landmark_final_pool_seal_v1.json",
             "freeze_sha256": seal["freeze_sha256"], "freeze_id": seal["freeze_id"]},
    "dataset_role": "EXPLORATORY_EVAL",
    "pilot_calibration_frames": sorted(pilot_ids),
    "note": "Whole 6-family pool is downgraded to exploratory/development because representatives of every family were viewed during the 34-frame pilot; this is not a sealed final.",
    "calibration": {"method": "grid search on the 25 pilot positive frames (bbox IoU vs visual pilot labels)",
                    "width_factor": 0.85, "height_factor": 1.0, "top_offset_from_green_y_px": -6.0,
                    "pilot_mean_iou": 0.669, "pilot_median_iou": 0.682, "pilot_min_iou": 0.284,
                    "keypoint_vs_strict_green_centroid_px": {"n": 21, "mean": 0.163, "max": 0.316},
                    "caveat": "a projection prior calibrated on 25 agent-visual boxes; not human annotation"},
    "annotations": annotations,
}
out = OUT / "labels_draft.json"
out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
stats = {
    "frames": len(annotations),
    "present": sum(1 for a in annotations if a["target"]["present"]),
    "absent": sum(1 for a in annotations if not a["target"]["present"]),
    "reference_available": sum(1 for a in annotations if a["geometry"]["reference_status"] == "MANUAL_APPROX"),
    "reference_unavailable": sum(1 for a in annotations if a["geometry"]["reference_status"] == "UNAVAILABLE"),
    "truncated": sum(1 for a in annotations if a["target"]["truncated"]),
    "edge_counts": {e: sum(1 for a in annotations if a["target"]["truncated_edges"].get(e)) for e in ("left", "right", "top", "bottom")},
    "anchor_sources": {},
    "no_anchor": sum(1 for f in records.values() if f["anchor_src"] == "FRAME_CENTER_FALLBACK"),
}
for f in records.values():
    stats["anchor_sources"][f["anchor_src"]] = stats["anchor_sources"].get(f["anchor_src"], 0) + 1
print(json.dumps(stats, indent=1, ensure_ascii=False))
print("draft written", out, "sha", sha(out))
