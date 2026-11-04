"""Finalize the 279-frame exploratory labels: corrections, notes, manifest."""
import hashlib
import json
from pathlib import Path

REPO = Path(r"E:\isaac\proj_boom_birds")
BASE = REPO / "docs/reports/perception/annotation_verify_20261104"
OUT = REPO / "outputs/perception/final_exploratory_20261104"
LABEL_DIR_PILOT = REPO / "outputs/perception/landmark_final_annotations_20261104"
spec_path = REPO / "configs/perception/landmark_annotation_spec_v2_1.json"
spec_sha = hashlib.sha256(spec_path.read_bytes()).hexdigest()
seal = json.loads((REPO / "configs/perception/landmark_final_pool_seal_v1.json").read_text(encoding="utf-8"))
cond = {r["frame_id"]: r for r in json.loads((REPO / "docs/reports/perception/capture_20261104/frame_conditions.json").read_text(encoding="utf-8"))}
draft = json.loads((OUT / "labels_draft.json").read_text(encoding="utf-8"))
pilot = json.loads((LABEL_DIR_PILOT / "labels_v1.json").read_text(encoding="utf-8"))
pilot_by = {a["frame_id"]: a for a in pilot["annotations"]}
pilot_ids = sorted(pilot_by)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

CORRECTIONS = {
    # no-green backoff frame: draft used a frame-centre-ish anchor from interpolation; visual read fixes it
    "lmf_backoff_0-follow_only_g2_69.png": {
        "bbox_xywh": [129.0, 115.0, 47.0, 46.0],
        "note": "bbox corrected during full visual QA: no green pixels (anchor fallback), visual box only",
    },
}

def iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix0, iy0 = max(ax, bx), max(ay, by)
    ix1, iy1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0

corrections_applied = []
for ann in draft["annotations"]:
    fid = ann["frame_id"]
    fam = ann["source"]["family"]
    c = cond[fid]
    t = ann["target"]
    g = ann["geometry"]
    if fid in CORRECTIONS:
        fix = CORRECTIONS[fid]
        g["bbox_xywh"] = fix["bbox_xywh"]
        ann["notes"] = fix["note"]
        corrections_applied.append(fid)
    # notes: make each annotation self-explanatory
    if t["present"]:
        edge_note = ", ".join(e for e in ("left", "right", "top", "bottom") if t["truncated_edges"].get(e)) or "none"
        if g["reference_status"] == "MANUAL_APPROX":
            ref_note = "reference from strict green centroid (green_pixels=%d)" % g["green_pixels"]
        else:
            ref_note = "reference UNAVAILABLE: green_pixels=%d < 3 (REFERENCE_TOO_SMALL)" % g["green_pixels"]
        ann["notes"] = ("bulk draft bbox from capture span prior calibrated on pilot frames; "
                        "visually reviewed on QA sheet; truncated edges=%s; %s" % (edge_note, ref_note))
    else:
        if fam == "lmf_side_negative":
            ann["notes"] = ("target absent: tower physically present but fully outside camera FOV "
                            "(static side pose, yaw +pi/2); no green; no confusers recorded")
        else:
            ann["notes"] = ("target absent: camera faces away (bearing ~180 deg); central-field structures "
                            "visible but not verified as a similar tower; green_pixels=%d (sub-threshold); "
                            "no confusers recorded; HN1 remains unverified" % g["green_pixels"])
    ann["annotator"]["note"] = ("bulk calibrated draft + full visual review (24 contact sheets, 12 frames each); "
                                "bbox_source=PROJECTION_AID_CALIBRATED; reference_source=COLOR_CUE_ASSISTED; "
                                "not human annotation")

# pilot vs final consistency on the 34 calibration frames
pilot_consistency = {"frames": 0, "presence_agree": 0, "truncated_agree": 0,
                     "keypoint_compared": 0, "keypoint_dist_px": [],
                     "bbox_iou": []}
