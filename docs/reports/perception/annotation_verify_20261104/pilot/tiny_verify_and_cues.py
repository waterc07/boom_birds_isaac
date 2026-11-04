"""Verify blind frame list, compute strict green cue, render 3x grid views."""
import hashlib, json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO = Path(r"E:\isaac\proj_boom_birds")
BASE = REPO/"docs/reports/perception/annotation_verify_20261104"
LIST = REPO/"docs/reports/perception/posteval_20261104/TINY_BLIND_REANNOTATION_FRAMES_20261104.json"
OUT = BASE/"pilot/tiny_blind"
OUT.mkdir(parents=True, exist_ok=True)
doc = json.loads(LIST.read_text(encoding="utf-8"))
assert hashlib.sha256(LIST.read_bytes()).hexdigest() == "fc3508de23b8d16c593d0e2bad27889de89d3e4ed68a1704e01ba50b37364941"

def strict_green(path):
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    r,g,b = rgb[...,0], rgb[...,1], rgb[...,2]
    mask = (g>=90) & (g-r>=25) & (g-b>=25)
    ys,xs = np.nonzero(mask)
    if len(xs)==0:
        return {"green_pixels":0,"centroid":None,"bbox":None}
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

def font(size=12):
    for name in ("DejaVuSans.ttf","arial.ttf"):
        try: return ImageFont.truetype(name,size)
        except Exception: pass
    return ImageFont.load_default()
F=font(13)
def grid_view(src,dst,scale=3,step=10):
    img=Image.open(src).convert("RGB"); W,H=img.size
    big=img.resize((W*scale,H*scale),Image.LANCZOS)
    canvas=Image.new("RGB",(W*scale+50,H*scale+22),(25,25,25)); canvas.paste(big,(50,22))
    ov=Image.new("RGBA",canvas.size,(0,0,0,0)); d=ImageDraw.Draw(ov)
    for x in range(0,W+1,step):
        xs=50+x*scale
        if xs>=canvas.size[0]-1: continue
        d.line([(xs,22),(xs,22+H*scale)],fill=(255,0,255,70))
    for y in range(0,H+1,step):
        ys=22+y*scale
        if ys>=canvas.size[1]-1: continue
        d.line([(50,ys),(50+W*scale,ys)],fill=(255,0,255,70))
    for x in range(0,W+1,20):
        xs=50+x*scale
        if xs<canvas.size[0]-12: d.text((xs-10,3),str(x),font=F,fill=(255,255,0,255))
    for y in range(0,H+1,20):
        ys=22+y*scale
        if ys<canvas.size[1]-12: d.text((2,ys-8),str(y),font=F,fill=(255,255,0,255))
    Image.alpha_composite(canvas.convert("RGBA"),ov).convert("RGB").save(dst)

cues={}
rows=[]
for i,fr in enumerate(doc["frames"]):
    p=REPO/fr["image"]
    ok=p.is_file()
    sha=hashlib.sha256(p.read_bytes()).hexdigest() if ok else None
    cue=strict_green(p) if ok else None
    cues[fr["frame_id"]]={"exists":ok,"sha_ok":sha==fr["image_sha256"],"sha":sha,**(cue or {})}
    grid_view(p, OUT/("grid_%02d.png"%i))
    rows.append((i,fr["frame_id"],ok,sha==fr["image_sha256"],cue["green_pixels"] if cue else None, cue["centroid"] if cue else None, cue["bbox"] if cue else None))
(OUT/"cues.json").write_text(json.dumps(cues,indent=1,ensure_ascii=False)+"\n",encoding="utf-8")
print("frames:",len(rows))
for r in rows: print(r)
print("all files/sha ok:", all(r[2] and r[3] for r in rows))
