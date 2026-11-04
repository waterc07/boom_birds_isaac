"""Holdout annotation pipeline skeleton (lightweight; prepared before trigger).

Subcommands:
  selection --run <sensor_run> --families A,B,C --per-family 20 --out selection.json
  stats --labels labels.json --out stats.json

No heavy compute; selection verifies image shas and applies a frozen
midpoint-systematic rule. Actual annotation/QA stays with
scripts/validate_landmark_annotations.py.
"""
import argparse, hashlib, json
from collections import Counter
from pathlib import Path

REPO = Path(r"E:\isaac\proj_boom_birds")

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def midpoint_systematic(frames, k):
    n = len(frames); k = min(k, n)
    return [frames[min(n-1, int((i+0.5)*n/k))] for i in range(k)]

def cmd_selection(args):
    run = REPO/args.run
    summary = json.loads((run/"summary.json").read_text(encoding="utf-8"))
    images = [Path(p).name for p in summary.get("images", [])]
    families = [f.strip() for f in args.families.split(",") if f.strip()]
    per_family = args.per_family
    sel, report = [], {}
    for fam in families:
        frames = sorted([f for f in images if f.startswith(fam)],
                        key=lambda f: int(f.rsplit("_", 1)[1].split(".")[0]))
        picked = midpoint_systematic(frames, per_family)
        rows = []
        for f in picked:
            p = run/"images"/f
            rows.append({"frame_id": f, "image": str(p.relative_to(REPO)).replace("\\", "/"),
                         "image_sha256": sha(p)})
            sel.append(rows[-1])
        report[fam] = {"accepted": len(frames), "selected": len(picked)}
    doc = {"schema_version": "dsh.landmark_holdout_selection.v1",
           "status": "PREDECLARED_SAMPLING_APPLIED_AFTER_CAPTURE",
           "run": args.run, "families": families,
           "rule": {"id": "holdout_midpoint_systematic_v1",
                    "text": "per family accepted frames sorted by sequence; midpoint systematic floor((i+0.5)*n/k); frozen before image inspection; no model score used",
                    "per_family": per_family, "total": len(sel)},
           "per_family": report, "frames": sel}
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=False)+"\n", encoding="utf-8")
    print(json.dumps({"selected": len(sel), "out": str(out), "sha256": sha(out),
                      "per_family": report}, indent=1))

def cmd_stats(args):
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))["annotations"]
    def bucket(a):
        b = a["geometry"].get("bbox_xywh")
        if not b: return "NONE"
        side = max(b[2], b[3]); return "TINY" if side < 15 else ("SMALL" if side < 40 else ("MEDIUM" if side < 100 else "LARGE"))
    stats = {"frames": len(labels),
             "present": sum(1 for a in labels if a["target"]["present"]),
             "undecidable": sum(1 for a in labels if a["target"]["undecidable"]),
             "absent": sum(1 for a in labels if not a["target"]["present"] and not a["target"]["undecidable"]),
             "gt_unobservable": sum(1 for a in labels if a["target"]["occluded"] and not a["geometry"]["bbox_xywh"]),
             "ambiguous": sum(1 for a in labels if a["target"]["ambiguous"]),
             "reference_available": sum(1 for a in labels if a["geometry"]["reference_status"] == "MANUAL_APPROX"),
             "reference_unavailable": sum(1 for a in labels if a["geometry"]["reference_status"] == "UNAVAILABLE"),
             "truncated": sum(1 for a in labels if a["target"]["truncated"]),
             "edge_counts": {e: sum(1 for a in labels if a["target"]["truncated_edges"].get(e)) for e in ("left","right","top","bottom")},
             "scale_buckets": dict(Counter(bucket(a) for a in labels if a["geometry"].get("bbox_xywh"))),
             "confusers": sum(len(a.get("confusers") or []) for a in labels),
             "confusers_verified": sum(1 for a in labels for c in (a.get("confusers") or []) if c.get("verified"))}
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stats, indent=1, ensure_ascii=False)+"\n", encoding="utf-8")
    print(json.dumps(stats, indent=1))

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("selection"); s.add_argument("--run", required=True)
    s.add_argument("--families", required=True); s.add_argument("--per-family", type=int, default=20)
    s.add_argument("--out", required=True); s.set_defaults(func=cmd_selection)
    t = sub.add_parser("stats"); t.add_argument("--labels", required=True)
    t.add_argument("--out", required=True); t.set_defaults(func=cmd_stats)
    args = ap.parse_args(); args.func(args)

if __name__ == "__main__":
    main()
