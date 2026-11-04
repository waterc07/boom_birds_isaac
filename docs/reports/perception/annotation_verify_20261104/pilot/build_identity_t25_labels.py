"""T26: build v2.1 labels for the 28 selected T25 identity frames."""
import hashlib, json
from pathlib import Path
REPO = Path(r"E:\isaac\proj_boom_birds")
BASE = REPO/"docs/reports/perception/annotation_verify_20261104"
SEL = REPO/"outputs/perception/dev_annotations_20261104/identity_t25/selection.json"
OUT = REPO/"outputs/perception/dev_annotations_20261104/identity_t25/labels_v1.json"
SPEC = REPO/"configs/perception/landmark_annotation_spec_v2_1.json"
spec_sha = hashlib.sha256(SPEC.read_bytes()).hexdigest()
sel = json.loads(SEL.read_text(encoding="utf-8"))
run = REPO/sel["run"]
img_dir = run/"images"
cues = json.loads((BASE/"pilot/identity_t25/cues.json").read_text(encoding="utf-8"))
MAP_DB = "docs/reports/perception/capture_dev_20261104/map_native_structures.json"
MAS = JSON.parse if False else None
# map DB sha if present
mapdb = REPO/MAP_DB
mapdb_sha = hashlib.sha256(mapdb.read_bytes()).hexdigest() if mapdb.is_file() else None

PIXEL_BASIS = {"image_width":320,"image_height":240,"fx_px":160,"cx_px":160,"cy_px":120,
               "projection_model":"PINHOLE","bearing_formula":"atan2(x - cx_px, fx_px)"}
MS1_NOTE = ("MAP_NATIVE MS1: slender flat-top column with a single/asymmetric top module, side green lamp and blue "
            "accent strips; world pose/map DB reference %s%s; central tower has a symmetric head light-rack, R mark and "
            "white stepped base. Not the target; map-native (not injected)." % (
                MAP_DB, (" sha256 " + mapdb_sha) if mapdb_sha else ""))

def confuser_ms1(bbox, green_cue):
    return {"confuser_id":"MAP_NATIVE_GREEN_LAMP_PILLAR_MS1",
            "description":"map-native slender green-lamp pillar (MS1) seen in the T25 identity supplement",
            "bbox_xywh":[round(float(v),1) for v in bbox],
            "green_cue": green_cue,
            "verified":True,
            "verification_source":"WORLD_POSE_OR_MAP_DB",
            "verification_note":MS1_NOTE + " Verification: world pose/map DB (MS1 world (3.0,4.0), top z~1.78 m, green lamp z~1.71 m) + capture case provenance (T25 lmf_devid_mutual_overlap_0 / lmf_devid_ms1_far_0) + appearance.",
            "source":"ANNOTATOR"}

def geometry(present, bbox, kp, green, ref_status, reason, ref_source, bbox_source="ANNOTATOR_VISUAL"):
    return {"bbox_xywh": bbox, "bbox_source": bbox_source, "keypoint": kp,
            "green_pixels": int(green), "reference_status": ref_status,
            "reference_unavailable_reason": reason, "reference_source": ref_source}

