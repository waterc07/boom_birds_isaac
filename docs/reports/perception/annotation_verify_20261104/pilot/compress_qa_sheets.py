import hashlib, json
from pathlib import Path
from PIL import Image
REPO = Path(r"E:\isaac\proj_boom_birds")
BASE = REPO / "docs/reports/perception/annotation_verify_20261104"
OUT = REPO / "outputs/perception/final_exploratory_20261104"
sheets_dir = BASE / "pilot/qa_sheets"
index_path = BASE / "pilot/qa_sheets_index.json"
index = json.loads(index_path.read_text(encoding="utf-8"))
new_index = {}
for name, frames in index.items():
    png = sheets_dir / name
    jpg = png.with_suffix(".jpg")
    Image.open(png).convert("RGB").save(jpg, quality=82, optimize=True)
    png.unlink()
    new_index[jpg.name] = frames
index_path.write_text(json.dumps(new_index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
index_sha = hashlib.sha256(index_path.read_bytes()).hexdigest()
# update label doc + manifest
labels_path = OUT / "labels_v1.json"
labels = json.loads(labels_path.read_text(encoding="utf-8"))
labels["visual_qa"]["contact_sheet_dir"] = "docs/reports/perception/annotation_verify_20261104/pilot/qa_sheets"
labels["visual_qa"]["contact_sheet_index_sha256"] = index_sha
labels_path.write_text(json.dumps(labels, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
label_sha = hashlib.sha256(labels_path.read_bytes()).hexdigest()
man_path = BASE / "pilot/final_exploratory_labels_manifest.json"
man = json.loads(man_path.read_text(encoding="utf-8"))
man["label_file"]["sha256"] = label_sha
man["visual_qa"]["contact_sheet_index_sha256"] = index_sha
man_path.write_text(json.dumps(man, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
(OUT / "labels_manifest.json").write_text(json.dumps(man, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("index sha", index_sha)
print("label sha", label_sha)
print("manifest sha", hashlib.sha256(man_path.read_bytes()).hexdigest())
print("sheets:", len(new_index))
