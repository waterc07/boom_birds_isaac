"""Render wide band crops (5x) for TINY blind frames to identify tiny targets."""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
REPO = Path(r"E:\isaac\proj_boom_birds")
BASE = REPO/"docs/reports/perception/annotation_verify_20261104"
LIST = REPO/"docs/reports/perception/posteval_20261104/TINY_BLIND_REANNOTATION_FRAMES_20261104.json"
OUT = BASE/"pilot/tiny_blind"
doc = json.loads(LIST.read_text(encoding="utf-8"))
def font(size=13):
    for name in ("DejaVuSans.ttf","arial.ttf"):
        try: return ImageFont.truetype(name,size)
        except Exception: pass
    return ImageFont.load_default()
F = font(14)
def band(src,dst,box=(0,60,320,175),scale=5,step=10):
    img=Image.open(src).convert("RGB"); x0,y0,x1,y1=box
    crop=img.crop(box); cw,ch=crop.size
    big=crop.resize((cw*scale,ch*scale),Image.LANCZOS)
    canvas=Image.new("RGB",(cw*scale+46,ch*scale+22),(25,25,25)); canvas.paste(big,(46,22))
    ov=Image.new("RGBA",canvas.size,(0,0,0,0)); d=ImageDraw.Draw(ov)
    for x in range(x0,x1+1,step):
        xs=46+(x-x0)*scale
        d.line([(xs,22),(xs,22+ch*scale)],fill=(255,0,255,60))
        if (x-x0)%20==0: d.text((xs-10,3),str(x),font=F,fill=(255,255,0,255))
    for y in range(y0,y1+1,step):
        ys=22+(y-y0)*scale
        d.line([(46,ys),(46+cw*scale,ys)],fill=(255,0,255,60))
        if (y-y0)%20==0: d.text((2,ys-8),str(y),font=F,fill=(255,255,0,255))
    Image.alpha_composite(canvas.convert("RGBA"),ov).convert("RGB").save(dst)
cues=json.loads((OUT/"cues.json").read_text(encoding="utf-8"))
for i,fr in enumerate(doc["frames"]):
    p=REPO/fr["image"]
    dst=OUT/("band_%02d.png"%i)
    band(p,dst,(0,60,320,175),5,10)
    c=cues[fr["frame_id"]]
    if c["centroid"]:
        img=Image.open(dst).convert("RGB"); d=ImageDraw.Draw(img)
        u,v=c["centroid"]; xs=46+u*5; ys=22+(v-60)*5
        d.ellipse([xs-7,ys-7,xs+7,ys+7],outline=(0,255,255),width=2)
        img.save(dst)
print("bands:", len(doc["frames"]))
