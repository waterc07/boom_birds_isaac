import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
REPO=Path(r"E:\isaac\proj_boom_birds")
BASE=REPO/"docs/reports/perception/annotation_verify_20261104"
OUT=BASE/"pilot/tiny_blind"
LIST=REPO/"docs/reports/perception/posteval_20261104/TINY_BLIND_REANNOTATION_FRAMES_20261104.json"
doc=json.loads(LIST.read_text(encoding="utf-8"))
cues=json.loads((OUT/"cues.json").read_text(encoding="utf-8"))
def font(size=14):
    for name in ("DejaVuSans.ttf","arial.ttf"):
        try: return ImageFont.truetype(name,size)
        except Exception: pass
    return ImageFont.load_default()
F=font(15)
def zoom(src,dst,cx,cy,half=26,scale=14,step=5):
    cx=int(round(cx)); cy=int(round(cy))
    img=Image.open(src).convert("RGB"); x0=max(0,cx-half); y0=max(0,cy-half); x1=min(320,cx+half); y1=min(240,cy+half)
    crop=img.crop((x0,y0,x1,y1)); cw,ch=crop.size
    big=crop.resize((cw*scale,ch*scale),Image.NEAREST)
    canvas=Image.new("RGB",(cw*scale+52,ch*scale+22),(25,25,25)); canvas.paste(big,(52,22))
    ov=Image.new("RGBA",canvas.size,(0,0,0,0)); d=ImageDraw.Draw(ov)
    for x in range(x0,x1+1):
        if (x-x0)%step: continue
        xs=52+(x-x0)*scale; d.line([(xs,22),(xs,22+ch*scale)],fill=(255,0,255,80)); d.text((xs-12,3),str(x),font=F,fill=(255,255,0,255))
    for y in range(y0,y1+1):
        if (y-y0)%step: continue
        ys=22+(y-y0)*scale; d.line([(52,ys),(52+cw*scale,ys)],fill=(255,0,255,80)); d.text((2,ys-8),str(y),font=F,fill=(255,255,0,255))
    Image.alpha_composite(canvas.convert("RGBA"),ov).convert("RGB").save(dst)
for idx in (8,12,13,14,15,16,17,0,1,3,4,11):
    fr=doc["frames"][idx]; c=cues[fr["frame_id"]]
    if not c["centroid"]: continue
    zoom(REPO/fr["image"], OUT/("zoom_%02d.png"%idx), c["centroid"][0], c["centroid"][1])
print("zooms done")
