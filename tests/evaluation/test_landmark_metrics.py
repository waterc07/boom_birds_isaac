"""Tests for the pre-training landmark metric definitions (definition only).

These tests pin the denominator rules from
docs/reports/perception/LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md:

- UNKNOWN/REJECTED observations are never counted as TP/FN/TN/FP;
- a target-present frame without a visible reference point is not a reference failure;
- unlabelled reference frames never count as joint failures;
- the joint narrow denominator and the all-positive lower bound are reported together;
- a single-landmark identity metric needs similar-structure negatives to be evaluable.
"""
import pytest

from boom_birds.evaluation.landmark_metrics import (
    evaluate_frame, summarize, MetricDefinitionError)


def present_gt(**overrides):
    gt = {'frame_id': 'f1', 'present': True, 'landmark_id': 'RMUC2027_CENTRAL_TOWER_PROPOSED',
          'bbox_xywh': [100.0, 50.0, 80.0, 120.0], 'reference': 'VISIBLE'}
    gt.update(overrides)
    return gt


def detected(**overrides):
    pred = {'status': 'DETECTED', 'landmark_id': 'RMUC2027_CENTRAL_TOWER_PROPOSED',
            'bbox_xywh': [100.0, 50.0, 80.0, 120.0], 'score': 0.9,
            'keypoint_px': (140.0, 70.0), 'reject_reason': None}
    pred.update(overrides)
    return pred


def absent_gt(**overrides):
    gt = {'frame_id': 'f0', 'present': False, 'landmark_id': None,
          'bbox_xywh': None, 'reference': None}
    gt.update(overrides)
    return gt


def no_detection(**overrides):
    pred = {'status': 'NOT_DETECTED', 'landmark_id': None, 'bbox_xywh': None,
            'score': None, 'keypoint_px': None, 'reject_reason': 'TARGET_NOT_DETECTED'}
    pred.update(overrides)
    return pred


def test_present_detected_with_reference_is_joint_success():
    row = evaluate_frame(present_gt(), detected(), tau_iou=0.3,
                         reference_px=(142.0, 71.0), tau_px=5.0,
                         tau_conf=0.5)
    assert row['presence_class'] == 'TP'
    assert row['reference_class'] == 'PRESENT_AND_AVAILABLE'
    assert row['identity_claim'] is True
    assert row['joint_evaluable'] is True
    assert row['joint_ok'] is True


def test_unknown_observation_is_never_tn_or_fn():
    row = evaluate_frame(present_gt(), {'status': 'UNKNOWN', 'landmark_id': None,
                                        'bbox_xywh': None, 'score': None,
                                        'keypoint_px': None,
                                        'reject_reason': 'DETECTOR_ERROR'},
                         tau_iou=0.3, reference_px=None, tau_px=5.0,
                         tau_conf=0.5)
    assert row['presence_class'] == 'UNOBSERVABLE'
    assert row['counted_in_confusion'] is False
    summary = summarize([row])
    assert summary['presence']['tp'] == 0
    assert summary['presence']['fn'] == 0
    assert summary['presence']['tn'] == 0
    assert summary['presence']['unknown_rejected'] == 1


def test_absent_without_detection_is_tn_and_no_identity_claim():
    row = evaluate_frame(absent_gt(), no_detection(), tau_iou=0.3,
                         reference_px=None, tau_px=5.0, tau_conf=0.5)
    assert row['presence_class'] == 'TN'
    assert row['identity_claim'] is False
    assert row['identity_correct'] is None


def test_absent_with_central_tower_claim_counts_as_high_confidence_false_match():
    pred = detected(bbox_xywh=[10.0, 10.0, 20.0, 20.0], score=0.95)
    row = evaluate_frame(absent_gt(), pred, tau_iou=0.3, reference_px=None,
                         tau_px=5.0, tau_conf=0.5)
    assert row['presence_class'] == 'FP'
    assert row['identity_claim'] is True
    assert row['identity_correct'] is False
    summary = summarize([row])
    assert summary['identity']['high_confidence_false_matches'] == 1
    assert summary['identity']['negative_denominator'] == 1


def test_present_with_unavailable_reference_and_no_keypoint_is_reference_correct():
    row = evaluate_frame(present_gt(reference='UNAVAILABLE'),
                         detected(keypoint_px=None), tau_iou=0.3,
                         reference_px=None, tau_px=5.0, tau_conf=0.5)
    assert row['reference_class'] == 'UNAVAILABLE_DECLARED'
    assert row['reference_correct'] is True
    # reference availability is unobservable here, but joint is still evaluable:
    # the correct UNAVAILABLE declaration is part of joint correctness.
    assert row['joint_evaluable'] is True
    assert row['joint_ok'] is True


def test_present_with_unavailable_reference_but_emitted_keypoint_is_false_reference():
    row = evaluate_frame(present_gt(reference='UNAVAILABLE'),
                         detected(keypoint_px=(140.0, 70.0)), tau_iou=0.3,
                         reference_px=None, tau_px=5.0, tau_conf=0.5)
    assert row['reference_class'] == 'UNAVAILABLE_EMITTED_KEYPOINT'
    assert row['reference_correct'] is False
    assert row['joint_ok'] is False


def test_unlabelled_reference_frame_is_not_a_joint_failure_but_lowers_coverage():
    labelled = evaluate_frame(present_gt(), detected(), tau_iou=0.3,
                              reference_px=(141.0, 71.0), tau_px=5.0,
                              tau_conf=0.5)
    unlabelled = evaluate_frame(present_gt(frame_id='f2', reference=None),
                                detected(), tau_iou=0.3, reference_px=None,
                                tau_px=5.0, tau_conf=0.5)
    assert unlabelled['joint_evaluable'] is False
    assert unlabelled['joint_ok'] is None
    summary = summarize([labelled, unlabelled])
    joint = summary['joint']
    assert joint['narrow_denominator'] == 1
    assert joint['narrow_tp'] == 1
    assert joint['coverage'] == pytest.approx(0.5)
    assert joint['all_positive_lower_bound'] == pytest.approx(0.5)


def test_anchor_error_above_tolerance_fails_reference_and_joint():
    row = evaluate_frame(present_gt(), detected(), tau_iou=0.3,
                         reference_px=(160.0, 70.0), tau_px=5.0,
                         tau_conf=0.5)
    assert row['reference_class'] == 'PRESENT_WRONG_ANCHOR'
    assert row['reference_correct'] is False
    assert row['joint_ok'] is False


def test_missing_required_gt_field_raises():
    with pytest.raises(MetricDefinitionError):
        evaluate_frame({'frame_id': 'x', 'present': True}, detected(),
                       tau_iou=0.3, reference_px=None, tau_px=5.0,
                       tau_conf=0.5)
