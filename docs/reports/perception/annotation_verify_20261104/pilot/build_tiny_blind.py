"""Build T16-B blind labels for the 22 TINY frames (v2.1)."""
import hashlib, json
from pathlib import Path
REPO = Path(r"E:\isaac\proj_boom_birds")
BASE = REPO/"docs/reports/perception/annotation_verify_20261104"
LIST = REPO/"docs/reports/perception/posteval_20261104/TINY_BLIND_REANNOTATION_FRAMES_20261104.json"
OUT = BASE/"labels_tiny_blind.json"
spec_sha = hashlib.sha256((REPO/"configs/perception/landmark_annotation_spec_v2_1.json").read_bytes()).hexdigest()
doc = json.loads(LIST.read_text(encoding="utf-8"))
assert hashlib.sha256(LIST.read_bytes()).hexdigest() == "fc3508de23b8d16c593d0e2bad27889de89d3e4ed68a1704e01ba50b37364941"
cues = json.loads((BASE/"pilot/tiny_blind/cues.json").read_text(encoding="utf-8"))

# blind decisions per frame index: (present, undecidable, bbox, keypoint, green_px_override, truncated_edges, confusers, confidence, note)
P = "present"; U = "undecidable"
decisions = {
 0: (False, True, None, None, None, [], [("green_top_pillar", "thin gray pillar with a 1 px strict-green top; consistent with a map-native green lamp/pillar confuser, not the central tower", [116,92,10,43], {"x":122.0,"y":103.0})], "LOW", "far inner_north frame (~20 m): central tower would be about 9 px; cannot distinguish it from the central-field gantry/robots at this resolution; largest strict-green component is on a thin pillar, not on a tower head"),
 1: (False, True, None, None, None, [], [("green_top_pillar", "small structure with a 1 px strict-green top; identity unverified, not the central tower head", [146,105,11,25], {"x":152.0,"y":113.0})], "LOW", "dynamic_A_north far frame: target-sized structure below reliable identifiability; green cue not on a tower head"),
 2: (False, True, None, None, 0, [], [], "LOW", "dev_south_new frame with no strict green; central gantry/robots visible but a ~10 px central tower cannot be identified with confidence"),
 3: (False, True, None, None, None, [], [("green_top_pillar", "thin pillar with a 1 px green top; not a tower head", [113,96,10,40], {"x":118.0,"y":105.0})], "LOW", "sensor_static_0: large gray box/robot dominates; target not identifiable"),
 4: (False, True, None, None, None, [], [("green_top_pillar", "thin pillar with 2 px green top; identity unverified", [117,84,11,40], {"x":123.5,"y":95.0})], "LOW", "inner_north far frame: target-size structure not separable from gantry"),
 5: (False, True, None, None, 0, [], [], "LOW", "dynamic_A_north: no strict green; central structures only, target not identifiable"),
 6: (False, True, None, None, 0, [], [], "LOW", "dev_south_new early frame: target not identifiable among central structures"),
 7: (False, True, None, None, 0, [], [], "LOW", "sensor_static_1: large gantry box/robot; target not identifiable"),
 8: (False, True, None, None, None, [], [("green_lit_object", "small green-lit object next to the gantry/robot; not a central-tower head (no tapered body/head evidence)", [178,108,12,14], {"x":183.33,"y":114.33})], "LOW", "inner_north: strict green (3 px) is on a green-lit object, not on an identifiable tower head"),
 9: (False, True, None, None, None, [], [("green_top_pillar", "small structure with 1 px green top; identity unverified", [185,110,11,20], {"x":190.0,"y":118.0})], "LOW", "test_north far frame: target not identifiable at this scale"),
 10: (False, True, None, None, 0, [], [], "LOW", "sensor_reset route view: gantry/robot structures; target not identifiable"),
 11: (False, True, None, None, None, [], [("green_top_pillar", "thin gray pillar with 2 px green top; map-native lamp/pillar confuser candidate, not a tower", [135,92,12,30], {"x":141.0,"y":97.5})], "LOW", "inner_north: green cue on thin pillar (confuser), tower not identifiable"),
 12: (True, False, [258,104,62,78], [286.5,109.0], None, ["right"], [], "HIGH", "target tower clearly identifiable at right edge, head+arms+green light; right side cut by frame edge"),
 13: (True, False, [72,108,64,58], [86.0,113.5], None, [], [], "HIGH", "target tower clearly identifiable centre-left; full tower with base visible"),
 14: (True, False, [175,132,90,56], [215.5,140.5], None, [], [], "HIGH", "target tower clearly identifiable at static_high view; full tower with base"),
 15: (True, False, [63,108,90,132], [88.5,122.0], None, ["bottom"], [], "HIGH", "target tower clearly identifiable close-up left; body/base continue past the bottom frame edge"),
 16: (True, False, [246,110,46,52], [264.5,115.5], None, [], [], "HIGH", "target tower clearly identifiable centre-right; small but complete"),
 17: (True, False, [26,109,50,57], [48.5,114.0], None, [], [], "HIGH", "target tower clearly identifiable left; full tower with base"),
 18: (False, False, None, None, 0, [], [("gray_pillar", "dark gray tapered pillar without tower head/arms; not the target; identity unverified", [52,124,30,44], None)], "MEDIUM", "static_negative view: no central-tower head/tapered body+green-light structure visible; confirmed absent"),
 19: (False, True, None, None, 0, [], [], "LOW", "dynamic_A_north late frame: near-empty floor/sky, only a very faint unresolved speck; target presence cannot be decided"),
 20: (False, True, None, None, 0, [], [("gray_gantry", "large gray gantry/platform structure right of centre; not a verified tower head", [200,68,72,140], None)], "LOW", "sensor_reset late frame: large gray structure could be the tower seen from an unfavourable angle or the gantry; no green light; identity unresolved"),
 21: (False, False, None, None, 0, [], [("gray_pillar", "map-native gray pillar with red band; not the target", [136,105,14,38], None)], "MEDIUM", "pilot_east_away target-absent pose: no central tower in view"),
}

