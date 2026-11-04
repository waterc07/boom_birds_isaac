# -*- coding: utf-8 -*-
"""Scratch inspection for the post-eval diagnosis (kept for reproducibility)."""
import json
import collections
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
print('ROOT', ROOT)

def load(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))

for label, path in [
    ('TRAIN', 'outputs/perception/dev_annotations_20261104/labels_train.json'),
    ('VAL', 'outputs/perception/dev_annotations_20261104/labels_val.json'),
    ('FINAL', 'outputs/perception/final_exploratory_20261104/labels_v1.json'),
]:
    d = load(path)
    a = d['annotations']
    pres = [x for x in a if (x.get('target') or {}).get('present') is True]
    bad = [x['frame_id'] for x in pres if (x.get('geometry') or {}).get('bbox_xywh') is None]
    pres = [x for x in pres if (x.get('geometry') or {}).get('bbox_xywh') is not None]
    ws = [x['geometry']['bbox_xywh'][2] for x in pres]
    hs = [x['geometry']['bbox_xywh'][3] for x in pres]
    buckets = collections.Counter()
    for w, h in zip(ws, hs):
        ar = w * h
        buckets['TINY' if ar < 1500 else 'SMALL' if ar < 5000 else 'MEDIUM' if ar < 15000 else 'LARGE'] += 1
    tiny = [(x['frame_id'], round(x['geometry']['bbox_xywh'][2], 1),
             round(x['geometry']['bbox_xywh'][3], 1),
             (x.get('source') or {}).get('family'))
            for x in pres if max(x['geometry']['bbox_xywh'][2], x['geometry']['bbox_xywh'][3]) <= 14]
    print('==', label, 'frames', len(a), 'present', len(pres), 'present_no_bbox', len(bad))
    print('   w med/min', round(st.median(ws), 1), round(min(ws), 1),
          '| h med/min', round(st.median(hs), 1), round(min(hs), 1))
    print('   area buckets', dict(buckets))
    print('   maxside<=14 count', len(tiny))
    for t in tiny:
        print('    ', t)

# confusers in val / train
for label, path in [
    ('VAL', 'outputs/perception/dev_annotations_20261104/labels_val.json'),
    ('TRAIN', 'outputs/perception/dev_annotations_20261104/labels_train.json'),
]:
    d = load(path)
    conf = collections.Counter()
    examples = []
    for x in d['annotations']:
        for cf in (x.get('confusers') or []):
            key = (cf.get('structure_id'), (cf.get('description') or '')[:60],
                   cf.get('verified'), cf.get('verification_source'))
            conf[key] += 1
            if len(examples) < 3:
                examples.append({'frame': x['frame_id'], 'family': (x.get('source') or {}).get('family'), 'conf': cf})
    print('== confusers', label)
    for k, v in conf.items():
        print('  ', v, k)
    for ex in examples:
        print('   example', json.dumps(ex, ensure_ascii=False)[:500])

# final predictions strata + observation fields
rows = [json.loads(line) for line in (ROOT / 'outputs/perception/final_exploratory_eval_20261104/predictions.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
print('== final predictions', len(rows))
print('scale', collections.Counter(r['strata'].get('scale') for r in rows))
print('family', collections.Counter(r['strata'].get('family') for r in rows))
print('ref class x scale', collections.Counter((r['strata'].get('scale'), r['reference_class']) for r in rows))
print('presence x scale', collections.Counter((r['strata'].get('scale'), r['presence_class']) for r in rows))
print('truncation', collections.Counter(r['strata'].get('truncation') for r in rows))
# keypoint confidence distribution for detected
kc = [r['observation'].get('keypoint_confidence') for r in rows if r.get('observation')]
print('kpt conf present n', sum(1 for v in kc if v is not None), 'min', min([v for v in kc if v is not None], default=None))
