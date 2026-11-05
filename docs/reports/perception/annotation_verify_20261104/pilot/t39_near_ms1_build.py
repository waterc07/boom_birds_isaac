"""T39: build class1 labels for T38 near-MS1 pool frames (adaptive to capture condition fields).

Usage:
  python t39_near_ms1_build.py --conditions <json> --families f1,f2 --shard A --out-dir <dir> [--parity even|odd]
Condition fields accepted (first match): ms1_bbox_xyxy / ms1_bbox / (ms1_u_span+ms1_v_span) /
(ms1_u_span+camera pose projection) ; tower presence from target_fov_status/tower_u_span.
"""
import argparse, hashlib, json, math
from pathlib import Path
from collections import Counter
from PIL import Image, ImageDraw, ImageFont

REPO = Path(r"E:\isaac\proj_boom_birds")
BASE = REPO/"docs/reports/perception/annotation_verify_20261104"
SPEC = REPO/"configs/perception/landmark_two_class_label_spec_v1.json"
W, H = 320, 240
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def clip_box(b):
    x1, y1, x2, y2 = [float(v) for v in b]
    return [max(0.0,min(W,x1)), max(0.0,min(H,y1)), max(0.0,min(W,x2)), max(0.0,min(H,y2))]

def R_of(q):
    w,x,y,z = q
    return [[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
            [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
            [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]]

def project(pw, pos, R):
    d = [pw[i]-pos[i] for i in range(3)]
    pc = [sum(R[k][i]*d[k] for k in range(3)) for i in range(3)]
    if pc[0] <= 0.05: return None
    return (160.0 - 160.0*pc[1]/pc[0], 120.0 - 160.0*pc[2]/pc[0])

def ms1_bbox(c):
    for k in ("ms1_bbox_xyxy","ms1_bbox","ms1_bbox_px","ms1_box_xyxy"):
        if c.get(k): return list(c[k])
    u = c.get("ms1_u_span"); v = c.get("ms1_v_span")
    if u and v: return [u[0], v[0], u[1], v[1]]
    if u and (c.get("ms1_height_px") or c.get("height_px")):
        h = float(c.get("ms1_height_px") or c.get("height_px")); mid = (u[0]+u[1])/2.0
        # lamp near top: v unknown -> use centre y from ms1_pixel_uv_pred if present
        uv = c.get("ms1_pixel_uv_pred") or c.get("ms1_lamp_uv")
        if uv:
            cy = float(uv[1]); return [u[0], cy-0.06*h, u[1], cy+0.94*h]
    pos = c.get("camera_position_world_m"); quat = c.get("camera_quat_wxyz")
    if pos and quat:
        R = R_of(quat); pts=[]
        for dx,dy in ((-0.25,-0.25),(0.25,0.25),(-0.25,0.25),(0.25,-0.25)):
            for z in (0.05,0.6,1.2,1.71,1.78):
                pts.append((3.0+dx,4.0+dy,z))
        us=[]; vs=[]
        for pw in pts:
            uv=project(pw,pos,R)
            if uv: us.append(uv[0]); vs.append(uv[1])
        if us: return [min(us),min(vs),max(us),max(vs)]
    return None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--conditions", required=True)
    ap.add_argument("--families", required=True)
    ap.add_argument("--shard", default="A")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--split-mode", choices=["all","even","odd","first_half"], default="all")
    ap.add_argument("--pool-images", default=None)
    args=ap.parse_args()
    OUT=Path(args.out_dir); OUT.mkdir(parents=True, exist_ok=True)
    cond=json.loads(Path(args.conditions).read_text(encoding="utf-8"))
    rows=cond if isinstance(cond,list) else cond.get("frames",[])
    fams=set(f.strip() for f in args.families.split(",") if f.strip())
    rows=[r for r in rows if (r.get("in_pool") is not False) and r["frame_id"].split("-follow_only")[0] in fams]
    rows.sort(key=lambda r:(r["frame_id"].split("-follow_only")[0], r["sequence"]))
    if args.split_mode=="first_half":
        byfam={}
        for r in rows: byfam.setdefault(r["frame_id"].split("-follow_only")[0],[]).append(r)
        keep=[]
        for fam,fr in byfam.items():
            fr=sorted(fr,key=lambda x:x["sequence"]); k=(len(fr)+1)//2; keep.extend(fr[:k])
        rows=sorted(keep,key=lambda r:(r["frame_id"].split("-follow_only")[0], r["sequence"]))
    elif args.split_mode in ("even","odd"):
        rows=[r for r in rows if (r["sequence"]%2==0)==(args.split_mode=="even")]
    rows.sort(key=lambda r:(r["frame_id"].split("-follow_only")[0], r["sequence"]))
    frames=[]
    for c in rows:
        b=ms1_bbox(c)
        if not b: raise SystemExit("no ms1 bbox for "+c["frame_id"])
        b=clip_box(b)
        edges={"left":b[0]<=0.5,"right":b[2]>=W-0.5,"top":b[1]<=0.5,"bottom":b[3]>=H-0.5}
        raw=ms1_bbox(c); raw_edges={"left":raw[0]<0,"right":raw[2]>W,"top":raw[1]<0,"bottom":raw[3]>H}
        img=Path(args.pool_images)/c["frame_id"] if args.pool_images else None
        if not img or not img.is_file():
            for cand in ("outputs/sensor_shadow/lm_two_class_near_ms1_20261105_pool/images",
                         "outputs/sensor_shadow/lm_two_class_near_ms1_20261105_sensor/images"):
                p=REPO/cand/c["frame_id"]
                if p.is_file(): img=p; break
        if not img or not img.is_file(): raise SystemExit("missing image "+c["frame_id"])
        tower_present = False
        insts=[{"class":1,"bbox_xyxy":[round(x,2) for x in b],
                "truncated_edges":{k:bool(raw_edges[k]) for k in ("left","right","top","bottom")},
                "occluded":False,"keypoint_x":None,"keypoint_y":None,"v":0,
                "reference_available":False,"verified_source":"WORLD_POSE_OR_MAP_DB"}]
        frames.append({"frame_id":c["frame_id"],"image":str(img.relative_to(REPO)).replace("\\","/"),
                       "image_sha256":sha(img),"image_width":W,"image_height":H,
                       "family":c["frame_id"].split("-follow_only")[0],"shard":args.shard,
                       "sequence":c["sequence"],"tower_present":tower_present,"ms1_present":True,
                       "identity_ambiguity":"NONE","gt_uncertainty":"NONE","occlusion":"NONE",
                       "notes":"T38 near-MS1 class1-only label; capture condition bbox + projection; visual spot QA; agent proxy",
                       "other_structures":[],
                       "projection_aid":{"ms1_projected_max_side_px":round(max(b[2]-b[0],b[3]-b[1]),2),
                                         "tower_projected_max_side_px":0.0},
                       "instances":insts})
    doc={"schema_version":"dsh.landmark_two_class_annotations.v1",
         "status":"T38_NEAR_MS1_"+args.shard+"_AGENT_PROXY_PROJECTION_AID_VISUAL_QA",
         "annotation_spec":{"path":"configs/perception/landmark_two_class_label_spec_v1.json","sha256":sha(SPEC)},
         "coordinate_space":{"bbox":"SOURCE_IMAGE_PIXELS_XYXY","keypoint":"SOURCE_IMAGE_PIXELS_NORMALIZED_01"},
         "method":{"bbox":"T38 capture per-frame record (ms1 bbox/span) or map-native MS1 projection; visual spot QA; agent proxy, not independent human GT",
                   "class1_scope":"map-native MS1 only"},
         "frames":frames}
    (OUT/"labels_v1.json").write_text(json.dumps(doc,indent=1,ensure_ascii=False)+"\n",encoding="utf-8")
    sel={"schema_version":"dsh.landmark_two_class_selection.v1","status":"IN_POOL_SHARD_"+args.shard,
         "run":"outputs/sensor_shadow/lm_two_class_near_ms1_20261105_sensor","shard":args.shard,
         "rule":{"id":"t38_pool_"+args.split_mode,"text":"in-pool frames of assigned families; first_half = per-family first ceil(n/2) by sequence","total":len(frames)},
         "per_family":dict(Counter(f["family"] for f in frames)),"frames":frames}
    (OUT/"selection.json").write_text(json.dumps(sel,indent=1,ensure_ascii=False)+"\n",encoding="utf-8")
    # sheets
    SHEETS=BASE/("pilot/t39_near_ms1_shard_"+args.shard); SHEETS.mkdir(parents=True, exist_ok=True)
    def font(size=12):
        for n in ("DejaVuSans.ttf","arial.ttf"):
            try: return ImageFont.truetype(n,size)
            except Exception: pass
        return ImageFont.load_default()
    F=font(12); COLS,ROWS=3,4; CW,CH=640,480
    for si in range(0,len(frames),COLS*ROWS):
        batch=frames[si:si+COLS*ROWS]; canvas=Image.new("RGB",(COLS*CW,ROWS*CH),(30,30,30))
        for k,fr in enumerate(batch):
            im=Image.open(REPO/fr["image"]).convert("RGB").resize((CW,CH),Image.LANCZOS); d=ImageDraw.Draw(im)
            b=fr["instances"][0]["bbox_xyxy"]; d.rectangle([b[0]*2,b[1]*2,b[2]*2,b[3]*2],outline=(0,220,255),width=2)
            d.rectangle([0,0,220,14],fill=(0,0,0)); d.text((2,1),fr["frame_id"].replace("-follow_only","")[:40],font=F,fill=(255,255,0))
            canvas.paste(im,((k%COLS)*CW,(k//COLS)*CH))
        canvas.save(SHEETS/("near_ms1_%02d.png"%(si//(COLS*ROWS))))
    print(json.dumps({"frames":len(frames),"labels_sha":sha(OUT/"labels_v1.json"),
                      "selection_sha":sha(OUT/"selection.json"),"sheets":str(SHEETS)},indent=1))

if __name__=="__main__":
    main()
