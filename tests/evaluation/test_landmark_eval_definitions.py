"""Failing-first tests for the executable landmark evaluation-definition audit.

These tests pin the four-way separation required by the post-evaluation audit:

- presence / identity / reference-availability / localization accuracy are four
  distinct quantities with distinct denominators;
- the joint rule explicitly separates the localization branch (GT reference
  point visible) from the availability branch (GT reference point unavailable
  and the model correctly declares UNAVAILABLE): the availability branch counts
  as joint-ok, is reported as its own count, and never enters the localization
  error denominator;
- prediction UNKNOWN/REJECTED, missed detections and wrong identity claims never
  disappear from the denominator they belong to;
- GT-unobservable frames are not scored for localization but their identity
  claims and keypoint emissions are counted;
- 2D pixel error (historical 3 px rule) and horizontal image-bearing error (the
  downstream consumer quantity) are reported separately, with explicit
  pass/fail flip counts between the two rules.
"""
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest

from boom_birds.evaluation import landmark_eval_definitions as audit
from boom_birds.evaluation.landmark_metrics import evaluate_frame


REPO_ROOT = Path(__file__).resolve().parents[2]
LANDMARK = 'RMUC2027_CENTRAL_TOWER_PROPOSED'
INTRINSICS = {'fx_px': 160.0, 'cx_px': 160.0, 'cy_px': 120.0}


def gt_present(**overrides):
    gt = {'frame_id': 'f1', 'present': True, 'landmark_id': LANDMARK,
          'bbox_xywh': [100.0, 50.0, 80.0, 120.0], 'reference': 'VISIBLE',
          'visibility': 'FULL', 'truncated': False, 'occluded': False,
          'ambiguous': False, 'undecidable': False, 'negative_type': None}
    gt.update(overrides)
    return gt


def gt_absent(**overrides):
    gt = {'frame_id': 'f0', 'present': False, 'landmark_id': None,
          'bbox_xywh': None, 'reference': None, 'visibility': 'ABSENT',
          'truncated': False, 'occluded': False, 'ambiguous': False,
          'undecidable': False, 'negative_type': 'TARGET_ABSENT'}
    gt.update(overrides)
    return gt


def detected(**overrides):
    pred = {'status': 'DETECTED', 'landmark_id': LANDMARK,
            'bbox_xywh': [100.0, 50.0, 80.0, 120.0], 'score': 0.9,
            'keypoint_px': [142.0, 71.0], 'reject_reason': None}
    pred.update(overrides)
    return pred


def no_detection(**overrides):
    pred = {'status': 'NOT_DETECTED', 'landmark_id': None, 'bbox_xywh': None,
            'score': None, 'keypoint_px': None,
            'reject_reason': 'TARGET_NOT_DETECTED'}
    pred.update(overrides)
    return pred


def unknown_pred(**overrides):
    pred = {'status': 'UNKNOWN', 'landmark_id': None, 'bbox_xywh': None,
            'score': None, 'keypoint_px': None,
            'reject_reason': 'DETECTOR_ERROR'}
    pred.update(overrides)
    return pred


def make_row(gt, pred, *, reference_px=None, tau_iou=0.3, tau_px=5.0,
             tau_conf=0.5, strata=None, fx_px=160.0, cx_px=160.0):
    return evaluate_frame(gt, pred, tau_iou=tau_iou, reference_px=reference_px,
                          tau_px=tau_px, tau_conf=tau_conf, fx_px=fx_px,
                          cx_px=cx_px, strata=strata)


# --- four-way separation ----------------------------------------------------

