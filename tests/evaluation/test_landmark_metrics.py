"""Denominator-audit regression tests for the landmark metric definitions.

These tests pin the corrected denominator rules
(docs/reports/perception/TRAINING_EVAL_TOOLING_20261104.md):

- a prediction of UNKNOWN/REJECTED on a GT-observable positive is a MISS: it
  stays in the recall/coverage/joint denominators and is additionally listed
  by prediction status and reject reason;
- an annotation-side unobservable frame (undecidable / fully occluded without a
  visible box / ambiguous) is excluded from the fourfold and from every
  denominator, and is reported separately as GT_UNOBSERVABLE with a reason;
- GT_UNOBSERVABLE (annotation state) and prediction UNKNOWN (model state) are
  counted in separate buckets and never merged;
- a positive whose GT reference point is unavailable is still presence/recall
  material but is excluded from the anchor/bearing error denominators;
- the joint narrow denominator is the set of GT-observable positives with a
  complete bbox+reference label; a rejected/unknown prediction is a joint
  failure inside that denominator;
- stratified reporting exposes the worst condition with numerator/denominator.
"""
import math

import pytest

from boom_birds.evaluation.landmark_metrics import (
    MetricDefinitionError,
    evaluate_frame,
    stratified_summary,
    summarize,
)


LANDMARK = 'RMUC2027_CENTRAL_TOWER_PROPOSED'


def present_gt(**overrides):
    gt = {'frame_id': 'f1', 'present': True, 'landmark_id': LANDMARK,
          'bbox_xywh': [100.0, 50.0, 80.0, 120.0], 'reference': 'VISIBLE',
          'visibility': 'FULL', 'truncated': False, 'occluded': False,
          'ambiguous': False, 'undecidable': False, 'negative_type': None}
    gt.update(overrides)
    return gt


def detected(**overrides):
    pred = {'status': 'DETECTED', 'landmark_id': LANDMARK,
            'bbox_xywh': [100.0, 50.0, 80.0, 120.0], 'score': 0.9,
            'keypoint_px': (142.0, 71.0), 'reject_reason': None}
    pred.update(overrides)
    return pred


def absent_gt(**overrides):
    gt = {'frame_id': 'f0', 'present': False, 'landmark_id': None,
          'bbox_xywh': None, 'reference': None, 'visibility': 'ABSENT',
          'truncated': False, 'occluded': False, 'ambiguous': False,
          'undecidable': False, 'negative_type': 'TARGET_ABSENT'}
    gt.update(overrides)
    return gt


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


def run(gt, pred, **kwargs):
    kwargs.setdefault('tau_iou', 0.3)
    kwargs.setdefault('reference_px', None)
    kwargs.setdefault('tau_px', 5.0)
    kwargs.setdefault('tau_conf', 0.5)
    return evaluate_frame(gt, pred, **kwargs)


# --- presence denominators -------------------------------------------------

def test_present_detected_with_reference_is_joint_success():
    row = run(present_gt(), detected(), reference_px=(142.0, 71.0))
    assert row['presence_class'] == 'TP'
    assert row['reference_class'] == 'PRESENT_AND_AVAILABLE'
    assert row['identity_claim'] is True
    assert row['joint_evaluable'] is True
    assert row['joint_ok'] is True
    summary = summarize([row])
    assert summary['denominators']['positives'] == 1
    assert summary['presence']['recall'] == pytest.approx(1.0)
    assert summary['joint']['narrow_rate'] == pytest.approx(1.0)


def test_unknown_prediction_on_observable_positive_is_counted_as_a_miss():
    row = run(present_gt(), unknown_pred(), reference_px=(142.0, 71.0))
    assert row['gt_observable'] is True
    assert row['presence_class'] == 'FN'
    assert row['counted_in_confusion'] is True
    summary = summarize([row])
    presence = summary['presence']
    assert summary['denominators']['positives'] == 1
    assert summary['denominators']['negatives'] == 0
    assert presence['tp'] == 0
    assert presence['fn'] == 1
    assert presence['recall'] == 0.0          # the miss is visible in recall
    assert presence['fn_by_pred_status'] == {'UNKNOWN': 1}
    assert presence['unknown_rejected']['on_positive'] == 1
    assert presence['unknown_rejected']['by_reason'] == {'DETECTOR_ERROR': 1}
    assert summary['joint']['narrow_denominator'] == 1
    assert summary['joint']['narrow_tp'] == 0
    assert summary['joint']['fail_reasons'] == {'PRESENCE': 1}