for fid in pilot_ids:
    p = pilot_by[fid]
    f = next(a for a in draft["annotations"] if a["frame_id"] == fid)
    pilot_consistency["frames"] += 1
    pilot_consistency["presence_agree"] += int(p["target"]["present"] == f["target"]["present"])
    pilot_consistency["truncated_agree"] += int(bool(p["target"]["truncated"]) == bool(f["target"]["truncated"]))
    if p["target"]["present"] and f["target"]["present"] and p["geometry"]["bbox_xywh"] and f["geometry"]["bbox_xywh"]:
        pilot_consistency["bbox_iou"].append(iou(p["geometry"]["bbox_xywh"], f["geometry"]["bbox_xywh"]))
    pk, fk = p["geometry"]["keypoint"], f["geometry"]["keypoint"]
    if pk and fk:
        pilot_consistency["keypoint_compared"] += 1
        pilot_consistency["keypoint_dist_px"].append(
            ((pk["x"] - fk["x"]) ** 2 + (pk["y"] - fk["y"]) ** 2) ** 0.5)

def stats(vals):
    vals = sorted(vals)
    if not vals:
        return None
    n = len(vals)
    return {"n": n, "mean": round(sum(vals) / n, 3), "median": round(vals[n // 2], 3),
            "min": round(vals[0], 3), "max": round(vals[-1], 3)}

pilot_consistency["bbox_iou"] = stats(pilot_consistency["bbox_iou"])
pilot_consistency["keypoint_dist_px"] = stats(pilot_consistency["keypoint_dist_px"])

# QA sheet metadata
sheets = json.loads((BASE / "pilot/qa_sheets_index.json").read_text(encoding="utf-8"))
qa = {
    "method": "BULK_CALIBRATED_WITH_FULL_VISUAL_QA",
    "bbox_prior": "capture predicted tower span + calibrated 0.85/1.0 factors, top = green_y - 6",
    "calibration_pilot_frames": 25,
    "calibration_pilot_bbox_iou": {"mean": 0.669, "median": 0.682},
    "visual_review": "all 279 frames rendered as 24 contact sheets (12 frames per sheet, native resolution, bbox+keypoint overlay) and reviewed",
    "contact_sheets": 24,
    "contact_sheet_dir": "docs/reports/perception/annotation_verify_20261104/pilot/qa_sheets",
    "contact_sheet_index_sha256": sha(BASE / "pilot/qa_sheets_index.json"),
    "per_frame_corrections": corrections_applied,
    "flags": {
        "anchor_relaxed_green": 43,
        "anchor_neighbour_interpolated": 6,
        "anchor_frame_center_fallback": 3,
        "note": "the 3 frame-centre fallbacks belong to lmf_side_negative (absent frames, no bbox); "
                "the only present frame with a fallback/interpolated anchor (g2_69) was corrected visually",
    },
    "disputed_frames": [],
    "expected_sequence_outliers": "19 centre/size jumps coincide with trajectory waypoint transitions (camera height/yaw changes), reviewed and accepted",
}

# absent frames never carry truncation flags (no target pixels to clip)
for ann in draft["annotations"]:
    if not ann["target"]["present"]:
        ann["target"]["truncated_edges"] = {"left": False, "right": False,
                                            "top": False, "bottom": False}
        ann["target"]["truncation_source"] = {}
        ann["target"]["truncation_conflicts"] = []
        ann["target"]["truncated"] = False

# final counts
byfam = {}
for a in draft["annotations"]:
    fam = a["source"]["family"]
    b = byfam.setdefault(fam, {"frames": 0, "present": 0, "absent": 0,
                               "reference_available": 0, "reference_unavailable": 0,
                               "truncated": 0, "right": 0, "bottom": 0})
    b["frames"] += 1
    if a["target"]["present"]:
        b["present"] += 1
        if a["geometry"]["reference_status"] == "MANUAL_APPROX":
            b["reference_available"] += 1
        else:
            b["reference_unavailable"] += 1
    else:
        b["absent"] += 1
    b["truncated"] += int(a["target"]["truncated"])
    b["right"] += int(a["target"]["truncated_edges"]["right"])
    b["bottom"] += int(a["target"]["truncated_edges"]["bottom"])

counts = {
    "frames": len(draft["annotations"]),
    "present": sum(1 for a in draft["annotations"] if a["target"]["present"]),
    "absent": sum(1 for a in draft["annotations"] if not a["target"]["present"]),
    "reference_available": sum(1 for a in draft["annotations"] if a["geometry"]["reference_status"] == "MANUAL_APPROX"),
    "reference_unavailable": sum(1 for a in draft["annotations"] if a["geometry"]["reference_status"] == "UNAVAILABLE"),
    "truncated": sum(1 for a in draft["annotations"] if a["target"]["truncated"]),
    "truncated_edges": {e: sum(1 for a in draft["annotations"] if a["target"]["truncated_edges"].get(e))
                        for e in ("left", "right", "top", "bottom")},
    "undecidable": sum(1 for a in draft["annotations"] if a["target"]["undecidable"]),
    "ambiguous": sum(1 for a in draft["annotations"] if a["target"]["ambiguous"]),
    "occluded": sum(1 for a in draft["annotations"] if a["target"]["occluded"]),
    "gt_unobservable": sum(1 for a in draft["annotations"]
                           if a["target"]["undecidable"] or a["target"]["visibility"] == "OCCLUDED"),
    "negative_type": {n: sum(1 for a in draft["annotations"] if a["negative_type"] == n)
                      for n in ("TARGET_ABSENT", "SIMILAR_STRUCTURE", "OTHER_LANDMARK")},
    "annotation_calibration_frames": sum(1 for a in draft["annotations"] if a["dataset_role"] == "ANNOTATION_CALIBRATION"),
    "exploratory_frames": sum(1 for a in draft["annotations"] if a["dataset_role"] == "EXPLORATORY_EVAL"),
    "by_family": byfam,
}

doc = dict(draft)
doc["status"] = "EXPLORATORY_LABELS_AGENT_PROXY_BULK_CALIBRATED_WITH_FULL_VISUAL_QA"
doc["annotation_spec"] = {"path": "configs/perception/landmark_annotation_spec_v2_1.json",
                          "sha256": spec_sha, "status": "FROZEN_FOR_DATA"}
doc["seal"] = {"path": "configs/perception/landmark_final_pool_seal_v1.json",
               "freeze_sha256": seal["freeze_sha256"], "freeze_id": seal["freeze_id"],
               "original_status": seal["status"],
               "effective_status": "DOWNGRADED_TO_DEVELOPMENT_EXPLORATORY_AFTER_34_FRAME_PILOT"}
doc["dataset_role"] = "DEVELOPMENT_EXPLORATORY"
doc["pilot_calibration_frames"] = pilot_ids
doc["pilot_to_development_transfer"] = {
    "pilot_frames": len(pilot_ids),
    "pilot_status": "MOVED_TO_DEVELOPMENT_ANNOTATION_CALIBRATION",
    "reason": "representatives of every one of the 6 families were viewed during the 34-frame pilot, so the whole 6-family pool is contaminated for sealed-final purposes; removing the 34 frames is not enough",
    "not_sealed": True,
    "same_group_contamination": "all 6 families are affected (6/6); no family remains untouched",
}
doc["visual_qa"] = qa
doc["pilot_label_consistency"] = pilot_consistency
doc["counts"] = counts
doc["note"] = ("279-frame exploratory labels on the T1 final candidate pool after it was downgraded to development/exploratory "
               "by the 34-frame pilot; not a sealed final, not human annotation, not model/training evidence.")

final_path = OUT / "labels_v1.json"
final_path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
final_sha = sha(final_path)

manifest = {
    "schema_version": "dsh.landmark_exploratory_labels_manifest.v1",
    "status": doc["status"],
    "generated_at_local": "2026-11-04",
    "label_file": {"path": str(final_path.relative_to(REPO)).replace("\\", "/"),
                   "sha256": final_sha, "gitignored": True, "in_git": False},
    "draft_file": {"path": str((OUT / "labels_draft.json").relative_to(REPO)).replace("\\", "/"),
                   "sha256": sha(OUT / "labels_draft.json")},
    "annotation_spec": doc["annotation_spec"],
    "seal": doc["seal"],
    "dataset_role": doc["dataset_role"],
    "pilot_to_development_transfer": doc["pilot_to_development_transfer"],
    "counts": counts,
    "visual_qa": qa,
    "pilot_label_consistency": pilot_consistency,
    "validator": {"status": "PENDING_RUN", "errors": None, "warnings": None},
    "boundary": ("exploratory/development labels produced by a single agent proxy (bbox from a calibrated projection prior + full visual QA, "
                 "reference point from the green colour cue); not human independent annotation, not certification-grade, not for sealed-final claims"),
}
for target in (OUT / "labels_manifest.json", BASE / "pilot/final_exploratory_labels_manifest.json"):
    target.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({"final": str(final_path), "sha256": final_sha}, indent=1))
print(json.dumps(counts, indent=1, ensure_ascii=False))
print(json.dumps(pilot_consistency, indent=1, ensure_ascii=False))
print(json.dumps(qa, indent=1, ensure_ascii=False))
