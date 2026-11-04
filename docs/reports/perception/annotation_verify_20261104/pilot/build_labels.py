"""Build the T6 pilot v2 label document from the frozen selection + decisions.

Labels go to outputs/perception/landmark_final_annotations_20261104/labels_v1.json
(gitignored).  Only ids/stats/hashes are written into the repository report.
"""
import hashlib
import json
import time
from pathlib import Path

REPO = Path(r"E:\isaac\proj_boom_birds")
BASE = REPO / "docs/reports/perception/annotation_verify_20261104"
LABEL_DIR = REPO / "outputs/perception/landmark_final_annotations_20261104"
LABEL_DIR.mkdir(parents=True, exist_ok=True)

selection = json.loads((BASE / "pilot/selection.json").read_text(encoding="utf-8"))
decisions = {d["frame_id"]: d for d in json.loads((BASE / "pilot/decisions_partial.json").read_text(encoding="utf-8"))}
corrections = json.loads((BASE / "pilot/corrections.json").read_text(encoding="utf-8"))
seal = json.loads((REPO / "configs/perception/landmark_final_pool_seal_v1.json").read_text(encoding="utf-8"))
spec_path = REPO / "configs/perception/landmark_annotation_spec_v2.json"

GREEN_REF_MIN_PX = 3
PIXEL_BASIS = {
    "image_width": 320, "image_height": 240,
    "fx_px": 160.0, "cx_px": 160.0, "cy_px": 120.0,
    "projection_model": "PINHOLE",
    "bearing_formula": "atan2(x - cx_px, fx_px)",
}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def generation(frame_id):
    return int(frame_id.rsplit("_g", 1)[1].split(".")[0])

annotations = []
for row in selection["frames"]:
    fid = row["frame_id"]
    dec = dict(decisions[fid])
    dec.update(corrections.get(fid, {}))
    green = row["green_pixels"]
    bbox = dec.get("bbox")
    kp = dec.get("kp")
    negative_type = dec.get("negative_type")
    present = bbox is not None
    truncated = bool(dec.get("truncated", row["truncated_right"] or row["truncated_left"]))
    if present:
        visibility = "PARTIAL" if truncated else "FULL"
        if kp is not None:
            geometry = {
                "bbox_xywh": bbox,
                "keypoint": {"name": "green_roof_light_center",
                             "x": float(kp[0]), "y": float(kp[1]), "visible": True},
                "reference_status": "MANUAL_APPROX",
                "reference_unavailable_reason": None,
                "reference_source": "COLOR_CUE_ASSISTED",
            }
            notes = (dec.get("notes", "") +
                     " | reference point taken from the capture-derived green-pixel centroid (colour cue, disclosed); visually confirmed; annotation-source provenance not independent of the detector green cue").strip(" |")
        else:
            geometry = {
                "bbox_xywh": bbox, "keypoint": None,
                "reference_status": "UNAVAILABLE",
                "reference_unavailable_reason": "REFERENCE_TOO_SMALL",
                "reference_source": "NOT_APPLICABLE",
            }
            notes = (dec.get("notes", "") +
                     " | green_pixels=%d <= %d pilot threshold; reference point not observable, no keypoint guessed" % (green, GREEN_REF_MIN_PX)).strip(" |")
    else:
        visibility = "ABSENT"
        geometry = {
            "bbox_xywh": None, "keypoint": None,
            "reference_status": "NOT_APPLICABLE",
            "reference_unavailable_reason": None,
            "reference_source": "NOT_APPLICABLE",
        }
        truncated = False
        notes = dec.get("notes", "")
    annotations.append({
        "frame_id": fid,
        "image": "outputs/sensor_shadow/lm_final_candidate_20261104_sensor/images/" + fid,
        "image_sha256": row["image_sha256"],
        "image_width": 320,
        "image_height": 240,
        "source": {
            "run": "lm_final_candidate_20261104_sensor",
            "family": row["family_id"],
            "group_id": row["group_id"],
            "split": "test",
            "origin_split_in_freeze": "test",
            "generation": generation(fid),
            "sequence": row["sequence"],
        },
        "target": {
            "landmark_id": "RMUC2027_CENTRAL_TOWER_PROPOSED",
            "class": "tower",
            "present": present,
            "undecidable": False,
            "visibility": visibility,
            "truncated": truncated,
            "occluded": False,
            "ambiguous": False,
            "ambiguous_reason": None,
            "undecidable_reason": None,
        },
        "geometry": geometry,
        "candidates": [],
        "negative_type": negative_type if not present else None,
        "annotator": {
            "annotator_type": "AGENT_PROXY",
            "annotator_id": "annot (DSH teammate, DeepSeek agent)",
            "independent_of_model_dev": True,
            "independent_of_detector_cue": False,
            "review_status": "SELF_CHECKED",
            "note": "single-agent pilot annotation; process isolation + hash commitment only, not human review",
        },
        "pixel_basis": dict(PIXEL_BASIS),
        "notes": notes,
    })

