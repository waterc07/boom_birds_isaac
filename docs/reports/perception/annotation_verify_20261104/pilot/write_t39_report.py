import hashlib, json
from pathlib import Path
REPO=Path(r"E:\isaac\proj_boom_birds")
BASE=REPO/"docs/reports/perception/annotation_verify_20261104"
OUT=REPO/"outputs/perception/dev_annotations_20261105/two_class/near_ms1/shard_a"
FULL=REPO/"outputs/perception/dev_annotations_20261105/two_class/near_ms1/full"
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
lab=json.loads((OUT/"labels_v1.json").read_text(encoding="utf-8"))
qa=json.loads((OUT/"qa_v1.json").read_text(encoding="utf-8"))
full=json.loads((FULL/"labels_v1.json").read_text(encoding="utf-8"))
Aids={f["frame_id"] for f in lab["frames"]}
B=[f for f in full["frames"] if f["frame_id"] not in Aids]
fams={}
for f in lab["frames"]: fams[f["family"]]=fams.get(f["family"],0)+1
lines=[
"# T39 近距 MS1 训练族标注：shard A（T38 final，2026-11-05）",
"",
"> **状态：** PROVISIONAL（数据准备/标注；final run 位姿投影 + 目视抽查；agent 代理，非独立人工 GT；不提升 Gate）",
"> **来源章节：** configs/perception/landmark_two_class_protocol_v1.json、landmark_two_class_label_spec_v1.json（FROZEN_2026_11_05）、T38/T39 任务书、lead 2026-11-05 指示（final run，旧 discarded 作废）",
"> **证据域：** 离线标注 QA（T38 final run accepted RGB 102 帧中的 shard A 52 帧；Isaac 合成 320×240；无训练/推理）",
"> **最后核对：** 2026-11-05（HEAD 47d1063）",
"",
"## 0. 结论先行",
"",
"1. **shard A 完成**：final run 的 2 个近距 MS1 族（f1 49 + f2 53 = 102 accepted）按每族前 ceil(n/2) 取 **52 帧**（f1 25 + f2 27）标注 class1；QA **PASS 52/52**。",
"2. 全部 52 帧：\`tower_present=false\`（final observations 逐帧检查 tower 投影不在画面内）、\`ms1_present=true\`、class1 实例 52、v=0、keypoint null、bbox 由 map-native MS1 (3.0,4.0, z0.05–1.78) 用 final run 相机位姿投影 + 2× contact sheet 目视抽查。",
"3. 口径澄清：capture 先前 108 帧 pool/conditions 属于 **pilotA_discarded**（已作废）；final run accepted=**102**、sensor images 108（含非 accepted），f1 名改为 \`lmf_t38_f1_ms1_near_north_0\`。旧 discarded 标签不得用于 v6.2/训练。",
"4. 分片：A=52（本文件）；B=50（annot2 按同一 final pool 重标：f1 后 24 + f2 后 26）；A+B=102。",
"5. QA warning 25 条均为 tower 投影全跨度≥8px 但 \`tower_present=false\`（fov 判定在画面外，非实际可见），记录不阻塞。",
"",
"## 1. 数据与分片",
"",
"| 项 | 值 |",
"| --- | --- |",
"| run | outputs/sensor_shadow/lm_two_class_near_ms1_20261105（run.complete PASS；sensor 108 images） |",
"| accepted | 102（gate.accepted RGB） |",
"| 族 | f1 lmf_t38_f1_ms1_near_north_0 49；f2 lmf_t38_f2_ms1_near_se_0 53 |",
"| 分片规则 | 每族前 ceil(n/2)=A；其余=B；A+B=102 |",
"| A | 52（f1 25 + f2 27） |",
"| B（annot2） | 50（f1 24 + f2 26） |",
"",
"## 2. 标签统计（分母 52）",
"",
"| 指标 | 值 |",
"| --- | ---: |",
"| frames | **52** |",
"| tower_present / ms1_present | 0 / 52 |",
"| class0 实例 | 0 |",
"| class1 实例（v=0） | 52 |",
"| keypoint | 0（class1 恒 v=0） |",
"| 截断实例 | 见标签（bottom 截断帧按 capture/几何记录） |",
"| other_structures | 空（class1 仅 map-native MS1） |",
"",
"## 3. QA",
"",
"- 工具：pilot/two_class_tools.py qa → **PASS 52/52，0 error**；25 warning（tower 投影全跨度≥8px 但 tower_present=false，fov 画面外）。",
"- 检查：1:1、image sha/320×240、class1 v=0/keypoint null/reference false、bbox 界内/有序、投影 gate（MS1 投影≥8px 必有 class1）、class0=0。",
"",
"## 4. 方法、披露、边界",
"",
"- bbox：map-native MS1 世界位姿 + final run observations 相机位姿投影；2× contact sheet 目视抽查；**投影辅助 + agent 目视，非独立人工 GT**；bbox 约 ±3–8px。",
"- class1 仅 map-native MS1；不得映射 central-tower ID；keypoint 恒 null/v=0（loader 写 0 0 0 占位且被 loss mask 排除）。",
"- final conditions 尚未补发；capture 条件到位后我会做 diff 复核（若有差异以 capture 条件为准重出）。",
"- 旧 discarded 数据/标签作废；本批为 development 训练输入；不认证/不作独立测试/holdout；未 commit/push；未跑 Isaac/训练。",
"",
"## 5. 证据与 sha",
"",
"| 文件 | sha256 |",
"| --- | --- |",
"| shard_a/labels_v1.json（ignored） | "+sha(OUT/"labels_v1.json")+" |",
"| shard_a/selection.json（ignored） | "+sha(OUT/"selection.json")+" |",
"| shard_a/qa_v1.json（ignored） | "+sha(OUT/"qa_v1.json")+" |",
"| full/labels_v1.json（ignored，102 帧 provisional） | "+sha(FULL/"labels_v1.json")+" |",
"| full/selection.json（ignored） | "+sha(FULL/"selection.json")+" |",
"",
"## 6. 待办",
"",
"- annot2 重标 B（50 帧，final pool），完成后 A+B 合并=102。",
"- final conditions 补发后 diff 复核（本批用 final observations 位姿，若条件不同则重出）。",
"- 报告/证据供 v6.2 冻结与 train/datafreeze 消费。",
""
]
(BASE/"T39_NEAR_MS1_SHARD_A_ANNOTATION_20261105.md").write_text("\n".join(lines),encoding="utf-8")
print(json.dumps({"report":str(BASE/"T39_NEAR_MS1_SHARD_A_ANNOTATION_20261105.md"),
 "A":len(lab["frames"]),"B":len(B),"full":len(full["frames"]),"qa":qa["status"],
 "label_sha":sha(OUT/"labels_v1.json"),"qa_sha":sha(OUT/"qa_v1.json")},indent=1))
