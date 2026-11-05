import hashlib, json
from pathlib import Path
REPO=Path(r"E:\isaac\proj_boom_birds")
CAP=REPO/"docs/reports/perception/capture_dev_20261104/two_class_near_ms1_20261105"
cond=json.loads((CAP/"t38_frame_conditions.json").read_text(encoding="utf-8"))
pool=json.loads((CAP/"t38_pool_selection.json").read_text(encoding="utf-8"))
print("cond rows:",len(cond),"pool size:",pool.get("pool_size"),"ids:",len(pool.get("pool_frame_ids",[])))
print("pool dir exists:", (REPO/"outputs/sensor_shadow/lm_two_class_near_ms1_20261105_pool/images").is_dir(),
      "images:", len(list((REPO/"outputs/sensor_shadow/lm_two_class_near_ms1_20261105_pool/images").glob("*.png"))) if (REPO/"outputs/sensor_shadow/lm_two_class_near_ms1_20261105_pool/images").is_dir() else 0)
c0=cond[0]; print("cond fields:", [k for k in c0.keys() if "bbox" in k or "span" in k or "trunc" in k])
print("sample bbox:", c0.get("ms1_bbox_uv"), "trunc:", c0.get("ms1_four_side_truncation"))
# diff against my shard A
OUT=REPO/"outputs/perception/dev_annotations_20261105/two_class/near_ms1/shard_a"
lab=json.loads((OUT/"labels_v1.json").read_text(encoding="utf-8"))
byid={c["frame_id"]:c for c in cond}
def iou(a,b):
    ix0,iy0=max(a[0],b[0]),max(a[1],b[1]); ix1,iy1=min(a[2],b[2]),min(a[3],b[3])
    iw,ih=max(0,ix1-ix0),max(0,iy1-iy0); inter=iw*ih
    ua=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter
    return inter/ua if ua>0 else 0
ious=[]; mism=[]
for f in lab["frames"]:
    c=byid.get(f["frame_id"])
    if not c: mism.append((f["frame_id"],"missing cond")); continue
    bb=c["ms1_bbox_uv"]; b=[bb["u_min"],bb["v_min"],bb["u_max"],bb["v_max"]]
    mine=f["instances"][0]["bbox_xyxy"]
    v=iou(mine,b); ious.append(v)
    if v<0.8: mism.append((f["frame_id"],round(v,3),mine,b))
print("n:",len(ious),"mean IoU:",round(sum(ious)/len(ious),4),"min:",round(min(ious),4),"<0.8:",len(mism))
for m in mism[:5]: print(m)
# edge disagreement
ed=0
for f in lab["frames"]:
    c=byid[f["frame_id"]]; tr=c["ms1_four_side_truncation"]
    if any(bool(f["instances"][0]["truncated_edges"].get(k))!=bool(tr.get(k)) for k in ("left","right","top","bottom")): ed+=1
print("edge disagreements:",ed)
