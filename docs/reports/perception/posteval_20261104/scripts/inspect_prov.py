# -*- coding: utf-8 -*-
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[5]
prov = json.loads((ROOT / 'docs/reports/perception/capture_dev_20261104/provenance_20261104.json').read_text(encoding='utf-8'))
print('== runs')
print(json.dumps(prov['runs'], ensure_ascii=False, indent=1)[:6000])
print('== families')
print(json.dumps(prov['families'], ensure_ascii=False, indent=1)[:12000])
print('== four_side')
print(json.dumps(prov['four_side_truncation_and_green_metadata'], ensure_ascii=False)[:4000])
print('== artifacts')
print(json.dumps(prov['artifacts_sha256'], ensure_ascii=False, indent=1))
