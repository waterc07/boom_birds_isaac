"""V4.1 train MS1 addendum: class1 instances for the 38 same-frame frames (projection draft + visual QA)."""
import hashlib, json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
REPO=Path(r"E:\isaac\proj_boom_birds")
BASE=REPO/"docs/reports/perception/annotation_verify_20261104"
OUT=REPO/"outputs/perception/dev_annotations_20261105/two_class/v41_ms1_addendum"
OUT.mkdir(parents=True, exist_ok=True)
SIDE=REPO/"outputs/landmark_train/dataset/dev_v4_1/sidecars/train_sidecar.jsonl"
RISK=REPO/"docs/reports/perception/posteval_20261104/V41_UNLABELED_MS1_RISK_20261105.json"
MERGED=REPO/"outputs/landmark_train/dataset/labels_train_v4_1_merged.json"
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
side={}
for line in SIDE.read_text(encoding="utf-8").splitlines():
    if not line.strip(): continue
    r=json.loads(line)
    if r.get("included_in_training"): side[r["frame_id"]]=r
risk={f["frame_id"]:f for f in json.loads(RISK.read_text(encoding="utf-8"))["frames"]}
sel=[]
for fid,row in side.items():
    r=risk.get(fid)
    if not r: continue
    h=r.get("height_px") or 0
    if h>=8.0 and r.get("ms1_visible"):
        sel.append((fid,row,r))
print("actual inputs with ms1>=8px:",len(sel),"present:",sum(1 for _,row,_ in sel if row.get("present")))
frames=[]
for fid,row,r in sorted(sel,key=lambda x:x[0]):
    if not row.get("present"): continue  # 38 same-frame positive labels first
    u,v=r["lamp_uv"]; h=r["height_px"]; w=0.29*h
    x0=max(0.0,min(u-0.145*h,u+0.145*h)); x1=min(320.0,max(u-0.145*h,u+0.145*h))
    y0=max(0.0,min(v-0.04*h,v+0.99*h)); y1=min(240.0,max(v-0.04*h,v+0.99*h))
    if x1-x0 < 1.0: x1=x0+1.0
    if y1-y0 < 1.0: y1=y0+1.0
    edges={"left":u-0.145*h<0,"right":u+0.145*h>320,"top":v-0.04*h<0,"bottom":v+0.99*h>240}
    frames.append({"frame_id":fid,"image":row["image"],"image_sha256":row["image_sha256"],
                   "image_width":320,"image_height":240,"family":row.get("family"),"group_id":row.get("group_id"),
                   "tower_present":True,"ms1_present":True,"identity_ambiguity":"NONE","gt_uncertainty":"NONE",
                   "occlusion":"NONE","notes":"class1-only supplement; class0 tower labels unchanged in v4.1 base labels; MS1 bbox from projection (lamp uv + projected height) + visual spot QA; agent proxy",
                   "other_structures":[],
                   "projection_aid":{"ms1_projected_height_px":round(h,2),"ms1_lamp_uv":[u,v]},
                   "instances":[{"class":1,"bbox_xyxy":[round(x0,1),round(y0,1),round(x1,1),round(y1,1)],
                                 "truncated_edges":edges,"occluded":False,"keypoint_x":None,"keypoint_y":None,"v":0,
                                 "reference_available":False,"verified_source":"WORLD_POSE_OR_MAP_DB"}]})
doc={"schema_version":"dsh.landmark_two_class_annotations.v1",
     "status":"V41_TRAIN_MS1_ADDENDUM_PROVISIONAL_DIAGNOSTIC",
     "annotation_spec":{"path":"configs/perception/landmark_two_class_label_spec_v1.json","sha256":sha(REPO/"configs/perception/landmark_two_class_label_spec_v1.json")},
     "coordinate_space":{"bbox":"SOURCE_IMAGE_PIXELS_XYXY","keypoint":"SOURCE_IMAGE_PIXELS_NORMALIZED_01"},
     "addendum":{"kind":"class1_only_supplement_to_v4_1_train_labels",
                 "base_labels":{"path":"outputs/landmark_train/dataset/labels_train_v4_1_merged.json","sha256":sha(MERGED)},
                 "does_not_modify_base":True,
                 "method":"projection from V41_UNLABELED_MS1_RISK lamp_uv/height_px + contact-sheet visual spot QA; projection-assisted, agent proxy, NOT independent human GT",
                 "source_risk":{"path":"docs/reports/perception/posteval_20261104/V41_UNLABELED_MS1_RISK_20261105.json","sha256":sha(RISK)},
                 "scope":"38 same-frame v4.1 training inputs (tower label present) where projected MS1 height >=8px"},
     "frames":frames}
(OUT/"labels_addendum.json").write_text(json.dumps(doc,indent=1,ensure_ascii=False)+"\n",encoding="utf-8")
# sheets
SHEETS=BASE/"pilot/v41_ms1_addendum"; SHEETS.mkdir(parents=True, exist_ok=True)
def font(size=12):
    for n in ("DejaVuSans.ttf","arial.ttf"):
        try: return ImageFont.truetype(n,size)
        except Exception: pass
    return ImageFont.load_default()
F=font(12); COLS,ROWS=3,4; CW,CH=640,480; idx={}
for si in range(0,len(frames),COLS*ROWS):
    batch=frames[si:si+COLS*ROWS]; canvas=Image.new("RGB",(COLS*CW,ROWS*CH),(30,30,30))
    for k,fr in enumerate(batch):
        img=Image.open(REPO/fr["image"]).convert("RGB").resize((CW,CH),Image.LANCZOS); d=ImageDraw.Draw(img)
        b=fr["instances"][0]["bbox_xyxy"]; d.rectangle([b[0]*2,b[1]*2,b[2]*2,b[3]*2],outline=(0,220,255),width=2)
        lab="%s"%fr["frame_id"].replace("-follow_only","").replace(".png","")
        d.rectangle([0,0,min(len(lab)*6+4,CW),14],fill=(0,0,0)); d.text((2,1),lab[:48],font=F,fill=(255,255,0))
        canvas.paste(img,((k%COLS)*CW,(k//COLS)*CH))
    name="v41_addendum_%02d.png"%(si//(COLS*ROWS)); canvas.save(SHEETS/name); idx[name]=[f["frame_id"] for f in batch]
(SHEETS/"index.json").write_text(json.dumps(idx,indent=1,ensure_ascii=False)+"\n",encoding="utf-8")
print(json.dumps({"frames":len(frames),"sheets":len(idx),"out":str(OUT/"labels_addendum.json"),"sha256":sha(OUT/"labels_addendum.json")},indent=1))
