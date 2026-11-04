"""Render contact sheets for full visual QA of the 279 draft labels."""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

REPO = Path(r"E:\isaac\proj_boom_birds")
BASE = REPO / "docs/reports/perception/annotation_verify_20261104"
OUT = REPO / "outputs/perception/final_exploratory_20261104"
IMG = REPO / "outputs/sensor_shadow/lm_final_candidate_20261104_sensor/images"

draft = json.loads((OUT / "labels_draft.json").read_text(encoding="utf-8"))
sheets_dir = BASE / "pilot/qa_sheets"
sheets_dir.mkdir(parents=True, exist_ok=True)

def font(size=10):
    for name in ("DejaVuSans.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()

CELL_W, CELL_H = 320, 240
COLS, ROWS = 4, 3
F = font(11)
FAMSHORT = {"lmf_sweep": "swp", "lmf_backoff": "bck", "lmf_near": "near",
            "lmf_edge": "edge", "lmf_similar_negative": "sneg", "lmf_side_negative": "sdneg"}
sheets = {}
for si in range(0, len(draft["annotations"]), COLS * ROWS):
    batch = draft["annotations"][si:si + COLS * ROWS]
    canvas = Image.new("RGB", (COLS * CELL_W, ROWS * CELL_H), (30, 30, 30))
    for k, ann in enumerate(batch):
        img = Image.open(IMG / ann["frame_id"]).convert("RGB")
        draw = ImageDraw.Draw(img)
        geom = ann["geometry"]
        bbox = geom["bbox_xywh"]
        if bbox:
            x, y, w, h = bbox
            draw.rectangle([x, y, x + w, y + h], outline=(255, 0, 0), width=1)
        kp = geom["keypoint"]
        if kp:
            kx, ky = kp["x"], kp["y"]
            draw.line([(kx - 5, ky), (kx + 5, ky)], fill=(0, 140, 255), width=1)
            draw.line([(kx, ky - 5), (kx, ky + 5)], fill=(0, 140, 255), width=1)
        edges = ann["target"]["truncated_edges"]
        flags = "".join(e[0].upper() for e in ("left", "right", "top", "bottom") if edges.get(e))
        fam = FAMSHORT[ann["source"]["family"]]
        label = "%03d %s s%d g%d %s" % (si + k, fam, ann["source"]["sequence"],
                                        geom["green_pixels"], ("T" + flags) if flags else "")
        draw.rectangle([0, 0, len(label) * 6 + 4, 12], fill=(0, 0, 0))
        draw.text((2, 0), label, font=F, fill=(255, 255, 0))
        cx, cy = (k % COLS) * CELL_W, (k // COLS) * CELL_H
        canvas.paste(img, (cx, cy))
    path = sheets_dir / ("qa_sheet_%02d.png" % (si // (COLS * ROWS)))
    canvas.save(path)
    sheets[path.name] = [a["frame_id"] for a in batch]
(BASE / "pilot/qa_sheets_index.json").write_text(
    json.dumps(sheets, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print("sheets:", len(sheets), "first size:", Image.open(sheets_dir / "qa_sheet_00.png").size)