def test_rejected_prediction_on_observable_positive_is_counted_as_a_miss():
    pred = {'status': 'REJECTED', 'landmark_id': None, 'bbox_xywh': None,
            'score': None, 'keypoint_px': None,
            'reject_reason': 'MISSING_CALIBRATION'}
    row = run(present_gt(), pred, reference_px=(142.0, 71.0))
    assert row['presence_class'] == 'FN'
    summary = summarize([row])
    assert summary['presence']['recall'] == 0.0
    assert summary['presence']['unknown_rejected']['on_positive'] == 1
    assert summary['presence']['unknown_rejected']['by_reason'] == {
        'MISSING_CALIBRATION': 1}
    assert summary['presence']['unknown_rejected']['by_status'] == {'REJECTED': 1}


def test_unavailable_reference_positive_stays_in_recall_but_not_in_anchor_denominator():
    row = run(present_gt(reference='UNAVAILABLE'), no_detection())
    assert row['presence_class'] == 'FN'
    summary = summarize([row])
    assert summary['denominators']['positives'] == 1
    assert summary['denominators']['reference_unavailable'] == 1
    assert summary['denominators']['reference_available'] == 0
    assert summary['reference']['anchor_error_px']['count'] == 0
    assert summary['reference']['anchor_error_px_correct_only']['count'] == 0
    assert summary['joint']['narrow_denominator'] == 1   # label is complete
    assert summary['joint']['narrow_tp'] == 0


def test_absent_without_detection_is_tn_and_no_identity_claim():
    row = run(absent_gt(), no_detection())
    assert row['presence_class'] == 'TN'
    assert row['identity_claim'] is False
    assert row['identity_correct'] is None


def test_unknown_prediction_on_absent_negative_is_not_credited_as_tn():
    row = run(absent_gt(), unknown_pred())
    assert row['presence_class'] == 'NEGATIVE_UNOBSERVABLE'
    summary = summarize([row])
    presence = summary['presence']
    assert summary['denominators']['negatives'] == 1
    assert presence['tn'] == 0
    assert presence['fp'] == 0
    assert presence['negative_unobservable'] == 1
    assert presence['negative_coverage'] == 0.0
    assert presence['unknown_rejected']['on_negative'] == 1


def test_absent_with_central_tower_claim_counts_as_high_confidence_false_match():
    pred = detected(bbox_xywh=[10.0, 10.0, 20.0, 20.0], score=0.95)
    row = run(absent_gt(), pred)
    assert row['presence_class'] == 'FP'
    assert row['identity_correct'] is False
    summary = summarize([row])
    assert summary['identity']['high_confidence_false_matches'] == 1
    assert summary['identity']['negative_denominator'] == 1
    assert summary['identity']['false_match_rate'] == pytest.approx(1.0)


# --- GT unobservable is never merged with prediction UNKNOWN ---------------

def test_gt_undecidable_frame_is_excluded_and_kept_separate_from_pred_unknown():
    gt = {'frame_id': 'f9', 'present': False, 'landmark_id': None,
          'bbox_xywh': None, 'reference': None, 'visibility': 'UNKNOWN',
          'truncated': False, 'occluded': False, 'ambiguous': False,
          'undecidable': True, 'negative_type': None}
    row = run(gt, unknown_pred())
    assert row['gt_observable'] is False
    assert row['presence_class'] == 'GT_UNOBSERVABLE'
    summary = summarize([row])
    assert summary['denominators']['positives'] == 0
    assert summary['denominators']['negatives'] == 0
    assert summary['denominators']['gt_unobservable'] == 1
    assert summary['gt_unobservable_by_reason'] == {'UNDECIDABLE': 1}
    presence = summary['presence']
    assert presence['tp'] == 0 and presence['fn'] == 0
    assert presence['tn'] == 0 and presence['fp'] == 0
    # prediction UNKNOWN is still counted, but in its own bucket
    assert presence['unknown_rejected']['total'] == 1
    assert presence['unknown_rejected']['on_gt_unobservable'] == 1
    assert presence['unknown_rejected']['on_positive'] == 0
    assert presence['unknown_rejected']['on_negative'] == 0


