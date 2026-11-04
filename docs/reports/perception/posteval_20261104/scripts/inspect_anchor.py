# -*- coding: utf-8 -*-
import json
import collections
from pathlib import Path
ROOT = Path(__file__).resolve().parents[5]
lab = json.loads((ROOT / 'outputs/perception/final_exploratory_20261104/labels_v1.json').read_text(encoding='utf-8'))
ann = lab['annotations']
present = [a for a in ann if (a.get('target') or {}).get('present') is True]
kpt = [a for a in present if ((a.get('geometry') or {}).get('keypoint'))]
nokpt = [a for a in present if not ((a.get('geometry') or {}).get('keypoint'))]
print('present', len(present), 'with keypoint', len(kpt), 'without', len(nokpt))
low = [a for a in kpt if (a['geometry'].get('green_pixels') or 0) < 3]
high_null = [a for a in nokpt if (a['geometry'].get('green_pixels') or 0) >= 3]
print('keypoint with green<3:', len(low), 'keypoint null with green>=3:', len(high_null))
for a in low[:12]:
    g = a['geometry']
    print('  LOW', a['frame_id'], 'green', g.get('green_pixels'), 'ref', g.get('reference_status'),
          'kpt', [round(g['keypoint']['x'], 1), round(g['keypoint']['y'], 1)],
          'fam', (a.get('source') or {}).get('family'))
print('low by family', collections.Counter((a.get('source') or {}).get('family') for a in low))
print('green dist among kpt', collections.Counter((a['geometry'].get('green_pixels') or 0) for a in kpt).most_common(15))
print('reference_source dist', collections.Counter((a['geometry'].get('reference_source')) for a in present))
print('unavailable reason', collections.Counter((a['geometry'].get('reference_unavailable_reason')) for a in present))
for p in ['outputs/perception/final_exploratory_20261104/labels_manifest.json',
          'docs/reports/perception/annotation_verify_20261104/pilot/qa_sheets_index.json']:
    try:
        d = json.loads((ROOT / p).read_text(encoding='utf-8'))
        print('==', p, 'type', type(d).__name__)
        if isinstance(d, dict):
            print('   keys', list(d.keys())[:25])
            print(json.dumps(d, ensure_ascii=False)[:1200])
        else:
            print('   len', len(d), json.dumps(d[:2], ensure_ascii=False)[:1200])
    except Exception as e:
        print('==', p, 'ERR', e)
