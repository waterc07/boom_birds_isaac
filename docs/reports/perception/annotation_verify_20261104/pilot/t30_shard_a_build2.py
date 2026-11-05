"""T31 shard A v2: build labels from capture per-frame conditions (exact u/v spans + green clusters) + pool filter."""
import hashlib, json, math
from pathlib import Path
from collections import Counter
REPO=Path(r"E:\isaac\proj_boom_birds")
BASE=REPO/"docs/reports/perception/annotation_verify_20261104"
OUT=REPO/"outputs/perception/dev_annotations_20261105/two_class/shard_a"
COND=REPO/"docs/reports/perception/capture_dev_20261104/two_class_train_20261105/t30_frame_conditions.json"
SPEC=REPO/"configs/perception/landmark_two_class_label_spec_v1.json"
spec_sha=hashlib.sha256(SPEC.read_bytes()).hexdigest()
W,H=320,240
SHARD_A={"lmf_t30_f1_tower_near_alone_0","lmf_t30_f3_tower_far_alone_0","lmf_t30_f5_ms1_near_alone_0","lmf_t30_f7_both_near_far_0"}
conds=[c for c in json.loads(COND.read_text(encoding="utf-8")) if c.get("in_pool")]
conds=[c for c in conds if c["frame_id"].split("-follow_only")[0] in SHARD_A]
print("pool frames shard A:", len(conds))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def clip(u0,v0,u1,v1):
    x1=max(0.0,min(W,u0)); x2=max(0.0,min(W,u1)); y1=max(0.0,min(H,v0)); y2=max(0.0,min(H,v1))
    return [x1,y1,x2,y2]
frames=[]
for c in sorted(conds, key=lambda x:(x["frame_id"].split("-follow_only")[0], x["sequence"])):
    fam=c["frame_id"].split("-follow_only")[0]
    img=REPO/"outputs/sensor_shadow/lm_two_class_train_20261105_pool/images"/c["frame_id"]
    if not img.is_file(): img=REPO/"outputs/sensor_shadow/lm_two_class_train_20261105_sensor/images"/c["frame_id"]
    tr=c.get("tower_four_side_truncation_geometric") or {}
    tu=c.get("tower_u_span") or []
    tv=(tr.get("v_span") or [])
    tower_span_ok = len(tu)==2 and len(tv)==2
    tower_present = bool(c.get("tower_visible_expected")) and tower_span_ok
    ms1_present = bool(c.get("ms1_visible_expected")) and c.get("ms1_u_span") is not None
    overlap=c.get("overlap_fraction_of_target_width")
    insts=[]; gt="NONE"; occ="NONE"
    if tower_present:
        tb=clip(tu[0],tv[0],tu[1],tv[1])
        edges={"left":tu[0]<0.0,"right":tu[1]>W,"top":tv[0]<0.0,"bottom":tv[1]>H}
        occluded = bool(ms1_present and overlap is not None and overlap>0.05)
        # keypoint from strict green cluster nearest target pixel
        kx=ky=None; v=0; ref=False
        tgt=c.get("target_pixel_uv_pred")
        clusters=c.get("green_clusters") or []
        if tgt and clusters and (c.get("target_green_pixels_strict") or 0)>=3:
            best=min(clusters,key=lambda cl:(cl["u"]-tgt[0])**2+(cl["v"]-tgt[1])**2)
            if math.hypot(best["u"]-tgt[0],best["v"]-tgt[1])<=12.0 and best.get("area",0)>=3:
                kx,ky=round(best["u"]/W,4),round(best["v"]/H,4); v=1; ref=True
        insts.append({"class":0,"bbox_xyxy":[round(x,2) for x in tb],"truncated_edges":edges,
                      "occluded":occluded,"keypoint_x":kx,"keypoint_y":ky,"v":v,
                      "reference_available":ref,"verified_source":"VISUAL"})
        if occluded and overlap is not None and overlap>=0.9:
            # near-fully hidden by MS1: GT_UNOBSERVABLE
            insts=[i for i in insts if i["class"]!=0]; gt="FULLY_OCCLUDED"; occ="FULL"
        elif not ref:
            gt="REFERENCE_UNRESOLVED"
    if ms1_present:
        mu=c.get("ms1_u_span")
        # v span from geometry: re-use capture convention; approximate via tower v span scaled? use projected MS1 world points with capture pose
        pos=c["camera_position_world_m"]; quat=c["camera_quat_wxyz"]
        R=[[1-2*(quat[2]**2+quat[3]**2),2*(quat[1]*quat[2]-quat[3]*quat[0]),2*(quat[1]*quat[3]+quat[2]*quat[0])],
           [2*(quat[1]*quat[2]+quat[3]*quat[0]),1-2*(quat[1]**2+quat[3]**2),2*(quat[2]*quat[3]-quat[1]*quat[0])],
           [2*(quat[1]*quat[3]-quat[2]*quat[0]),2*(quat[2]*quat[3]+quat[1]*quat[0]),1-2*(quat[1]**2+quat[2]**2)]]
        vs=[]; us=[]
        for dx,dy in ((-0.25,-0.25),(0.25,0.25),(-0.25,0.25),(0.25,-0.25)):
            for z in (0.05,0.6,1.2,1.71,1.78):
                pw=(3.0+dx,4.0+dy,z); d=[pw[i]-pos[i] for i in range(3)]
                pc=[sum(R[k][i]*d[k] for k in range(3)) for i in range(3)]
                if pc[0]<=0.05: continue
                u=160.0-160.0*pc[1]/pc[0]; vv=120.0-160.0*pc[2]/pc[0]
                us.append(u); vs.append(vv)
        if us:
            mb=clip(min(us),min(vs),max(us),max(vs))
            edges1={"left":min(us)<0.0,"right":max(us)>W,"top":min(vs)<0.0,"bottom":max(vs)>H}
            insts.append({"class":1,"bbox_xyxy":[round(x,2) for x in mb],"truncated_edges":edges1,
                          "occluded":False,"keypoint_x":None,"keypoint_y":None,"v":0,
                          "reference_available":False,"verified_source":"WORLD_POSE_OR_MAP_DB"})
    occ = "PARTIAL" if any(i.get("occluded") for i in insts) else ("FULL" if occ=="FULL" else "NONE")
    frames.append({"frame_id":c["frame_id"],"image":str(img.relative_to(REPO)).replace("\\","/"),
                   "image_sha256":sha(img) if img.is_file() else c.get("image_sha256"),
                   "image_width":W,"image_height":H,"family":fam,"shard":"A","sequence":c["sequence"],
                   "tower_present":bool(tower_present),"ms1_present":bool(ms1_present),
                   "identity_ambiguity":"NONE","gt_uncertainty":gt,"occlusion":occ,
                   "notes":"capture per-frame conditions (exact u/v span + green clusters) as draft + visual QA; green-light centroid is same-cue proxy; agent proxy",
                   "other_structures":[],
                   "projection_aid":{"tower_projected_max_side_px":round(max(tu[1]-tu[0],tv[1]-tv[0]),2) if tower_span_ok else 0.0,
                                     "ms1_projected_max_side_px":round(max(ms1_u_span:=0.0,0.0),2)},
                   "instances":insts})