def test_gt_full_occlusion_present_without_bbox_is_gt_unobservable_not_fn():
    gt = present_gt(bbox_xywh=None, reference='UNAVAILABLE',
                    visibility='OCCLUDED', occluded=True)
    row = run(gt, no_detection())
    assert row['presence_class'] == 'GT_UNOBSERVABLE'
    assert row['gt_unobservable_reason'] == 'FULL_OCCLUSION'
    summary = summarize([row])
    assert summary['denominators']['positives'] == 0
    assert summary['presence']['fn'] == 0
    assert summary['gt_unobservable_by_reason'] == {'FULL_OCCLUSION': 1}


def test_gt_ambiguous_positive_is_excluded_from_denominators():
    gt = present_gt(ambiguous=True, ambiguous_reason='MULTIPLE_SIMILAR_STRUCTURES')
    row = run(gt, detected(), reference_px=(142.0, 71.0))
    assert row['presence_class'] == 'GT_UNOBSERVABLE'
    summary = summarize([row])
    assert summary['denominators']['positives'] == 0
    assert summary['gt_unobservable_by_reason'] == {'AMBIGUOUS': 1}


def test_claims_on_gt_unobservable_frames_are_not_scored_in_identity_denominators():
    gt = {'frame_id': 'f7', 'present': False, 'landmark_id': None,
          'bbox_xywh': None, 'reference': None, 'visibility': 'UNKNOWN',
          'undecidable': True, 'ambiguous': False, 'truncated': False,
          'occluded': False, 'negative_type': None}
    row = run(gt, detected(bbox_xywh=[10.0, 10.0, 20.0, 20.0]))
    assert row['identity_claim'] is True
    assert row['identity_correct'] is None
    summary = summarize([row])
    assert summary['identity']['claims'] == 0
    assert summary['identity']['claims_on_gt_unobservable'] == 1
    assert summary['identity']['precision'] is None


# --- reference denominators -------------------------------------------------

def test_present_with_unavailable_reference_and_no_keypoint_is_reference_correct():
    row = run(present_gt(reference='UNAVAILABLE'), detected(keypoint_px=None))
    assert row['reference_class'] == 'UNAVAILABLE_DECLARED'
    assert row['reference_correct'] is True
    assert row['joint_evaluable'] is True
    assert row['joint_ok'] is True


def test_present_with_unavailable_reference_but_emitted_keypoint_is_false_reference():
    row = run(present_gt(reference='UNAVAILABLE'), detected(keypoint_px=(140.0, 70.0)))
    assert row['reference_class'] == 'UNAVAILABLE_EMITTED_KEYPOINT'
    assert row['reference_correct'] is False
    assert row['joint_ok'] is False
    summary = summarize([row])
    assert summary['reference']['unavailable_denominator'] == 1
    assert summary['reference']['false_reference_rate'] == pytest.approx(1.0)
    assert summary['reference']['anchor_error_px']['count'] == 0


def test_unlabelled_reference_frame_is_not_a_joint_failure_but_lowers_coverage():
    labelled = run(present_gt(), detected(), reference_px=(141.0, 71.0))
    unlabelled = run(present_gt(frame_id='f2', reference=None), detected())
    assert unlabelled['joint_evaluable'] is False
    assert unlabelled['joint_ok'] is None
    summary = summarize([labelled, unlabelled])
    joint = summary['joint']
    assert joint['narrow_denominator'] == 1
    assert joint['narrow_tp'] == 1
    assert joint['coverage'] == pytest.approx(0.5)
    assert joint['all_positive_lower_bound'] == pytest.approx(0.5)
    assert summary['reference']['not_labelled'] == 1


