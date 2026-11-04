# -*- coding: utf-8 -*-
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[5]
data = json.loads((ROOT / 'docs/reports/perception/capture_dev_20261104/frame_conditions.json').read_text(encoding='utf-8'))
print('TYPE', type(data), 'keys', list(data.keys())[:20] if isinstance(data, dict) else len(data))
if isinstance(data, dict):
    for k, v in data.items():
        print(' ', k, type(v), (len(v) if hasattr(v, '__len__') else v))
    frames = data.get('frames') or data.get('conditions') or []
else:
    frames = data
print('nframes', len(frames))
want = ['lmf_dev_inner_north_0-follow_only_g1_88.png',
        'lmf_dev_inner_north_0-follow_only_g1_91.png',
        'lmf_dev_inner_north_0-follow_only_g1_135.png',
        'lmf_dev_static_negative_0-follow_only_g5_3.png']
for fr in frames:
    fid = fr.get('frame_id') or fr.get('frame')
    if fid in want:
        print(json.dumps(fr, ensure_ascii=False, indent=1)[:3000])
