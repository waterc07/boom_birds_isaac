"""Build a 5-frame v2.1 validation example from the 34-frame pilot labels."""
import hashlib
import json
from pathlib import Path

REPO = Path(r"E:\isaac\proj_boom_birds")
BASE = REPO / "docs/reports/perception/annotation_verify_20261104"
spec_sha = (BASE / "pilot/spec_v2_1_sha.txt").read_text(encoding="utf-8").strip()
pilot = json.loads((BASE / "pilot/labels_manifest.json").read_text(encoding="utf-8"))
labels = json.loads((REPO / "outputs/perception/landmark_final_annotations_20261104/labels_v1.json").read_text(encoding="utf-8"))
cond = {r["frame_id"]: r for r in json.loads((REPO / "docs/reports/perception/capture_20261104/frame_conditions.json").read_text(encoding="utf-8"))}
by_id = {a["frame_id"]: a for a in labels["annotations"]}

PIXEL_BASIS = {"image_width": 320, "image_height": 240, "fx_px": 160.0,
               "cx_px": 160.0, "cy_px": 120.0, "projection_model": "PINHOLE",
               "bearing_formula": "atan2(x - cx_px, fx_px)"}

def convert(frame_id, edges, sources, conflicts, negative_type, confusers, notes):
    src_ann = by_id[frame_id]
    c = cond[frame_id]
    green = c["green_pixels"]
    ann = {
        "frame_id": frame_id,
        "image": src_ann["image"],
        "image_sha256": src_ann["image_sha256"],
        "image_width": 320, "image_height": 240,
        "source": dict(src_ann["source"]),
        "dataset_role": "ANNOTATION_CALIBRATION",
        "target": {
            "landmark_id": "RMUC2027_CENTRAL_TOWER_PROPOSED", "class": "tower",
            "present": src_ann["target"]["present"],
            "undecidable": False,
            "visibility": src_ann["target"]["visibility"],
            "truncated": any(edges.values()),
            "truncated_edges": dict(edges),
            "truncation_source": dict(sources),
            "truncation_conflicts": list(conflicts),
            "occluded": False,
            "ambiguous": False,
            "ambiguous_reason": None,
            "undecidable_reason": None,
        },
        "geometry": {
            "bbox_xywh": src_ann["geometry"]["bbox_xywh"],
            "bbox_source": "ANNOTATOR_VISUAL",
            "keypoint": src_ann["geometry"]["keypoint"],
            "green_pixels": green,
            "reference_status": src_ann["geometry"]["reference_status"],
            "reference_unavailable_reason": src_ann["geometry"]["reference_unavailable_reason"],
            "reference_source": src_ann["geometry"]["reference_source"],
        },
        "confusers": confusers,
        "negative_type": negative_type,
        "annotator": {
            "annotator_type": "AGENT_PROXY",
            "annotator_id": "annot (DSH teammate, DeepSeek agent)",
            "annotation_mode": "FRAME_BY_FRAME_VISUAL",
            "independent_of_model_dev": True,
            "independent_of_detector_cue": False,
            "review_status": "SELF_CHECKED",
            "note": "v2.1 validator example on real pilot frames; not a production label batch",
        },
        "pixel_basis": dict(PIXEL_BASIS),
        "notes": notes,
    }
    return ann

doc = {
    "schema_version": "dsh.tower_annotation.v2_1",
    "status": "V21_VALIDATOR_EXAMPLE_REAL_FRAMES_NOT_PRODUCTION",
    "annotation_spec": {"path": "configs/perception/landmark_annotation_spec_v2_1.json",
                        "sha256": spec_sha, "status": "FROZEN_FOR_DATA"},
    "note": "5 real frames re-expressed in v2.1 to exercise the validator: normal, bottom truncation (metadata conflict), right truncation (metadata agree), unavailable reference, TARGET_ABSENT + unverified confuser.",
    "annotations": [
        convert("lmf_sweep_0-follow_only_g1_9.png",
                {"left": False, "right": False, "top": False, "bottom": False}, {},
                [], None, [],
                "normal full tower; reference from colour cue, green_pixels=8"),
        convert("lmf_near_0-follow_only_g3_5.png",
                {"left": False, "right": False, "top": False, "bottom": True},
                {"bottom": "ANNOTATOR_VISUAL"},
                [{"edge": "bottom", "capture": False, "annotator": True,
                  "resolution": "ANNOTATOR_OVER_CAPTURE"}],
                None, [],
                "bottom base pedestal clipped; capture metadata only tracked left/right (recorded conflict)"),
        convert("lmf_edge_0-follow_only_g4_10.png",
                {"left": False, "right": True, "top": False, "bottom": False},
                {"right": "BOTH"}, [], None, [],
                "right-edge truncation; capture metadata and annotator agree"),
        convert("lmf_backoff_0-follow_only_g2_60.png",
                {"left": False, "right": False, "top": False, "bottom": False}, {},
                [], None, [],
                "8.0 m; green_pixels=1 < 3 -> UNAVAILABLE/REFERENCE_TOO_SMALL"),
        convert("lmf_similar_negative_0-follow_only_g5_6.png",
                {"left": False, "right": False, "top": False, "bottom": False}, {},
                [], "TARGET_ABSENT",
                [{"confuser_id": "c_dark_pillar",
                  "description": "distant dark tower-like pillar at the right edge; identity unverified",
                  "bbox_xywh": [300, 95, 20, 65], "green_cue": None,
                  "verified": False, "verification_source": None,
                  "verification_note": "visual only; no world-pose/map check, NOT a verified similar tower",
                  "source": "ANNOTATOR"}],
                "target absent (camera yaw ~180 deg); central-field structure recorded as unverified confuser"),
    ],
}
out = BASE / "pilot/v2_1_example_annotations.json"
out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print("wrote", out, "items", len(doc["annotations"]), "spec sha", spec_sha[:12])
