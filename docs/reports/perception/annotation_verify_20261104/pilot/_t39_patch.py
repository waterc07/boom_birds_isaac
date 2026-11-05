from pathlib import Path
BASE=Path(r"E:\isaac\proj_boom_birds\docs\reports\perception\annotation_verify_20261104")
p=BASE/"pilot/t39_near_ms1_build.py"
s=p.read_text(encoding="utf-8")
s=s.replace('    ap.add_argument("--parity", choices=["all","even","odd"], default="all")',
            '    ap.add_argument("--split-mode", choices=["all","even","odd","first_half"], default="all")')
old="""    if args.parity!="all":
        rows=[r for r in rows if (r["sequence"]%2==0)==(args.parity=="even")]
    rows.sort(key=lambda r:(r["frame_id"].split("-follow_only")[0], r["sequence"]))"""
new="""    rows.sort(key=lambda r:(r["frame_id"].split("-follow_only")[0], r["sequence"]))
    if args.split_mode=="first_half":
        byfam={}
        for r in rows: byfam.setdefault(r["frame_id"].split("-follow_only")[0],[]).append(r)
        keep=[]
        for fam,fr in byfam.items():
            fr=sorted(fr,key=lambda x:x["sequence"]); k=(len(fr)+1)//2; keep.extend(fr[:k])
        rows=sorted(keep,key=lambda r:(r["frame_id"].split("-follow_only")[0], r["sequence"]))
    elif args.split_mode in ("even","odd"):
        rows=[r for r in rows if (r["sequence"]%2==0)==(args.split_mode=="even")]
    rows.sort(key=lambda r:(r["frame_id"].split("-follow_only")[0], r["sequence"]))"""
assert old in s
s=s.replace(old,new)
s=s.replace('"rule":{"id":"t38_pool_"+args.parity,"text":"all in-pool frames of assigned families (or sequence parity if split)"',
            '"rule":{"id":"t38_pool_"+args.split_mode,"text":"in-pool frames of assigned families; first_half = per-family first ceil(n/2) by sequence"')
p.write_text(s,encoding="utf-8")
dp=BASE/"T39_NEAR_MS1_ANNOTATION_PREP_20261105.md"
d=dp.read_text(encoding="utf-8")
add="""## 1.1 已冻结分片规则（与 annot2 一致，2026-11-05）

- T38 pool 全部帧按 (family, integer sequence) 排序；**每个族内前 ceil(n/2) 帧 = annot（shard A）**，其余 = annot2（shard B）；两族各半、B 约 pool 一半（45–60 帧）。
- 规则在 T38 run.complete/pool 落盘后冻结（selection sha 记录）；builder 用 --split-mode first_half。
- 落点：annot = outputs/perception/dev_annotations_20261105/two_class/near_ms1/shard_a/；annot2 = .../shard_b/；互不覆盖。

## 2. 标签内容与 schema"""
assert "## 2. 标签内容与 schema" in d
d=d.replace("## 2. 标签内容与 schema",add,1)
dp.write_text(d,encoding="utf-8")
print("patched ok")