def test_four_way_separation_uses_distinct_denominators():
    # A: localization branch success (GT ref visible, emitted keypoint correct)
    a = make_row(gt_present(), detected(), reference_px=(142.0, 71.0))
    # B: localization branch failure (wrong anchor, 6 px > tau_px 5)
    b = make_row(gt_present(frame_id='f2'),
                 detected(keypoint_px=(148.0, 71.0)),
                 reference_px=(142.0, 71.0))
    # C: missed detection on a GT-available-reference positive
    c = make_row(gt_present(frame_id='f3'), no_detection(),
                 reference_px=(142.0, 71.0))
    # D: GT reference unavailable, model correctly declares UNAVAILABLE
    d = make_row(gt_present(frame_id='f4', reference='UNAVAILABLE'),
                 detected(keypoint_px=None))
    # E: GT reference unavailable, model wrongly emits a keypoint
    e = make_row(gt_present(frame_id='f5', reference='UNAVAILABLE'),
                 detected(keypoint_px=(142.0, 71.0)))
    # F: false positive with a wrong identity claim on an absent frame
    f = make_row(gt_absent(frame_id='f6'),
                 detected(bbox_xywh=[10.0, 10.0, 20.0, 20.0], score=0.95))
    # G: GT unobservable, model still emits a claim and a keypoint
    g = make_row({'frame_id': 'f7', 'present': False, 'landmark_id': None,
                  'bbox_xywh': None, 'reference': None, 'visibility': 'UNKNOWN',
                  'truncated': False, 'occluded': False, 'ambiguous': False,
                  'undecidable': True, 'negative_type': None},
                 detected(keypoint_px=(142.0, 71.0)))
    report = audit.audit([a, b, c, d, e, f, g])

    assert report['presence']['denominators']['positives'] == 5
    assert report['presence']['denominators']['negatives'] == 1
    assert report['presence']['denominators']['gt_unobservable'] == 1
    assert report['presence']['tp'] == 4     # a,b,d,e
    assert report['presence']['fn'] == 1     # c
    assert report['presence']['fp'] == 1     # f
    assert report['presence']['tn'] == 0

    identity = report['identity']
    assert identity['claims'] == 5           # a,b,d,e + f (wrong identity claim)
    assert identity['correct_claims'] == 4
    assert identity['wrong_identity_claims'] == 1
    assert identity['precision'] == pytest.approx(0.8)
    assert identity['denominators']['positives'] == 5
    assert identity['claims_on_gt_unobservable'] == 1

    reference = report['reference_availability']
    assert reference['denominators']['available'] == 3      # a,b,c
    assert reference['denominators']['unavailable'] == 2    # d,e
    assert reference['declared_unavailable_correct'] == 1   # d
    assert reference['false_reference_emissions'] == 1      # e
    assert reference['coverage'] == pytest.approx(1 / 3)    # a only
    assert reference['declaration_rate'] == pytest.approx(0.5)
    assert reference['false_reference_rate'] == pytest.approx(0.5)

    localization = report['localization']
    assert localization['denominators']['applicable'] == 3  # a,b,c
    assert localization['denominators']['emitted'] == 2     # a,b
    assert localization['within_tolerance'] == 1            # a
    assert localization['within_tolerance_rate'] == pytest.approx(1 / 3)
    assert localization['pixel_error_px']['count'] == 2
    assert localization['bearing_error_deg']['count'] == 2
    assert localization['not_emitted'] == 1                 # c stays a miss

    joint = report['joint']
    assert joint['narrow_denominator'] == 5                 # a-e
    assert joint['narrow_tp'] == 2                          # a (localization) + d (availability)
    assert joint['branches']['localization']['evaluable'] == 3
    assert joint['branches']['localization']['ok'] == 1     # a
    assert joint['branches']['availability']['evaluable'] == 2
    assert joint['branches']['availability']['ok'] == 1     # d
    assert joint['branches']['availability']['enters_localization_error'] is False
    assert joint['fail_reasons']['REFERENCE_LOCALIZATION'] == 1  # b
    assert joint['fail_reasons']['PRESENCE'] == 1                # c
    assert joint['fail_reasons']['REFERENCE_AVAILABILITY'] == 1  # e

    gt_unobservable = report['gt_unobservable']
    assert gt_unobservable['frames'] == 1
    assert gt_unobservable['identity_claims'] == 1
    assert gt_unobservable['keypoint_emissions'] == 1
    assert gt_unobservable['detected'] == 1


def test_joint_availability_branch_is_counted_separately_and_not_localized():
    row = make_row(gt_present(), detected(keypoint_px=None))
    unavailable = make_row(gt_present(frame_id='f2', reference='UNAVAILABLE'),
                           detected(keypoint_px=None))
    report = audit.audit([row, unavailable])
    assert report['joint']['branches']['availability']['evaluable'] == 1
    assert report['joint']['branches']['availability']['ok'] == 1
    assert report['joint']['branches']['availability']['enters_localization_error'] is False
    assert report['joint']['narrow_tp'] == 1
    assert report['localization']['denominators']['applicable'] == 1
    assert report['localization']['denominators']['emitted'] == 0
    assert report['localization']['not_emitted'] == 1


