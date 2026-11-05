"""Failing-first tests for the two-class landmark consumer evaluation.

Pins the pre-registered two-class protocol
(configs/perception/landmark_two_class_protocol_v1.json) and label spec
(landmark_two_class_label_spec_v1.json):

- class 0 = central_tower, class 1 = similar_structure_ms1; per-class
  confusion/recall and a confusion matrix (with misclassification counted);
- a central-tower landmark_id claim may only come from a class-0 detection with
  score >= tau_det and no class conflict; class 1 must NEVER map to the tower ID;
- MS1-only frames with a tower claim are wrong claims;
- same-frame (tower + MS1) frames report whether the TOWER was selected;
- class 0 only may emit the reference keypoint (class 1 keypoint is always
  unavailable and never a bbox-centre substitute);
- reference availability / emission / horizontal bearing / consumer success are
  reported with explicit denominators; UNKNOWN/REJECTED stay in the denominator;
- GT-uncertain / fully-occluded frames must not receive improper identity claims;
- the frozen single-class v2 pipeline is compared on the same definitions.

Tests use synthetic frames plus the real 62-frame development identity pool when
the saved single-class predictions are present (skip otherwise).
"""
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest

from boom_birds.evaluation import landmark_two_class_eval as tc


REPO_ROOT = Path(__file__).resolve().parents[2]
TOWER = 'RMUC2027_CENTRAL_TOWER_PROPOSED'
PROTOCOL_PATH = REPO_ROOT / 'configs/perception/landmark_two_class_protocol_v1.json'


def protocol_doc():
    return {
        'schema_version': 'dsh.landmark_two_class_protocol.v1',
        'status': 'TEST_PROTOCOL',
        'classes': {'0': {'name': 'central_tower'},
                    '1': {'name': 'similar_structure_ms1'}},
        'identity_output_rules': {
            'tower_claim': 'class0 only', 'ms1_claim': 'never'},
        'evaluation': {'denominator_policy': 'UNKNOWN/REJECTED kept'},
        'baseline': 'frozen single-class v2',
    }


def truth(*, tower=True, ms1=(), tower_bbox=(100.0, 50.0, 80.0, 120.0),
          reference='VISIBLE', keypoint=(142.0, 71.0), uncertain=False,
          unobservable=False, frame_id='f.png', family='fam'):
    return {
        'frame_id': frame_id,
        'image': 'images/' + frame_id,
        'image_width': 320,
        'image_height': 240,
        'intrinsics': {'fx_px': 160.0, 'cx_px': 160.0, 'cy_px': 120.0},
        'tower_present': tower,
        'ms1_present': bool(ms1),
        'gt_tower_bbox': (list(tower_bbox) if (tower and not unobservable)
                          else None),
        'gt_tower_reference': ('VISIBLE' if (tower and reference == 'VISIBLE'
                                             and not unobservable) else
                               ('UNAVAILABLE' if tower and not unobservable
                                else None)),
        'gt_tower_keypoint': (list(keypoint)
                              if (tower and reference == 'VISIBLE'
                                  and not unobservable) else None),
        'gt_ms1_boxes': [[float(v) for v in box] for box in ms1],
        'gt_uncertain': bool(uncertain),
        'gt_unobservable': bool(unobservable),
        'same_frame': bool(tower and ms1 and not unobservable),
        'family': family,
        'scale': 'MEDIUM',
        'truncation': 'NOT_TRUNCATED',
    }


def detection(class_id, bbox, score=0.9, keypoint=(142.0, 71.0), kpt_conf=0.9):
    return {'class_id': class_id,
            'bbox_xywh': [float(v) for v in bbox],
            'score': float(score),
            'keypoint_px': (None if keypoint is None else [float(v) for v in keypoint]),
            'keypoint_confidence': kpt_conf}


def observation(detections, *, tower_claim=None, frame_id='f.png'):
    return {'frame_id': frame_id, 'status': 'DETECTED',
            'detections': detections,
            'landmark_id': tower_claim,
            'reject_reason': None}


def merge_protocol():
    return tc.merge_protocol(protocol_doc())


def evaluate(truth_row, detections, *, tower_claim=None, policy='confirmed_only',
             protocol=None):
    protocol = protocol or merge_protocol()
    return tc.evaluate_frame(truth_row, observation(detections, tower_claim=tower_claim),
                             protocol, identity_policy=policy)