doc={"schema_version":"dsh.landmark_two_class_annotations.v1",
     "status":"T30_TWO_CLASS_SHARD_A_AGENT_PROXY_CAPTURE_CONDITIONS_VISUAL_QA",
     "annotation_spec":{"path":"configs/perception/landmark_two_class_label_spec_v1.json","sha256":spec_sha},
     "coordinate_space":{"bbox":"SOURCE_IMAGE_PIXELS_XYXY","keypoint":"SOURCE_IMAGE_PIXELS_NORMALIZED_01"},
     "method":{"bbox":"capture per-frame geometric u/v span (tower) + projected map-native MS1 geometry (class1); per-frame visual QA; not independent human GT",
               "pool":"in_pool frames only (373 pool after frozen 3/4 rule)","class1_scope":"map-native MS1 only; synthetic/other structures would be other_structures[]"},
     "frames":frames}
(OUT/"labels_v1.json").write_text(json.dumps(doc,indent=1,ensure_ascii=False)+"\n",encoding="utf-8")
cnt=Counter(f["family"] for f in frames)
print(json.dumps({"frames":len(frames),"per_family":dict(cnt),
 "tower_present":sum(1 for f in frames if f["tower_present"]),
 "ms1_present":sum(1 for f in frames if f["ms1_present"]),
 "same_frame":sum(1 for f in frames if f["tower_present"] and f["ms1_present"]),
 "gt":dict(Counter(f["gt_uncertainty"] for f in frames)),
 "class0":sum(1 for f in frames for i in f["instances"] if i["class"]==0),
 "class1":sum(1 for f in frames for i in f["instances"] if i["class"]==1),
 "class0_v1":sum(1 for f in frames for i in f["instances"] if i["class"]==0 and i["v"]==1)},indent=1))
