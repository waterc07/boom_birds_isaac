
import json, hashlib, sys
from pathlib import Path
from PIL import Image, ImageDraw

repo = Path(r"E:\isaac\proj_boom_birds")
work = repo / "docs/reports/perception/annotation_verify_20261104/work"
dec = json.loads((work / "decisions_final.json").read_text(encoding="utf-8"))

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

anns = []
for (fid, img, family, origin_split, seq, present, vis, trunc, occl, amb, bbox, kp, refstatus, negtype, notes) in dec:
    p = repo / img
    with Image.open(p) as im:
        w, h = im.size
    item = {
        "frame_id": fid,
        "image": img.replace("\\", "/"),
        "image_sha256": sha(p),
        "image_width": w,
        "image_height": h,
        "source": {
            "run": "sensor_shadow",
            "family": family,
            "generation": int(fid.rsplit("_g", 1)[1].split(".")[0]),
            "sequence": seq,
            "origin_split_in_freeze": origin_split,
            "split": "exposed_development",
            "exposure_note": "frames were declared sealed_test in the original freeze but have since been exposed/used; they are NOT sealed test data and are relabelled exposed_development per repo policy",
            "image_path": img.replace("\\", "/")
        },
        "target": {
            "landmark_id": "RMUC2027_CENTRAL_TOWER_PROPOSED",
            "class": "tower",
            "present": present,
            "visibility": vis,
            "truncated": trunc,
            "occluded": occl,
            "ambiguous": amb
        },
        "geometry": {
            "bbox_xywh": bbox,
            "bbox_definition": "axis-aligned box of the visible tower object (head+arms, tapering body, attached stepped base pedestal), clipped to image border; excludes ground markings, shadows and unrelated structures",
            "keypoint": None if kp is None else {"name": "green_roof_light_center", "x": kp[0], "y": kp[1], "visible": True},
            "reference_status": refstatus
        },
        "negative_type": negtype,
        "annotator": "agent:annot (DSH teammate, DeepSeek agent, proxy pixel annotation at 16x-20x zoom); NOT an expert or human independent reviewer",
        "annotation_uncertainty": {
            "bbox_px": 3.0,
            "keypoint_px": 1.5,
            "identity": "not_ambiguous" if not amb else "similar_structure_present_identity_unresolved",
            "note": "bbox edges of soft/white base and blur are uncertain by a few px; green light is only 3-8 px wide at 320x240"
        },
        "blind_pass": {
            "protocol": "images only; old labels/geometry NOT opened before this file was written",
            "view_aids": "3x/16x nearest-neighbour zoom crops with native-pixel grid; zoom windows centred using a disclosed pure-green colour cue (threshold g>=90,g-r>=25,g-b>=25); final centre chosen by eye",
            "uncertainty_floor": "green-light core is 10-49 px area (bbox 4x3 to 8x7 px); manual centre reproducibility ~+/-1.5 px = +/-0.54 deg"
        },
        "notes": notes
    }
    anns.append(item)

doc = {
    "schema_version": "dsh.tower_annotation.v1",
    "status": "AGENT_BLIND_PROXY_REANNOTATION_EXPOSED_DATA_NOT_SEALED_NOT_EXPERT",
    "note": "Independent blind re-annotation of exposed frames by an agent, for annotation-consistency checking only. NOT expert review, NOT sealed test labels, NOT model evidence.",
    "coordinate_contract": {
        "image_origin": "top-left",
        "bbox_format": "xywh_px",
        "keypoint_units": "px",
        "normalization": "none; source pixels"
    },
    "root": str(repo),
    "annotations": anns
}
out = repo / "docs/reports/perception/annotation_verify_20261104/blind_pass/annotations_blind.json"
out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("wrote", out, "count", len(anns))

# render QA overlays (blind only)
od = work / "overlay_final"
od.mkdir(parents=True, exist_ok=True)
scale = 2
for item in anns:
    p = repo / item["image"]
    im = Image.open(p).convert("RGB")
    big = im.resize((im.width*scale, im.height*scale), Image.LANCZOS)
    d = ImageDraw.Draw(big)
    g = item["geometry"]
    if g["bbox_xywh"]:
        x,y,w,h = g["bbox_xywh"]
        d.rectangle([x*scale, y*scale, (x+w)*scale-1, (y+h)*scale-1], outline=(255,0,0), width=2)
    if g["keypoint"]:
        kx, ky = g["keypoint"]["x"]*scale, g["keypoint"]["y"]*scale
        d.line([(kx-10,ky),(kx+10,ky)], fill=(0,120,255), width=1)
        d.line([(kx,ky-10),(kx,ky+10)], fill=(0,120,255), width=1)
        d.ellipse([kx-5,ky-5,kx+5,ky+5], outline=(0,80,255), width=2)
    big.save(od / item["frame_id"])
print("overlays", len(anns))