# --- protocol / truth -------------------------------------------------------

def test_load_two_class_protocol_and_record_sha():
    protocol = tc.load_protocol(PROTOCOL_PATH)
    assert protocol['schema_version'] == 'dsh.landmark_two_class_protocol.v1'
    assert protocol['status'].startswith('PRE_REGISTERED')
    assert protocol['_source']['sha256']


def test_truth_from_two_class_annotation_instances():
    annotation = {
        'schema_version': 'dsh.landmark_two_class_annotation.v1',
        'frame_id': 'a.png', 'image': 'images/a.png',
        'image_width': 320, 'image_height': 240,
        'tower_present': True, 'ms1_present': True,
        'identity_ambiguity': False, 'gt_uncertainty': False,
        'instances': [
            {'class': 0, 'bbox_xyxy': [100.0, 50.0, 180.0, 170.0],
             'keypoint_x': 142.0, 'keypoint_y': 71.0, 'v': 1,
             'reference_available': True},
            {'class': 1, 'bbox_xyxy': [20.0, 40.0, 60.0, 190.0],
             'keypoint_x': None, 'keypoint_y': None, 'v': 0,
             'reference_available': False},
        ],
    }
    row = tc.truth_from_two_class_annotation(annotation)
    assert row['tower_present'] is True and row['ms1_present'] is True
    assert row['same_frame'] is True
    assert row['gt_tower_bbox'] == pytest.approx([100.0, 50.0, 80.0, 120.0])
    assert row['gt_ms1_boxes'] == [[20.0, 40.0, 40.0, 150.0]]
    assert row['gt_tower_reference'] == 'VISIBLE'


def test_truth_from_train_side_annotations_frames_schema(tmp_path):
    frame = {
        'frame_id': 'train.png', 'image': 'images/train.png',
        'image_width': 320, 'image_height': 240,
        'tower_present': True, 'ms1_present': True,
        'gt_uncertainty': False, 'occluded': False,
        'instances': [
            {'class': 0, 'bbox_xyxy': [100.0, 50.0, 180.0, 170.0],
             'keypoint_normalized': [142.0 / 320.0, 71.0 / 240.0],
             'v': 1, 'reference_available': True},
            {'class': 1, 'bbox_xyxy': [20.0, 40.0, 60.0, 190.0],
             'keypoint': None, 'v': 0, 'reference_available': False},
        ],
    }
    document = {'schema_version': 'dsh.landmark_two_class_annotations.v1',
                'frames': [frame]}
    path = tmp_path / 'two_class_train.json'
    path.write_text(json.dumps(document), encoding='utf-8')
    loaded_document, rows = tc.load_two_class_labels(path)
    assert loaded_document['schema_version'].endswith('annotations.v1')
    assert len(rows) == 1
    row = rows[0]
    assert row['tower_present'] is True and row['ms1_present'] is True
    assert row['same_frame'] is True
    assert row['gt_tower_bbox'] == pytest.approx([100.0, 50.0, 80.0, 120.0])
    assert row['gt_tower_keypoint'] == pytest.approx([142.0, 71.0])
    assert row['gt_tower_reference'] == 'VISIBLE'
    assert row['gt_ms1_boxes'] == [[20.0, 40.0, 40.0, 150.0]]

def test_normalized_keypoint_x_y_in_frozen_schema_is_scaled():
    annotation = {
        'schema_version': 'dsh.landmark_two_class_annotations.v1',
        'frame_id': 'norm.png', 'image': 'images/norm.png',
        'image_width': 320, 'image_height': 240,
        'tower_present': True, 'tower_observable': True,
        'gt_unobservable': False, 'negative': False,
        'instances': [{'class': 0, 'bbox_xyxy': [100.0, 50.0, 180.0, 170.0],
                       'keypoint_x': 0.5, 'keypoint_y': 0.5, 'v': 1,
                       'reference_available': True}],
    }
    row = tc.truth_from_two_class_annotation(annotation)
    assert row['gt_tower_keypoint'] == pytest.approx([160.0, 120.0])
    assert row['gt_tower_reference'] == 'VISIBLE'

