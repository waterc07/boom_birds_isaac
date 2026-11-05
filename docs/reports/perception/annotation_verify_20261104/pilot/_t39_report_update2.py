from pathlib import Path
BASE=Path(r"E:\isaac\proj_boom_birds\docs\reports\perception\annotation_verify_20261104")
p=BASE/"T39_NEAR_MS1_SHARD_A_ANNOTATION_20261105.md"
t=p.read_text(encoding="utf-8")
t=t.replace("final run 位姿投影 + 目视抽查","final capture conditions（ms1_bbox_uv）+ 目视抽查")
old_start=t.find("| shard_a/labels_v1.json")
old_end=t.find("## 6. 待办")
new_block='''| shard_a/labels_v1.json（ignored） | deef8284f46384c218b77bc6f90a9a7c7cfa77781b3e4950b4bee9b9817bf504 |
| shard_a/selection.json（ignored） | cc35eb2ee7d2c62b5e02dc81b1b6c87c7033f6ad903b6adb2568e3793b86a702 |
| shard_a/qa_v1.json（ignored；PASS 0/0） | f6b0b7f14538426490da6bf8367ecb572bf883903f887cdcefbcbc32614018fc |
| full/labels_v1.json（ignored，102 帧 provisional） | db08d47b73f47ca371a33d2f754e55cd4508f7f7afb6312aa180641b21b0854c |
| full/selection.json（ignored） | 4344f91ed6fc04185dae133a4af9675b2f795da56b9aa7ba9b2b982ed4dc036a |

> 注：本表为 final capture conditions 重建后的 sha；先前基于 final observations 纯投影的版本（labels a2da4339…）已被取代。A(52)+B(50)=102；与 annot2 final shard B（bfb73d68…）互补校验：交集 0、并集 102=pool、无 missing/extra。

'''
if old_start!=-1 and old_end!=-1:
    t=t[:old_start]+new_block+t[old_end:]
p.write_text(t,encoding="utf-8")
print("updated")
