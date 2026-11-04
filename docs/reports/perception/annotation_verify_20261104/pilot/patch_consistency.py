import hashlib, json
from pathlib import Path
REPO = Path(r"E:\isaac\proj_boom_birds")
BASE = REPO / "docs/reports/perception/annotation_verify_20261104"
OUT = REPO / "outputs/perception/final_exploratory_20261104"
labels = json.loads((OUT / "labels_v1.json").read_text(encoding="utf-8"))
pilot = json.loads((REPO / "outputs/perception/landmark_final_annotations_20261104/labels_v1.json").read_text(encoding="utf-8"))
pilot_by = {a["frame_id"]: a for a in pilot["annotations"]}
def iou(a,b):
    ax,ay,aw,ah=a; bx,by,bw,bh=b
    ix0,iy0=max(ax,bx),max(ay,by); ix1,iy1=min(ax+aw,bx+bw),min(ay+ah,by+bh)
    iw,ih=max(0.0,ix1-ix0),max(0.0,iy1-iy0); inter=iw*ih; union=aw*ah+bw*bh-inter
    return inter/union if union>0 else 0.0
def stats(vals):
    vals=sorted(vals); n=len(vals)
    return {"n":n,"mean":round(sum(vals)/n,3),"median":round(vals[n//2],3),"min":round(vals[0],3),"max":round(vals[-1],3)}
cons={"frames":0,"presence_agree":0,"truncated_agree":0,"keypoint_compared":0,"keypoint_dist_px":[],"bbox_iou":[]}
for fid,p in pilot_by.items():
    f=next(a for a in labels["annotations"] if a["frame_id"]==fid)
    cons["frames"]+=1
    cons["presence_agree"]+=int(p["target"]["present"]==f["target"]["present"])
    cons["truncated_agree"]+=int(bool(p["target"]["truncated"])==bool(f["target"]["truncated"]))
    if p["target"]["present"] and f["target"]["present"] and p["geometry"]["bbox_xywh"] and f["geometry"]["bbox_xywh"]:
        cons["bbox_iou"].append(iou(p["geometry"]["bbox_xywh"], f["geometry"]["bbox_xywh"]))
    pk,fk=p["geometry"]["keypoint"],f["geometry"]["keypoint"]
    if pk and fk:
        cons["keypoint_compared"]+=1
        cons["keypoint_dist_px"].append(((pk["x"]-fk["x"])**2+(pk["y"]-fk["y"])**2)**0.5)
cons["bbox_iou"]=stats(cons["bbox_iou"]); cons["keypoint_dist_px"]=stats(cons["keypoint_dist_px"])
labels["pilot_label_consistency"]=cons
(OUT / "labels_v1.json").write_text(json.dumps(labels, indent=1, ensure_ascii=False)+"\n", encoding="utf-8")
print(json.dumps(cons, ensure_ascii=False))
print("label sha", hashlib.sha256((OUT/"labels_v1.json").read_bytes()).hexdigest())
