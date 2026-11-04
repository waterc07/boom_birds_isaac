"""Compare the independent blind re-annotation with the old landmark labels.

No model, detector or training code.  Reads:
  - docs/reports/perception/annotation_verify_20261104/blind_pass/annotations_blind.json
  - configs/perception/landmark_independent_labels_v1.json   (old, 9 localization frames)
  - configs/perception/geometry_test_labels_v2.json          (old, 9 localization + 3 negative frames)
  - docs/reports/perception/annotation_sample_v1/annotations.json (old copy of the 12 sample frames)

Writes a machine-readable comparison JSON with bbox IoU, centre/width/height
deltas, keypoint pixel deltas, image-bearing deltas (fx=160 px, cx=160 px,
320x240), a colour-cue sensitivity centroid and an explicit classification.

This is a proxy re-annotation consistency check by one agent; it is not an
expert or human independent review and it is not a sealed-test label set.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

FX = 160.0
CX = 160.0
CY = 120.0
DEG_PER_PX = math.degrees(math.atan(1.0 / FX))  # 0.358 deg per px at the optical axis

CLASSES = ("consistent", "acceptable_deviation", "substantive_disagreement", "undeterminable")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bearing_deg(x):
    return math.degrees(math.atan2(float(x) - CX, FX))


def bbox_iou(a, b):
    if not a or not b:
        return None
    ax, ay, aw, ah = [float(v) for v in a]
    bx, by, bw, bh = [float(v) for v in b]
    ix0, iy0 = max(ax, bx), max(ay, by)
    ix1, iy1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def colour_centroid(image_path):
    """Pure colour cue for the green roof light; independent of the blind pick."""
    rgb = np.asarray(Image.open(image_path).convert("RGB")).astype(np.int16)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mask = (g >= 90) & (g - r >= 25) & (g - b >= 25)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    # keep the largest 4-connected component
    seen = np.zeros(mask.shape, dtype=bool)
    best = None
    for y0, x0 in zip(ys, xs):
        if seen[y0, x0]:
            continue
        stack = [(y0, x0)]
        seen[y0, x0] = True
        comp = []
        while stack:
            y, x = stack.pop()
            comp.append((y, x))
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < mask.shape[0] and 0 <= nx < mask.shape[1] and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if best is None or len(comp) > len(best):
            best = comp
    if best is None or len(best) < 2:
        return None
    yy = [p[0] for p in best]
    xx = [p[1] for p in best]
    return {
        "centroid_px": [round(sum(xx) / len(xx), 2), round(sum(yy) / len(yy), 2)],
        "bbox_xyxy": [min(xx), min(yy), max(xx), max(yy)],
        "pixels": len(best),
    }


def keypoint(flat):
    if flat is None:
        return None
    if isinstance(flat, dict):
        return [float(flat["x"]), float(flat["y"])]
    return [float(flat[0]), float(flat[1])]


def load_old(repo):
    recs = {}
    ind = json.loads((repo / "configs/perception/landmark_independent_labels_v1.json").read_text(encoding="utf-8"))
    for item in ind["labels"]:
        recs.setdefault(item["frame_id"], []).append({
            "source": "landmark_independent_labels_v1",
            "present": item.get("present"),
            "visibility": item.get("visibility"),
            "truncated": item.get("truncated"),
            "occluded": item.get("occluded"),
            "ambiguous": item.get("ambiguous"),
            "negative_type": item.get("negative_type"),
            "bbox_xywh": item.get("bbox_xywh"),
            "reference_point_px": item.get("reference_point_px"),
            "reference_status": item.get("reference_status"),
            "localization_subset": item.get("localization_subset"),
            "notes": item.get("notes"),
        })
    geo = json.loads((repo / "configs/perception/geometry_test_labels_v2.json").read_text(encoding="utf-8"))
    for item in geo["labels"]:
        recs.setdefault(item["frame_id"], []).append({
            "source": "geometry_test_labels_v2",
            "present": item.get("present"),
            "visibility": item.get("visibility"),
            "truncated": item.get("truncated"),
            "occluded": item.get("occluded"),
            "ambiguous": item.get("ambiguous"),
            "negative_type": item.get("negative_type"),
            "bbox_xywh": item.get("bbox_xywh"),
            "reference_point_px": item.get("reference_point_px"),
            "reference_status": item.get("reference_status"),
            "localization_subset": item.get("localization_subset"),
            "notes": item.get("notes"),
        })
    smp = json.loads((repo / "docs/reports/perception/annotation_sample_v1/annotations.json").read_text(encoding="utf-8"))
    for item in smp["annotations"]:
        target, geom = item.get("target", {}), item.get("geometry", {})
        kp = geom.get("keypoint")
        recs.setdefault(item["frame_id"], []).append({
            "source": "annotation_sample_v1",
            "present": target.get("present"),
            "visibility": target.get("visibility"),
            "truncated": target.get("truncated"),
            "occluded": target.get("occluded"),
            "ambiguous": target.get("ambiguous"),
            "negative_type": item.get("negative_type"),
            "bbox_xywh": geom.get("bbox_xywh"),
            "reference_point_px": None if kp is None else [kp.get("x"), kp.get("y")],
            "reference_status": geom.get("reference_status"),
            "localization_subset": None,
            "notes": None,
        })
    return recs


def _worst(class_a, class_b):
    order = ["consistent", "acceptable_deviation", "undeterminable", "substantive_disagreement"]
    return class_a if order.index(class_a) >= order.index(class_b) else class_b


def _norm_ref(value):
    if value is None:
        return None
    return "UNAVAILABLE" if str(value).startswith("UNAVAILABLE") else value


def classify(blind, old, iou, kp_px, kp_unavailable, ambiguous):
    """Return (combined, bbox_class, keypoint_class, semantic_class, reasons).

    Missing old fields (schema differences) are NOT counted as mismatches; they
    are reported as not-comparable and are a spec/format finding of their own.
    """
    reasons = []
    semantic = "match"
    sem_detail = []
    if blind["present"] != old["present"]:
        semantic = "mismatch"
        sem_detail.append("present blind=%s old=%s" % (blind["present"], old["present"]))
    else:
        comparable = 0
        for field in ("visibility", "reference_status"):
            bv, ov = blind.get(field), old.get(field)
            if field == "reference_status":
                bv, ov = _norm_ref(bv), _norm_ref(ov)
            if bv is not None and ov is not None:
                comparable += 1
                if bv != ov:
                    sem_detail.append("%s blind=%r old=%r" % (field, bv, ov))
        for field in ("truncated", "negative_type"):
            bv, ov = blind.get(field), old.get(field)
            if bv is not None and ov is not None:
                comparable += 1
                if bv != ov:
                    sem_detail.append("%s blind=%r old=%r" % (field, bv, ov))
        if sem_detail:
            semantic = "mismatch"
        elif comparable == 0:
            semantic = "not_comparable"
    if semantic == "mismatch":
        reasons.extend(sem_detail)

    if ambiguous:
        reasons.append("blind target identity/negative semantics flagged ambiguous")
        return "undeterminable", "undeterminable", "undeterminable", semantic, reasons
    if not blind["present"] and old["present"] is False:
        combined = "consistent" if semantic == "match" else "substantive_disagreement"
        reasons.append("both absent; no geometry to compare")
        return combined, "not_applicable", "not_applicable", semantic, reasons
    if blind["present"] and old["present"]:
        if iou is None:
            bbox_class = "undeterminable"
        elif iou >= 0.70:
            bbox_class = "consistent"
        elif iou >= 0.30:
            bbox_class = "acceptable_deviation"
        else:
            bbox_class = "substantive_disagreement"
        if kp_unavailable:
            kp_class = "undeterminable"
        elif kp_px is None:
            kp_class = "undeterminable"
        elif kp_px <= 2.0:
            kp_class = "consistent"
        elif kp_px <= 4.0:
            kp_class = "acceptable_deviation"
        else:
            kp_class = "substantive_disagreement"
        if semantic == "mismatch":
            combined = "substantive_disagreement"
        elif bbox_class == "undeterminable" or kp_class == "undeterminable":
            combined = "undeterminable"
        else:
            combined = _worst(bbox_class, kp_class)
        reasons.append("bbox_iou=%s keypoint_px=%s" % ("NA" if iou is None else round(iou, 3),
                                                      "NA" if kp_px is None else kp_px))
        return combined, bbox_class, kp_class, semantic, reasons
    reasons.append("present/absent bookkeeping inconsistency")
    return "undeterminable", "undeterminable", "undeterminable", semantic, reasons


def render_compare(blind, old, out_path, repo):
    image = Image.open(repo / blind["image"]).convert("RGB")
    draw = ImageDraw.Draw(image)
    if blind["geometry"]["bbox_xywh"]:
        x, y, w, h = blind["geometry"]["bbox_xywh"]
        draw.rectangle([x, y, x + w, y + h], outline=(255, 0, 0), width=1)
    if old and old.get("bbox_xywh"):
        x, y, w, h = old["bbox_xywh"]
        draw.rectangle([x, y, x + w, y + h], outline=(0, 80, 255), width=1)
    kb = blind["geometry"]["keypoint"]
    ko = old.get("reference_point_px") if old else None
    if kb:
        draw.ellipse([kb["x"] - 2, kb["y"] - 2, kb["x"] + 2, kb["y"] + 2], outline=(255, 0, 0))
    if ko:
        draw.ellipse([ko[0] - 2, ko[1] - 2, ko[0] + 2, ko[1] + 2], outline=(0, 80, 255))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--blind", type=Path,
                        default=Path("docs/reports/perception/annotation_verify_20261104/blind_pass/annotations_blind.json"))
    parser.add_argument("--prereg", type=Path,
                        default=Path("docs/reports/perception/annotation_verify_20261104/blind_pass/pre_registration.json"))
    parser.add_argument("--output", type=Path,
                        default=Path("docs/reports/perception/annotation_verify_20261104/annotation_verification_20261104.json"))
    parser.add_argument("--overlay-dir", type=Path,
                        default=Path("docs/reports/perception/annotation_verify_20261104/compare_overlays"))
    args = parser.parse_args()
    repo = args.repo.resolve()

    blind_doc = json.loads((repo / args.blind).read_text(encoding="utf-8"))
    prereg = json.loads((repo / args.prereg).read_text(encoding="utf-8"))
    old_recs = load_old(repo)

    items = []
    for ann in blind_doc["annotations"]:
        fid = ann["frame_id"]
        present = ann["target"]["present"]
        geom = ann["geometry"]
        bbox = geom.get("bbox_xywh")
        kp = keypoint(geom.get("keypoint"))
        old_list = old_recs.get(fid, [])
        if not old_list:
            items.append({"frame_id": fid, "match": False})
            continue
        colour = colour_centroid(repo / ann["image"])
        per_old = []
        for old in old_list:
            obbox = old.get("bbox_xywh")
            okp = keypoint(old.get("reference_point_px"))
            iou = bbox_iou(bbox, obbox)
            centre = None
            wh = None
            if bbox and obbox:
                bcx, bcy = bbox[0] + bbox[2] / 2.0, bbox[1] + bbox[3] / 2.0
                ocx, ocy = obbox[0] + obbox[2] / 2.0, obbox[1] + obbox[3] / 2.0
                centre = [round(bcx - ocx, 2), round(bcy - ocy, 2)]
                wh = [round(bbox[2] - obbox[2], 2), round(bbox[3] - obbox[3], 2)]
            kp_px = None
            kp_delta = None
            if kp and okp:
                kp_delta = [round(kp[0] - okp[0], 2), round(kp[1] - okp[1], 2)]
                kp_px = round(math.hypot(kp_delta[0], kp_delta[1]), 3)
            color_delta = None
            if colour and okp:
                c = colour["centroid_px"]
                color_delta = {
                    "colour_vs_old_px": [round(c[0] - okp[0], 2), round(c[1] - okp[1], 2)],
                    "colour_vs_old_dist_px": round(math.hypot(c[0] - okp[0], c[1] - okp[1]), 3),
                }
                if kp:
                    color_delta["colour_vs_blind_dist_px"] = round(math.hypot(c[0] - kp[0], c[1] - kp[1]), 3)
            bearing_old = bearing_deg(okp[0]) if okp else None
            bearing_blind = bearing_deg(kp[0]) if kp else None
            bear_delta = None if (bearing_old is None or bearing_blind is None) else round(bearing_blind - bearing_old, 3)
            cls, bbox_cls, kp_cls, sem_cls, reasons = classify(
                {"present": present, "visibility": ann["target"]["visibility"],
                 "reference_status": geom.get("reference_status"),
                 "negative_type": ann.get("negative_type"),
                 "truncated": ann["target"]["truncated"]},
                {"present": old.get("present"), "visibility": old.get("visibility"),
                 "truncated": old.get("truncated"), "reference_status": old.get("reference_status"),
                 "negative_type": old.get("negative_type")},
                iou, kp_px if kp_px is not None else 999.0,
                (kp is None) or (okp is None), bool(ann["target"]["ambiguous"]))
            per_old.append({
                "old_source": old["source"],
                "old_present": old.get("present"),
                "old_visibility": old.get("visibility"),
                "old_truncated": old.get("truncated"),
                "old_ambiguous": old.get("ambiguous"),
                "old_negative_type": old.get("negative_type"),
                "old_reference_status": old.get("reference_status"),
                "old_bbox_xywh": obbox,
                "old_reference_px": okp,
                "bbox_iou": None if iou is None else round(iou, 4),
                "bbox_centre_delta_px": centre,
                "bbox_width_height_delta_px": wh,
                "keypoint_delta_px": kp_delta,
                "keypoint_dist_px": kp_px,
                "bearing_old_deg": None if bearing_old is None else round(bearing_old, 3),
                "bearing_blind_deg": None if bearing_blind is None else round(bearing_blind, 3),
                "bearing_delta_deg": bear_delta,
                "bearing_delta_1px_rule": None if kp_px is None else round(kp_px * DEG_PER_PX, 3),
                "colour_cue": None if colour is None else {
                    "centroid_px": colour["centroid_px"], "pixels": colour["pixels"],
                    **color_delta,
                },
                "classification": cls,
                "bbox_classification": bbox_cls,
                "keypoint_classification": kp_cls,
                "semantic_classification": sem_cls,
                "reasons": reasons,
            })
        render_compare(ann, old_recs[fid][0], repo / args.overlay_dir / fid, repo)
        items.append({
            "frame_id": fid,
            "image": ann["image"],
            "family": ann["source"]["family"],
            "blind_present": present,
            "blind_visibility": ann["target"]["visibility"],
            "blind_truncated": ann["target"]["truncated"],
            "blind_ambiguous": ann["target"]["ambiguous"],
            "blind_negative_type": ann.get("negative_type"),
            "blind_bbox_xywh": bbox,
            "blind_keypoint_px": kp,
            "blind_reference_status": geom.get("reference_status"),
            "old_records": per_old,
        })

    # ---- summary over (frame, old-source) records ----
    records = [r for it in items if it.get("match", True) for r in it.get("old_records", [])]
    frames = [it for it in items if it.get("match", True) and it.get("old_records")]

    def stats(values):
        if not values:
            return None
        values = sorted(values)
        n = len(values)
        def pct(p):
            k = (n - 1) * p
            lo, hi = int(math.floor(k)), int(math.ceil(k))
            return values[lo] + (values[hi] - values[lo]) * (k - lo)
        return {"n": n, "mean": round(sum(values) / n, 3), "median": round(pct(0.5), 3),
                "p90": round(pct(0.9), 3), "min": round(values[0], 3), "max": round(values[-1], 3)}

    def summarise(recs, label):
        counts = {c: 0 for c in CLASSES}
        bbox_counts = {c: 0 for c in CLASSES}
        kp_counts = {c: 0 for c in CLASSES}
        sem_counts = {"match": 0, "mismatch": 0, "not_comparable": 0}
        for r in recs:
            counts[r["classification"]] += 1
            bbox_counts[r["bbox_classification"]] += 1
            kp_counts[r["keypoint_classification"]] += 1
            sem_counts[r["semantic_classification"]] += 1
        ious = [r["bbox_iou"] for r in recs if r["bbox_iou"] is not None]
        kps = [r["keypoint_dist_px"] for r in recs if r["keypoint_dist_px"] is not None]
        bear = [abs(r["bearing_delta_deg"]) for r in recs if r["bearing_delta_deg"] is not None]
        col = [r["colour_cue"]["colour_vs_old_dist_px"] for r in recs
               if r["colour_cue"] and "colour_vs_old_dist_px" in r["colour_cue"]]
        colb = [r["colour_cue"]["colour_vs_blind_dist_px"] for r in recs
                if r["colour_cue"] and "colour_vs_blind_dist_px" in r["colour_cue"]]
        cdx = [r["bbox_centre_delta_px"][0] for r in recs if r["bbox_centre_delta_px"]]
        cdy = [r["bbox_centre_delta_px"][1] for r in recs if r["bbox_centre_delta_px"]]
        dw = [r["bbox_width_height_delta_px"][0] for r in recs if r["bbox_width_height_delta_px"]]
        dh = [r["bbox_width_height_delta_px"][1] for r in recs if r["bbox_width_height_delta_px"]]
        return {
            "scope": label,
            "records": len(recs),
            "classification_counts": counts,
            "bbox_classification_counts": bbox_counts,
            "keypoint_classification_counts": kp_counts,
            "semantic_classification_counts": sem_counts,
            "bbox_iou": stats(ious),
            "keypoint_dist_px": stats(kps),
            "keypoint_dist_deg": None if not kps else {
                "mean": round(sum(kps) / len(kps) * DEG_PER_PX, 3),
                "max": round(max(kps) * DEG_PER_PX, 3)},
            "bearing_abs_delta_deg": stats(bear),
            "bbox_centre_delta_px": {"dx": stats(cdx), "dy": stats(cdy)},
            "bbox_size_delta_px": {"dw": stats(dw), "dh": stats(dh)},
            "colour_cue_vs_old_px": stats(col),
            "colour_cue_vs_blind_px": stats(colb),
        }

    # per-frame primary record: ind source for ind frames, geo/sample otherwise
    primary = []
    for it in frames:
        recs = it["old_records"]
        pick = next((r for r in recs if r["old_source"] == "landmark_independent_labels_v1"), recs[0])
        primary.append((it, pick))

    sem_fields = ("present", "visibility", "reference_status", "truncated", "negative_type")
    sem = {f + "_agree": 0 for f in sem_fields}
    sem.update({f + "_mismatch": 0 for f in sem_fields})
    sem.update({f + "_not_comparable": 0 for f in sem_fields})
    sem["records"] = len(primary)
    sem_detail = []
    for it, r in primary:
        def get_old(field):
            if field == "present":
                return r["old_present"]
            return r["old_" + field]
        def get_blind(field):
            if field == "present":
                return it["blind_present"]
            return it["blind_" + field] if field != "negative_type" else it["blind_negative_type"]
        row = {}
        for field in sem_fields:
            bv, ov = get_blind(field), get_old(field)
            if field == "reference_status":
                bv, ov = _norm_ref(bv), _norm_ref(ov)
            if ov is None:
                sem[field + "_not_comparable"] += 1
                row[field] = ["not_comparable", bv, ov]
            elif bv == ov:
                sem[field + "_agree"] += 1
            else:
                sem[field + "_mismatch"] += 1
                row[field] = ["mismatch", bv, ov]
        if row:
            row["frame_id"] = it["frame_id"]
            sem_detail.append(row)

    # old bbox centre vs old reference point bearing (shows bbox centre is not the reference)
    old_centre_bearing = []
    for it, r in primary:
        bb, ref = r["old_bbox_xywh"], r["old_reference_px"]
        if bb and ref:
            old_centre_bearing.append(abs(bearing_deg(bb[0] + bb[2] / 2.0) - bearing_deg(ref[0])))

    # per-family split
    families = {}
    for it, r in primary:
        families.setdefault(it["family"], []).append(r)

    # colour-cue rule provenance: how close old reference points are to the pure colour centroid
    provenance = []
    for it, r in primary:
        cc = r["colour_cue"]
        if cc and r["old_reference_px"]:
            provenance.append({
                "frame_id": it["frame_id"],
                "old_reference_px": r["old_reference_px"],
                "colour_centroid_px": cc["centroid_px"],
                "old_minus_colour_px": cc["colour_vs_old_px"],
                "distance_px": cc["colour_vs_old_dist_px"],
                "green_pixels": cc["pixels"],
            })

    # semantic comparison per old source (field availability differs between schemas)
    by_source = {}
    for it in frames:
        for r in it["old_records"]:
            src_bucket = by_source.setdefault(r["old_source"], {
                "records": 0,
                "fields": {f: {"comparable": 0, "agree": 0, "mismatch": 0} for f in ("present", "visibility", "truncated", "negative_type", "reference_status")},
                "mismatch_detail": [],
            })
            src_bucket["records"] += 1
            pairs = {
                "present": (it["blind_present"], r["old_present"]),
                "visibility": (it["blind_visibility"], r["old_visibility"]),
                "truncated": (it["blind_truncated"], r["old_truncated"]),
                "negative_type": (it["blind_negative_type"], r["old_negative_type"]),
                "reference_status": (_norm_ref(it["blind_reference_status"]), _norm_ref(r["old_reference_status"])),
            }
            for field, (bv, ov) in pairs.items():
                if ov is None:
                    continue
                bucket = src_bucket["fields"][field]
                bucket["comparable"] += 1
                if bv == ov:
                    bucket["agree"] += 1
                else:
                    bucket["mismatch"] += 1
                    src_bucket["mismatch_detail"].append(
                        {"frame_id": it["frame_id"], "field": field, "blind": bv, "old": ov})

    per_frame_rows = []
    for it, r in primary:
        per_frame_rows.append({
            "frame_id": it["frame_id"],
            "family": it["family"],
            "old_source": r["old_source"],
            "combined": r["classification"],
            "bbox_class": r["bbox_classification"],
            "keypoint_class": r["keypoint_classification"],
            "semantic_class": r["semantic_classification"],
            "bbox_iou": r["bbox_iou"],
            "keypoint_dist_px": r["keypoint_dist_px"],
            "bearing_delta_deg": r["bearing_delta_deg"],
            "blind_present": it["blind_present"],
            "old_present": r["old_present"],
            "blind_visibility": it["blind_visibility"],
            "old_visibility": r["old_visibility"],
        })

    summary = {
        "unique_frames": len(items),
        "unique_frames_with_old_record": len(primary),
        "matched_old_records": len(records),
        "classification_per_frame": summarise([r for _, r in primary], "one primary old record per frame"),
        "classification_all_records": summarise(records, "all old records (sample duplicates geo)"),
        "semantic_agreement": sem,
        "semantic_mismatch_detail": sem_detail,
        "family_split": {k: summarise(v, "family " + k) for k, v in families.items()},
        "old_label_provenance_check": {
            "note": "how close the old reference points are to a pure colour-cue centroid; if the old 'manual pixel' reference matches the colour rule to within a fraction of the light size, the 0.036 deg anchor agreement is circular (label and detector share the green cue)",
            "records": provenance,
            "distance_px": stats([p["distance_px"] for p in provenance]),
        },
        "old_bbox_centre_vs_old_reference_bearing_abs_deg": stats(old_centre_bearing),
        "semantic_check_by_old_source": by_source,
        "per_frame_rows": per_frame_rows,
        "colour_cue_rule": "g>=90, g-r>=25, g-b>=25, 4-connectivity, largest component >=2 px (same rule disclosed in the blind pass view aids)",
        "deg_per_px": round(DEG_PER_PX, 4),
    }

    output = {
        "schema_version": "dsh.annotation_verification.v1",
        "created_at_local": "2026-11-04",
        "evidence_domain": "offline annotation QA on exposed Isaac sensor-shadow frames; no model, no board, no navigation claim",
        "proxy_statement": "single-agent blind proxy re-annotation; not an expert or human independent review; not inter-annotator agreement in the statistical sense",
        "blind_annotations": str(args.blind),
        "blind_sha256": sha(repo / args.blind),
        "pre_registration": str(args.prereg),
        "pre_registration_sha256": sha(repo / args.prereg),
        "bearing_model": {"image_width": 320, "image_height": 240, "fx": FX, "cx": CX,
                          "deg_per_px_at_axis": round(DEG_PER_PX, 4),
                          "deg_per_px_source": "1px ~= atan(1/160) = 0.3581 deg"},
        "old_label_sources": {
            "landmark_independent_labels_v1": {"schema": "dsh.landmark_independent_labels.v1", "records": 79},
            "geometry_test_labels_v2": {"schema": "dsh.geometry_test_labels.v2", "records": 30},
            "annotation_sample_v1": {"schema": "dsh.tower_annotation.v1", "records": 12},
        },
        "frames": items,
        "summary": summary,
    }
    out = repo / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(out),
        "frames": len(items),
        "classification_per_frame": summary["classification_per_frame"]["classification_counts"],
        "bbox_classification": summary["classification_per_frame"]["bbox_classification_counts"],
        "keypoint_classification": summary["classification_per_frame"]["keypoint_classification_counts"],
        "semantic_agreement": {k: v for k, v in sem.items() if k.endswith("_mismatch") or k == "records"},
        "bbox_iou": summary["classification_per_frame"]["bbox_iou"],
        "keypoint_dist_px": summary["classification_per_frame"]["keypoint_dist_px"],
        "colour_vs_old_px": summary["classification_per_frame"]["colour_cue_vs_old_px"],
        "old_bbox_centre_vs_ref_bearing_deg": summary["old_bbox_centre_vs_old_reference_bearing_abs_deg"],
    }, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
