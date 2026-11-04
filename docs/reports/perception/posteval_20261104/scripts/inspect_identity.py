# -*- coding: utf-8 -*-
"""Inspect saved predictions on val_identity and identity labels/conditions."""
import json, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parents[5]
def load(p): return json.loads((ROOT / p).read_text(encoding="utf-8"))
for run in ["eval_last","eval_best","eval_epoch20","eval_epoch40"]:
    p = "outputs/landmark_train/runs/improvement_v4/baseline_seed0/%s/predictions.jsonl" % run
    try: rows=[json.loads(l) for l in (ROOT/p).read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception as e: print(run, "ERR", e); continue
    devid=[r for r in rows if "devid" in r.get("frame_id","")]
    print(run, "frames", len(rows), "devid", len(devid), "families", collections.Counter((r.get("strata") or {}).get("family") for r in rows))
    if devid:
        print("  devid sample", json.dumps(devid[0], ensure_ascii=False)[:600])
        print("  status", collections.Counter((r.get("observation") or {}).get("status") for r in devid))
# identity labels
lab = load("outputs/perception/dev_annotations_20261104/labels_identity_dev.json")
print("identity labels keys", list(lab.keys()), "n", len(lab["annotations"]))
print("families", collections.Counter((a.get("source") or {}).get("family") for a in lab["annotations"]))
print("present", sum(1 for a in lab["annotations"] if (a.get("target") or {}).get("present") is True))
print("sample", json.dumps(lab["annotations"][0], ensure_ascii=False, indent=1)[:1800])
cond = load("outputs/perception/dev_annotations_20261104/identity/identity_frame_conditions.json")
print("conditions type", type(cond).__name__, "keys", list(cond.keys())[:10] if isinstance(cond,dict) else len(cond))
if isinstance(cond, dict):
    for k,v in cond.items(): print(" ", k, type(v).__name__, (len(v) if hasattr(v,"__len__") else v))
    frames = cond.get("frames") or cond.get("conditions") or []
else: frames = cond
print("conditions frames", len(frames))
if frames: print("cond sample", json.dumps(frames[0], ensure_ascii=False, indent=1)[:1800])
