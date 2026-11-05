"""Rebuild T39 shard A labels from capture FINAL conditions (authoritative ms1_bbox_uv)."""
import hashlib, json
from pathlib import Path
from collections import Counter
REPO=Path(r"E:\isaac\proj_boom_birds")
CAP=REPO/"docs/reports/perception/capture_dev_20261104/two_class_near_ms1_20261105"
COND=CAP/"t38_frame_conditions.json"; POOL=CAP/"t38_pool_selection.json"
SPEC=REPO/"configs/perception/landmark_two_class_label_spec_v1.json"
W,H=320,240
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
cond={c["frame_id"]:c for c in json.loads(COND.read_text(encoding="utf-8"))}
pool=json.loads(POOL.read_text(encoding="utf-8"))
ids=[f for f in pool["pool_frame_ids"]]
rows=sorted([cond[f] for f in ids], key=lambda c:(c["frame_id"].split("-follow_only")[0], c["sequence"]))
byfam={}
for c in rows: byfam.setdefault(c["frame_id"].split("-follow_only")[0],[]).append(c)
A=[]
for fam,fr in byfam.items():
    fr=sorted(fr,key=lambda x:x["sequence"]); k=(len(fr)+1)//2; A.extend(fr[:k])
A=sorted(A,key=lambda c:(c["frame_id"].split("-follow_only")[0],c["sequence"]))
def build(rows, outdir, status, shard):
    OUT=Path(outdir); OUT.mkdir(parents=True,exist_ok=True); frames=[]
    for c in rows:
        fid=c["frame_id"]; fam=fid.split("-follow_only")[0]
        img=REPO/"outputs/sensor_shadow/lm_two_class_near_ms1_20261105_pool/images"/fid
        if not img.is_file(): raise SystemExit("missing "+fid)
        bb=c["ms1_bbox_uv"]; tr=c.get("ms1_four_side_truncation") or {}
        x0=max(0.0,min(W,bb["u_min"])); x1=max(0.0,min(W,bb["u_max"]))
        y0=max(0.0,min(H,bb["v_min"])); y1=max(0.0,min(H,bb["v_max"]))
        edges={k:bool(tr.get(k)) for k in ("left","right","top","bottom")}
        frames.append({"frame_id":fid,"image":str(img.relative_to(REPO)).replace("\\","/"),
                       "image_sha256":sha(img),"image_width":W,"image_height":H,"family":fam,"shard":shard,
                       "sequence":c["sequence"],"tower_present":False,"ms1_present":True,
                       "identity_ambiguity":"NONE","gt_uncertainty":"NONE","occlusion":"NONE",
                       "notes":"T38 FINAL capture conditions (ms1_bbox_uv + truncation); class1-only; projection/geometry-assisted + visual spot QA; agent proxy",
                       "other_structures":[],
                       "projection_aid":{"ms1_projected_max_side_px":round(max(bb["width_px"],bb["height_px"]),2),
                                         "tower_projected_max_side_px":0.0},
                       "instances":[{"class":1,"bbox_xyxy":[round(x0,2),round(y0,2),round(x1,2),round(y1,2)],
                                     "truncated_edges":edges,"occluded":False,"keypoint_x":None,"keypoint_y":None,"v":0,
                                     "reference_available":False,"verified_source":"WORLD_POSE_OR_MAP_DB"}]})
    doc={"schema_version":"dsh.landmark_two_class_annotations.v1","status":status,
         "annotation_spec":{"path":"configs/perception/landmark_two_class_label_spec_v1.json","sha256":sha(SPEC)},
         "coordinate_space":{"bbox":"SOURCE_IMAGE_PIXELS_XYXY","keypoint":"SOURCE_IMAGE_PIXELS_NORMALIZED_01"},
         "method":{"bbox":"T38 FINAL capture per-frame ms1_bbox_uv + ms1_four_side_truncation; visual spot QA; projection/geometry-assisted, agent proxy, not independent human GT",
                   "class1_scope":"map-native MS1 only; tower not in FOV"},
         "frames":frames}
    (OUT/"labels_v1.json").write_text(json.dumps(doc,indent=1,ensure_ascii=False)+"\n",encoding="utf-8")
    sel={"schema_version":"dsh.landmark_two_class_selection.v1","status":"T38_FINAL_POOL_"+shard,
         "run":"outputs/sensor_shadow/lm_two_class_near_ms1_20261105_sensor","shard":shard,
         "rule":{"id":"t38_final_pool_"+shard,"text":"final pool 102 accepted; shard A = per-family first ceil(n/2) by sequence; full = all 102","total":len(frames)},
         "per_family":dict(Counter(f["family"] for f in frames)),"frames":frames}
    (OUT/"selection.json").write_text(json.dumps(sel,indent=1,ensure_ascii=False)+"\n",encoding="utf-8")
    return sha(OUT/"labels_v1.json"), sha(OUT/"selection.json")
sa=REPO/"outputs/perception/dev_annotations_20261105/two_class/near_ms1/shard_a"
fu=REPO/"outputs/perception/dev_annotations_20261105/two_class/near_ms1/full"
a_lab,a_sel=build(A,str(sa),"T38_FINAL_SHARD_A_AGENT_PROXY_CAPTURE_CONDITIONS","A")
f_lab,f_sel=build(rows,str(fu),"T38_FINAL_FULL_AGENT_PROXY_CAPTURE_CONDITIONS","full")
print(json.dumps({"A":len(A),"full":len(rows),"A_per_family":dict(Counter(f["family"] for f in A)),
 "A_labels_sha":a_lab,"A_sel_sha":a_sel,"full_labels_sha":f_lab,"full_sel_sha":f_sel},indent=1))
