import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
REPO=Path(r"E:\isaac\proj_boom_birds")
BASE=REPO/"docs/reports/perception/annotation_verify_20261104"
OUT=REPO/"outputs/perception/dev_annotations_20261105/two_class/shard_a"
SHEETS=BASE/"pilot/two_class_shard_a_v2"; SHEETS.mkdir(parents=True, exist_ok=True)
lab=json.loads((OUT/"labels_v1.json").read_text(encoding="utf-8"))
def font(size=12):
    for n in ("DejaVuSans.ttf","arial.ttf"):
        try: return ImageFont.truetype(n,size)
        except Exception: pass
    return ImageFont.load_default()
F=font(12); COLS,ROWS=3,4; CW,CH=640,480
fams={}
for f in lab["frames"]: fams.setdefault(f["family"],[]).append(f)
idx={}
for fam,fl in fams.items():
    fl=sorted(fl,key=lambda x:x["sequence"])
    for si in range(0,len(fl),COLS*ROWS):
        batch=fl[si:si+COLS*ROWS]; canvas=Image.new("RGB",(COLS*CW,ROWS*CH),(30,30,30))
        for k,fr in enumerate(batch):
            img=Image.open(REPO/fr["image"]).convert("RGB").resize((CW,CH),Image.LANCZOS); d=ImageDraw.Draw(img)
            for inst in fr["instances"]:
                b=inst["bbox_xyxy"]; col=(255,150,0) if inst["class"]==0 else (0,220,255)
                d.rectangle([b[0]*2,b[1]*2,b[2]*2,b[3]*2],outline=col,width=2)
                if inst["class"]==0 and inst["v"]==1:
                    d.ellipse([inst["keypoint_x"]*CW-4,inst["keypoint_y"]*CH-4,inst["keypoint_x"]*CW+4,inst["keypoint_y"]*CH+4],outline=(0,255,0),width=2)
            label="%s s%d"%(fam.replace("lmf_t30_","").replace("_follow",""),fr["sequence"])
            d.rectangle([0,0,len(label)*7+4,14],fill=(0,0,0)); d.text((2,1),label,font=F,fill=(255,255,0))
            canvas.paste(img,((k%COLS)*CW,(k//COLS)*CH))
        name="%s_%02d.png"%(fam,si//(COLS*ROWS)); canvas.save(SHEETS/name); idx[name]=[f["frame_id"] for f in batch]
(SHEETS/"index.json").write_text(json.dumps(idx,indent=1,ensure_ascii=False)+"\n",encoding="utf-8")
print("sheets:",len(idx))