def test_truth_from_existing_identity_pool_labels_and_decisions(tmp_path):
    labels = {'schema_version': 'dsh.tower_annotation.v2_1', 'annotations': [
        {'frame_id': 'both.png', 'image': 'images/both.png',
         'image_width': 320, 'image_height': 240,
         'source': {'family': 'f', 'group_id': 'g', 'split': 'val'},
         'target': {'landmark_id': TOWER, 'class': 'tower', 'present': True,
                    'undecidable': False, 'visibility': 'FULL',
                    'truncated': False, 'occluded': False, 'ambiguous': False,
                    'truncated_edges': {'left': False, 'right': False,
                                        'top': False, 'bottom': False},
                    'truncation_source': {}},
         'geometry': {'bbox_xywh': [200, 60, 60, 120],
                      'keypoint': {'x': 230.0, 'y': 70.0, 'visible': True},
                      'green_pixels': 12, 'reference_status': 'MANUAL_APPROX',
                      'reference_unavailable_reason': None,
                      'reference_source': 'COLOR_CUE_ASSISTED'},
         'confusers': [], 'negative_type': None,
         'annotator': {'annotator_type': 'AGENT_PROXY'},
         'pixel_basis': {'fx_px': 160.0, 'cx_px': 160.0, 'cy_px': 120.0}},
    ]}
    labels_path = tmp_path / 'labels.json'
    labels_path.write_text(json.dumps(labels), encoding='utf-8')
    decisions = {'schema_version': 'dsh.landmark_identity_decisions.v1',
                 'frames': [{'frame_id': 'both.png',
                             'identity_condition': 'both_in_frame_similar_scale',
                             'decision': 'BOTH_TARGET_IDENTIFIED',
                             'target_bbox': [200.0, 60.0, 60.0, 120.0],
                             'target_keypoint': [230.0, 70.0],
                             'confusers': [{'confuser_id': 'MS1',
                                            'confuser_kind': 'MAP_NATIVE_MS1',
                                            'bbox_xywh': [20.0, 40.0, 40.0, 150.0],
                                            'verification_source': 'WORLD_POSE_OR_MAP_DB'}]}]}
    decisions_path = tmp_path / 'decisions.json'
    decisions_path.write_text(json.dumps(decisions), encoding='utf-8')
    rows = tc.build_truth_from_identity_pool(labels_path, decisions_path)
    assert len(rows) == 1
    row = rows[0]
    assert row['tower_present'] is True and row['ms1_present'] is True
    assert row['same_frame'] is True
    assert row['gt_tower_bbox'] == pytest.approx([200.0, 60.0, 60.0, 120.0])
    assert row['gt_ms1_boxes'] == [[20.0, 40.0, 40.0, 150.0]]


# --- two-class decoding / identity rules -----------------------------------

def test_decode_claims_only_from_class0_without_conflict():
    protocol = merge_protocol()
    decoded = tc.decode_detections([detection(0, [100, 50, 80, 120])],
                                   'f.png', protocol)
    assert decoded['landmark_id'] == TOWER
    assert decoded['tower_claim_source'] == 'CLASS0'
    ms1_only = tc.decode_detections([detection(1, [20, 40, 40, 150])],
                                    'ms1.png', protocol)
    assert ms1_only['landmark_id'] is None
    assert ms1_only['reject_reason'] == 'NO_TOWER_CLASS'
    conflict = tc.decode_detections(
        [detection(0, [100, 50, 80, 120]), detection(1, [100, 50, 80, 120])],
        'conflict.png', protocol)
    assert conflict['landmark_id'] is None
    assert conflict['reject_reason'] == 'CLASS_CONFLICT'


def test_decode_multi_candidate_margin_and_low_score():
    protocol = merge_protocol()
    multi = tc.decode_detections(
        [detection(0, [100, 50, 80, 120], score=0.90),
         detection(0, [200, 60, 60, 120], score=0.85)],
        'multi.png', protocol)
    assert multi['landmark_id'] is None
    assert multi['reject_reason'] == 'MULTIPLE_CANDIDATES'
    low = tc.decode_detections([detection(0, [100, 50, 80, 120], score=0.10)],
                               'low.png', protocol)
    assert low['status'] == 'NOT_DETECTED'
    assert low['landmark_id'] is None


def test_class1_keypoint_is_never_emitted():
    protocol = merge_protocol()
    decoded = tc.decode_detections(
        [detection(1, [20, 40, 40, 150], keypoint=(30.0, 50.0))],
        'ms1.png', protocol)
    class1 = [d for d in decoded['detections'] if d['class_id'] == 1][0]
    assert class1['keypoint_px'] is None
    assert class1['reference_available'] is False


