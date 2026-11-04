import json, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def font(size=13):
    for name in ["DejaVuSans.ttf", "arial.ttf"]:
        try: return ImageFont.truetype(name, size)
        except Exception: pass
    return ImageFont.load_default()

def crop_grid(src, dst, box, scale=3, step=10):
    img = Image.open(src).convert("RGB")
    x0,y0,x1,y1 = box
    crop = img.crop(box); cw,ch = crop.size
    big = crop.resize((cw*scale, ch*scale), Image.LANCZOS)
    canvas = Image.new("RGB", (cw*scale+50, ch*scale+22), (25,25,25))
    canvas.paste(big, (50, 22))
    ov = Image.new("RGBA", canvas.size, (0,0,0,0)); d = ImageDraw.Draw(ov); f = font(13)
    for x in range(x0, x1+1, step):
        xs = 50 + (x-x0)*scale
        d.line([(xs,22),(xs,22+ch*scale)], fill=(255,0,255,70))
        d.text((xs-10, 3), str(x), font=f, fill=(255,255,0,255))
    for y in range(y0, y1+1, step):
        ys = 22 + (y-y0)*scale
        d.line([(50,ys),(50+cw*scale,ys)], fill=(255,0,255,70))
        d.text((2, ys-7), str(y), font=f, fill=(255,255,0,255))
    Image.alpha_composite(canvas.convert("RGBA"), ov).convert("RGB").save(dst)

cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for item in cfg: crop_grid(item["src"], item["dst"], item["box"], item.get("scale",3))
print("done", len(cfg))
