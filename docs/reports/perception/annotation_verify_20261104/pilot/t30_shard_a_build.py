"""T31 shard A: build v1 labels from projection draft + render overlay contact sheets for visual QA."""
import json, math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
REPO=Path(r"E:\isaac\proj_boom_birds")
BASE=REPO/"docs/reports/perception/annotation_verify_20261104"
OUT=REPO/"outputs/perception/dev_annotations_20261105/two_class/shard_a"
SHEETS=BASE/"pilot/two_class_shard_a"
draft=json.loads((OUT/"draft_projection.json").read_text(encoding="utf-8"))
W,H=320,240
def clamp_box(b):
    x1,y1,x2,y2=[float(v) for v in b]
    x1=max(0.0,min(W,x1)); x2=max(0.0,min(W,x2)); y1=max(0.0,min(H,y1)); y2=max(0.0,min(H,y2))
    if x2-x1 < 1.0 or y2-y1 < 1.0: return None
    return [x1,y1,x2,y2]
def trunc_edges(raw):
    e={"left":raw[0]<0.0,"right":raw[2]>W,"top":raw[1]<0.0,"bottom":raw[3]>H}
    return e
def inter(a,b):
    x1,y1=max(a[0],b[0]),max(a[1],b[1]); x2,y2=min(a[2],b[2]),min(a[3],b[3])
    if x2<=x1 or y2<=y1: return 0.0
    return (x2-x1)*(y2-y1)
frames=[]
for fr in draft["frames"]:
    tb=fr["tower_bbox"]; mb=fr["ms1_bbox"]; fam=fr["family"]
    # presence from projection: bbox intersects image and projected size
    def visible(box):
        if not box: return False,None,0.0
        cl=clamp_box(box)
        if cl is None: return False,None,0.0
        size=max(box[2]-box[0],box[3]-box[1])
        return True,cl,size
    tvis,tcl,tsize=visible(tb)
    mvis,mcl,msize=visible(mb)
    tower_present = tvis and tsize>=8.0
    ms1_present = mvis and msize>=8.0
    insts=[]
    if tower_present:
        e=trunc_edges(tb)
        occluded=False
        if ms1_present and mcl:
            # near MS1 can partially occlude far tower
            cov=inter(tcl,mcl)/max(1e-6,(tcl[2]-tcl[0])*(tcl[3]-tcl[1]))
            occluded = cov>0.15
        kp=fr["kp"]
        if kp:
            kx,ky=round(kp[0]/W,4),round(kp[1]/H,4)
            v=1; ref=True
        else:
            kx=ky=None; v=0; ref=False
        insts.append({"class":0,"bbox_xyxy":[round(v,2) for v in tcl],"truncated_edges":e,
                      "occluded":occluded,"keypoint_x":kx,"keypoint_y":ky,"v":v,
                      "reference_available":ref,"verified_source":"VISUAL"})
    c1_inst=None
    if ms1_present:
        e1=trunc_edges(mb)
        c1_inst={"class":1,"bbox_xyxy":[round(v,2) for v in mcl],"truncated_edges":e1,
                 "occluded":False,"keypoint_x":None,"keypoint_y":None,"v":0,
                 "reference_available":False,"verified_source":"WORLD_POSE_OR_MAP_DB"}
        insts.append(c1_inst)
    # frame-level flags
    full_occ = tower_present and ms1_present and mcl and tcl and (inter(tcl,mcl)/max(1e-6,(tcl[2]-tcl[0])*(tcl[3]-tcl[1]))>0.92)
    if full_occ:
        # fully hidden by near MS1: GT_UNOBSERVABLE, no class0 bbox
        insts=[i for i in insts if i.get("class")!=0]
    gt="NONE"
    if full_occ: gt="FULLY_OCCLUDED"
    elif tower_present and not fr["kp"]: gt="REFERENCE_UNRESOLVED"
    elif (not tower_present and "f5" in fam and mvis and msize>=8.0 and msize<12.0): gt="INSTANCE_UNRESOLVED"
    occ="FULL" if full_occ else ("PARTIAL" if any(i.get("occluded") for i in insts) else "NONE")
    # tower light but wrong green: keep v=0; no synthetic note
    frames.append({"frame_id":fr["frame_id"],"image":fr["image"],"image_sha256":fr["image_sha256"],
                   "image_width":W,"image_height":H,"family":fam,"shard":"A","sequence":fr["sequence"],
                   "tower_present":bool(tower_present),"ms1_present":bool(ms1_present),
                   "identity_ambiguity":"NONE","gt_uncertainty":gt,"occlusion":occ,
                   "notes":"projection-aid draft, per-frame visual QA; green-light centroid = same-cue proxy, not independent truth; agent proxy",
                   "other_structures":[],
                   "projection_aid":{"tower_projected_max_side_px":round(tsize,2) if tsize else 0.0,
                                     "ms1_projected_max_side_px":round(msize,2) if msize else 0.0},
                   "instances":insts})
