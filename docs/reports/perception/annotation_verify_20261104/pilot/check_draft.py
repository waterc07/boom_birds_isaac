import json, numpy as np
from pathlib import Path
from PIL import Image
REPO = Path(r"E:\isaac\proj_boom_birds")
draft = json.loads((REPO/"outputs/perception/final_exploratory_20261104/labels_draft.json").read_text(encoding="utf-8"))
cond = {r["frame_id"]: r for r in json.loads((REPO/"docs/reports/perception/capture_20261104/frame_conditions.json").read_text(encoding="utf-8"))}
mismatch = []
byfam = {}
for a in draft["annotations"]:
    fid = a["frame_id"]; fam = a["source"]["family"]
    byfam.setdefault(fam, {"n":0,"present":0,"vis":0,"unav":0,"trunc":0,"bottom":0,"right":0,"green_le2":0})
    b = byfam[fam]; b["n"]+=1
    b["present"] += int(a["target"]["present"])
    b["vis"] += int(a["geometry"]["green_pixels"]>=3 and a["target"]["present"])
    b["unav"] += int(a["geometry"]["reference_status"]=="UNAVAILABLE")
    b["trunc"] += int(a["target"]["truncated"])
    b["bottom"] += int(a["target"]["truncated_edges"]["bottom"])
    b["right"] += int(a["target"]["truncated_edges"]["right"])
    b["green_le2"] += int(a["geometry"]["green_pixels"]<=2)
    cg = cond[fid]["green_pixels"]
    if int(a["geometry"]["green_pixels"]) != int(cg):
        mismatch.append((fid, int(a["geometry"]["green_pixels"]), int(cg)))
print(json.dumps(byfam, indent=1))
print("green count mismatches:", len(mismatch), "of", len(draft["annotations"]))
print(mismatch[:20])
