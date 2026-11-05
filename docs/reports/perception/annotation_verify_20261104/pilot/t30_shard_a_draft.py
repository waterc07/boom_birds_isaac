"""T31 shard A: projection-aid draft + contact sheets (per-frame visual QA follows)."""
import hashlib, json, math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO = Path(r"E:\isaac\proj_boom_birds")
BASE = REPO/"docs/reports/perception/annotation_verify_20261104"
RUN = REPO/"outputs/sensor_shadow/lm_two_class_train_20261105_sensor"
OUT = REPO/"outputs/perception/dev_annotations_20261105/two_class/shard_a"
SHEETS = BASE/"pilot/two_class_shard_a"
OUT.mkdir(parents=True, exist_ok=True); SHEETS.mkdir(parents=True, exist_ok=True)
SPEC = REPO/"configs/perception/landmark_two_class_label_spec_v1.json"
spec_sha = hashlib.sha256(SPEC.read_bytes()).hexdigest()

SHARD_A = ["lmf_t30_f1_tower_near_alone_0", "lmf_t30_f3_tower_far_alone_0",
           "lmf_t30_f5_ms1_near_alone_0", "lmf_t30_f7_both_near_far_0"]

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

# camera / projection
INTR = {"fx":160.0,"fy":160.0,"cx":160.0,"cy":120.0}
def quat_to_R(q):
    w,x,y,z=q
    return [[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
            [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
            [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]]
def project(pw, pos, quat):
    R=quat_to_R(quat)
    d=[pw[i]-pos[i] for i in range(3)]
    pc=[sum(R[k][i]*d[k] for k in range(3)) for i in range(3)]
    if pc[0] <= 0.05: return None
    return (INTR["cx"]-INTR["fx"]*pc[1]/pc[0], INTR["cy"]-INTR["fy"]*pc[2]/pc[0])

TOWER=[]  # approx world points of central tower
for dx,dy,z in [(-0.55,-0.55,0.02),(0.55,0.55,0.02),(-0.45,-0.45,0.16),(0.45,0.45,0.16),
                (-0.35,-0.35,0.80),(0.35,0.35,0.80),(-0.28,-0.28,1.15),(0.28,0.28,1.15),
                (-0.85,-0.10,1.55),(0.85,0.10,1.55),(-0.85,0.10,1.55),(0.85,-0.10,1.55),
                (-0.85,-0.10,1.72),(0.85,0.10,1.72)]:
    TOWER.append((11.52+dx, -0.01+dy, z))
TOWER_LIGHT=(11.52,-0.01,1.28)
MS1=[]
for dx,dy in [(-0.25,-0.25),(0.25,0.25),(-0.25,0.25),(0.25,-0.25)]:
    for z in (0.02,0.6,1.2,1.71,1.78):
        MS1.append((3.0+dx, 4.0+dy, z))

def bbox_of(points, pos, quat):
    us=[]; vs=[]
    for p in points:
        uv=project(p,pos,quat)
        if uv: us.append(uv[0]); vs.append(uv[1])
    if not us: return None
    return [min(us),min(vs),max(us),max(vs)]

def strict_green_components(path):
    rgb=np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    r,g,b=rgb[...,0],rgb[...,1],rgb[...,2]
    mask=(g>=90)&(g-r>=25)&(g-b>=25)
    ys,xs=np.nonzero(mask)
    if len(xs)==0: return []
    seen=np.zeros(mask.shape,bool); comps=[]
    for y0,x0 in zip(ys,xs):
        if seen[y0,x0]: continue
        st=[(y0,x0)]; seen[y0,x0]=True; comp=[]
        while st:
            y,x=st.pop(); comp.append((y,x))
            for dy,dx in ((1,0),(-1,0),(0,1),(0,-1)):
                ny,nx=y+dy,x+dx
                if 0<=ny<mask.shape[0] and 0<=nx<mask.shape[1] and mask[ny,nx] and not seen[ny,nx]:
                    seen[ny,nx]=True; st.append((ny,nx))
        xs2=[p[1] for p in comp]; ys2=[p[0] for p in comp]
        comps.append({"n":len(comp),"cx":float(sum(xs2)/len(xs2)),"cy":float(sum(ys2)/len(ys2)),
                      "u0":int(min(xs2)),"v0":int(min(ys2)),"u1":int(max(xs2)),"v1":int(max(ys2))})
    comps.sort(key=lambda c:-c["n"])
    return comps

rows=[json.loads(l) for l in (RUN/"observations.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
accepted=[r for r in rows if (r.get("gate") or {}).get("accepted") is True and r.get("sensor",{}).get("modality")=="RGB_IMAGE"]
print("accepted RGB:", len(accepted))
frames=[]
for r in accepted:
    ref=r["payload"]["ref"]; name=Path(ref).name
    fam=name.split("-follow_only")[0]
    if fam not in SHARD_A: continue
    seq=int(name.rsplit("_",1)[1].split(".")[0])
    ext=r["sensor"]["extrinsics"]; pos=ext["position_world_m"]; quat=ext["quat_w_world"]
    img=REPO/ref
    tb=bbox_of(TOWER,pos,quat); mb=bbox_of(MS1,pos,quat); tl=project(TOWER_LIGHT,pos,quat)
    comps=strict_green_components(img)
    # green light for class0: component nearest tower light projection and >=3 px
    kp=None
    if tl and comps:
        best=min(comps,key=lambda c: (c["cx"]-tl[0])**2+(c["cy"]-tl[1])**2)
        dist=math.hypot(best["cx"]-tl[0], best["cy"]-tl[1])
        if best["n"]>=3 and dist<=12.0:
            kp=(best["cx"],best["cy"],best["n"])
    frames.append({"frame_id":name,"image":str(img.relative_to(REPO)).replace("\\","/"),
                   "image_sha256":sha(img),"family":fam,"sequence":seq,
                   "tower_bbox":tb,"ms1_bbox":mb,"tower_light":tl,"green":comps,"kp":kp,
                   "pos":pos,"quat":quat})
print("shard A frames:", len(frames))
draft={"schema_version":"dsh.landmark_two_class_annotations.v1",
       "status":"DRAFT_PROJECTION_AID_FOR_VISUAL_QA",
       "annotation_spec":{"path":"configs/perception/landmark_two_class_label_spec_v1.json","sha256":spec_sha},
       "coordinate_space":{"bbox":"SOURCE_IMAGE_PIXELS_XYXY","keypoint":"SOURCE_IMAGE_PIXELS_NORMALIZED_01"},
       "draft_meta":{"method":"projection-aid draft from world geometry + capture camera poses; NOT final; every frame must be visually checked",
                     "tower_points":len(TOWER),"ms1_points":len(MS1)},
       "frames":frames}
(OUT/"draft_projection.json").write_text(json.dumps(draft,indent=1,ensure_ascii=False)+"\n",encoding="utf-8")
print("draft sha:", sha(OUT/"draft_projection.json"))