def geom(present, bbox, kp, green, ref_status, reason, ref_source):
    return {"bbox_xywh": bbox, "bbox_source": "ANNOTATOR_VISUAL",
            "keypoint": kp, "green_pixels": green,
            "reference_status": ref_status, "reference_unavailable_reason": reason,
            "reference_source": ref_source}

annotations = []
for i, fr in enumerate(doc["frames"]):
    present, undecidable, bbox, kp_xy, green_override, trunc_edges, confusers, conf, note = decisions[i]
    cue = cues[fr["frame_id"]]
    green = cue["green_pixels"] if green_override is None else green_override
    edges = {k: (k in trunc_edges) for k in ("left", "right", "top", "bottom")}
    if present:
        kp = {"name": "green_roof_light_center", "x": float(kp_xy[0]), "y": float(kp_xy[1]), "visible": True}
        geometry = geom(True, bbox, kp, green, "MANUAL_APPROX", None, "COLOR_CUE_ASSISTED")
        target = {"landmark_id":"RMUC2027_CENTRAL_TOWER_PROPOSED","class":"tower","present":True,
                  "undecidable":False,"visibility":"PARTIAL" if any(edges.values()) else "FULL",
                  "truncated":any(edges.values()),"truncated_edges":edges,
                  "truncation_source":{e:"ANNOTATOR_VISUAL" for e in trunc_edges},
                  "truncation_conflicts":[],"occluded":False,"ambiguous":False,
                  "ambiguous_reason":None,"undecidable_reason":None}
        negative_type = None
    elif undecidable:
        geometry = {"bbox_xywh":None,"bbox_source":"ANNOTATOR_VISUAL","keypoint":None,
                    "green_pixels":green,"reference_status":"NOT_APPLICABLE",
                    "reference_unavailable_reason":None,"reference_source":"NOT_APPLICABLE"}
        target = {"landmark_id":"RMUC2027_CENTRAL_TOWER_PROPOSED","class":"tower","present":False,
                  "undecidable":True,"visibility":"UNKNOWN","truncated":False,
                  "truncated_edges":{"left":False,"right":False,"top":False,"bottom":False},
                  "truncation_source":{},"truncation_conflicts":[],"occluded":False,
                  "ambiguous":False,"ambiguous_reason":None,
                  "undecidable_reason":"IDENTITY_UNRESOLVED"}
        negative_type = None
    else:
        geometry = geom(False, None, None, green, "NOT_APPLICABLE", None, "NOT_APPLICABLE")
        target = {"landmark_id":"RMUC2027_CENTRAL_TOWER_PROPOSED","class":"tower","present":False,
                  "undecidable":False,"visibility":"ABSENT","truncated":False,
                  "truncated_edges":{"left":False,"right":False,"top":False,"bottom":False},
                  "truncation_source":{},"truncation_conflicts":[],"occluded":False,
                  "ambiguous":False,"ambiguous_reason":None,"undecidable_reason":None}
        negative_type = "TARGET_ABSENT"
    conf_list = []
    for cid, desc, cbbox, cgreen in confusers:
        conf_list.append({"confuser_id":cid,"description":desc,"bbox_xywh":cbbox,
                          "green_cue":cgreen,"verified":False,"verification_source":None,
                          "verification_note":"visual only; identity unverified; not the verified target",
                          "source":"ANNOTATOR"})
    annotations.append({
        "frame_id": fr["frame_id"], "image": fr["image"], "image_sha256": fr["image_sha256"],
        "image_width": 320, "image_height": 240,
        "source": {"run": Path(fr["image"]).parent.parent.name, "family": "tiny_blind_sample",
                   "group_id": "g_tiny_blind", "split": "development",
                   "origin_split_in_freeze": "development_blind_sample",
                   "generation": int(fr["frame_id"].rsplit("_g",1)[1].split(".")[0]),
                   "sequence": int(fr["frame_id"].rsplit("_",1)[1].split(".")[0])},
        "dataset_role": "DEVELOPMENT",
        "target": target, "geometry": geometry, "confusers": conf_list, "candidates": [],
        "negative_type": negative_type,
        "annotator": {"annotator_type":"AGENT_PROXY","annotator_id":"annot (DSH teammate, DeepSeek agent)",
                      "annotation_mode":"FRAME_BY_FRAME_VISUAL","independent_of_model_dev":True,
                      "independent_of_detector_cue":False,"review_status":"SELF_CHECKED",
                      "note":"T16-B blind re-annotation; subjective confidence %s; agent proxy, not human independent review" % conf},
        "pixel_basis": {"image_width":320,"image_height":240,"fx_px":160,"cx_px":160,"cy_px":120,
                        "projection_model":"PINHOLE","bearing_formula":"atan2(x - cx_px, fx_px)"},
        "confidence": conf,
        "notes": note + " | blind: did not read original labels/model predictions/old final results; green_pixels uses the strict cue (g>=90,g-r>=25,g-b>=25, largest 4-connected); reference_source=COLOR_CUE_ASSISTED and independent_of_detector_cue=false (same green cue as the detector).",
    })

