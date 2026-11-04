"""T25 identity annotation: verify selection, compute strict green cues, render 2x contact sheets."""
import hashlib, json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO = Path(r"E:\isaac\proj_boom_birds")
BASE = REPO/"docs/reports/perception/annotation_verify_20261104"
SEL = REPO/"outputs/perception/dev_annotations_20261104/identity_t25/selection.json"
OUT = BASE/"pilot/identity_t25"
OUT.mkdir(parents=True, exist_ok=True)
sel = json.loads(SEL.read_text(encoding="utf-8"))
run_rel = sel["run"]; run = REPO/run_rel
img_dir = run/"images"
frames = sel["frames"]
print("selected:", len(frames), "run:", run_rel)

def strict_green(path):
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    r,g,b = rgb[...,0], rgb[...,1], rgb[...,2]
    mask = (g>=90) & (g-r>=25) & (g-b>=25)
    ys,xs = np.nonzero(mask)
    if len(xs)==0: return {"green_pixels":0,"centroid":None,"bbox":None}
    seen=np.zeros(mask.shape,bool); best=[]
    for y0,x0 in zip(ys,xs):
        if seen[y0,x0]: continue
        st=[(y0,x0)]; seen[y0,x0]=True; comp=[]
        while st:
            y,x=st.pop(); comp.append((y,x))
            for dy,dx in ((1,0),(-1,0),(0,1),(0,-1)):
                ny,nx=y+dy,x+dx
                if 0<=ny<mask.shape[0] and 0<=nx<mask.shape[1] and mask[ny,nx] and not seen[ny,nx]:
                    seen[ny,nx]=True; st.append((ny,nx))
        if len(comp)>len(best): best=comp
    xs2=[p[1] for p in best]; ys2=[p[0] for p in best]
    return {"green_pixels":len(best),
            "centroid":[round(float(sum(xs2)/len(xs2)),2), round(float(sum(ys2)/len(ys2)),2)],
            "bbox":[int(min(xs2)),int(min(ys2)),int(max(xs2)),int(max(ys2))]}

cues = {}
for f in frames:
    p = img_dir/f
    assert p.is_file(), p
    cues[f] = {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), **strict_green(p)}
(OUT/"cues.json").write_text(json.dumps(cues, indent=1, ensure_ascii=False)+"\n", encoding="utf-8")

def font(size=12):
    for name in ("DejaVuSans.ttf","arial.ttf"):
        try: return ImageFont.truetype(name,size)
        except Exception: pass
    return ImageFont.load_default()
F=font(13)
COLS,ROWS=3,4; CW,CH=640,480
sheets={}
for si in range(0,len(frames),COLS*ROWS):
    batch=frames[si:si+COLS*ROWS]
    canvas=Image.new("RGB",(COLS*CW,ROWS*CH),(30,30,30))
    for k,f in enumerate(batch):
        img=Image.open(img_dir/f).convert("RGB").resize((CW,CH),Image.LANCZOS)
        c=cues[f]
        if c["centroid"]:
            d=ImageDraw.Draw(img); u,v=c["centroid"]
            d.ellipse([u*2-10,v*2-10,u*2+10,v*2+10],outline=(0,255,255),width=2)
        label="%02d %s" % (si+k, f.replace("-follow_only","").replace(".png",""))
        d=ImageDraw.Draw(img); d.rectangle([0,0,len(label)*7+4,14],fill=(0,0,0)); d.text((2,1),label,font=F,fill=(255,255,0))
        canvas.paste(img,((k%COLS)*CW,(k//COLS)*CH))
    name="identity_t25_%02d.png"%(si//(COLS*ROWS))
    canvas.save(OUT/name)
    sheets[name]=batch
(OUT/"index.json").write_text(json.dumps(sheets,indent=1,ensure_ascii=False)+"\n",encoding="utf-8")
print("sheets:", len(sheets), "->", OUT)
print("cues green>0:", sum(1 for c in cues.values() if c["green_pixels"]>0), "green>=3:", sum(1 for c in cues.values() if c["green_pixels"]>=3))