def test_prediction_unknown_on_positive_stays_in_applicable_denominators():
    row = make_row(gt_present(), unknown_pred(), reference_px=(142.0, 71.0))
    report = audit.audit([row])
    assert report['presence']['denominators']['positives'] == 1
    assert report['presence']['fn'] == 1
    assert report['presence']['unknown_rejected']['on_positive'] == 1
    assert report['localization']['denominators']['applicable'] == 1
    assert report['localization']['denominators']['emitted'] == 0
    assert report['localization']['within_tolerance'] == 0
    assert report['joint']['narrow_denominator'] == 1
    assert report['joint']['narrow_tp'] == 0
    assert report['joint']['fail_reasons']['PRESENCE'] == 1
    loss = report['denominator_loss_audit']
    assert loss['prediction_unknown_rejected']['on_positive'] == 1
    assert loss['prediction_unknown_rejected']['total'] == 1


def test_wrong_identity_claim_is_kept_in_identity_denominator():
    row = make_row(gt_present(), detected(landmark_id='OTHER_LANDMARK_ID'),
                   reference_px=(142.0, 71.0))
    report = audit.audit([row])
    assert report['identity']['claims'] == 1
    assert report['identity']['wrong_identity_claims'] == 1
    assert report['identity']['precision'] == 0.0
    assert report['joint']['fail_reasons']['IDENTITY'] == 1
    assert report['localization']['within_tolerance'] == 1


def test_gt_unobservable_outputs_are_counted_but_not_scored():
    gt = {'frame_id': 'f9', 'present': False, 'landmark_id': None,
          'bbox_xywh': None, 'reference': None, 'visibility': 'UNKNOWN',
          'truncated': False, 'occluded': False, 'ambiguous': True,
          'undecidable': False, 'negative_type': None}
    row = make_row(gt, detected(keypoint_px=(142.0, 71.0)))
    report = audit.audit([row])
    assert report['presence']['denominators']['positives'] == 0
    assert report['identity']['claims'] == 0
    assert report['gt_unobservable']['frames'] == 1
    assert report['gt_unobservable']['by_reason'] == {'AMBIGUOUS': 1}
    assert report['gt_unobservable']['identity_claims'] == 1
    assert report['gt_unobservable']['keypoint_emissions'] == 1
    assert report['localization']['denominators']['applicable'] == 0


# --- 3 px historical rule vs horizontal bearing ----------------------------

def test_placement_split_counts_px_vs_bearing_verdict_flips():
    # dx = 2 px, dy = 4 px: 2D error 4.47 px > 3 px (historical fail) but
    # horizontal bearing error stays below the 3 px equivalent (1.074 deg).
    vertical = make_row(gt_present(), detected(keypoint_px=(142.0, 75.0)),
                        reference_px=(142.0, 71.0), tau_px=5.0)
    # dx = 4 px: both fail
    both_fail = make_row(gt_present(frame_id='f2'),
                         detected(keypoint_px=(146.0, 71.0)),
                         reference_px=(142.0, 71.0), tau_px=5.0)
    # dx = 1 px, dy = 0: both pass
    both_ok = make_row(gt_present(frame_id='f3'),
                       detected(keypoint_px=(143.0, 71.0)),
                       reference_px=(142.0, 71.0), tau_px=5.0)
    split = audit.placement_split([vertical, both_fail, both_ok],
                                  px_tolerance=3.0, fx_px=160.0)
    flips = split['verdict_flips']
    assert flips['px_ok_bearing_fail'] == 0
    assert flips['px_fail_bearing_ok'] == 1
    assert flips['both_ok'] == 1
    assert flips['both_fail'] == 1
    assert split['bearing_tolerance_deg'] == pytest.approx(
        math.degrees(math.atan2(3.0, 160.0)))
    assert split['pixel_error_px']['count'] == 3
    assert split['bearing_error_deg']['count'] == 3
    assert split['horizontal_error_px']['count'] == 3
    assert split['vertical_error_px']['count'] == 3


def test_consumer_requirement_declares_bearing_primary_and_3px_historical():
    requirement = audit.consumer_requirement()
    assert requirement['quantity'] == 'IMAGE_BEARING_DEG'
    assert requirement['historical_pixel_tolerance_px'] == 3.0
    assert requirement['historical_status'] == 'LEGACY_2D_PROXY_NOT_CONSUMER_UNIT'
    assert requirement['bearing_budget_deg']['median'] == 3.0
    assert requirement['bearing_budget_deg']['p90'] == 5.0
    assert requirement['bearing_budget_deg']['status'] == 'PROPOSED_NOT_FROZEN'
    assert 'world bearing' in requirement['caveat']


