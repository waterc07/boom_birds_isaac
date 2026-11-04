import json, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def font(size=12):
    for name in ["DejaVuSans.ttf", "arial.ttf"]:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()

def grid_view(src, dst, scale=3, step=10, label_step=20):
    img = Image.open(src).convert("RGB")
    W, H = img.size
    big = img.resize((W*scale, H*scale), Image.LANCZOS)
    canvas = Image.new("RGB", (W*scale+46, H*scale+22), (25,25,25))
    canvas.paste(big, (46, 22))
    overlay = Image.new("RGBA", canvas.size, (0,0,0,0))
    d = ImageDraw.Draw(overlay)
    f = font(12)
    for x in range(0, W+1, step):
        xs = 46 + x*scale
        if xs >= canvas.size[0]: break
        d.line([(xs,22),(xs,22+H*scale)], fill=(255,0,255,70), width=1)
    for y in range(0, H+1, step):
        ys = 22 + y*scale
        if ys >= canvas.size[1]: break
        d.line([(46,ys),(46+W*scale,ys)], fill=(255,0,255,70), width=1)
    for x in range(0, W+1, label_step):
        xs = 46 + x*scale
        if xs >= canvas.size[0]-10: continue
        d.text((xs-8, 3), str(x), font=f, fill=(255,255,0,255))
    for y in range(0, H+1, label_step):
        ys = 22 + y*scale
        if ys >= canvas.size[1]-10: continue
        d.text((2, ys-6), str(y), font=f, fill=(255,255,0,255))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    canvas.save(dst)

def zoom_view(src, dst, cx, cy, half=22, scale=12, step=5):
    img = Image.open(src).convert("RGB")
    W, H = img.size
    x0 = max(0, cx-half); x1 = min(W, cx+half)
    y0 = max(0, cy-half); y1 = min(H, cy+half)
    crop = img.crop((x0,y0,x1,y1))
    cw, ch = crop.size
    big = crop.resize((cw*scale, ch*scale), Image.NEAREST)
    canvas = Image.new("RGB", (cw*scale+50, ch*scale+22), (25,25,25))
    canvas.paste(big, (50, 22))
    overlay = Image.new("RGBA", canvas.size, (0,0,0,0))
    d = ImageDraw.Draw(overlay)
    f = font(13)
    for x in range(x0, x1+1):
        if (x - x0) % step: continue
        xs = 50 + (x-x0)*scale
        d.line([(xs,22),(xs,22+ch*scale)], fill=(255,0,255,90), width=1)
        d.text((xs-12, 3), str(x), font=f, fill=(255,255,0,255))
    for y in range(y0, y1+1):
        if (y - y0) % step: continue
        ys = 22 + (y-y0)*scale
        d.line([(50,ys),(50+cw*scale,ys)], fill=(255,0,255,90), width=1)
        d.text((2, ys-7), str(y), font=f, fill=(255,255,0,255))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    canvas.save(dst)

if __name__ == "__main__":
    cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    for item in cfg["grids"]:
        grid_view(item["src"], item["dst"], item.get("scale",3))
        print("grid", item["dst"])
    for item in cfg.get("zooms", []):
        zoom_view(item["src"], item["dst"], item["cx"], item["cy"], item.get("half",22), item.get("scale",12))
        print("zoom", item["dst"])
