"""T39 final: MS1 class1 bbox from FINAL T38 run poses + map-native MS1 projection; shard A (first ceil(n/2) per family)."""
import hashlib, json, math
from pathlib import Path
from collections import Counter
from PIL import Image, ImageDraw, ImageFont
REPO=Path(r"E:\isaac\proj_boom_birds")
BASE=REPO/"docs/reports/perception/annotation_verify_20261104"
RUN=REPO/"outputs/sensor_shadow/lm_two_class_near_ms1_20261105_sensor"
OUT=REPO/"outputs/perception/dev_annotations_20261105/two_class/near_ms1/shard_a"
SPEC=REPO/"configs/perception/landmark_two_class_label_spec_v1.json"
spec_sha=hashlib.sha256(SPEC.read_bytes()).hexdigest(); W,H=320,240
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
rows=[json.loads(l) for l in (RUN/"observations.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
acc=[r for r in rows if (r.get("gate") or {}).get("accepted") is True and r.get("sensor",{}).get("modality")=="RGB_IMAGE"]
print("accepted RGB:",len(acc))
def R_of(q):
    w,x,y,z=q
    return [[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
            [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
            [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]]
def project(pw,pos,R):
    d=[pw[i]-pos[i] for i in range(3)]
    pc=[sum(R[k][i]*d[k] for k in range(3)) for i in range(3)]
    if pc[0]<=0.05: return None
    return (160.0-160.0*pc[1]/pc[0],120.0-160.0*pc[2]/pc[0])
MS1=[]; TOWER=[]
for dx,dy in ((-0.25,-0.25),(0.25,0.25),(-0.25,0.25),(0.25,-0.25)):
    for z in (0.05,0.6,1.2,1.71,1.78): MS1.append((3.0+dx,4.0+dy,z))
for dx,dy,z in ((-0.55,-0.55,0.02),(0.55,0.55,0.02),(-0.45,-0.45,0.16),(0.45,0.45,0.16),
                (-0.35,-0.35,0.80),(0.35,0.35,0.80),(-0.28,-0.28,1.15),(0.28,0.28,1.15),
                (-0.85,-0.10,1.55),(0.85,0.10,1.55)):
    TOWER.append((11.52+dx,-0.01+dy,z))
frames=[]
for r in acc:
    ref=r["payload"]["ref"]; fid=Path(ref).name; fam=fid.split("-follow_only")[0]
    seq=int(fid.rsplit("_",1)[1].split(".")[0])
    ext=r["sensor"]["extrinsics"]; pos=ext["position_world_m"]; quat=ext["quat_w_world"]; R=R_of(quat)
    def span(pts):
        us=[];vs=[]
        for p in pts:
            uv=project(p,pos,R)
            if uv: us.append(uv[0]); vs.append(uv[1])
        return (min(us),min(vs),max(us),max(vs)) if us else None
    ms=span(MS1); tw=span(TOWER)
    if not ms: raise SystemExit("no ms1 proj "+fid)
    x0=max(0.0,min(W,ms[0])); x1=max(0.0,min(W,ms[2])); y0=max(0.0,min(H,ms[1])); y1=max(0.0,min(H,ms[3]))
    edges={"left":ms[0]<0.0,"right":ms[2]>W,"top":ms[1]<0.0,"bottom":ms[3]>H}
    tower_in = tw is not None and (min(W,tw[2])-max(0.0,tw[0]))>2 and (min(H,tw[3])-max(0.0,tw[1]))>2
    img=REPO/ref
    frames.append({"frame_id":fid,"image":str(img.relative_to(REPO)).replace("\\","/"),"image_sha256":sha(img),
                   "image_width":W,"image_height":H,"family":fam,"shard":"A","sequence":seq,
                   "tower_present":bool(tower_in),"ms1_present":True,
                   "identity_ambiguity":"NONE","gt_uncertainty":"NONE","occlusion":"NONE",
                   "notes":"T38 FINAL run; class1 bbox from map-native MS1 projection (final camera pose); projection-assisted + visual spot QA; agent proxy; tower check per frame",
                   "other_structures":[],
                   "projection_aid":{"ms1_projected_max_side_px":round(max(x1-x0,y1-y0),2),
                                     "tower_projected_max_side_px":round(max(tw[2]-tw[0],tw[3]-tw[1]),2) if tw else 0.0},
                   "instances":[{"class":1,"bbox_xyxy":[round(x0,2),round(y0,2),round(x1,2),round(y1,2)],
                                 "truncated_edges":edges,"occluded":False,"keypoint_x":None,"keypoint_y":None,"v":0,
                                 "reference_available":False,"verified_source":"WORLD_POSE_OR_MAP_DB"}]})
frames.sort(key=lambda f:(f["family"],f["sequence"]))
byfam={}
for f in frames: byfam.setdefault(f["family"],[]).append(f)
A=[]
for fam,fl in byfam.items():
    fl=sorted(fl,key=lambda x:x["sequence"]); k=(len(fl)+1)//2; A.extend(fl[:k])
A=sorted(A,key=lambda f:(f["family"],f["sequence"]))
print("families:",{k:len(v) for k,v in byfam.items()},"A:",len(A),"tower_in:",sum(1 for f in A if f["tower_present"]))
# write full provisional (all 108) and shard A
def write(frames_list, outdir, status, shard):
    OUT=Path(outdir); OUT.mkdir(parents=True, exist_ok=True)
    doc={"schema_version":"dsh.landmark_two_class_annotations.v1","status":status,
         "annotation_spec":{"path":"configs/perception/landmark_two_class_label_spec_v1.json","sha256":spec_sha},
         "coordinate_space":{"bbox":"SOURCE_IMAGE_PIXELS_XYXY","keypoint":"SOURCE_IMAGE_PIXELS_NORMALIZED_01"},
         "method":{"bbox":"map-native MS1 (3.0,4.0, z0.05-1.78) projected with FINAL T38 camera poses; visual spot QA; projection-assisted, agent proxy, not independent human GT",
                   "class1_scope":"map-native MS1 only; class1 keypoint always v=0"},
         "frames":frames_list}
    (OUT/"labels_v1.json").write_text(json.dumps(doc,indent=1,ensure_ascii=False)+"\n",encoding="utf-8")
    sel={"schema_version":"dsh.landmark_two_class_selection.v1","status":"T38_FINAL_POOL_"+shard,
         "run":"outputs/sensor_shadow/lm_two_class_near_ms1_20261105_sensor","shard":shard,
         "rule":{"id":"t38_final_pool_"+shard,"text":"final run accepted frames; shard A = per-family first ceil(n/2) by sequence; full = all accepted","total":len(frames_list)},
         "per_family":dict(Counter(f["family"] for f in frames_list)),"frames":frames_list}
    (OUT/"selection.json").write_text(json.dumps(sel,indent=1,ensure_ascii=False)+"\n",encoding="utf-8")
    return sha(OUT/"labels_v1.json"), sha(OUT/"selection.json")
fa_dir=REPO/"outputs/perception/dev_annotations_20261105/two_class/near_ms1/full"
sa_dir=OUT
full_sha,full_sel=write(frames,str(fa_dir),"T38_FINAL_FULL_AGENT_PROXY_PROJECTION_VISUAL_QA","full")
sa_sha,sa_sel=write(A,str(sa_dir),"T38_FINAL_SHARD_A_AGENT_PROXY_PROJECTION_VISUAL_QA","A")
# sheets for A
SHEETS=BASE/"pilot/t39_near_ms1_shard_a_final"; SHEETS.mkdir(parents=True,exist_ok=True)
def font(size=12):
    for n in ("DejaVuSans.ttf","arial.ttf"):
        try: return ImageFont.truetype(n,size)
        except Exception: pass
    return ImageFont.load_default()
F=font(12); COLS,ROWS=3,4; CW,CH=640,480; idx={}
for si in range(0,len(A),COLS*ROWS):
    batch=A[si:si+COLS*ROWS]; canvas=Image.new("RGB",(COLS*CW,ROWS*CH),(30,30,30))
    for k,fr in enumerate(batch):
        im=Image.open(REPO/fr["image"]).convert("RGB").resize((CW,CH),Image.LANCZOS); d=ImageDraw.Draw(im)
        b=fr["instances"][0]["bbox_xyxy"]; d.rectangle([b[0]*2,b[1]*2,b[2]*2,b[3]*2],outline=(0,220,255),width=2)
        d.rectangle([0,0,240,14],fill=(0,0,0)); d.text((2,1),fr["frame_id"].replace("-follow_only","")[:42],font=F,fill=(255,255,0))
        canvas.paste(im,((k%COLS)*CW,(k//COLS)*CH))
    name="near_ms1_final_%02d.png"%(si//(COLS*ROWS)); canvas.save(SHEETS/name); idx[name]=[f["frame_id"] for f in batch]
(SHEETS/"index.json").write_text(json.dumps(idx,indent=1,ensure_ascii=False)+"\n",encoding="utf-8")
print(json.dumps({"full":{"frames":len(frames),"sha":full_sha,"sel":full_sel},
                  "shard_a":{"frames":len(A),"sha":sa_sha,"sel":sa_sel,"sheets":len(idx)},
                  "per_family_A":dict(Counter(f["family"] for f in A)),
                  "tower_in_A":sum(1 for f in A if f["tower_present"])},indent=1))