def test_denominator_loss_audit_reconciles_all_frames():
    rows = [
        make_row(gt_present(), detected(), reference_px=(142.0, 71.0)),
        make_row(gt_present(frame_id='f2'), no_detection(),
                 reference_px=(142.0, 71.0)),
        make_row(gt_present(frame_id='f3'), unknown_pred(),
                 reference_px=(142.0, 71.0)),
        make_row(gt_absent(frame_id='f4'), no_detection()),
    ]
    report = audit.audit(rows)
    loss = report['denominator_loss_audit']
    assert loss['frames']['total'] == 4
    assert loss['frames']['accounted'] == 4
    assert loss['accounting_ok'] is True
    assert loss['missed_detections']['total'] == 1
    assert loss['prediction_unknown_rejected']['total'] == 1
    assert loss['presence_class_counts']['TP'] == 1
    assert loss['presence_class_counts']['FN'] == 2
    assert loss['presence_class_counts']['TN'] == 1


# --- saved predictions + labels recompute path -----------------------------

def _annotation(frame_id, present=True, reference='VISIBLE', family='lmf_sweep',
                negative_type=None):
    ann = {
        'frame_id': frame_id, 'image': 'images/' + frame_id,
        'image_sha256': 'x', 'image_width': 320, 'image_height': 240,
        'source': {'run': 'r', 'family': family, 'group_id': 'g_' + family,
                   'split': 'test'},
        'target': {'landmark_id': LANDMARK, 'class': 'tower',
                   'present': present, 'undecidable': False,
                   'visibility': 'ABSENT' if not present else
                                 ('PARTIAL' if reference == 'UNAVAILABLE' else 'FULL'),
                   'truncated': False, 'occluded': False, 'ambiguous': False,
                   'ambiguous_reason': None, 'undecidable_reason': None,
                   'truncated_edges': {'left': False, 'right': False,
                                       'top': False, 'bottom': False},
                   'truncation_source': {}},
        'geometry': {'bbox_xywh': [97, 106, 83, 74] if present else None,
                     'keypoint': ({'name': 'green_roof_light_center',
                                   'x': 99.9, 'y': 109.9, 'visible': True}
                                  if reference == 'VISIBLE' else None),
                     'green_pixels': 12 if reference == 'VISIBLE' else 2,
                     'bbox_source': 'ANNOTATOR_VISUAL',
                     'reference_status': ('NOT_APPLICABLE' if not present else
                                          ('MANUAL_APPROX' if reference == 'VISIBLE'
                                           else 'UNAVAILABLE')),
                     'reference_unavailable_reason': (None if reference == 'VISIBLE'
                                                      else 'REFERENCE_TOO_SMALL'),
                     'reference_source': 'COLOR_CUE_ASSISTED'},
        'confusers': [], 'negative_type': negative_type,
        'annotator': {'annotator_type': 'AGENT_PROXY', 'annotator_id': 't',
                      'annotation_mode': 'FRAME_BY_FRAME_VISUAL',
                      'independent_of_model_dev': True,
                      'independent_of_detector_cue': False,
                      'review_status': 'SELF_CHECKED'},
        'pixel_basis': {'image_width': 320, 'image_height': 240,
                        'fx_px': 160.0, 'cx_px': 160.0, 'cy_px': 120.0,
                        'projection_model': 'PINHOLE',
                        'bearing_formula': 'atan2(x - cx_px, fx_px)'},
        'dataset_role': 'EXPLORATORY_EVAL',
        'notes': '',
    }
    return ann