def test_anchor_error_above_tolerance_fails_reference_and_joint():
    row = run(present_gt(), detected(), reference_px=(160.0, 70.0))
    assert row['reference_class'] == 'PRESENT_WRONG_ANCHOR'
    assert row['reference_correct'] is False
    assert row['joint_ok'] is False


def test_anchor_and_bearing_error_statistics_carry_denominators():
    gt = present_gt()
    pred = detected(keypoint_px=(142.0, 71.0))
    row = run(gt, pred, reference_px=(145.0, 74.0),
              fx_px=160.0, cx_px=160.0)
    expected_px = math.hypot(142.0 - 145.0, 71.0 - 74.0)
    assert row['anchor_error_px'] == pytest.approx(expected_px)
    gt_bearing = math.degrees(math.atan2(145.0 - 160.0, 160.0))
    pred_bearing = math.degrees(math.atan2(142.0 - 160.0, 160.0))
    assert row['bearing_error_deg'] == pytest.approx(abs(pred_bearing - gt_bearing))
    summary = summarize([row])
    anchor = summary['reference']['anchor_error_px']
    assert anchor['count'] == 1
    assert anchor['median_px'] == pytest.approx(expected_px)
    bearing = summary['reference']['bearing_error_deg']
    assert bearing['count'] == 1
    assert bearing['median_deg'] == pytest.approx(abs(pred_bearing - gt_bearing))
    assert summary['denominators']['reference_available'] == 1


def test_bearing_stats_require_both_intrinsics():
    with pytest.raises(MetricDefinitionError):
        run(present_gt(), detected(), reference_px=(142.0, 71.0), fx_px=160.0)


def test_bbox_iou_diagnostic_has_its_own_denominator():
    matched = run(present_gt(), detected(), reference_px=(142.0, 71.0))
    shifted = run(present_gt(frame_id='f2'),
                  detected(bbox_xywh=[100.0, 200.0, 80.0, 120.0]),
                  reference_px=(142.0, 71.0))
    no_box = run(present_gt(frame_id='f3'), no_detection())
    assert matched['presence_class'] == 'TP'
    assert shifted['presence_class'] == 'FN'
    assert shifted['bbox_iou'] == 0.0
    assert no_box['bbox_iou'] is None
    summary = summarize([matched, shifted, no_box])
    iou = summary['presence']['bbox_iou_diagnostic']
    # count = frames with both a GT box and a predicted box; denominator = all
    # GT-observable positives that carry a GT box (the missed one stays in it)
    assert iou['count'] == 2
    assert iou['denominator'] == 3
    assert iou['median'] == pytest.approx(0.5)


# --- identity denominators --------------------------------------------------

def test_identity_precision_and_recall_denominators_are_explicit():
    correct = run(present_gt(), detected(), reference_px=(142.0, 71.0))
    missed = run(present_gt(frame_id='f2'), no_detection())
    summary = summarize([correct, missed])
    identity = summary['identity']
    assert identity['claims'] == 1
    assert identity['correct_claims'] == 1
    assert identity['precision'] == pytest.approx(1.0)
    assert identity['recall'] == pytest.approx(0.5)
    assert summary['denominators']['positives'] == 2


def test_unknown_on_positive_lowers_identity_recall_without_a_claim():
    row = run(present_gt(), unknown_pred(), reference_px=(142.0, 71.0))
    summary = summarize([row])
    assert summary['identity']['claims'] == 0
    assert summary['identity']['recall'] == 0.0
    assert summary['identity']['precision'] is None



# --- additive per-frame definition fields (audit support) -------------------

def test_row_records_keypoint_emission_and_joint_branch():
    localization = run(present_gt(), detected(), reference_px=(142.0, 71.0))
    assert localization['keypoint_emitted'] is True
    assert localization['gt_reference_available'] is True
    assert localization['joint_branch'] == 'LOCALIZATION'
    availability = run(present_gt(reference='UNAVAILABLE'),
                       detected(keypoint_px=None))
    assert availability['keypoint_emitted'] is False
    assert availability['gt_reference_unavailable'] is True
    assert availability['joint_branch'] == 'AVAILABILITY_DECLARATION'
    missed = run(present_gt(), no_detection(), reference_px=(142.0, 71.0))
    assert missed['keypoint_emitted'] is False
    assert missed['joint_branch'] == 'LOCALIZATION'
    assert missed['joint_ok'] is False


