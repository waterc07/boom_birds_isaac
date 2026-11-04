# -*- coding: utf-8 -*-
"""Generate the pre-registered TINY/4-10px blind re-annotation plan."""
import hashlib, json, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / "docs/reports/perception/posteval_20261104"
def load(p): return json.loads((ROOT / p).read_text(encoding="utf-8"))
train = load("outputs/perception/dev_annotations_20261104/labels_train.json")
val = load("outputs/perception/dev_annotations_20261104/labels_val.json")

def size(a):
    b = (a.get("geometry") or {}).get("bbox_xywh")
    return max(float(b[2]), float(b[3])) if b else float("inf")

def fam(a): return (a.get("source") or {}).get("family") or "UNSPECIFIED"

def select(pool, n):
    groups = collections.defaultdict(list)
    for a in pool: groups[fam(a)].append(a)
    for f in groups: groups[f].sort(key=lambda a: (size(a) if size(a) != float("inf") else 1e9, a["frame_id"]))
    out = []; names = sorted(groups)
    while len(out) < n:
        progressed = False
        for f in names:
            if len(out) >= n: break
            if groups[f]: out.append(groups[f].pop(0)); progressed = True
        if not progressed: break
    return out

annotations = train["annotations"] + val["annotations"]
tiny_pool, green_pool, control_pool = [], [], []
for a in annotations:
    t = a.get("target") or {}; g = a.get("geometry") or {}
    if t.get("present") is not True:
        if t.get("undecidable") is not True and a.get("negative_type") == "TARGET_ABSENT":
            control_pool.append(a)
        continue
    if g.get("bbox_xywh") is None: continue
    s = size(a)
    if s <= 14.0: tiny_pool.append(a); continue
    kp = g.get("keypoint"); gp = int(g.get("green_pixels") or 0)
    if kp is not None and kp.get("visible") is True and 3 <= gp <= 49:
        green_pool.append(a)

tiny = select(tiny_pool, 12)
green = select(green_pool, 6)
controls = select(control_pool, 4)
print("pools tiny", len(tiny_pool), "green", len(green_pool), "control", len(control_pool))
print("selected", len(tiny), len(green), len(controls))

criteria = {
  "blind": True,
  "selection_source": "development labels only (labels_train.json + labels_val.json); the old final exploratory predictions/metrics are never used to choose frames",
  "annotation_spec": "configs/perception/landmark_annotation_spec_v2_1.json (sha 010255d9..., FROZEN_FOR_DATA)",
  "bbox_convention": "spec v2.1 tower box: head/light-rack + tan body + attached stepped base, clipped at every true image edge; independent visual judgement only, no capture projection prior, no original label",
  "reference_rule": "strict green cue ONLY: g>=90, g-r>=25, g-b>=25, largest 4-connected component; keypoint non-null ONLY when green_pixels>=3 AND the green roof-light is visually confirmed at the annotated position; otherwise keypoint=null + reference_status=UNAVAILABLE + reason (REFERENCE_TOO_SMALL / REFERENCE_OCCLUDED / REFERENCE_NOT_PRESENT)",
  "green_pixels_recording": "integer pixel count of the strict-green largest 4-connected component (same rule above), recorded even when below 3",
  "color_cue_provenance": "record geometry.reference_source=COLOR_CUE_ASSISTED and annotator.independent_of_detector_cue=false; the reference point and the detector cue are the SAME operational cue, so agreement with existing anchors is same-source reproducibility, not independent physical accuracy",
  "undecidable_policy": "presence cannot be decided -> undecidable=true, no bbox/keypoint, no negative_type; never guess",
  "ambiguous_policy": "multiple equally plausible target candidates -> ambiguous=true + candidates[]; never emit a guessed keypoint",
  "truncation_policy": "record left/right/top/bottom with truncation_source=ANNOTATOR_VISUAL; target.truncated = any(edge)",
  "confuser_policy": "record visible non-target green structures in confusers[] with verified=false unless verified by a non-image source; unverified confusers under TARGET_ABSENT only",
  "disagreement_metrics": ["presence agreement", "reference-availability agreement", "bbox IoU", "keypoint Euclidean px", "image bearing deg", "truncation-edge agreement"],
  "pre_registered_pass_criteria": {"presence_agreement_min": 0.90, "reference_availability_agreement_min": 0.90, "keypoint_median_px_max": 2.0, "keypoint_p90_px_max": 4.0, "bbox_iou_median_min": 0.50},
  "size_note": "development target max-side floor is about 9.3 px; a pure 4-8 px target range is absent from development data, so any sub-9.3 px annotatability conclusion stays UNKNOWN/extrapolated",
  "independence": "blind: the frame list below carries no original coordinates and no model output; do not open labels_train/labels_val, freeze files or prediction files while labelling"
}

def record(a, role):
    return {"frame_id": a["frame_id"], "image": a.get("image"), "image_sha256": a.get("image_sha256"),
            "image_width": a.get("image_width"), "image_height": a.get("image_height"),
            "family": fam(a), "role": role, "target_max_side_px": round(size(a), 2) if size(a) != float("inf") else None}

plan = {
  "schema_version": "dsh.landmark_tiny_blind_plan.v1",
  "created_at": "2026-11-04",
  "status": "PREREGISTERED_BEFORE_ANNOT_LABELS",
  "max_side_px": 14.0,
  "sampling": {"tiny_pool": len(tiny_pool), "small_green_pool": len(green_pool), "control_pool": len(control_pool),
               "selected_tiny": len(tiny), "selected_small_green": len(green), "selected_control": len(controls),
               "note": "roles withheld from the blind frame list; role mapping recomputable from the frozen development annotations"},
  "selection_rule": "round-robin across families (sorted), each family ordered by (target max side, frame_id); controls ordered by frame_id",
  "criteria": criteria,
  "frames": [record(a, "tiny_positive") for a in tiny] + [record(a, "small_green_cue") for a in green] + [record(a, "control_absent") for a in controls]
}

# verify image files and hashes
missing = []; sha_bad = []
for f in plan["frames"]:
    p = ROOT / f["image"].replace("\\", "/")
    if not p.is_file(): missing.append(str(f["image"])); continue
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    if f["image_sha256"] and h != f["image_sha256"]: sha_bad.append(f["frame_id"])
plan["validation"] = {"images_missing": missing, "sha_mismatch": sha_bad, "checked": len(plan["frames"])}

(OUT / "TINY_BLIND_REANNOTATION_KEY_20261104.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
public = {
  "schema_version": "dsh.landmark_tiny_blind_frames.v1",
  "created_at": "2026-11-04",
  "blind": True,
  "criteria": criteria,
  "selection_rule": plan["selection_rule"],
  "sampling": {"total": len(plan["frames"]), "note": "stratified development sample; per-frame strata withheld to preserve blindness"},
  "frames": [{"frame_id": f["frame_id"], "image": f["image"], "image_sha256": f["image_sha256"], "image_width": f["image_width"], "image_height": f["image_height"]} for f in plan["frames"]],
}
(OUT / "TINY_BLIND_REANNOTATION_FRAMES_20261104.json").write_text(json.dumps(public, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("WROTE plan + public list")
print("missing", missing, "sha_bad", sha_bad)
for f in plan["frames"]: print(f["role"], f["frame_id"], f["family"], f["target_max_side_px"])