# --- per-class confusion ---------------------------------------------------

def test_class_confusion_and_misclassification():
    protocol = merge_protocol()
    row = evaluate(truth(),
                   [detection(0, [100, 50, 80, 120])])
    assert row['class_confusion']['tp']['0'] == 1
    ms1_frame = tc.truth_from_two_class_annotation({
        'schema_version': 'dsh.landmark_two_class_annotation.v1',
        'frame_id': 'm.png', 'image': 'images/m.png',
        'image_width': 320, 'image_height': 240,
        'tower_present': False, 'ms1_present': True,
        'instances': [{'class': 1, 'bbox_xyxy': [20.0, 40.0, 60.0, 190.0],
                       'v': 0, 'reference_available': False}]})
    wrong_class = evaluate(ms1_frame,
                           [detection(0, [20, 40, 40, 150])])
    assert wrong_class['class_confusion']['fp']['0'] == 1
    assert wrong_class['class_confusion']['fn']['1'] == 1
    assert wrong_class['class_confusion']['misclassified'] == 1


# --- tower identity claim --------------------------------------------------

def test_tower_identity_precision_recall_and_ms1_wrong_claims():
    protocol = merge_protocol()
    correct = evaluate(truth(), [detection(0, [100, 50, 80, 120])],
                       tower_claim=TOWER)
    ms1_only = tc.truth_from_two_class_annotation({
        'schema_version': 'dsh.landmark_two_class_annotation.v1',
        'frame_id': 'm.png', 'image': 'images/m.png', 'image_width': 320,
        'image_height': 240, 'tower_present': False, 'ms1_present': True,
        'instances': [{'class': 1, 'bbox_xyxy': [20.0, 40.0, 60.0, 190.0],
                       'v': 0, 'reference_available': False}]})
    wrong = evaluate(ms1_only, [detection(1, [20, 40, 40, 150])],
                     tower_claim=TOWER)
    class1_mapped = evaluate(ms1_only, [detection(1, [20, 40, 40, 150])],
                             tower_claim=TOWER)
    assert correct['tower_claim_correct'] is True
    assert wrong['tower_claim'] is True
    assert wrong['wrong_claim'] is True
    assert wrong['wrong_claim_category'] == 'MS1_ONLY'
    summary = tc.summarize([correct, wrong, class1_mapped], protocol=protocol,
                           identity_policy='confirmed_only')
    assert summary['identity']['claims'] == 3
    assert summary['identity']['correct_claims'] == 1
    assert summary['identity']['wrong_claims'] == 2
    assert summary['identity']['wrong_claim_categories']['MS1_ONLY'] == 2
    assert summary['identity']['ms1_only_frames'] == 2  # same frame scored twice in this unit test


# --- same-frame target selection ------------------------------------------

def test_same_frame_target_selection_rate():
    protocol = merge_protocol()
    both = truth(tower=True, ms1=([20.0, 40.0, 40.0, 150.0],))
    selected = evaluate(both, [detection(0, [100, 50, 80, 120]),
                               detection(1, [20, 40, 40, 150])],
                        tower_claim=TOWER)
    picked_ms1 = evaluate(both, [detection(1, [20, 40, 40, 150])],
                          tower_claim=TOWER)
    refused = evaluate(both, [detection(0, [100, 50, 80, 120])],
                       tower_claim=None)
    summary = tc.summarize([selected, picked_ms1, refused], protocol=protocol,
                           identity_policy='confirmed_only')
    same = summary['same_frame']
    assert same['denominator'] == 3
    assert same['tower_selected'] == 1
    assert same['ms1_selected'] == 1
    assert same['not_selected'] == 1
    assert same['tower_selection_rate'] == pytest.approx(1 / 3)


# --- reference / bearing / consumer success --------------------------------

