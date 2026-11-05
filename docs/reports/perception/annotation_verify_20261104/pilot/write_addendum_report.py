import hashlib, json
from pathlib import Path
REPO=Path(r"E:\isaac\proj_boom_birds")
BASE=REPO/"docs/reports/perception/annotation_verify_20261104"
OUT=REPO/"outputs/perception/dev_annotations_20261105/two_class/v41_ms1_addendum"
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
doc=json.loads((OUT/"labels_addendum.json").read_text(encoding="utf-8"))
qa=json.loads((OUT/"qa_addendum.json").read_text(encoding="utf-8"))
labels_sha=sha(OUT/"labels_addendum.json"); qa_sha=sha(OUT/"qa_addendum.json")
base_sha=doc["addendum"]["base_labels"]["sha256"]
risk_sha=doc["addendum"]["source_risk"]["sha256"]
lines=[
"# T31 附：v4.1 train MS1 补标 addendum（38 同框帧，2026-11-05）",
"",
"> **状态：** PROVISIONAL_DIAGNOSTIC（补标证据；投影辅助 + 抽样目视复核；agent 代理，非独立人工 GT；不改旧 v4.1 标签）",
"> **来源章节：** diag T35 裁定 B（补标而非排除）；V41_UNLABELED_MS1_RISK_20261105.json；landmark_two_class_label_spec_v1.json（FROZEN）",
"> **证据域：** 离线补标（v4.1 实际训练输入 436 帧中的 38 个同框正例帧；MS1 投影高度≥8px；无训练/推理）",
"> **最后核对：** 2026-11-05（HEAD 47d1063）",
"",
"## 0. 结论",
"",
"- diag 风险：436 个实际 v4.1 训练输入中 **69 帧投影 MS1 可见（≥8px）**，其中 38 帧是「塔标签存在但 MS1 未标」的同框帧、31 帧是「空负例但 MS1 可见」。",
"- 本 addendum 完成 **38 个同框正例帧**的 class1 补标（每帧 1 个 MS1 bbox；v=0、无 keypoint、WORLD_POSE_OR_MAP_DB），**不修改 v4.1 基础标签**，供 train/datafreeze 按 frame_id 合并。",
"- 31 个空负例帧暂未补（可后续按同一方法扩展）；按 lead 的 5 分钟规则，训练可先用 A 方案（排除 69 帧）。",
"- QA：自定义 fail-loud **PASS 38/38**（1:1、base 正例、sha、bbox 界内、class1 v=0/无 keypoint/reference=false、无重复）。",
"",
"## 1. 数据与来源",
"",
"| 项 | 值 |",
"| --- | --- |",
"| 基础标签 | outputs/landmark_train/dataset/labels_train_v4_1_merged.json（sha "+base_sha+"） |",
"| 风险源 | docs/reports/perception/posteval_20261104/V41_UNLABELED_MS1_RISK_20261105.json（sha "+risk_sha+"） |",
"| sidecar | outputs/landmark_train/dataset/dev_v4_1/sidecars/train_sidecar.jsonl（436 included） |",
"| 选区 | included_in_training ∩ ms1_visible ∩ height_px≥8 ∩ base present（=38） |",
"",
"## 2. 标注内容（38 帧）",
"",
"- class1 = map-native MS1（WORLD_POSE_OR_MAP_DB；map_native_structures.json 世界位姿），bbox 由风险 JSON 的 lamp_uv + projected height 推得（宽≈0.29×高，顶部在灯上方），clamp 到 320×240；truncated_edges 按 clamp 记录。",
"- 全部 v=0、keypoint_x/y=null、reference_available=false；loader 写 0 0 0 占位且被 keypoint loss mask 排除。",
"- 帧层：tower_present=true（沿用 v4.1 正例），ms1_present=true；不写入 class0 实例（class0 由 v4.1 基础标签保留）。",
"- 披露：bbox 为**投影辅助 + 4 张 2× contact sheet 抽样目视复核**，非逐帧像素级人工标注；误差约 ±3–8px。",
"",
"## 3. QA",
"",
"- 结果 **PASS 38/38**，0 error；qa_addendum.json sha "+qa_sha+"。",
"- 检查：frame 唯一、均属于 v4.1 included 且 base present、image sha/存在、class1 only、v=0、keypoint null、reference false、bbox 界内且有序。",
"",
"## 4. 证据",
"",
"| 文件 | sha256 |",
"| --- | --- |",
"| labels_addendum.json（ignored） | "+labels_sha+" |",
"| qa_addendum.json（ignored） | "+qa_sha+" |",
"| overlays（pilot/v41_ms1_addendum/，4 张 2× sheets） | 见目录 |",
"",
"## 5. 边界",
"",
"- 不改旧 v4.1 标签/冻结/hash；仅 addendum 供合并；不认证/不作独立测试；agent 代理 + 投影辅助（非人工 GT）。",
"- 31 帧空负例（MS1 可见但 base 空标签）未补；如需补标或采用 A 方案，由 lead/datafreeze 决定。",
"- 未 commit/push；未跑 Isaac/训练。",
""
]
(BASE/"T31_V41_MS1_ADDENDUM_20261105.md").write_text("\n".join(lines), encoding="utf-8")
print(json.dumps({"labels_sha":labels_sha,"qa_sha":qa_sha,"frames":len(doc["frames"]),"qa_status":qa["status"]},indent=1))
