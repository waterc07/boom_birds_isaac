import hashlib, json
from pathlib import Path
REPO=Path(r"E:\isaac\proj_boom_birds")
cond=json.loads((REPO/"docs/reports/perception/capture_dev_20261104/two_class_near_ms1_20261105/t38_frame_conditions.json").read_text(encoding="utf-8"))
sd=REPO/"outputs/sensor_shadow/lm_two_class_near_ms1_20261105_sensor/images"
imgs={p.name:p for p in sd.glob("*.png")}
print("final images:",len(imgs),"cond rows:",len(cond))
match=0; missing=0; sha_ok=0
for c in cond:
    fid=c["frame_id"]; p=imgs.get(fid)
    if not p: missing+=1; continue
    match+=1
    if hashlib.sha256(p.read_bytes()).hexdigest()==c["image_sha256"]: sha_ok+=1
print("cond ids present in final images:",match,"missing:",missing,"sha identical:",sha_ok)
fams={}
for c in cond: fams.setdefault(c["frame_id"].split("-follow_only")[0],[]).append(c["sequence"])
for f,seqs in fams.items(): print(f, "n=",len(seqs), "seq range", min(seqs), max(seqs))
# pool ids
pool=json.loads((REPO/"docs/reports/perception/capture_dev_20261104/two_class_near_ms1_20261105/t38_pool_selection.json").read_text(encoding="utf-8"))
print("pool size:", pool.get("pool_size"), "ids example:", pool.get("pool_frame_ids",[])[:2])
print("pool ids all in cond:", all(f in {c["frame_id"] for c in cond} for f in pool.get("pool_frame_ids",[])))
