from pathlib import Path
BASE=Path(r"E:\isaac\proj_boom_birds\docs\reports\perception\annotation_verify_20261104")
p=BASE/"T39_NEAR_MS1_SHARD_A_ANNOTATION_20261105.md"
t=p.read_text(encoding="utf-8")
import re
t=t.replace("> **状态：** PROVISIONAL（数据准备/标注；final run 位姿投影 + 目视抽查；agent 代理，非独立人工 GT；不提升 Gate）",
"> **状态：** PROVISIONAL（数据准备/标注；**final capture conditions（ms1_bbox_uv）** + 目视抽查；agent 代理，非独立人工 GT；不提升 Gate）")
t=t.replace("3. 口径澄清：capture 先前 108 帧 pool/conditions 属于 **pilotA_discarded**（已作废）；final run accepted=**102**、sensor images 108（含非 accepted），f1 名改为 \`lmf_t38_f1_ms1_near_north_0\`。旧 discarded 标签不得用于 v6.2/训练。",
"3. 口径澄清：capture 先前 108 帧 pool/conditions 属于 **pilotA_discarded**（已作废）；final run accepted=**102**、sensor images 108（含非 accepted），f1 名改为 \`lmf_t38_f1_ms1_near_north_0\`。旧 discarded 标签不得用于 v6.2/训练。")
# replace sha table block
old_start=t.find("| shard_a/labels_v1.json（ignored）")
old_end=t.find("## 6. 待办")
if old_start!=-1 and old_end!=-1:
    new_block="""| shard_a/labels_v1.json（ignored） | """+aLab+""" |
| shard_a/selection.json（ignored） | """+aSel+""" |
| shard_a/qa_v1.json（ignored；PASS 0/0） | """+aQa+""" |
| full/labels_v1.json（ignored，102 帧 provisional） | """+fLab+""" |
| full/selection.json（ignored） | """+fSel+""" |

> 注：本表为 final capture conditions 重建后的 sha；先前基于 final observations 单纯投影的版本（labels a2da4339…）已被取代。A(52)+B(50)=102，与 annot2 final shard B（bfb73d68…）互补校验：交集 0、并集 102=pool、无 missing/extra。

"""
    t=t[:old_start]+new_block+t[old_end:]
p.write_text(t,encoding="utf-8")
print("report updated")
