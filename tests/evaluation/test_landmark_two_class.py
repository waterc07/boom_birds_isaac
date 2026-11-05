"""Two-class landmark contract tests (no ML backend required).

Pins: two-class conversion (class0 keypoint supervised, class1 v=0 always and
masked), fail-loud QA for the frozen T31/T32 schema, shard merging, detector-level
metrics with explicit denominators, dataset build and single-class compatibility.
"""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / 'src'))

from boom_birds.evaluation import landmark_two_class as two
from boom_birds.evaluation import landmark_yolo as single

TWO_CLASS_SCRIPT = REPO_ROOT / 'scripts' / 'landmark_train_two_class.py'
IDENTITY_LABELS = REPO_ROOT / 'outputs/perception/dev_annotations_20261104/labels_identity_dev.json'


def _load_script():
    spec = importlib.util.spec_from_file_location('landmark_train_two_class', TWO_CLASS_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _annotation(present=True, bbox=None, keypoint=None, reference='MANUAL_APPROX',
                confusers=None, occluded=False, undecidable=False, frame='f.png',
                negative_type=None):
    target = {'present': present, 'undecidable': undecidable,
              'visibility': 'ABSENT' if not present else ('FULL' if bbox else 'OCCLUDED'),
              'occluded': occluded, 'ambiguous': False}
    geometry = {'bbox_xywh': bbox, 'keypoint': keypoint,
                'reference_status': reference}
    return {'frame_id': frame, 'image': 'img/%s' % frame, 'image_width': 320,
            'image_height': 240, 'source': {'split': 'val', 'family': 'fam', 'group_id': 'g'},
            'target': target, 'geometry': geometry,
            'confusers': confusers or [], 'negative_type': negative_type}


def _ms1_confuser(bbox=(100.0, 40.0, 40.0, 160.0)):
    return {'confuser_id': 'MAP_NATIVE_GREEN_LAMP_PILLAR_MS1',
            'description': 'map-native slender green-lamp pillar (MS1)',
            'bbox_xywh': list(bbox), 'verified': True,
            'verification_source': 'WORLD_POSE_OR_DB'}


def _real_identity_annotations():
    if not IDENTITY_LABELS.is_file():
        pytest.skip('labels_identity_dev is gitignored and absent')
    return json.loads(IDENTITY_LABELS.read_text(encoding='utf-8'))['annotations']


# --- conversion --------------------------------------------------------------

def test_class0_visible_keypoint_is_supervised():
    annotation = _annotation(bbox=[99.1, 82.6, 149.3, 99.0],
                             keypoint={'x': 171.8, 'y': 105.4, 'visible': True})
    record = two.convert_annotation(annotation)
    parts = record['lines'][0].split()
    assert len(parts) == 8
    assert parts[0] == '0'
    assert float(parts[7]) == 1.0
    assert float(parts[5]) == pytest.approx(171.8 / 320, abs=1e-6)
    assert float(parts[6]) == pytest.approx(105.4 / 240, abs=1e-6)
    assert two.keypoint_mask_for_instances(
        [{'class_id': 0, 'keypoint_visible': True}]) == [1]


def test_class0_unavailable_reference_is_v0_placeholder():
    annotation = _annotation(bbox=[10, 10, 100, 80], keypoint=None, reference='UNAVAILABLE')
    record = two.convert_annotation(annotation)
    parts = record['lines'][0].split()
    assert float(parts[7]) == 0.0
    assert float(parts[5]) == pytest.approx((10 + 50) / 320, abs=1e-6)
    assert two.keypoint_mask_for_instances(
        [{'class_id': 0, 'keypoint_visible': False}]) == [0]


def test_ms1_only_frame_emits_class1_v0_and_no_tower():
    annotation = _annotation(present=False, bbox=None, confusers=[_ms1_confuser()],
                             reference='NOT_APPLICABLE', negative_type='SIMILAR_STRUCTURE')
    record = two.convert_annotation(annotation)
    assert len(record['lines']) == 1
    parts = record['lines'][0].split()
    assert parts[0] == '1'
    assert float(parts[7]) == 0.0
    assert record['sidecar']['class0_lines'] == 0
    assert record['sidecar']['class1_lines'] == 1
    assert two.keypoint_mask_for_instances(
        [{'class_id': 1, 'keypoint_visible': False}]) == [0]


def test_same_frame_has_both_classes_and_class1_masked():
    annotation = _annotation(bbox=[10, 10, 120, 90],
                             keypoint={'x': 70.0, 'y': 30.0, 'visible': True},
                             confusers=[_ms1_confuser()])
    record = two.convert_annotation(annotation)
    assert len(record['lines']) == 2
    classes = sorted(int(line.split()[0]) for line in record['lines'])
    assert classes == [0, 1]
    class1_line = next(line for line in record['lines'] if line.startswith('1 '))
    assert float(class1_line.split()[7]) == 0.0


def test_full_occlusion_is_gt_unobservable_not_negative():
    annotation = _annotation(present=True, bbox=None, keypoint=None,
                             reference='UNAVAILABLE', occluded=True)
    record = two.convert_annotation(annotation)
    assert record['lines'] == []
    assert record['sidecar']['gt_unobservable'] is True
    assert record['sidecar']['exclusion_reason'] == 'GT_UNOBSERVABLE'


def test_convert_document_counts_classes_and_same_frame():
    document = {'annotations': [
        _annotation(bbox=[10, 10, 120, 90],
                    keypoint={'x': 70.0, 'y': 30.0, 'visible': True}, frame='a.png'),
        _annotation(present=False, confusers=[_ms1_confuser()], frame='b.png',
                    negative_type='SIMILAR_STRUCTURE'),
        _annotation(bbox=[10, 10, 120, 90], keypoint={'x': 70.0, 'y': 30.0, 'visible': True},
                    confusers=[_ms1_confuser()], frame='c.png'),
    ]}
    converted = two.convert_document(document)
    counts = converted['counts']
    assert counts['class0_instances'] == 2
    assert counts['class1_instances'] == 2
    assert counts['same_frame_instances'] == 1
    assert counts['class1_keypoint_visibility_histogram']['class1']['v0'] == 2


def test_single_class_compatibility_for_frame_without_ms1():
    annotations = [a for a in _real_identity_annotations() if not a.get('confusers')]
    if not annotations:
        pytest.skip('no no-confuser identity frame available')
    annotation = annotations[0]
    single_document = {'schema_version': 'dsh.tower_annotation.v2_1',
                       'annotations': [annotation]}
    single_lines = list(single.convert_annotation_document(single_document, root=REPO_ROOT,
                                                           split=None)['labels'].values())
    two_record = two.convert_annotation(annotation)
    assert single_lines and two_record['lines']
    assert single_lines[0] == two_record['lines'][0]


# --- new schema (T31/T32) ----------------------------------------------------

def _two_class_frame_from(annotation):
    instances = []
    geometry = annotation.get('geometry') or {}
    if (annotation.get('target') or {}).get('present') is True and geometry.get('bbox_xywh'):
        x, y, w, h = geometry['bbox_xywh']
        keypoint = geometry.get('keypoint')
        visible = bool(keypoint) and annotation.get('geometry', {}).get('reference_status') == 'MANUAL_APPROX'
        instances.append({'class': 0, 'bbox_xyxy': [x, y, x + w, y + h],
                          'truncated_edges': {'left': False, 'right': False, 'top': False, 'bottom': False},
                          'occluded': False,
                          'keypoint_x': (float(keypoint['x']) / 320) if visible else None,
                          'keypoint_y': (float(keypoint['y']) / 240) if visible else None,
                          'v': 1 if visible else 0,
                          'reference_available': visible,
                          'verified_source': 'VISUAL'})
    for confuser in annotation.get('confusers') or []:
        x, y, w, h = confuser['bbox_xywh']
        instances.append({'class': 1, 'bbox_xyxy': [x, y, x + w, y + h],
                          'truncated_edges': {'left': False, 'right': False, 'top': False, 'bottom': False},
                          'occluded': False, 'keypoint_x': None, 'keypoint_y': None,
                          'v': 0, 'reference_available': False,
                          'verified_source': confuser.get('verification_source')})
    return {'frame_id': annotation['frame_id'], 'image': annotation['image'],
            'image_sha256': annotation['image_sha256'],
            'image_width': annotation['image_width'], 'image_height': annotation['image_height'],
            'family': annotation['source']['family'], 'group_id': annotation['source']['group_id'],
            'split': annotation['source']['split'],
            'tower_present': (annotation.get('target') or {}).get('present') is True,
            'ms1_present': bool(annotation.get('confusers')),
            'identity_ambiguity': 'NONE', 'gt_uncertainty': 'NONE',
            'occlusion': 'NONE', 'instances': instances}


def _two_class_document(frames):
    return {'schema_version': two.TWO_CLASS_SCHEMA, 'status': 'TEST',
            'coordinate_space': dict(two.COORDINATE_SPACE), 'frames': frames}


def test_valid_two_class_document_passes_qa():
    annotations = _real_identity_annotations()
    same_frame = [a for a in annotations if a.get('confusers')]
    if not same_frame:
        pytest.skip('no MS1 identity annotation available')
    document = _two_class_document([_two_class_frame_from(a) for a in same_frame[:3]])
    qa = two.validate_two_class_file(document, REPO_ROOT)
    assert qa['ok'], qa['problems']


def test_qa_rejects_class1_visible_keypoint_and_normalised_bbox():
    frame = _two_class_frame_from(_real_identity_annotations()[0])
    bad = copy.deepcopy(frame)
    bad['instances'].append({'class': 1, 'bbox_xyxy': [10, 10, 40, 40],
                             'truncated_edges': {}, 'occluded': False,
                             'keypoint_x': 0.5, 'keypoint_y': 0.5, 'v': 1,
                             'reference_available': True, 'verified_source': 'X'})
    document = _two_class_document([bad])
    qa = two.validate_two_class_file(document, REPO_ROOT)
    assert not qa['ok']
    assert any('class1 keypoint must be null/v=0' in problem for problem in qa['problems'])
    normalised = copy.deepcopy(frame)
    normalised['instances'] = [{'class': 0, 'bbox_xyxy': [0.1, 0.2, 0.5, 0.8],
                                'truncated_edges': {}, 'occluded': False,
                                'keypoint_x': None, 'keypoint_y': None, 'v': 0,
                                'reference_available': False, 'verified_source': 'X'}]
    qa = two.validate_two_class_file(_two_class_document([normalised]), REPO_ROOT)
    assert not qa['ok']
    assert any('normalised' in problem for problem in qa['problems'])


def test_qa_rejects_ms1_present_mismatch_and_duplicate_frame():
    frame = _two_class_frame_from(_real_identity_annotations()[0])
    frame['ms1_present'] = True  # no class1 instances
    qa = two.validate_two_class_file(_two_class_document([frame]), REPO_ROOT)
    assert not qa['ok']
    assert any('ms1_present' in problem for problem in qa['problems'])
    frame2 = copy.deepcopy(frame)
    frame2['ms1_present'] = False
    qa = two.validate_two_class_file(_two_class_document([frame2, copy.deepcopy(frame2)]), REPO_ROOT)
    assert not qa['ok']
    assert any('duplicate frame_id' in problem for problem in qa['problems'])


def test_merge_shards_ok_duplicate_and_coordinate_mismatch(tmp_path):
    annotations = [a for a in _real_identity_annotations() if a.get('confusers')]
    if len(annotations) < 2:
        pytest.skip('need at least two MS1 identity annotations')
    shard_a = tmp_path / 'shard_a.json'
    shard_b = tmp_path / 'shard_b.json'
    shard_a.write_text(json.dumps(_two_class_document([_two_class_frame_from(annotations[0])])), encoding='utf-8')
    shard_b.write_text(json.dumps(_two_class_document([_two_class_frame_from(annotations[1])])), encoding='utf-8')
    merged = tmp_path / 'merged.json'
    result = two.merge_two_class_shards([shard_a, shard_b], merged, REPO_ROOT)
    assert result['ok'] and result['frames'] == 2
    assert json.loads(merged.read_text(encoding='utf-8'))['sources'][0]['sha256']
    duplicate = tmp_path / 'dup.json'
    result = two.merge_two_class_shards([shard_a, shard_a], duplicate, REPO_ROOT)
    assert not result['ok']
    assert any('duplicate frame across shards' in problem for problem in result['problems'])
    mismatched = json.loads(shard_b.read_text(encoding='utf-8'))
    mismatched['coordinate_space'] = {'bbox': 'NORMALISED', 'keypoint': 'PIXELS'}
    bad_shard = tmp_path / 'bad.json'
    bad_shard.write_text(json.dumps(mismatched), encoding='utf-8')
    result = two.merge_two_class_shards([shard_a, bad_shard], tmp_path / 'bad_merged.json', REPO_ROOT)
    assert not result['ok']


# --- detector metrics --------------------------------------------------------

def _prediction(frame, detections):
    return {'frame_id': frame, 'detections': detections}


def test_evaluate_two_class_denominators_and_ms1_only_claims():
    tower_annotation = _annotation(bbox=[10, 10, 100, 100],
                                   keypoint={'x': 60.0, 'y': 30.0, 'visible': True}, frame='tower.png')
    ms1_annotation = _annotation(present=False, confusers=[_ms1_confuser((100, 40, 40, 160))],
                                 frame='ms1.png', negative_type='SIMILAR_STRUCTURE')
    both_annotation = _annotation(bbox=[10, 10, 100, 100],
                                  keypoint={'x': 60.0, 'y': 30.0, 'visible': True},
                                  confusers=[_ms1_confuser((100, 40, 40, 160))], frame='both.png')
    predictions = [
        _prediction('tower.png', [{'class_id': 0, 'score': 0.9,
                                   'bbox_xywh': [10, 10, 100, 100],
                                   'keypoint_px': [60.0, 30.0]}]),
        _prediction('ms1.png', [{'class_id': 1, 'score': 0.8,
                                 'bbox_xywh': [100, 40, 40, 160]}]),
        _prediction('both.png', [{'class_id': 0, 'score': 0.9, 'bbox_xywh': [10, 10, 100, 100],
                                  'keypoint_px': [60.0, 30.0]},
                                 {'class_id': 1, 'score': 0.8, 'bbox_xywh': [100, 40, 40, 160]}]),
    ]
    metrics = two.evaluate_two_class(predictions,
                                     [tower_annotation, ms1_annotation, both_annotation])
    assert metrics['tower']['gt_positives'] == 2 and metrics['tower']['tp'] == 2
    assert metrics['tower']['recall'] == 1.0
    assert metrics['ms1']['gt_instances'] == 2 and metrics['ms1']['tp'] == 2
    assert metrics['ms1_only']['frames'] == 1
    assert metrics['ms1_only']['wrong_tower_claims'] == 0
    assert metrics['same_frame']['frames'] == 1 and metrics['same_frame']['correct'] == 1
    assert metrics['identity']['precision'] == 1.0
    assert metrics['reference']['available_frames'] == 2
    assert metrics['reference']['correct_within_tau_px'] == 2
    assert metrics['consumer_metrics']['status'].startswith('PENDING')


def test_evaluate_two_class_counts_wrong_tower_claim_on_ms1_only():
    ms1_annotation = _annotation(present=False, confusers=[_ms1_confuser((100, 40, 40, 160))],
                                 frame='ms1.png', negative_type='SIMILAR_STRUCTURE')
    predictions = [_prediction('ms1.png', [
        {'class_id': 1, 'score': 0.8, 'bbox_xywh': [100, 40, 40, 160]},
        {'class_id': 0, 'score': 0.9, 'bbox_xywh': [100, 40, 40, 160]},
    ])]
    metrics = two.evaluate_two_class(predictions, [ms1_annotation])
    assert metrics['ms1_only']['wrong_tower_claims'] == 1
    assert metrics['identity']['precision'] == 0.0


# --- dataset build + CLI -----------------------------------------------------

def test_build_two_class_dataset_from_identity_subset(tmp_path):
    annotations = _real_identity_annotations()
    same_frame = [a for a in annotations if a.get('confusers')][:3]
    tower_only = [a for a in annotations if not a.get('confusers')][:2]
    if not same_frame or not tower_only:
        pytest.skip('identity annotations unavailable')
    document = {'annotations': same_frame + tower_only}
    summary = two.build_dataset([document], tmp_path / 'ds', REPO_ROOT, splits=('val',))
    counts = summary['splits']['val']['counts']
    assert counts['class0'] >= 1 and counts['class1'] >= 1
    data_yaml = (tmp_path / 'ds' / 'data.yaml').read_text(encoding='utf-8')
    assert 'names:' in data_yaml and '0: central_tower' in data_yaml
    assert '1: similar_structure_ms1' in data_yaml and 'kpt_shape: [1, 3]' in data_yaml
    for label_file in (tmp_path / 'ds' / 'labels' / 'val').glob('*.txt'):
        for line in label_file.read_text(encoding='utf-8').splitlines():
            if line.strip():
                assert len(line.split()) == 8
                if line.split()[0] == '1':
                    assert float(line.split()[7]) == 0.0


def test_two_class_cli_help_runs():
    completed = subprocess.run([sys.executable, str(TWO_CLASS_SCRIPT), '--help'],
                               capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0
    assert '--smoke' in completed.stdout and '--train' in completed.stdout


def test_two_class_cli_merge_requires_shards():
    completed = subprocess.run([sys.executable, str(TWO_CLASS_SCRIPT), '--merge-shards'],
                               capture_output=True, text=True, timeout=120)
    assert completed.returncode == 2


# --- frozen checkpoint selection rules ---------------------------------------

def _candidate(name, tower, ms1, same):
    return {'candidate': name,
            'tower_metrics_val_main': {'tower': {'recall': tower}},
            'identity_metrics': {'ms1': {'recall': ms1},
                                 'same_frame': {'rate': same}}}


def test_selection_metrics_exposes_rule_inputs():
    metrics = two.selection_metrics(_candidate('last', 0.82, 0.29, 0.85))
    assert metrics == {'tower_recall_val_main': 0.82,
                       'ms1_recall_identity': 0.29,
                       'same_frame_rate_identity': 0.85}


def test_r1_rule_prefers_tower_recall_then_ms1():
    tower_first = _candidate('last', 0.82, 0.10, 0.40)
    ms1_first = _candidate('best', 0.76, 0.20, 0.90)
    assert two.candidate_rank_key(tower_first, 'r1_detector') < two.candidate_rank_key(ms1_first, 'r1_detector')
    assert two.candidate_rank_key(tower_first, 'r2_joint') > two.candidate_rank_key(ms1_first, 'r2_joint')


def test_r2_joint_rule_uses_equal_weight_sum_then_same_frame():
    low_sum = _candidate('a', 0.60, 0.30, 0.90)
    high_sum = _candidate('b', 0.50, 0.50, 0.10)
    assert two.candidate_rank_key(high_sum, 'r2_joint') < two.candidate_rank_key(low_sum, 'r2_joint')
    tied_low = _candidate('c', 0.60, 0.30, 0.10)
    tied_high = _candidate('d', 0.60, 0.30, 0.50)
    assert two.candidate_rank_key(tied_high, 'r2_joint') < two.candidate_rank_key(tied_low, 'r2_joint')


def test_r2_joint_rule_name_is_deterministic_tiebreak():
    last = _candidate('last', 0.60, 0.30, 0.50)
    best = _candidate('best', 0.60, 0.30, 0.50)
    # ascending candidate name is the final deterministic tie-break
    assert two.candidate_rank_key(best, 'r2_joint') < two.candidate_rank_key(last, 'r2_joint')
