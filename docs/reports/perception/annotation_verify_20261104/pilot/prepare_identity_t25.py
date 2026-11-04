"""T26 preparation: select representative frames + draft v2.1 skeleton for the
T25 identity supplement capture (mutual MS1/target occlusion, far MS1).

BLOCKED until T25 capture exists. The selection rule and annotation rules are
predeclared here BEFORE images are seen (see T26_IDENTITY_T25_READINESS).

Usage (after capture):
  python prepare_identity_t25.py --run outputs/sensor_shadow/<t25_sensor_run> \
      --cases lmf_devid_ms1_target_occlusion_0,lmf_devid_ms1_far_0 \
      --total 28 --out-json outputs/perception/dev_annotations_20261104/identity_t25/selection.json
"""
import argparse, hashlib, json, sys
from pathlib import Path

REPO = Path(r"E:\isaac\proj_boom_birds")

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def midpoint_systematic(frames, k):
    n = len(frames)
    k = min(k, n)
    return [frames[min(n - 1, int((i + 0.5) * n / k))] for i in range(k)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="sensor run dir with summary.json/images")
    ap.add_argument("--cases", required=True, help="comma separated new case ids")
    ap.add_argument("--total", type=int, default=28)
    ap.add_argument("--out-json", required=True)
    args = ap.parse_args()
    run = REPO / args.run
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    cases = [c.strip() for c in args.cases.split(",") if c.strip()]
    per_case = max(1, args.total // max(1, len(cases)))
    selected, meta = [], {}
    for ep in summary.get("episodes", []):
        ep_id = ep.get("episode_id", "")
        case = next((c for c in cases if ep_id.startswith(c)), None)
        if not case:
            continue
        frames = [Path(p).name for p in summary.get("images", [])
                  if Path(p).name.startswith(ep_id + "_")]
        frames.sort(key=lambda f: int(f.rsplit("_", 1)[1].split(".")[0]))
        picked = midpoint_systematic(frames, per_case)
        selected.extend(picked)
        meta[case] = {"episode_id": ep_id, "accepted": len(frames), "selected": picked}
    out = {"schema_version": "dsh.landmark_identity_t25_selection.v1",
           "status": "PREDECLARED_SELECTION_RULE_APPLIED_AFTER_CAPTURE",
           "run": str(run.relative_to(REPO)).replace("\\", "/"),
           "rule": {"id": "identity_midpoint_systematic_v1",
                    "text": "per new case: accepted front_rgb frames sorted by sequence, midpoint systematic floor((i+0.5)*n/k); frozen before image inspection; no model score used",
                    "total_target": args.total, "per_case": per_case},
           "cases": meta, "frames": selected}
    p = Path(args.out_json)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"selected": len(selected), "per_case": per_case,
                      "out": str(p), "sha256": sha(p)}, indent=1))

if __name__ == "__main__":
    main()
