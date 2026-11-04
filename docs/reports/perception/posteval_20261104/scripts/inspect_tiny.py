# -*- coding: utf-8 -*-
import json
import collections
from pathlib import Path
ROOT = Path(__file__).resolve().parents[5]

def load(p):
    return json.loads((ROOT / p).read_text(encoding='utf-8'))

for name in ['labels_train', 'labels_val']:
    d = load('outputs/perception/dev_annotations_20261104/%s.json' % name)
    a = d['annotations']
    present = [x for x in a if (x.get('target') or {}).get('present') is True and (x.get('geometry') or {}).get('bbox_xywh')]
    tiny = [x for x in present if max(x['geometry']['bbox_xywh'][2], x['geometry']['bbox_xywh'][3]) <= 14]
    gp = [x for x in present if x['geometry'].get('green_pixels') is not None]
    dist = collections.Counter()
    for x in present:
        g = x['geometry'].get('green_pixels')
        if g is None:
            dist['none'] += 1
        elif g == 0:
            dist['0'] += 1
        elif g <= 2:
            dist['1-2'] += 1
        elif g <= 12:
            dist['3-12'] += 1
        elif g <= 49:
            dist['13-49'] += 1
        else:
            dist['50+'] += 1
    ref = collections.Counter(x['geometry'].get('reference_status') for x in present)
    print('==', name, 'present', len(present), 'tiny(maxside<=14)', len(tiny), 'reference', dict(ref))
    print('   green_pixels dist', dict(dist))
    # S2: keypoint visible and green 3..49
    s2 = [x for x in present if x['geometry'].get('keypoint') and 3 <= (x['geometry'].get('green_pixels') or 0) <= 49]
    print('   S2 keypoint visible & 3<=green<=49:', len(s2))
    for x in tiny[:60]:
        print('   TINY', x['frame_id'], [round(v,1) for v in x['geometry']['bbox_xywh']],
              'green', x['geometry'].get('green_pixels'), 'ref', x['geometry'].get('reference_status'),
              'fam', (x.get('source') or {}).get('family'))
    print('   S2 examples:')
    for x in s2[:25]:
        print('    ', x['frame_id'], [round(v,1) for v in x['geometry']['bbox_xywh']],
              'green', x['geometry'].get('green_pixels'), 'kpt',
              [round(x['geometry']['keypoint']['x'],1), round(x['geometry']['keypoint']['y'],1)],
              'fam', (x.get('source') or {}).get('family'))

# final labels calibration
fin = load('outputs/perception/final_exploratory_20261104/labels_v1.json')
print('== FINAL calibration')
print(json.dumps(fin.get('calibration'), ensure_ascii=False, indent=1)[:3000])
print('== FINAL visual_qa keys', list((fin.get('visual_qa') or {}).keys()))
print(json.dumps(fin.get('visual_qa'), ensure_ascii=False, indent=1)[:3000])