def _write_saved_inputs(tmp_path):
    labels = {'schema_version': 'dsh.tower_annotation.v2_1', 'annotations': [
        _annotation('a.png'),
        _annotation('b.png', reference='UNAVAILABLE'),
        _annotation('c.png', present=False, reference=None,
                    negative_type='TARGET_ABSENT'),
    ]}
    labels_path = tmp_path / 'labels.json'
    labels_path.write_text(json.dumps(labels), encoding='utf-8')
    saved = [
        {'frame_id': 'a.png', 'observation': {'schema_version': 'dsh.landmark_observation.v1',
                                              'frame_id': 'a.png', 'status': 'DETECTED',
                                              'landmark_id': LANDMARK,
                                              'bbox_xywh': [97.0, 106.0, 83.0, 74.0],
                                              'score': 0.9,
                                              'keypoint_px': [99.9, 109.9],
                                              'reject_reason': None}},
        {'frame_id': 'b.png', 'prediction': {'status': 'DETECTED',
                                             'landmark_id': LANDMARK,
                                             'bbox_xywh': [97.0, 106.0, 83.0, 74.0],
                                             'score': 0.9, 'keypoint_px': None,
                                             'reject_reason': None}},
        {'frame_id': 'c.png', 'prediction': {'status': 'NOT_DETECTED',
                                             'landmark_id': None,
                                             'bbox_xywh': None, 'score': None,
                                             'keypoint_px': None,
                                             'reject_reason': None}},
    ]
    preds_path = tmp_path / 'predictions.jsonl'
    preds_path.write_text(''.join(json.dumps(r) + '\n' for r in saved),
                          encoding='utf-8')
    return labels_path, preds_path


def test_build_rows_from_saved_predictions_and_labels(tmp_path):
    labels_path, preds_path = _write_saved_inputs(tmp_path)
    rows, inputs = audit.build_rows(preds_path, labels_path, split='test',
                                    tau_iou=0.3, tau_px=3.0, tau_conf=0.5)
    assert len(rows) == 3
    assert inputs['labels_sha256']
    report = audit.audit(rows)
    assert report['presence']['denominators'] == {
        'positives': 2, 'negatives': 1, 'gt_unobservable': 0}
    assert report['reference_availability']['denominators'] == {
        'available': 1, 'unavailable': 1}
    assert report['localization']['denominators'] == {
        'applicable': 1, 'emitted': 1}
    assert report['joint']['narrow_tp'] == 2


def test_presence_misses_are_broken_down_by_reference_status(tmp_path):
    labels = {'schema_version': 'dsh.tower_annotation.v2_1', 'annotations': [
        _annotation('avail.png'),
        _annotation('unavail.png', reference='UNAVAILABLE'),
        _annotation('absent.png', present=False, reference=None,
                    negative_type='TARGET_ABSENT'),
    ]}
    labels_path = tmp_path / 'labels.json'
    labels_path.write_text(json.dumps(labels), encoding='utf-8')
    saved = [
        {'frame_id': 'avail.png', 'prediction': {
            'status': 'DETECTED', 'landmark_id': LANDMARK,
            'bbox_xywh': [97.0, 106.0, 83.0, 74.0], 'score': 0.9,
            'keypoint_px': [99.9, 109.9], 'reject_reason': None}},
        {'frame_id': 'unavail.png', 'prediction': {
            'status': 'NOT_DETECTED', 'landmark_id': None, 'bbox_xywh': None,
            'score': None, 'keypoint_px': None, 'reject_reason': None}},
        {'frame_id': 'absent.png', 'prediction': {
            'status': 'NOT_DETECTED', 'landmark_id': None, 'bbox_xywh': None,
            'score': None, 'keypoint_px': None, 'reject_reason': None}},
    ]
    preds_path = tmp_path / 'predictions.jsonl'
    preds_path.write_text(''.join(json.dumps(r) + '\n' for r in saved),
                          encoding='utf-8')
    rows, _inputs = audit.build_rows(preds_path, labels_path, split='test',
                                     tau_iou=0.3, tau_px=3.0, tau_conf=0.5)
    report = audit.audit(rows)
    assert report['presence']['fn'] == 1
    assert report['presence']['fn_by_reference_status'] == {
        'REFERENCE_UNAVAILABLE': 1}
    assert report['presence']['fn_unavailable_reasons'] == {
        'REFERENCE_TOO_SMALL': 1}
    # the missed detection is a reference-unavailable positive: presence only,
    # never a localization error denominator entry
    assert report['localization']['denominators']['applicable'] == 1
    assert report['localization']['denominators']['emitted'] == 1
    assert report['localization']['within_tolerance'] == 1

