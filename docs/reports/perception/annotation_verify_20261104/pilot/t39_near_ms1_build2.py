"""T39 build v2: class1 labels for T38 near-MS1 pool frames (full + shard A) from capture conditions."""
import hashlib, json
from pathlib import Path
from collections import Counter
from PIL import Image, ImageDraw, ImageFont
REPO=Path(r"E:\isaac\proj_boom_birds")
BASE=REPO/"docs/reports/perception/annotation_verify_20261104"
CAP=REPO/"docs/reports/perception/capture_dev_20261104/two_class_near_ms1_20261105"
COND=CAP/"t38_frame_conditions.json"
POOL=json.loads((CAP/"t38_pool_selection.json").read_text(encoding="utf-8"))
SPEC=REPO/"configs/perception/landmark_two_class_label_spec_v1.json"
spec_sha=hashlib.sha256(SPEC.read_bytes()).hexdigest(); W,H=320,240
print("pool meta:", {k:POOL.get(k) for k in ("rule","raw_accepted","pool_size")})
pool_ids=list(POOL.get("pool_frame_ids") or [])
conds={c["frame_id"]:c for c in json.loads(COND.read_text(encoding="utf-8"))}
rows=[conds[f] for f in pool_ids if f in conds]
print("pool ids:", len(pool_ids), "cond rows:", len(rows))
rows.sort(key=lambda c:(c["frame_id"].split("-follow_only")[0], c["sequence"]))
byfam={}
for c in rows: byfam.setdefault(c["frame_id"].split("-follow_only")[0],[]).append(c)
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def build(sel_rows, outdir, status, shard):
    OUT=Path(outdir); OUT.mkdir(parents=True, exist_ok=True); frames=[]
    for c in sel_rows:
        fid=c["frame_id"]; fam=fid.split("-follow_only")[0]; img=None
        for cand in (REPO/"outputs/sensor_shadow/lm_two_class_near_ms1_20261105_pool/images"/fid,
                     REPO/"outputs/sensor_shadow/lm_two_class_near_ms1_20261105_sensor/images"/fid,
                     REPO/"outputs/sensor_shadow/lm_two_class_near_ms1_20261105/images"/fid):
            if cand.is_file(): img=cand; break
        if img is None: raise SystemExit("missing image "+fid)
        bb=c["ms1_bbox_uv"]; tr=c.get("ms1_four_side_truncation") or {}
        x0=max(0.0,min(W,bb["u_min"])); x1=max(0.0,min(W,bb["u_max"]))
        y0=max(0.0,min(H,bb["v_min"])); y1=max(0.0,min(H,bb["v_max"]))
        edges={k:bool(tr.get(k)) for k in ("left","right","top","bottom")}
        insts=[{"class":1,"bbox_xyxy":[round(x0,2),round(y0,2),round(x1,2),round(y1,2)],
                "truncated_edges":edges,"occluded":False,"keypoint_x":None,"keypoint_y":None,"v":0,
                "reference_available":False,"verified_source":"WORLD_POSE_OR_MAP_DB"}]
        frames.append({"frame_id":fid,"image":str(img.relative_to(REPO)).replace("\\","/"),
                       "image_sha256":sha(img),"image_width":W,"image_height":H,
                       "family":fam,"shard":shard,"sequence":c["sequence"],
                       "tower_present":False,"ms1_present":True,"identity_ambiguity":"NONE",
                       "gt_uncertainty":"NONE","occlusion":"NONE",
                       "notes":"T38 near-MS1 class1-only; bbox from capture ms1_bbox_uv + truncation; projection-assisted + visual spot QA; agent proxy",
                       "other_structures":[],
                       "projection_aid":{"ms1_projected_max_side_px":round(max(bb["width_px"],bb["height_px"]),2),
                                         "tower_projected_max_side_px":0.0},
                       "instances":insts})
    doc={"schema_version":"dsh.landmark_two_class_annotations.v1","status":status,
         "annotation_spec":{"path":"configs/perception/landmark_two_class_label_spec_v1.json","sha256":spec_sha},
         "coordinate_space":{"bbox":"SOURCE_IMAGE_PIXELS_XYXY","keypoint":"SOURCE_IMAGE_PIXELS_NORMALIZED_01"},
         "method":{"bbox":"T38 capture ms1_bbox_uv + ms1_four_side_truncation; visual spot QA; projection-assisted, agent proxy, not independent human GT",
                   "class1_scope":"map-native MS1 only; tower not in FOV in this batch"},
         "frames":frames}
    (OUT/"labels_v1.json").write_text(json.dumps(doc,indent=1,ensure_ascii=False)+"\n",encoding="utf-8")
    sel={"schema_version":"dsh.landmark_two_class_selection.v1","status":"T38_POOL_"+shard,
         "run":"outputs/sensor_shadow/lm_two_class_near_ms1_20261105_sensor","shard":shard,
         "rule":{"id":"t38_pool_"+shard,"text":"T38 pool frames; shard A = per-family first ceil(n/2) by sequence, full = all pool frames","total":len(frames)},
         "per_family":dict(Counter(f["family"] for f in frames)),"frames":frames}
    (OUT/"selection.json").write_text(json.dumps(sel,indent=1,ensure_ascii=False)+"\n",encoding="utf-8")
    return frames, sha(OUT/"labels_v1.json"), sha(OUT/"selection.json")