doc = {
    "schema_version": "dsh.tower_annotation.v2",
    "status": "T6_PILOT_LABELS_AGENT_PROXY_NOT_FULL_TEST_LABELS",
    "note": "T6 pilot labels on the sealed final candidate pool; 24-36 stratified frames. Not a complete test label set, not human review, not for model/threshold development.",
    "seal": {"path": "configs/perception/landmark_final_pool_seal_v1.json",
             "freeze_sha256": seal["freeze_sha256"], "freeze_id": seal["freeze_id"]},
    "annotation_spec": {"path": "configs/perception/landmark_annotation_spec_v2.json",
                        "sha256": sha(spec_path), "status": "PILOT_FROZEN_LEAD_APPROVED_2026-11-04"},
    "selection": {"path": "docs/reports/perception/annotation_verify_20261104/pilot/selection.json",
                  "rule_id": selection["rule"]["rule_id"], "total_frames": selection["total_frames"],
                  "counts": selection["counts"]},
    "pilot_rules": {
        "green_reference_min_px": GREEN_REF_MIN_PX,
        "truncation": "bbox clipped at frame edge; truncated=true on clipped frames; bottom-edge clipping discovered in near family too",
        "absent": "target absent -> no geometry, negative_type required",
        "reference": "green centroid only when green_pixels >= 3 and visually confirmed; otherwise UNAVAILABLE/REFERENCE_TOO_SMALL",
    },
    "annotations": annotations,
}
label_path = LABEL_DIR / "labels_v1.json"
label_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
label_sha = sha(label_path)

by_family = {}
for a in annotations:
    by_family.setdefault(a["source"]["family"], 0)
    by_family[a["source"]["family"]] += 1
present = [a for a in annotations if a["target"]["present"]]
unavailable = [a for a in present if a["geometry"]["reference_status"] == "UNAVAILABLE"]
manifest = {
    "schema_version": "dsh.landmark_final_pilot_manifest.v1",
    "status": "T6_PILOT_LABELS_PRODUCED_NOT_FULL_TEST_LABELS",
    "generated_at_local": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "seal": doc["seal"],
    "annotation_spec": doc["annotation_spec"],
    "selection": doc["selection"],
    "label_file": {"path": str(label_path.relative_to(REPO)).replace("\\", "/"),
                   "sha256": label_sha, "gitignored": True, "in_git": False},
    "counts": {
        "frames": len(annotations),
        "by_family": by_family,
        "present": len(present),
        "absent": len(annotations) - len(present),
        "reference_available": len(present) - len(unavailable),
        "reference_unavailable": len(unavailable),
        "undecidable": sum(1 for a in annotations if a["target"]["undecidable"]),
        "ambiguous": sum(1 for a in annotations if a["target"]["ambiguous"]),
        "truncated": sum(1 for a in annotations if a["target"]["truncated"]),
        "occluded": sum(1 for a in annotations if a["target"]["occluded"]),
        "negative_type": {nt: sum(1 for a in annotations if a["negative_type"] == nt)
                          for nt in ("TARGET_ABSENT", "SIMILAR_STRUCTURE", "OTHER_LANDMARK")},
    },
    "boundary": "pilot only; same agent annotates and may later develop the model -> process isolation + hash commitment, no statistical independence; labels not in git",
}
labelled = set(a["frame_id"] for a in annotations)
for a in annotations:
    row = next(r for r in selection["frames"] if r["frame_id"] == a["frame_id"])
    if row["image_sha256"] != a["image_sha256"]:
        raise SystemExit("sha mismatch " + a["frame_id"])
( LABEL_DIR / "labels_manifest.json" ).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
(BASE / "pilot/labels_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps({"label_path": str(label_path), "label_sha256": label_sha,
                  "frames": len(annotations), "by_family": by_family,
                  "present": len(present), "absent": len(annotations)-len(present),
                  "unavailable": len(unavailable), "truncated": manifest["counts"]["truncated"]},
                 indent=1, ensure_ascii=False))