def test_reference_handling_and_bearing_for_class0():
    protocol = merge_protocol()
    visible = evaluate(truth(), [detection(0, [100, 50, 80, 120])],
                       tower_claim=TOWER)
    assert visible['reference_correct'] is True
    assert visible['bearing_error_deg'] == pytest.approx(0.0)
    far = evaluate(truth(), [detection(0, [100, 50, 80, 120],
                                       keypoint=(155.0, 71.0))],
                   tower_claim=TOWER)
    assert far['bearing_error_deg'] > 3.0
    assert far['bearing_ok'] is False
    unavailable = evaluate(truth(reference='UNAVAILABLE'),
                           [detection(0, [100, 50, 80, 120], keypoint=None)],
                           tower_claim=TOWER)
    assert unavailable['reference_correct'] is True
    false_ref = evaluate(truth(reference='UNAVAILABLE'),
                         [detection(0, [100, 50, 80, 120])], tower_claim=TOWER)
    assert false_ref['false_reference'] is True


def test_consumer_success_all_positive_and_negatives_keep_unknowns():
    protocol = merge_protocol()
    good = evaluate(truth(), [detection(0, [100, 50, 80, 120])],
                    tower_claim=TOWER)
    unobservable = tc.truth_from_two_class_annotation({
        'schema_version': 'dsh.landmark_two_class_annotation.v1',
        'frame_id': 'o.png', 'image': 'images/o.png', 'image_width': 320,
        'image_height': 240, 'tower_present': True, 'ms1_present': False,
        'occluded': True, 'instances': []})
    unknown = evaluate(unobservable, [], tower_claim=None)
    negative = tc.truth_from_two_class_annotation({
        'schema_version': 'dsh.landmark_two_class_annotation.v1',
        'frame_id': 'n.png', 'image': 'images/n.png', 'image_width': 320,
        'image_height': 240, 'tower_present': False, 'ms1_present': False,
        'instances': []})
    negative_ok = evaluate(negative, [], tower_claim=None)
    summary = tc.summarize([good, unknown, negative_ok], protocol=protocol,
                           identity_policy='confirmed_only')
    assert summary['domains']['all_positive']['denominator'] == 2
    assert summary['domains']['all_positive']['success'] == 1
    assert summary['domains']['observable_positive']['denominator'] == 1
    assert summary['domains']['negatives']['success'] == 1
    assert summary['gt_unobservable']['frames'] == 1
    assert summary['gt_unobservable']['tower_claims'] == 0


def test_gt_uncertain_and_occluded_do_not_receive_improper_claims():
    protocol = merge_protocol()
    uncertain = evaluate(truth(uncertain=True),
                         [detection(0, [100, 50, 80, 120])],
                         tower_claim=TOWER)
    assert uncertain['gt_uncertain'] is True
    assert uncertain['improper_claim'] is True
    occluded = tc.truth_from_two_class_annotation({
        'schema_version': 'dsh.landmark_two_class_annotation.v1',
        'frame_id': 'o.png', 'image': 'images/o.png', 'image_width': 320,
        'image_height': 240, 'tower_present': True, 'ms1_present': False,
        'occluded': True, 'gt_uncertainty': False, 'instances': []})
    improper = evaluate(occluded, [detection(0, [100, 50, 80, 120])],
                        tower_claim=TOWER)
    assert improper['gt_unobservable'] is True
    assert improper['improper_claim'] is True
    summary = tc.summarize([uncertain, improper], protocol=protocol,
                           identity_policy='confirmed_only')
    assert summary['gt_uncertain']['frames'] == 1
    assert summary['gt_uncertain']['improper_claims'] == 1
    assert summary['gt_unobservable']['improper_claims'] == 1


# --- summarization / baseline comparison / CLI -----------------------------

def test_summarize_reports_per_class_and_confusion_matrix():
    protocol = merge_protocol()
    tower_row = evaluate(truth(), [detection(0, [100, 50, 80, 120])],
                         tower_claim=TOWER)
    ms1_truth = tc.truth_from_two_class_annotation({
        'schema_version': 'dsh.landmark_two_class_annotation.v1',
        'frame_id': 'm.png', 'image': 'images/m.png', 'image_width': 320,
        'image_height': 240, 'tower_present': False, 'ms1_present': True,
        'instances': [{'class': 1, 'bbox_xyxy': [20.0, 40.0, 60.0, 190.0],
                       'v': 0, 'reference_available': False}]})
    ms1_row = evaluate(ms1_truth, [detection(1, [20, 40, 40, 150])])
    summary = tc.summarize([tower_row, ms1_row], protocol=protocol,
                           identity_policy='confirmed_only')
    assert summary['classes']['0']['tp'] == 1
    assert summary['classes']['1']['tp'] == 1
    assert summary['classes']['0']['recall'] == pytest.approx(1.0)
    assert summary['classes']['1']['recall'] == pytest.approx(1.0)
    assert summary['confusion_matrix']['gt_0_pred_0'] == 1
    assert summary['confusion_matrix']['gt_1_pred_1'] == 1