out_doc = {
    "schema_version": "dsh.tower_annotation.v2_1",
    "status": "TINY_BLIND_REANNOTATION_AGENT_PROXY_22_FRAMES",
    "annotation_spec": {"path":"configs/perception/landmark_annotation_spec_v2_1.json","sha256":spec_sha,"status":"FROZEN_FOR_DATA"},
    "blind_protocol": {"frame_list":"docs/reports/perception/posteval_20261104/TINY_BLIND_REANNOTATION_FRAMES_20261104.json",
                       "frame_list_sha256":"fc3508de23b8d16c593d0e2bad27889de89d3e4ed68a1704e01ba50b37364941",
                       "blind":True,"did_not_read":["original annotations","model predictions","old final exploratory results"]},
    "note":"Blind development re-annotation for TINY/4-10px annotatability analysis; labels are agent proxy, not human; no original-label coordinates were viewed.",
    "annotations": annotations,
}
OUT.write_text(json.dumps(out_doc, indent=1, ensure_ascii=False)+"\n", encoding="utf-8")
sha = hashlib.sha256(OUT.read_bytes()).hexdigest()
print(json.dumps({"file":str(OUT),"sha256":sha,"frames":len(annotations),
                  "present":sum(1 for a in annotations if a["target"]["present"]),
                  "undecidable":sum(1 for a in annotations if a["target"]["undecidable"]),
                  "absent":sum(1 for a in annotations if not a["target"]["present"] and not a["target"]["undecidable"]),
                  "with_keypoint":sum(1 for a in annotations if a["geometry"]["keypoint"] is not None),
                  "confusers":sum(len(a["confusers"]) for a in annotations)}, indent=1))