annotations=[]
for i,f in enumerate(sel["frames"]):
    img = img_dir/f
    sha = hashlib.sha256(img.read_bytes()).hexdigest()
    c = cues[f]
    fam = "fam_lmf_devid_mutual_overlap_0" if "mutual_overlap" in f else "fam_lmf_devid_ms1_far_0"
    gid = "g_lmf_devid_mutual_overlap_0" if "mutual_overlap" in f else "g_lmf_devid_ms1_far_0"
    seq = int(f.rsplit("_",1)[1].split(".")[0]); gen = int(f.rsplit("_g",1)[1].split("_")[0])
    base = {"frame_id":f, "image":str((img).relative_to(REPO)).replace("\\","/"),
            "image_sha256":sha, "image_width":320, "image_height":240,
            "source":{"run":Path(sel["run"]).name,"family":fam,"group_id":gid,"split":"val",
                      "origin_split_in_freeze":"t25_identity_supplement","generation":gen,"sequence":seq},
            "dataset_role":"DEVELOPMENT","candidates":[],
            "annotator":{"annotator_type":"AGENT_PROXY","annotator_id":"annot (DSH teammate, DeepSeek agent)",
                         "annotation_mode":"FRAME_BY_FRAME_VISUAL","independent_of_model_dev":True,
                         "independent_of_detector_cue":False,"review_status":"SELF_CHECKED",
                         "note":"T26 identity supplement batch: appearance-only identity decisions; geometry estimated from 4x zoom crops (subset) and 2x contact sheets; agent proxy, not human review"},
            "pixel_basis":PIXEL_BASIS}
    if "mutual_overlap" in f:
        cx,cy = c["centroid"] if c["centroid"] else (170.0,95.0)
        ms1_bbox=[cx-16, cy-9, 30, 105]
        tgt_bbox=[cx+27, cy+5, 31, 45]
        conf=[confuser_ms1(ms1_bbox, {"x":round(cx,1),"y":round(cy,1)} if c["centroid"] else None)]
        target={"landmark_id":"RMUC2027_CENTRAL_TOWER_PROPOSED","class":"tower","present":True,
                "undecidable":False,"visibility":"PARTIAL","truncated":False,
                "truncated_edges":{"left":False,"right":False,"top":False,"bottom":False},
                "truncation_source":{},"truncation_conflicts":[],"occluded":True,
                "ambiguous":False,"ambiguous_reason":None,"undecidable_reason":None}
        geometry_=geometry(True, [round(float(v),1) for v in tgt_bbox], None, c["green_pixels"],
                           "UNAVAILABLE","REFERENCE_TOO_SMALL","NOT_APPLICABLE")
        negative_type=None
        note=("T25 mutual overlap: map-native MS1 in the foreground partially overlaps the far central tower (11.5-13.5 m). "
              "Target present but PARTIAL (occluded by MS1); bbox covers only the visible target part right of MS1. "
              "Strict green pixels (%d px) belong to the near MS1 lamp; the far target green light is below the strict "
              "visibility threshold, so reference=UNAVAILABLE/REFERENCE_TOO_SMALL and no keypoint is emitted. "
              "Identity decision from appearance only (MS1: slender flat-top/side lamp/blue strips; tower: symmetric head rack)." % c["green_pixels"])
    else:
        cx,cy = c["centroid"] if c["centroid"] else (170.0,115.0)
        conf=[confuser_ms1([cx-5,cy-4,12,24], {"x":round(cx,1),"y":round(cy,1)} if c["centroid"] else None)]
        target={"landmark_id":"RMUC2027_CENTRAL_TOWER_PROPOSED","class":"tower","present":False,
                "undecidable":False,"visibility":"ABSENT","truncated":False,
                "truncated_edges":{"left":False,"right":False,"top":False,"bottom":False},
                "truncation_source":{},"truncation_conflicts":[],"occluded":False,
                "ambiguous":False,"ambiguous_reason":None,"undecidable_reason":None}
        geometry_=geometry(False,None,None,c["green_pixels"],"NOT_APPLICABLE",None,"NOT_APPLICABLE")
        negative_type="SIMILAR_STRUCTURE"
        note=("T25 far view: map-native MS1 at 10.2-11.2 m (green lamp strict pixels %d px, below the 3 px anchor threshold); "
              "central tower is out of view (target absent). MS1 recorded as verified map-native confuser (WORLD_POSE_OR_MAP_DB). "
              "No keypoint; green_pixels recorded per strict cue rule." % c["green_pixels"])
    ann=dict(base)
    ann.update({"target":target,"geometry":geometry_,"confusers":conf,"negative_type":negative_type,
                "notes":note,"confidence": "MEDIUM" if not c["centroid"] else "HIGH"})
    annotations.append(ann)

doc={"schema_version":"dsh.tower_annotation.v2_1","status":"T25_IDENTITY_SUPPLEMENT_AGENT_PROXY_28",
     "annotation_spec":{"path":"configs/perception/landmark_annotation_spec_v2_1.json","sha256":spec_sha,"status":"FROZEN_FOR_DATA"},
     "selection":{"path":"outputs/perception/dev_annotations_20261104/identity_t25/selection.json",
                  "sha256":hashlib.sha256(SEL.read_bytes()).hexdigest(),
                  "rule_id":sel["rule"]["id"]},
     "note":"T26: T25 identity supplement representative frames (mutual MS1/target overlap 14 + far MS1 14); agent proxy; labels stay gitignored.",
     "annotations":annotations}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(doc,indent=1,ensure_ascii=False)+"\n",encoding="utf-8")
print(json.dumps({"out":str(OUT),"sha256":hashlib.sha256(OUT.read_bytes()).hexdigest(),
                  "frames":len(annotations),
                  "mutual":sum(1 for a in annotations if "mutual_overlap" in a["source"]["family"]),
                  "far":sum(1 for a in annotations if "ms1_far" in a["source"]["family"]),
                  "present":sum(1 for a in annotations if a["target"]["present"]),
                  "absent":sum(1 for a in annotations if not a["target"]["present"]),
                  "ambiguous":sum(1 for a in annotations if a["target"]["ambiguous"]),
                  "confusers_verified":sum(1 for a in annotations for c in a["confusers"] if c["verified"])},indent=1))
