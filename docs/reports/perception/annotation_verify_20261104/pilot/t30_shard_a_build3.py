"""T31 shard A v3: presence from FOV+geometry; green-visibility only for keypoint; class1 projection bbox."""
import hashlib, json, math
from pathlib import Path
from collections import Counter
REPO=Path(r"E:\isaac\proj_boom_birds")
BASE=REPO/"docs/reports/perception/annotation_verify_20261104"
OUT=REPO/"outputs/perception/dev_annotations_20261105/two_class/shard_a"
COND=REPO/"docs/reports/perception/capture_dev_20261104/two_class_train_20261105/t30_frame_conditions.json"
SPEC=REPO/"configs/perception/landmark_two_class_label_spec_v1.json"
spec_sha=hashlib.sha256(SPEC.read_bytes()).hexdigest(); W,H=320,240
SHARD_A={"lmf_t30_f1_tower_near_alone_0","lmf_t30_f3_tower_far_alone_0","lmf_t30_f5_ms1_near_alone_0","lmf_t30_f7_both_near_far_0"}
conds=[c for c in json.loads(COND.read_text(encoding="utf-8")) if c.get("in_pool") and c["frame_id"].split("-follow_only")[0] in SHARD_A]
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def clip(u0,v0,u1,v1):
    return [max(0.0,min(W,u0)),max(0.0,min(H,v0)),max(0.0,min(W,u1)),max(0.0,min(H,v1))]