shardA=[]
for fam,fr in byfam.items():
    fr=sorted(fr,key=lambda x:x["sequence"]); k=(len(fr)+1)//2; shardA.extend(fr[:k])
shardA=sorted(shardA,key=lambda c:(c["frame_id"].split("-follow_only")[0],c["sequence"]))
fa_dir=REPO/"outputs/perception/dev_annotations_20261105/two_class/near_ms1/full"
sa_dir=REPO/"outputs/perception/dev_annotations_20261105/two_class/near_ms1/shard_a"
f_frames,f_sha,f_sel=build(rows, str(fa_dir), "T38_NEAR_MS1_FULL_AGENT_PROXY_CONDITIONS_VISUAL_QA","full")
s_frames,s_sha,s_sel=build(shardA, str(sa_dir), "T38_NEAR_MS1_SHARD_A_AGENT_PROXY_CONDITIONS_VISUAL_QA","A")
def font(size=12):
    for n in ("DejaVuSans.ttf","arial.ttf"):
        try: return ImageFont.truetype(n,size)
        except Exception: pass
    return ImageFont.load_default()
F=font(12); COLS,ROWS=3,4; CW,CH=640,480
def sheets(frames, out):
    out.mkdir(parents=True, exist_ok=True); names=[]
    for si in range(0,len(frames),COLS*ROWS):
        batch=frames[si:si+COLS*ROWS]; canvas=Image.new("RGB",(COLS*CW,ROWS*CH),(30,30,30))
        for k,fr in enumerate(batch):
            im=Image.open(REPO/fr["image"]).convert("RGB").resize((CW,CH),Image.LANCZOS); d=ImageDraw.Draw(im)
            b=fr["instances"][0]["bbox_xyxy"]; d.rectangle([b[0]*2,b[1]*2,b[2]*2,b[3]*2],outline=(0,220,255),width=2)
            d.rectangle([0,0,240,14],fill=(0,0,0)); d.text((2,1),fr["frame_id"].replace("-follow_only","")[:42],font=F,fill=(255,255,0))
            canvas.paste(im,((k%COLS)*CW,(k//COLS)*CH))
        name="near_ms1_%02d.png"%(si//(COLS*ROWS)); canvas.save(out/name); names.append(name)
    return names
sa_sheets=sheets(s_frames, BASE/"pilot/t39_near_ms1_shard_a")
full_sheets=sheets(f_frames, BASE/"pilot/t39_near_ms1_full")
print(json.dumps({"full":{"frames":len(f_frames),"sha":f_sha,"sel":f_sel},
                  "shard_a":{"frames":len(s_frames),"sha":s_sha,"sel":s_sel,"sheets":len(sa_sheets)},
                  "per_family_full":dict(Counter(f["family"] for f in f_frames)),
                  "per_family_A":dict(Counter(f["family"] for f in s_frames)),
                  "full_sheets":len(full_sheets)}, indent=1))
