import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
REPO=Path(r"E:\isaac\proj_boom_birds")
BASE=REPO/"docs/reports/perception/annotation_verify_20261104"
SEL=REPO/"outputs/perception/dev_annotations_20261104/identity_t25/selection.json"
sel=json.loads(SEL.read_text(encoding="utf-8")); run=REPO/sel["run"]; imgdir=run/"images"
OUT=BASE/"pilot/identity_t25"
frames=sel["frames"]
def font(size=13):
    for n in ("DejaVuSans.ttf","arial.ttf"):
        try: return ImageFont.truetype(n,size)
        except Exception: pass
    return ImageFont.load_default()
F=font(13)
def crop(idx,dst,box,scale=4,step=10):
    f=frames[idx]; img=Image.open(imgdir/f).convert("RGB"); x0,y0,x1,y1=box
    c=img.crop(box); cw,ch=c.size; big=c.resize((cw*scale,ch*scale),Image.LANCZOS)
    canvas=Image.new("RGB",(cw*scale+46,ch*scale+22),(25,25,25)); canvas.paste(big,(46,22))
    ov=Image.new("RGBA",canvas.size,(0,0,0,0)); d=ImageDraw.Draw(ov)
    for x in range(x0,x1+1,step):
        xs=46+(x-x0)*scale; d.line([(xs,22),(xs,22+ch*scale)],fill=(255,0,255,70)); d.text((xs-12,3),str(x),font=F,fill=(255,255,0))
    for y in range(y0,y1+1,step):
        ys=22+(y-y0)*scale; d.line([(46,ys),(46+cw*scale,ys)],fill=(255,0,255,70)); d.text((2,ys-8),str(y),font=F,fill=(255,255,0))
    Image.alpha_composite(canvas.convert("RGBA"),ov).convert("RGB").save(dst)
crop(0, OUT/"zoom_mutual_00.png", (80,60,260,200), 4)
crop(7, OUT/"zoom_mutual_07.png", (80,60,260,200), 4)
crop(15, OUT/"zoom_far_15.png", (60,70,260,200), 4)
crop(22, OUT/"zoom_far_22.png", (60,70,260,200), 4)
print("done")
