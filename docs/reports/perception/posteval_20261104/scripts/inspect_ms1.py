# -*- coding: utf-8 -*-
"""Inspect MS1-related saved evidence (no inference)."""
import json
import collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]

def load(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))

val = load('outputs/perception/dev_annotations_20261104/labels_val.json')
preds = [json.loads(l) for l in (ROOT / 'outputs/landmark_train/runs/bounded_v2/seed1/eval_last/predictions.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
by_id = {p['frame_id']: p for p in preds}
inner = [a for a in val['annotations'] if (a.get('source') or {}).get('family') == 'fam_dev_inner_north']
print('inner_north annotations', len(inner), 'with pred', sum(1 for a in inner if a['frame_id'] in by_id))
rows = []
for a in inner:
    p = by_id.get(a['frame_id'])
    if not p:
        continue
    obs = p.get('observation') or {}
    rows.append({
        'frame': a['frame_id'],
        'seq': (a.get('source') or {}).get('sequence'),
        'gt_bbox': (a.get('geometry') or {}).get('bbox_xywh'),
        'gt_kpt': (a.get('geometry') or {}).get('keypoint'),
        'gt_green_px': (a.get('geometry') or {}).get('green_pixels'),
        'gt_ref': (a.get('geometry') or {}).get('reference_status'),
        'pred_status': obs.get('status'),
        'candidates': obs.get('candidate_count'),
        'scores': [round(c.get('score', 0), 4) for c in (obs.get('candidates') or [])],
        'kpt_conf': obs.get('keypoint_confidence'),
        'pred_bbox': obs.get('bbox_xywh'),
        'pred_kpt': obs.get('keypoint_px'),
        'reject': obs.get('reject_reason'),
        'ref_status': obs.get('reference_status'),
        'confusers': [(c.get('confuser_id'), c.get('green_cue')) for c in (a.get('confusers') or [])],
    })
for r in sorted(rows, key=lambda v: (v['seq'] or 0)):
    print(json.dumps(r, ensure_ascii=False))

print('== candidate_count distribution inner_north', collections.Counter(r['candidates'] for r in rows))
print('== status', collections.Counter(r['pred_status'] for r in rows))

# final similar_negative predictions
fin = [json.loads(l) for l in (ROOT / 'outputs/perception/final_exploratory_eval_20261104/predictions.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
sn = [r for r in fin if r['strata'].get('family') == 'lmf_similar_negative']
print('== final similar_negative', len(sn), collections.Counter(r['observation'].get('status') for r in sn),
      'candidates', collections.Counter(r['observation'].get('candidate_count') for r in sn))
for r in sn[:6]:
    print(json.dumps({'frame': r['frame_id'], 'status': r['observation'].get('status'),
                      'cand': r['observation'].get('candidate_count'),
                      'scores': [round(c.get('score', 0), 3) for c in (r['observation'].get('candidates') or [])]}, ensure_ascii=False))

# capture provenance / hn injection notes
prov = load('docs/reports/perception/capture_dev_20261104/provenance_20261104.json')
print('== provenance top keys', list(prov.keys()))
for k, v in prov.items():
    if isinstance(v, dict):
        print(' ', k, list(v.keys())[:12])
    elif isinstance(v, list):
        print(' ', k, 'list', len(v))
