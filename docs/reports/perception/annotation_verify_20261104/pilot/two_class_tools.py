"""Two-class (central_tower / similar_structure_ms1) annotation tools.

Subcommands:
  selection  build shard selection from a sensor run (midpoint systematic + sha check)
  template   create a fill-me labels skeleton from a selection
  qa         fail-loud label QA (1:1, instances, v distribution, coordinate domain, GT rules)
  stats      summarize labels

Schema: dsh.landmark_two_class_annotations.v1 (see T31 prep doc).
bbox = SOURCE_IMAGE_PIXELS_XYXY; class0 keypoint = SOURCE_IMAGE_PIXELS_NORMALIZED_01;
class1 keypoint = null, v=0 always.
"""
import argparse, hashlib, json, sys
from collections import Counter
from pathlib import Path

REPO = Path(r"E:\isaac\proj_boom_birds")
SPEC = REPO/"configs/perception/landmark_two_class_label_spec_v1.json"

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def midpoint_systematic(frames, k):
    n = len(frames); k = min(k, n)
    return [frames[min(n-1, int((i+0.5)*n/k))] for i in range(k)]

def write_json(path, doc):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=1, ensure_ascii=False)+"\n", encoding="utf-8")
    return sha(p)

def cmd_selection(args):
    run = REPO/args.run
    summary = json.loads((run/"summary.json").read_text(encoding="utf-8"))
    images = [Path(p).name for p in summary.get("images", [])]
    families = [f.strip() for f in args.families.split(",") if f.strip()]
    per_family = args.per_family
    frames, meta = [], {}
    for fam in families:
        fam_frames = sorted([f for f in images if f.startswith(fam)],
                            key=lambda f: int(f.rsplit("_", 1)[1].split(".")[0]))
        picked = midpoint_systematic(fam_frames, per_family)
        rows = []
        for f in picked:
            p = run/"images"/f
            rows.append({"frame_id": f, "image": str(p.relative_to(REPO)).replace("\\", "/"),
                         "image_sha256": sha(p), "family": fam, "shard": args.shard,
                         "sequence": int(f.rsplit("_", 1)[1].split(".")[0])})
        frames.extend(rows)
        meta[fam] = {"accepted": len(fam_frames), "selected": len(picked)}
    doc = {"schema_version": "dsh.landmark_two_class_selection.v1",
           "status": "PREDECLARED_SELECTION_APPLIED_AFTER_CAPTURE",
           "run": args.run, "shard": args.shard, "families": families,
           "rule": {"id": "two_class_midpoint_systematic_v1",
                    "text": "per family accepted front_rgb frames sorted by sequence; midpoint systematic floor((i+0.5)*n/k); frozen before image inspection; no model score used",
                    "per_family": per_family, "total": len(frames)},
           "per_family": meta, "frames": frames}
    print(json.dumps({"selected": len(frames), "sha256": write_json(args.out, doc),
                      "per_family": meta}, indent=1))

def cmd_template(args):
    sel = json.loads(Path(args.selection).read_text(encoding="utf-8"))
    spec_sha = sha(SPEC) if SPEC.is_file() else None
    frames = []
    for f in sel["frames"]:
        frames.append({**{k: f[k] for k in ("frame_id", "image", "image_sha256", "family", "shard", "sequence")},
                       "image_width": 320, "image_height": 240,
                       "tower_present": None, "ms1_present": None,
                       "identity_ambiguity": None, "gt_uncertainty": None,
                       "occlusion": None, "notes": "FILL_ME",
                       "instances": []})
    doc = {"schema_version": "dsh.landmark_two_class_annotations.v1",
           "status": "DRAFT_FILL_ME_NOT_A_LABEL",
           "annotation_spec": {"path": str(SPEC.relative_to(REPO)).replace("\\", "/"), "sha256": spec_sha},
           "coordinate_space": {"bbox": "SOURCE_IMAGE_PIXELS_XYXY",
                                "keypoint": "SOURCE_IMAGE_PIXELS_NORMALIZED_01"},
           "frames": frames}
    print(json.dumps({"frames": len(frames), "sha256": write_json(args.out, doc)}, indent=1))

def _bbox_ok(b, w, h):
    if not isinstance(b, list) or len(b) != 4: return False, "bbox_not_xyxy4"
    try: x1, y1, x2, y2 = [float(v) for v in b]
    except Exception: return False, "bbox_not_numeric"
    if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h): return False, "bbox_out_of_image_or_degenerate"
    return True, None