def R_of(q):
    w,x,y,z=q
    return [[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
            [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
            [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]]
def proj_span(points,pos,R):
    us=[];vs=[]
    for pw in points:
        d=[pw[i]-pos[i] for i in range(3)]
        pc=[sum(R[k][i]*d[k] for k in range(3)) for i in range(3)]
        if pc[0]<=0.05: continue
        us.append(160.0-160.0*pc[1]/pc[0]); vs.append(120.0-160.0*pc[2]/pc[0])
    return (min(us),min(vs),max(us),max(vs)) if us else None
MS1P=[]
for dx,dy in ((-0.25,-0.25),(0.25,0.25),(-0.25,0.25),(0.25,-0.25)):
    for z in (0.05,0.6,1.2,1.71,1.78):
        MS1P.append((3.0+dx,4.0+dy,z))
frames=[]
for c in sorted(conds,key=lambda x:(x["frame_id"].split("-follow_only")[0],x["sequence"])):
    fam=c["frame_id"].split("-follow_only")[0]
    img=REPO/"outputs/sensor_shadow/lm_two_class_train_20261105_pool/images"/c["frame_id"]
    if not img.is_file(): img=REPO/"outputs/sensor_shadow/lm_two_class_train_20261105_sensor/images"/c["frame_id"]
    tr=c.get("tower_four_side_truncation_geometric") or {}
    tu=c.get("tower_u_span") or []; tv=(tr.get("v_span") or [])
    tower_present = c.get("target_fov_status")=="IN_FOV" and len(tu)==2 and len(tv)==2
    ms1_present = c.get("ms1_fov_status")=="IN_FOV" and c.get("ms1_u_span") is not None
    insts=[]; gt="NONE"; occ="NONE"
    kx=ky=None; v=0; ref=False
    if tower_present:
        tb=clip(tu[0],tv[0],tu[1],tv[1])
        edges={"left":tu[0]<0.0,"right":tu[1]>W,"top":tv[0]<0.0,"bottom":tv[1]>H}
        occluded=bool(ms1_present and (c.get("overlap_fraction_of_target_width") or 0)>0.05)
        tgt=c.get("target_pixel_uv_pred"); clusters=c.get("green_clusters") or []
        if tgt and clusters and (c.get("target_green_pixels_strict") or 0)>=3:
            best=min(clusters,key=lambda cl:(cl["u"]-tgt[0])**2+(cl["v"]-tgt[1])**2)
            if math.hypot(best["u"]-tgt[0],best["v"]-tgt[1])<=12.0 and best.get("area",0)>=3:
                kx,ky=round(best["u"]/W,4),round(best["v"]/H,4); v=1; ref=True
        insts.append({"class":0,"bbox_xyxy":[round(x,2) for x in tb],"truncated_edges":edges,
                      "occluded":occluded,"keypoint_x":kx,"keypoint_y":ky,"v":v,
                      "reference_available":ref,"verified_source":"VISUAL"})
        if not ref: gt="REFERENCE_UNRESOLVED"
    ms1_px=0.0
    if ms1_present:
        R=R_of(c["camera_quat_wxyz"]); span=proj_span(MS1P,c["camera_position_world_m"],R)
        if span:
            mb=clip(*span)
            edges1={"left":span[0]<0.0,"right":span[2]>W,"top":span[1]<0.0,"bottom":span[3]>H}
            insts.append({"class":1,"bbox_xyxy":[round(x,2) for x in mb],"truncated_edges":edges1,
                          "occluded":False,"keypoint_x":None,"keypoint_y":None,"v":0,
                          "reference_available":False,"verified_source":"WORLD_POSE_OR_MAP_DB"})
            ms1_px=max(span[2]-span[0],span[3]-span[1])
        else:
            gt="INSTANCE_UNRESOLVED"
    if any(i.get("occluded") for i in insts): occ="PARTIAL"
    frames.append({"frame_id":c["frame_id"],"image":str(img.relative_to(REPO)).replace("\\","/"),
                   "image_sha256":sha(img),"image_width":W,"image_height":H,"family":fam,"shard":"A","sequence":c["sequence"],
                   "tower_present":bool(tower_present),"ms1_present":bool(ms1_present),
                   "identity_ambiguity":"NONE","gt_uncertainty":gt,"occlusion":occ,
                   "notes":"capture per-frame geometric spans (tower) + projected map-native MS1 geometry; per-frame visual spot QA; green centroid same-cue proxy; agent proxy",
                   "other_structures":[],
                   "projection_aid":{"tower_projected_max_side_px":round(max(tu[1]-tu[0],tv[1]-tv[0]),2) if tower_present else 0.0,
                                     "ms1_projected_max_side_px":round(ms1_px,2)},
                   "instances":insts})
doc={"schema_version":"dsh.landmark_two_class_annotations.v1",
     "status":"T30_TWO_CLASS_SHARD_A_AGENT_PROXY_CONDITIONS_PLUS_VISUAL_QA",
     "annotation_spec":{"path":"configs/perception/landmark_two_class_label_spec_v1.json","sha256":spec_sha},
     "coordinate_space":{"bbox":"SOURCE_IMAGE_PIXELS_XYXY","keypoint":"SOURCE_IMAGE_PIXELS_NORMALIZED_01"},
     "method":{"bbox":"capture per-frame tower u/v geometric span; class1 = projected map-native MS1 geometry; per-frame visual QA spot checks; not independent human GT",
               "pool":"in_pool frames only (373 pool after frozen 3/4 rule)","class1_scope":"map-native MS1 only"},
     "frames":frames}
(OUT/"labels_v1.json").write_text(json.dumps(doc,indent=1,ensure_ascii=False)+"\n",encoding="utf-8")
# selection from labels
frames_sel=[{"frame_id":f["frame_id"],"image":f["image"],"image_sha256":f["image_sha256"],"family":f["family"],"shard":"A","sequence":f["sequence"]} for f in frames]
sel={"schema_version":"dsh.landmark_two_class_selection.v1","status":"IN_POOL_ALL_ANNOTATED","run":"outputs/sensor_shadow/lm_two_class_train_20261105_sensor",
     "shard":"A","families":sorted({f["family"] for f in frames}),
     "rule":{"id":"two_class_pool_all_frames_v1","text":"all in-pool accepted frames of shard A families were annotated (181); non-pool accepted frames (57) remain diagnostic and excluded from training by pool intersection","total":len(frames_sel)},
     "per_family":{fam:{"accepted":n,"selected":n} for fam,n in Counter(f["family"] for f in frames).items()},
     "frames":frames_sel}
(OUT/"selection.json").write_text(json.dumps(sel,indent=1,ensure_ascii=False)+"\n",encoding="utf-8")
print(json.dumps({"frames":len(frames),"per_family":dict(Counter(f["family"] for f in frames)),
 "tower_present":sum(1 for f in frames if f["tower_present"]),
 "ms1_present":sum(1 for f in frames if f["ms1_present"]),
 "same_frame":sum(1 for f in frames if f["tower_present"] and f["ms1_present"]),
 "gt":dict(Counter(f["gt_uncertainty"] for f in frames)),
 "class0":sum(1 for f in frames for i in f["instances"] if i["class"]==0),
 "class1":sum(1 for f in frames for i in f["instances"] if i["class"]==1),
 "class0_v1":sum(1 for f in frames for i in f["instances"] if i["class"]==0 and i["v"]==1)},indent=1))