def test_baseline_comparison_reports_same_denominator_deltas():
    protocol = merge_protocol()
    row = evaluate(truth(), [detection(0, [100, 50, 80, 120])],
                   tower_claim=TOWER)
    single = tc.summarize([row], protocol=protocol,
                          identity_policy='raw_claim_upper_bound')
    two = tc.summarize([row], protocol=protocol, identity_policy='confirmed_only')
    comparison = tc.compare_summaries(single, two)
    assert comparison['single_class']['domains']['all_positive']['denominator'] == 1
    assert comparison['two_class']['domains']['all_positive']['denominator'] == 1
    assert 'domains' in comparison['delta']
    assert 'tower_class_recall' in comparison['single_class']['classes']


def test_cli_writes_metrics_and_refuses_overwrite(tmp_path):
    labels = {'schema_version': 'dsh.landmark_two_class_annotation.v1',
              'annotations': [{
                  'schema_version': 'dsh.landmark_two_class_annotation.v1',
                  'frame_id': 'a.png', 'image': 'images/a.png',
                  'image_width': 320, 'image_height': 240,
                  'tower_present': True, 'ms1_present': False,
                  'instances': [{'class': 0,
                                 'bbox_xyxy': [100.0, 50.0, 180.0, 170.0],
                                 'keypoint_x': 142.0, 'keypoint_y': 71.0,
                                 'v': 1, 'reference_available': True}]}]}
    labels_path = tmp_path / 'labels.json'
    labels_path.write_text(json.dumps(labels), encoding='utf-8')
    predictions = [{'frame_id': 'a.png', 'detections': [
        detection(0, [100, 50, 80, 120])], 'landmark_id': TOWER}]
    preds_path = tmp_path / 'predictions.jsonl'
    preds_path.write_text(''.join(json.dumps(r) + '\n' for r in predictions),
                          encoding='utf-8')
    protocol_path = tmp_path / 'protocol.json'
    protocol_path.write_text(json.dumps(protocol_doc()), encoding='utf-8')
    out = tmp_path / 'out'
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / 'scripts' / 'evaluate_landmark_two_class.py'),
         '--labels', str(labels_path), '--predictions', str(preds_path),
         '--protocol', str(protocol_path), '--output-dir', str(out)],
        cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert (out / 'two_class_metrics.json').is_file()
    assert (out / 'rows.jsonl').is_file()
    again = subprocess.run(
        [sys.executable, str(REPO_ROOT / 'scripts' / 'evaluate_landmark_two_class.py'),
         '--labels', str(labels_path), '--predictions', str(preds_path),
         '--protocol', str(protocol_path), '--output-dir', str(out)],
        cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert again.returncode == 3


# --- frozen eval-document flags (B2: canonical denominators) ----------------

def _frozen_frame(**overrides):
    frame_id = overrides.pop('frame_id')
    frame = {
        'schema_version': 'dsh.landmark_two_class_annotations.v1',
        'frame_id': frame_id,
        'image': 'images/' + frame_id,
        'image_width': 320, 'image_height': 240,
        'tower_present': False, 'tower_observable': False,
        'gt_unobservable': False, 'negative': False,
        'ms1_present': False, 'ms1_only': False, 'same_frame': False,
        'instances': [],
    }
    frame.update(overrides)
    return frame


def test_frozen_doc_flags_are_consumed_canonically():
    frames = [
        _frozen_frame(frame_id='obs.png', tower_present=True,
                      tower_observable=True, instances=[
                          {'class': 0, 'bbox_xyxy': [100.0, 50.0, 180.0, 170.0],
                           'keypoint_x': 142.0 / 320.0,
                           'keypoint_y': 71.0 / 240.0, 'v': 1,
                           'reference_available': True}]),
        _frozen_frame(frame_id='present_unobs.png', tower_present=True,
                      gt_unobservable=True),
        _frozen_frame(frame_id='absent_unknown.png', tower_present=False,
                      gt_unobservable=True, negative=False),
        _frozen_frame(frame_id='negative.png', tower_present=False,
                      negative=True),
        _frozen_frame(frame_id='ms1_only.png', ms1_present=True,
                      ms1_only=True, negative=False, instances=[
                          {'class': 1, 'bbox_xyxy': [20.0, 40.0, 60.0, 190.0],
                           'v': 0, 'reference_available': False}]),
    ]
    rows = [tc.truth_from_two_class_annotation(frame) for frame in frames]
    assert sum(1 for r in rows if r['tower_observable']) == 1
    assert sum(1 for r in rows if r['gt_unobservable']) == 2
    assert sum(1 for r in rows if r['negative']) == 1
    assert sum(1 for r in rows if r['ms1_only']) == 1
    protocol = merge_protocol()
    summary = tc.summarize([tc.evaluate_frame(r, {'frame_id': r['frame_id'],
                                                 'status': 'NOT_DETECTED',
                                                 'detections': []}, protocol)
                            for r in rows], protocol=protocol)
    assert summary['counts']['frames'] == 5
    assert summary['counts']['negatives'] == 1
    assert summary['identity']['ms1_only_frames'] == 1
    assert summary['identity']['wrong_claim_denominator'] == 2
    assert summary['gt_unobservable']['frames'] == 2
    assert summary['domains']['observable_positive']['denominator'] == 1


FROZEN_UNION = (REPO_ROOT / 'outputs/perception/two_class_eval_20261105/'
                'p2_smoke/labels_union_eval_frozen.json')


@pytest.mark.skipif(not FROZEN_UNION.is_file(),
                    reason='frozen P2 union eval document absent')
def test_frozen_union_loader_counts_match_doc_flags():
    document, rows = tc.load_two_class_labels(FROZEN_UNION)
    flags = {
        'tower_present_observable': sum(1 for f in document['frames']
                                        if f.get('tower_observable')),
        'gt_unobservable': sum(1 for f in document['frames']
                               if f.get('gt_unobservable')),
        'negatives': sum(1 for f in document['frames'] if f.get('negative')),
        'same_frame': sum(1 for f in document['frames'] if f.get('same_frame')),
        'ms1_only': sum(1 for f in document['frames'] if f.get('ms1_only')),
    }
    loaded = {
        'tower_present_observable': sum(1 for r in rows if r['tower_observable']),
        'gt_unobservable': sum(1 for r in rows if r['gt_unobservable']),
        'negatives': sum(1 for r in rows if r['negative']),
        'same_frame': sum(1 for r in rows if r['same_frame']),
        'ms1_only': sum(1 for r in rows if r['ms1_only']),
    }
    assert loaded == flags == {'tower_present_observable': 139,
                               'gt_unobservable': 38, 'negatives': 39,
                               'same_frame': 73, 'ms1_only': 9}

# --- GT isolation / class1 scope -------------------------------------------

def test_decode_rejects_ground_truth_argument_and_is_rename_independent():
    detections = [detection(0, [100, 50, 80, 120])]
    protocol = merge_protocol()
    tower_named = tc.decode_detections(detections, 'tower_visible.png', protocol)
    ms1_named = tc.decode_detections(detections, 'ms1_confuser_fake.png', protocol)
    tower_named.pop('frame_id')
    ms1_named.pop('frame_id')
    assert tower_named == ms1_named
    with pytest.raises(tc.TwoClassEvalError):
        tc.decode_detections(detections, truth(), protocol)


def test_gt_poison_does_not_change_inference_observations():
    class Boxes:
        xyxy = [[100.0, 50.0, 180.0, 170.0]]
        conf = [0.9]
        cls = [0.0]
        def __len__(self):
            return 1
    class Keypoints:
        xy = [[[142.0, 71.0]]]
        conf = [[0.9]]
        def __len__(self):
            return 1
    class Result:
        boxes = Boxes()
        keypoints = Keypoints()
    class Model:
        def predict(self, **kwargs):
            return [Result()]
    protocol = merge_protocol()
    clean = [truth(frame_id='p.png')]
    poisoned = [truth(frame_id='p.png', tower=False,
                      ms1=([20.0, 40.0, 40.0, 150.0],),
                      tower_bbox=(1.0, 1.0, 2.0, 2.0),
                      keypoint=(5.0, 5.0), reference='UNAVAILABLE')]
    resolver = lambda row: Path(__file__)
    clean_obs = tc.infer_observations(Model(), clean, None, protocol,
                                      image_resolver=resolver)
    poisoned_obs = tc.infer_observations(Model(), poisoned, None, protocol,
                                         image_resolver=resolver)
    assert clean_obs == poisoned_obs


def test_inference_and_decode_source_are_structurally_gt_free():
    source = (REPO_ROOT / 'src/boom_birds/evaluation/landmark_two_class_eval.py'
              ).read_text(encoding='utf-8')

    def block(name, next_name):
        start = source.index('def ' + name)
        end = source.index('def ' + next_name)
        return source[start:end]

    decode = block('decode_detections', 'single_class_predictions_to_observations')
    adapter = block('detections_from_ultralytics_result', '_default_image')
    infer = block('infer_observations', 'evaluate_saved')
    for name, body in (('decode', decode), ('adapter', adapter), ('infer', infer)):
        for token in ('gt_tower', 'gt_ms1', 'gt_other', 'ground_truth',
                      'oracle', 'target_world'):
            assert token not in body, (name, token)


def test_class1_gt_is_only_map_native_ms1_other_structures_separate():
    synthetic = tc.truth_from_two_class_annotation({
        'schema_version': 'dsh.landmark_two_class_annotation.v1',
        'frame_id': 'synthetic.png', 'image': 'images/synthetic.png',
        'image_width': 320, 'image_height': 240,
        'tower_present': False, 'ms1_present': False,
        'instances': [{'class': 1, 'bbox_xyxy': [20.0, 40.0, 60.0, 190.0],
                       'structure_kind': 'SYNTHETIC_INJECTED',
                       'v': 0, 'reference_available': False}]})
    assert synthetic['gt_ms1_boxes'] == []
    assert synthetic['gt_other_boxes'] == [[20.0, 40.0, 40.0, 150.0]]
    protocol = merge_protocol()
    row = evaluate(synthetic, [detection(0, [20, 40, 40, 150])],
                   tower_claim=TOWER)
    assert row['wrong_claim_category'] == 'OTHER_STRUCTURE'
    summary = tc.summarize([row], protocol=protocol,
                           identity_policy='confirmed_only')
    assert summary['classes']['1']['gt_instances'] == 0
    assert summary['other_structures']['frames'] == 1
    assert summary['other_structures']['wrong_claims'] == 1

# --- real 62-frame identity pool with frozen single-class baseline ---------

IDENTITY_LABELS = REPO_ROOT / 'outputs/perception/dev_annotations_20261104/labels_identity_dev.json'
IDENTITY_DECISIONS = REPO_ROOT / 'outputs/perception/dev_annotations_20261104/identity/identity_decisions.json'
SINGLE_CLASS_PREDS = REPO_ROOT / 'outputs/perception/consumer_eval_20261104/identity_baseline/predictions.jsonl'


@pytest.mark.skipif(not (IDENTITY_LABELS.is_file() and IDENTITY_DECISIONS.is_file()
                         and SINGLE_CLASS_PREDS.is_file()),
                    reason='development identity pool / single-class predictions absent')
def test_frozen_single_class_baseline_on_two_class_denominators():
    truth_rows = tc.build_truth_from_identity_pool(IDENTITY_LABELS,
                                                   IDENTITY_DECISIONS)
    assert len(truth_rows) == 62
    tower_rows = [row for row in truth_rows if row['tower_present']]
    ms1_rows = [row for row in truth_rows if row['ms1_present']]
    same_rows = [row for row in truth_rows if row['same_frame']]
    assert len(tower_rows) == 53
    assert len(ms1_rows) == 35
    assert len(same_rows) == 26
    predictions = {}
    for line in SINGLE_CLASS_PREDS.read_text(encoding='utf-8').splitlines():
        if line.strip():
            record = json.loads(line)
            predictions[record['frame_id']] = record
    observations = tc.single_class_predictions_to_observations(predictions)
    protocol = tc.load_protocol(PROTOCOL_PATH)
    result = tc.evaluate_rows(truth_rows, observations, protocol,
                              identity_policy='raw_claim_upper_bound')
    summary = result['summary']
    # single-class baseline cannot detect class 1 at all
    assert summary['classes']['1']['tp'] == 0
    assert summary['classes']['1']['recall'] == 0.0
    assert summary['identity']['ms1_only_frames'] == 9
    assert summary['same_frame']['denominator'] == 26
    assert summary['reference']['unavailable_denominator'] > 0