def cmd_qa(args):
    lab = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    sel = json.loads(Path(args.selection).read_text(encoding="utf-8"))
    errors, warnings = [], []
    frames = lab.get("frames", [])
    sel_frames = {f["frame_id"]: f for f in sel["frames"]}
    lab_frames = {f["frame_id"]: f for f in frames}
    if len(lab_frames) != len(frames): errors.append("duplicate frame_id in labels")
    if len(sel_frames) != len(sel.get("frames", [])): errors.append("duplicate frame_id in selection")
    missing = sorted(set(sel_frames) - set(lab_frames)); extra = sorted(set(lab_frames) - set(sel_frames))
    if missing: errors.append("missing labels for %d frames: %s" % (len(missing), missing[:5]))
    if extra: errors.append("extra labels not in selection: %d" % len(extra))
    x1_warn = 0
    for fid, f in lab_frames.items():
        s = sel_frames.get(fid)
        if not s: continue
        if f.get("image_sha256") != s.get("image_sha256"): errors.append(fid+": image sha mismatch")
        w, h = f.get("image_width"), f.get("image_height")
        if (w, h) != (320, 240): errors.append(fid+": image size not 320x240")
        tp, mp = f.get("tower_present"), f.get("ms1_present")
        if not isinstance(tp, bool): errors.append(fid+": tower_present must be bool (not filled?)")
        if not isinstance(mp, bool): errors.append(fid+": ms1_present must be bool (not filled?)")
        if f.get("identity_ambiguity") not in ("NONE", "UNCERTAIN", "AMBIGUOUS"):
            errors.append(fid+": identity_ambiguity invalid")
        if f.get("gt_uncertainty") not in ("NONE", "FULLY_OCCLUDED", "REFERENCE_UNRESOLVED", "INSTANCE_UNRESOLVED"):
            errors.append(fid+": gt_uncertainty invalid")
        if f.get("occlusion") not in ("NONE", "PARTIAL", "FULL"):
            errors.append(fid+": occlusion invalid")
        insts = f.get("instances") or []
        classes = [i.get("class") for i in insts]
        if any(c not in (0, 1) for c in classes): errors.append(fid+": instance class not 0/1")
        c0 = [i for i in insts if i.get("class") == 0]
        c1 = [i for i in insts if i.get("class") == 1]
        if len(c0) > 1: errors.append(fid+": class0 instance count > 1 (single tower)")
        if len(c1) == 0 and mp is True:
            pass  # handled below
        # duplicate same-class bbox
        seen_bbox = set()
        for i in insts:
            b = i.get("bbox_xyxy")
            key = (i.get("class"), tuple(round(float(v), 3) for v in b) if isinstance(b, list) and len(b) == 4 else None)
            if key in seen_bbox: errors.append(fid+": duplicate same-class bbox")
            seen_bbox.add(key)
        if not str(f.get("image", "")).startswith("outputs/"):
            errors.append(fid+": image must be repo-relative starting with outputs/")
        # truncated edges must touch the corresponding image edge (tolerance 1.5px)
        for i in insts:
            b = i.get("bbox_xyxy"); tr = i.get("truncated_edges") or {}
            if isinstance(b, list) and len(b) == 4:
                bx1, by1, bx2, by2 = [float(v) for v in b]
                tol = 1.5
                if tr.get("left") and bx1 > tol: errors.append(fid+": left truncation but bbox not touching left edge")
                if tr.get("right") and bx2 < 320 - tol: errors.append(fid+": right truncation but bbox not touching right edge")
                if tr.get("top") and by1 > tol: errors.append(fid+": top truncation but bbox not touching top edge")
                if tr.get("bottom") and by2 < 240 - tol: errors.append(fid+": bottom truncation but bbox not touching bottom edge")
                if not tr.get("left") and bx1 <= 0.5 and False:
                    pass
        full_occ = f.get("occlusion") == "FULL"
        if tp is True and not c0 and not full_occ:
            errors.append(fid+": tower_present=true but no class0 instance and occlusion!=FULL")
        if tp is False and c0: errors.append(fid+": tower_present=false but class0 instance exists")
        if mp is True and not c1: errors.append(fid+": ms1_present=true but no class1 instance")
        if mp is False and c1: errors.append(fid+": ms1_present=false but class1 instance exists")
        if tp is False and mp is False and insts: errors.append(fid+": negative frame has instances")
        # diag HIGH gate: MS1 projected >= 8px must have class1 instance or explicit INSTANCE_UNRESOLVED
        proj = f.get("projection_aid") or {}
        ms1_px = proj.get("ms1_projected_max_side_px")
        if isinstance(ms1_px, (int, float)) and ms1_px >= 8.0 and not c1:
            if f.get("gt_uncertainty") != "INSTANCE_UNRESOLVED":
                errors.append(fid+": MS1 projection >=8px but no class1 instance and no INSTANCE_UNRESOLVED")
        tower_px = proj.get("tower_projected_max_side_px")
        if isinstance(tower_px, (int, float)) and tower_px >= 8.0 and tp is False and f.get("gt_uncertainty") != "INSTANCE_UNRESOLVED":
            warnings.append(fid+": tower projection >=8px but tower_present=false (check FOV/occlusion)")
        for i in insts:
            ok, why = _bbox_ok(i.get("bbox_xyxy"), w, h)
            if not ok: errors.append(fid+": class%s %s" % (i.get("class"), why))
            if i.get("class") == 1:
                if i.get("v") != 0: errors.append(fid+": class1 v must be 0")
                if i.get("keypoint_x") is not None or i.get("keypoint_y") is not None:
                    errors.append(fid+": class1 keypoint must be null (bbox-centre forbidden)")
                if i.get("reference_available") is not False: errors.append(fid+": class1 reference_available must be false")
            if i.get("class") == 0:
                v = i.get("v")
                if v not in (0, 1): errors.append(fid+": class0 v must be 0/1")
                kx, ky = i.get("keypoint_x"), i.get("keypoint_y")
                if v == 1:
                    if kx is None or ky is None: errors.append(fid+": class0 v=1 without keypoint")
                    else:
                        if not (0.0 <= float(kx) <= 1.0 and 0.0 <= float(ky) <= 1.0):
                            errors.append(fid+": class0 keypoint not normalized [0,1]")
                    if i.get("reference_available") is not True: errors.append(fid+": class0 v=1 but reference_available!=true")
                if v == 0:
                    if kx is not None or ky is not None: errors.append(fid+": class0 v=0 must have null keypoint")
                    if i.get("reference_available") is not False: errors.append(fid+": class0 v=0 but reference_available!=false")
            tr = i.get("truncated_edges") or {}
            if set(tr) != {"left", "right", "top", "bottom"}:
                errors.append(fid+": truncated_edges must have 4 keys")
            # coordinate-domain sanity: bbox in pixels should be far above 1.0 somewhere
            b = i.get("bbox_xyxy")
            if isinstance(b, list) and len(b) == 4 and all(isinstance(x, (int, float)) and 0 <= x <= 1.0 for x in b):
                x1_warn += 1
    if x1_warn: errors.append("%d instances look normalized (all coords <=1.0) but bbox domain is pixels" % x1_warn)
    stats = {
        "frames": len(frames),
        "tower_present": sum(1 for f in frames if f.get("tower_present") is True),
        "ms1_present": sum(1 for f in frames if f.get("ms1_present") is True),
        "same_frame": sum(1 for f in frames if f.get("tower_present") is True and f.get("ms1_present") is True),
        "negatives": sum(1 for f in frames if f.get("tower_present") is False and f.get("ms1_present") is False),
        "gt_unobservable": sum(1 for f in frames if f.get("tower_present") is True and f.get("occlusion") == "FULL"),
        "class0_instances": sum(1 for f in frames for i in (f.get("instances") or []) if i.get("class") == 0),
        "class1_instances": sum(1 for f in frames for i in (f.get("instances") or []) if i.get("class") == 1),
        "class0_v1": sum(1 for f in frames for i in (f.get("instances") or []) if i.get("class") == 0 and i.get("v") == 1),
        "class0_v0": sum(1 for f in frames for i in (f.get("instances") or []) if i.get("class") == 0 and i.get("v") == 0),
        "class1_v1": sum(1 for f in frames for i in (f.get("instances") or []) if i.get("class") == 1 and i.get("v") == 1),
        "identity_ambiguity": dict(Counter(f.get("identity_ambiguity") for f in frames)),
        "gt_uncertainty": dict(Counter(f.get("gt_uncertainty") for f in frames)),
        "occlusion": dict(Counter(f.get("occlusion") for f in frames)),
    }
    report = {"status": "PASS" if not errors else "FAIL", "errors": errors,
              "warnings": warnings, "stats": stats,
              "labels_sha256": sha(args.labels), "selection_sha256": sha(args.selection)}
    write_json(args.out, report)
    print(json.dumps({k: report[k] for k in ("status", "errors", "warnings")}, indent=1))
    print(json.dumps(stats, indent=1))
    if errors: sys.exit(1)