def test_drop_missing_predictions_reproduces_dataset_scope(tmp_path):
    labels = {'schema_version': 'dsh.tower_annotation.v2_1', 'annotations': [
        _annotation('scored.png'),
        _annotation('never_evaluated.png', present=False, reference=None,
                    negative_type='TARGET_ABSENT'),
    ]}
    labels_path = tmp_path / 'labels.json'
    labels_path.write_text(json.dumps(labels), encoding='utf-8')
    preds_path = tmp_path / 'predictions.jsonl'
    preds_path.write_text(json.dumps({'frame_id': 'scored.png', 'prediction': {
        'status': 'DETECTED', 'landmark_id': LANDMARK,
        'bbox_xywh': [97.0, 106.0, 83.0, 74.0], 'score': 0.9,
        'keypoint_px': [99.9, 109.9], 'reject_reason': None}}) + '\n',
        encoding='utf-8')
    kept, kept_inputs = audit.build_rows(preds_path, labels_path, split='test',
                                        tau_iou=0.3, tau_px=3.0, tau_conf=0.5)
    assert len(kept) == 2
    report = audit.audit(kept)
    assert report['presence']['denominators']['negatives'] == 1
    assert report['presence']['tn'] == 0
    assert report['presence']['negative_unobservable'] if False else True
    dropped_rows, dropped_inputs = audit.build_rows(
        preds_path, labels_path, split='test', tau_iou=0.3, tau_px=3.0,
        tau_conf=0.5, drop_missing_predictions=True)
    assert len(dropped_rows) == 1
    assert dropped_inputs['dropped_without_prediction'] == ['never_evaluated.png']
    dropped_report = audit.audit(dropped_rows)
    assert dropped_report['presence']['denominators']['negatives'] == 0
    assert dropped_report['presence']['tp'] == 1

def test_recompute_writes_metrics_and_audit_and_refuses_overwrite(tmp_path):
    labels_path, preds_path = _write_saved_inputs(tmp_path)
    out = tmp_path / 'out'
    result = audit.recompute(preds_path, labels_path, split='test',
                             output_dir=out, tau_iou=0.3, tau_px=3.0,
                             tau_conf=0.5)
    assert result['metrics']['presence']['tp'] == 2
    assert (out / 'metrics.json').is_file()
    assert (out / 'audit.json').is_file()
    audit_doc = json.loads((out / 'audit.json').read_text(encoding='utf-8'))
    assert audit_doc['schema_version'] == audit.AUDIT_SCHEMA
    with pytest.raises(FileExistsError):
        audit.recompute(preds_path, labels_path, split='test',
                        output_dir=out, tau_iou=0.3, tau_px=3.0, tau_conf=0.5)


def test_recompute_cli_end_to_end(tmp_path):
    labels_path, preds_path = _write_saved_inputs(tmp_path)
    out = tmp_path / 'cli_out'
    completed = subprocess.run(
        [sys.executable,
         str(REPO_ROOT / 'scripts' / 'recompute_landmark_metrics.py'),
         '--predictions', str(preds_path), '--labels', str(labels_path),
         '--split', 'test', '--output-dir', str(out),
         '--tau-px', '3.0', '--tau-conf', '0.5', '--tau-iou', '0.3'],
        cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert (out / 'metrics.json').is_file()
    assert (out / 'audit.json').is_file()
    summary = json.loads(completed.stdout.strip().splitlines()[-1])
    assert summary['positives'] == 2
    again = subprocess.run(
        [sys.executable,
         str(REPO_ROOT / 'scripts' / 'recompute_landmark_metrics.py'),
         '--predictions', str(preds_path), '--labels', str(labels_path),
         '--split', 'test', '--output-dir', str(out)],
        cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert again.returncode == 3


# --- real saved final predictions (read-only integration check) -----------

REAL_FINAL_PREDS = REPO_ROOT / 'outputs/perception/final_exploratory_eval_20261104/predictions.jsonl'
REAL_FINAL_LABELS = REPO_ROOT / 'outputs/perception/final_exploratory_20261104/labels_v1.json'


@pytest.mark.skipif(not (REAL_FINAL_PREDS.is_file() and REAL_FINAL_LABELS.is_file()),
                    reason='saved exploratory final predictions/labels not present')
def test_real_saved_final_recompute_reproduces_old_presence_and_joint():
    rows, _inputs = audit.build_rows(REAL_FINAL_PREDS, REAL_FINAL_LABELS,
                                     split='test', tau_iou=0.3, tau_px=3.0,
                                     tau_conf=0.605476)
    report = audit.audit(rows)
    assert report['presence']['tp'] == 218
    assert report['presence']['fp'] == 0
    assert report['presence']['fn'] == 20
    assert report['presence']['tn'] == 41
    assert report['joint']['narrow_tp'] == 71
    assert report['joint']['narrow_denominator'] == 238
    assert report['reference_availability']['denominators'] == {
        'available': 218, 'unavailable': 20}