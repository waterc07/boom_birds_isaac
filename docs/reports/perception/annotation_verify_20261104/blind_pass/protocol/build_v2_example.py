"""Build a 3-frame v2 example document from the blind v1 annotations.

Only for demonstrating the v2 validator on real frames (full-visible,
present-with-unavailable-reference, absent-with-similar-structure).  It is NOT
a production label batch and NOT sealed test data.
"""
import hashlib
import json
from pathlib import Path

REPO = Path(r"E:\isaac\proj_boom_birds")
BASE = REPO / "docs/reports/perception/annotation_verify_20261104"
blind = json.loads((BASE / "blind_pass/annotations_blind.json").read_text(encoding="utf-8"))
by_id = {item["frame_id"]: item for item in blind["annotations"]}

PIXEL_BASIS = {
    "image_width": 320, "image_height": 240,
    "fx_px": 160.0, "cx_px": 160.0, "cy_px": 120.0,
    "projection_model": "PINHOLE",
    "bearing_formula": "atan2(x - cx_px, fx_px)",
}

def annotator(note):
    return {
        "annotator_type": "AGENT_PROXY",
        "annotator_id": "annot (DSH teammate, DeepSeek agent)",
        "independent_of_model_dev": True,
        "independent_of_detector_cue": False,
        "review_status": "SELF_CHECKED",
        "note": note,
    }

def source(blind_item):
    s = blind_item["source"]
    return {
        "run": s["run"], "family": s["family"],
        "group_id": s["family"] + "_g" + str(s["generation"]),
        "split": "exposed_development",
        "origin_split_in_freeze": s["origin_split_in_freeze"],
        "generation": s["generation"], "sequence": s["sequence"],
    }

def item(frame_id, target, geometry, negative_type, candidates, notes):
    blind_item = by_id[frame_id]
    return {
        "frame_id": frame_id,
        "image": blind_item["image"],
        "image_sha256": blind_item["image_sha256"],
        "image_width": blind_item["image_width"],
        "image_height": blind_item["image_height"],
        "source": source(blind_item),
        "target": target,
        "geometry": geometry,
        "candidates": candidates,
        "negative_type": negative_type,
        "annotator": annotator(notes),
        "pixel_basis": dict(PIXEL_BASIS),
        "notes": notes,
    }

def target_fields(present, undecidable, visibility, truncated, occluded, ambiguous,
                  ambiguous_reason=None, undecidable_reason=None):
    return {
        "landmark_id": "RMUC2027_CENTRAL_TOWER_PROPOSED", "class": "tower",
        "present": present, "undecidable": undecidable,
        "visibility": visibility, "truncated": truncated, "occluded": occluded,
        "ambiguous": ambiguous, "ambiguous_reason": ambiguous_reason,
        "undecidable_reason": undecidable_reason,
    }

def geom(bbox, kp, status, reason, ref_source):
    return {
        "bbox_xywh": bbox,
        "keypoint": kp,
        "reference_status": status,
        "reference_unavailable_reason": reason,
        "reference_source": ref_source,
    }

doc = {
    "schema_version": "dsh.tower_annotation.v2",
    "status": "V2_VALIDATOR_EXAMPLE_REAL_FRAMES_NOT_PRODUCTION_NOT_SEALED",
    "note": "3 exposed frames re-expressed in schema v2 to exercise the validator: "
            "FULL+visible reference, PARTIAL/truncated+unavailable reference, "
            "ABSENT+similar structure candidate. Not a production label batch.",
    "annotations": [
        item("geo_test_north_0-follow_only_g1_182.png",
             target_fields(True, False, "FULL", False, False, False),
             geom([158, 52, 159, 163],
                  {"name": "green_roof_light_center", "x": 229.0, "y": 59.5, "visible": True},
                  "MANUAL_APPROX", None, "MANUAL_VISUAL"),
             None, [],
             "full tower visible; reference point visually picked from 16x zoom"),
        item("test_north_0-follow_only_g3_181.png",
             target_fields(True, False, "PARTIAL", True, False, False),
             geom([247, 60, 73, 140], None,
                  "UNAVAILABLE", "REFERENCE_OUT_OF_FRAME", "NOT_APPLICABLE"),
             None, [],
             "target present at right edge; head partly out of frame; green roof light not visible; no keypoint guessed"),
        item("geo_test_static_c-follow_only_g4_3.png",
             target_fields(False, False, "ABSENT", False, False, False),
             geom(None, None, "NOT_APPLICABLE", None, "NOT_APPLICABLE"),
             "SIMILAR_STRUCTURE",
             [
                 {"candidate_id": "c_green_tip_pillar",
                  "bbox_xywh": [121, 108, 9, 29], "keypoint": None,
                  "green_cue": {"x": 123, "y": 110}, "source": "ANNOTATOR",
                  "note": "distant tapered structure with dim green tip; identity unresolved"},
                 {"candidate_id": "c_dark_pillar",
                  "bbox_xywh": [288, 99, 24, 42], "keypoint": None,
                  "green_cue": None, "source": "ANNOTATOR",
                  "note": "dark gray column; not the central tower"},
             ],
             "target-absent pose (yaw=pi); competing structures recorded so a green-seeded FP can be counted"),
    ],
}
out = BASE / "blind_pass/protocol/v2_example_annotations.json"
out.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print("wrote", out, "items", len(doc["annotations"]))