def cmd_stats(args):
    lab = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    frames = lab.get("frames", [])
    out = {"frames": len(frames),
           "class0_instances": sum(1 for f in frames for i in (f.get("instances") or []) if i.get("class") == 0),
           "class1_instances": sum(1 for f in frames for i in (f.get("instances") or []) if i.get("class") == 1),
           "same_frame": sum(1 for f in frames if f.get("tower_present") and f.get("ms1_present")),
           "negatives": sum(1 for f in frames if not f.get("tower_present") and not f.get("ms1_present")),
           "by_family": dict(Counter(f.get("family") for f in frames))}
    print(json.dumps(out, indent=1))

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("selection"); s.add_argument("--run", required=True)
    s.add_argument("--families", required=True); s.add_argument("--per-family", type=int, default=22)
    s.add_argument("--shard", default="A"); s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_selection)
    t = sub.add_parser("template"); t.add_argument("--selection", required=True)
    t.add_argument("--out", required=True); t.set_defaults(func=cmd_template)
    q = sub.add_parser("qa"); q.add_argument("--labels", required=True)
    q.add_argument("--selection", required=True); q.add_argument("--out", required=True)
    q.set_defaults(func=cmd_qa)
    st = sub.add_parser("stats"); st.add_argument("--labels", required=True)
    st.set_defaults(func=cmd_stats)
    args = ap.parse_args(); args.func(args)

if __name__ == "__main__":
    main()