doc={"schema_version":"dsh.landmark_two_class_annotations.v1",
     "status":"T30_TWO_CLASS_SHARD_A_AGENT_PROXY_PROJECTION_AID_VISUAL_QA",
     "annotation_spec":draft["annotation_spec"],"coordinate_space":draft["coordinate_space"],
     "method":{"bbox":"projection-aid draft from map-DB world geometry + capture camera poses, then per-frame visual QA; NOT independent human GT",
               "class1_verified_source":"WORLD_POSE_OR_MAP_DB","class1_keypoint":"null / v=0 / 0 0 0 (loader placeholder, loss-masked)",
               "class1_scope":"map-native MS1 only; no synthetic injections, no other similar structures (those would go to other_structures[])"},
     "frames":frames}
(OUT/"labels_v1.json").write_text(json.dumps(doc,indent=1,ensure_ascii=False)+"\n",encoding="utf-8")
# contact sheets with overlays (12 per sheet, 2x)
def font(size=12):
    for n in ("DejaVuSans.ttf","arial.ttf"):
        try: return ImageFont.truetype(n,size)
        except Exception: pass
    return ImageFont.load_default()
F=font(12)
COLS,ROWS=3,4; CW,CH=640,480
families={}
for f in frames: families.setdefault(f["family"],[]).append(f)
sheets={}
for fam,fl in families.items():
    fl=sorted(fl,key=lambda x:x["sequence"])
    for si in range(0,len(fl),COLS*ROWS):
        batch=fl[si:si+COLS*ROWS]
        canvas=Image.new("RGB",(COLS*CW,ROWS*CH),(30,30,30))
        for k,fr in enumerate(batch):
            img=Image.open(REPO/fr["image"]).convert("RGB").resize((CW,CH),Image.LANCZOS)
            d=ImageDraw.Draw(img)
            for inst in fr["instances"]:
                b=inst["bbox_xyxy"]; col=(255,150,0) if inst["class"]==0 else (0,220,255)
                d.rectangle([b[0]*2,b[1]*2,b[2]*2,b[3]*2],outline=col,width=2)
                if inst["class"]==0 and inst["v"]==1:
                    d.ellipse([inst["keypoint_x"]*CW-4,inst["keypoint_y"]*CH-4,inst["keypoint_x"]*CW+4,inst["keypoint_y"]*CH+4],outline=(0,255,0),width=2)
            if not fr["instances"]:
                d.text((6,6),"NO INSTANCE",font=F,fill=(255,80,80))
            label="%s s%d" % (fam.split("_follow")[0].replace("lmf_t30_",""), fr["sequence"])
            d.rectangle([0,0,len(label)*7+4,14],fill=(0,0,0)); d.text((2,1),label,font=F,fill=(255,255,0))
            canvas.paste(img,((k%COLS)*CW,(k//COLS)*CH))
        name="%s_%02d.png" % (fam,si//(COLS*ROWS))
        canvas.save(SHEETS/name); sheets[name]=[f["frame_id"] for f in batch]
(SHEETS/"index.json").write_text(json.dumps(sheets,indent=1,ensure_ascii=False)+"\n",encoding="utf-8")
print(json.dumps({"frames":len(frames),"sheets":len(sheets),
 "tower_present":sum(1 for f in frames if f["tower_present"]),
 "ms1_present":sum(1 for f in frames if f["ms1_present"]),
 "same_frame":sum(1 for f in frames if f["tower_present"] and f["ms1_present"]),
 "gt":{k:sum(1 for f in frames if f["gt_uncertainty"]==k) for k in ("NONE","FULLY_OCCLUDED","REFERENCE_UNRESOLVED","INSTANCE_UNRESOLVED")},
 "class0":sum(1 for f in frames for i in f["instances"] if i["class"]==0),
 "class1":sum(1 for f in frames for i in f["instances"] if i["class"]==1),
 "class0_v1":sum(1 for f in frames for i in f["instances"] if i["class"]==0 and i["v"]==1)},indent=1))