def test_row_records_pixel_error_components():
    row = run(present_gt(), detected(keypoint_px=(145.0, 76.0)),
              reference_px=(142.0, 71.0))
    assert row['dx_px'] == pytest.approx(3.0)
    assert row['dy_px'] == pytest.approx(5.0)
    assert row['anchor_error_px'] == pytest.approx(math.hypot(3.0, 5.0))


def test_unobservable_rows_do_not_carry_joint_branch():
    gt = present_gt(bbox_xywh=None, reference='UNAVAILABLE',
                    visibility='OCCLUDED', occluded=True)
    row = run(gt, no_detection())
    assert row['presence_class'] == 'GT_UNOBSERVABLE'
    assert row['joint_branch'] is None
    assert row['keypoint_emitted'] is False

# --- stratified reporting ---------------------------------------------------

def test_stratified_summary_reports_worst_condition_with_denominators():
    good = run(present_gt(frame_id='a1'), detected(),
               reference_px=(142.0, 71.0), strata={'family': 'north'})
    bad = run(present_gt(frame_id='b1'), detected(landmark_id=None),
              reference_px=(142.0, 71.0), strata={'family': 'south'})
    unlabelled = run(present_gt(frame_id='b2', reference=None), detected(),
                     strata={'family': 'south'})
    report = stratified_summary([good, bad, unlabelled], ['family'])
    assert set(report['strata']['family']) == {'north', 'south'}
    assert report['strata']['family']['north']['joint']['narrow_rate'] == pytest.approx(1.0)
    assert report['strata']['family']['south']['joint']['narrow_rate'] == 0.0
    worst = report['worst_conditions']['family']
    assert worst['joint_narrow_rate']['stratum'] == 'south'
    assert worst['joint_narrow_rate']['numerator'] == 0
    assert worst['joint_narrow_rate']['denominator'] == 1
    assert worst['presence_recall']['stratum'] == 'south'
    assert worst['presence_recall']['denominator'] == 2


def test_stratified_summary_marks_insufficient_strata():
    row = run(absent_gt(), no_detection(), strata={'family': 'empty'})
    report = stratified_summary([row], ['family'])
    worst = report['worst_conditions']['family']['joint_narrow_rate']
    assert worst['status'] == 'INSUFFICIENT_DENOMINATOR'
    assert worst['stratum'] == 'empty'
    assert worst['denominator'] == 0


# --- accounting and validation ---------------------------------------------

def test_accounting_is_complete_across_all_presence_classes():
    rows = [run(present_gt(), detected(), reference_px=(142.0, 71.0)),
            run(present_gt(frame_id='f2'), unknown_pred()),
            run(absent_gt(), no_detection()),
            run(absent_gt(frame_id='f3'), unknown_pred())]
    summary = summarize(rows)
    presence = summary['presence']
    accounted = (presence['tp'] + presence['fp'] + presence['fn']
                 + presence['tn'] + presence['gt_unobservable']
                 + presence['negative_unobservable'])
    assert accounted == summary['frames'] == 4
    assert summary['denominators']['positives'] == 2
    assert summary['denominators']['negatives'] == 2


def test_metric_status_is_incomplete_when_denominators_are_zero():
    summary = summarize([])
    assert summary['metric_status'] == 'INCOMPLETE'
    assert 'joint_narrow' in summary['insufficient_denominators']


def test_missing_required_gt_field_raises():
    with pytest.raises(MetricDefinitionError):
        run({'frame_id': 'x', 'present': True}, detected())


def test_undecidable_gt_with_present_true_is_rejected():
    with pytest.raises(MetricDefinitionError):
        run(present_gt(undecidable=True), no_detection())


def test_undecidable_gt_with_bbox_is_rejected():
    gt = present_gt(undecidable=True)
    gt['present'] = False
    with pytest.raises(MetricDefinitionError):
        run(gt, no_detection())


def test_unavailable_reference_on_absent_gt_is_rejected():
    with pytest.raises(MetricDefinitionError):
        run(absent_gt(reference='UNAVAILABLE'), no_detection())