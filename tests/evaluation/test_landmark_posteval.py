# -*- coding: utf-8 -*-
"""Regression tests for the post-evaluation landmark diagnosis.

The module under test does NOT rerun the frozen evaluation.  It reads the saved
exploratory predictions + labels and separates four capabilities that the old
single "joint" number conflated:

1. presence            -- was the tower class detected on a positive / absent on
                          a negative?
2. identity            -- was a landmark_id claimed, and was it correct?  The
                          claim denominator and the positive recall denominator
                          are different and both are reported.
3. reference availability -- is the keypoint emitted only when the GT reference
                          point is available, and declared unavailable when it
                          is not?
4. localization accuracy  -- among GT-reference-available positives, how many
                          keypoints are within tau_px?

The joint number is explicitly decomposed into "localized" and "correct
refusal" (target present but reference point not observable and the model
correctly emits no keypoint).  The correct-refusal case is joint-ok but never
enters the localization error denominator, and it must not be merged with
reference coverage.

These tests pin those definitions before the real diagnostic is computed.
"""
import math

import pytest

from boom_birds.evaluation import landmark_posteval as pe

LANDMARK = 'RMUC2027_CENTRAL_TOWER_PROPOSED'
FX = 160.0
CX = 160.0


def annotation(frame_id='f1', *, present=True, reference_available=True,
               keypoint=(140.0, 100.0), bbox=(100.0, 60.0, 80.0, 80.0),
               family='fam_a', green_pixels=10, visibility='FULL',
               truncated=False, undecidable=False, ambiguous=False,
               landmark_id=LANDMARK, split='val'):
    geometry = {'bbox_xywh': None, 'keypoint': None, 'green_pixels': 0,
                'reference_status': 'NOT_APPLICABLE',
                'reference_unavailable_reason': None}
    if present:
        geometry['bbox_xywh'] = list(bbox) if bbox is not None else None
        if reference_available:
            geometry['keypoint'] = {'name': 'green_roof_light_center',
                                    'x': keypoint[0], 'y': keypoint[1],
                                    'visible': True}
            geometry['reference_status'] = 'MANUAL_APPROX'
            geometry['green_pixels'] = green_pixels
        else:
            geometry['reference_status'] = 'UNAVAILABLE'
            geometry['reference_unavailable_reason'] = 'REFERENCE_TOO_SMALL'
    return {
        'frame_id': frame_id,
        'image': 'images/%s.png' % frame_id,
        'image_sha256': '0' * 64,
        'image_width': 320,
        'image_height': 240,
        'source': {'family': family, 'group_id': 'g_' + family,
                   'split': split, 'sequence': 1},
        'dataset_role': 'VALIDATION',
        'target': {
            'landmark_id': landmark_id if present else None,
            'class': 'tower',
            'present': present,
            'undecidable': undecidable,
            'ambiguous': ambiguous,
            'visibility': ('UNKNOWN' if undecidable else
                           ('ABSENT' if not present else visibility)),
            'truncated': truncated,
            'truncated_edges': {'left': False, 'right': False,
                                'top': False, 'bottom': False},
            'occluded': False,
        },
        'geometry': geometry,
        'confusers': [],
        'negative_type': None if present else 'TARGET_ABSENT',
        'pixel_basis': {'image_width': 320, 'image_height': 240,
                        'fx_px': FX, 'cx_px': CX, 'cy_px': 120.0,
                        'projection_model': 'PINHOLE',
                        'bearing_formula': 'atan2(x - cx_px, fx_px)'},
    }


def observation(frame_id='f1', *, status='DETECTED', bbox=(100.0, 60.0, 80.0, 80.0),
                score=0.9, keypoint=(140.0, 100.0), keypoint_confidence=0.99,
                landmark_id=LANDMARK, reject_reason=None, candidate_count=1):
    if status != 'DETECTED':
        bbox = None
        score = None
        keypoint = None
        keypoint_confidence = None
        landmark_id = None
    return {
        'schema_version': 'dsh.landmark_observation.v1',
        'frame_id': frame_id,
        'image': 'images/%s.png' % frame_id,
        'status': status,
        'landmark_class': 'tower' if status == 'DETECTED' else None,
        'landmark_id': landmark_id,
        'identity_claimed': landmark_id is not None,
        'bbox_xywh': list(bbox) if bbox is not None else None,
        'score': score,
        'keypoint_px': list(keypoint) if keypoint is not None else None,
        'keypoint_confidence': keypoint_confidence,
        'candidate_count': candidate_count,
        'reject_reason': reject_reason,
        'reject_reasons': [],
        'reference_status': ('VISIBLE' if keypoint is not None else 'UNAVAILABLE'),
    }


ARGS = {'tau_px': 3.0, 'tau_iou': 0.3, 'tau_conf': 0.5,
        'fx_px': FX, 'cx_px': CX}


def analyze(ann, obs):
    return pe.analyze_frame(ann, obs, **ARGS)


# --- per-frame capability separation ---------------------------------------

def test_correct_localization_is_joint_localized():
    row = analyze(annotation(), observation())
    assert row['reference_stage'] == pe.STAGE_AVAILABLE_CORRECT
    assert row['localization_status'] == 'CORRECT'
    assert row['joint_class'] == pe.JOINT_LOCALIZED
    assert row['signed_dx_px'] == 0.0
    assert row['signed_dy_px'] == 0.0
    assert row['anchor_error_px'] == 0.0


def test_correct_refusal_is_joint_ok_but_never_localization_evidence():
    row = analyze(annotation(reference_available=False, green_pixels=1),
                  observation(keypoint=None, keypoint_confidence=None))
    assert row['reference_stage'] == pe.STAGE_UNAVAILABLE_CORRECT
    assert row['joint_ok'] is True
    assert row['joint_class'] == pe.JOINT_CORRECT_REFUSAL
    assert row['localization_status'] == 'NOT_APPLICABLE'
    assert row['anchor_error_px'] is None
    summary = pe.aggregate([row])
    assert summary['localization']['denominator'] == 0
    assert summary['localization']['error_denominator'] == 0
    assert summary['reference_availability']['unavailable_denominator'] == 1
    assert summary['reference_availability']['correct_declarations'] == 1
    assert summary['joint']['correct_refusal'] == 1
    assert summary['joint']['localized'] == 0
    assert summary['joint']['composite_tp'] == 1
    assert summary['joint']['composite_rate'] == 1.0
    assert summary['joint']['localization_rate'] is None


def test_false_reference_on_unavailable_gt_is_a_semantic_error():
    row = analyze(annotation(reference_available=False, green_pixels=1),
                  observation())
    assert row['reference_stage'] == pe.STAGE_UNAVAILABLE_EMITTED
    assert row['joint_ok'] is False
    assert row['joint_class'] == pe.JOINT_FAIL_FALSE_REFERENCE
    summary = pe.aggregate([row])
    assert summary['reference_availability']['false_reference_emissions'] == 1
    assert summary['reference_availability']['false_reference_rate'] == 1.0
    assert summary['joint']['fail_false_reference'] == 1
    assert summary['localization']['denominator'] == 0


def test_no_keypoint_due_to_confidence_is_kept_in_the_denominator():
    row = analyze(annotation(),
                  observation(keypoint=None, keypoint_confidence=0.2))
    assert row['reference_stage'] == pe.STAGE_AVAILABLE_NO_KEYPOINT
    assert row['kpt_suppressed_by_confidence'] is True
    assert row['keypoint_confidence'] == 0.2
    assert row['joint_class'] == pe.JOINT_FAIL_REFERENCE
    summary = pe.aggregate([row])
    assert summary['reference_availability']['available_denominator'] == 1
    assert summary['localization']['denominator'] == 1
    assert summary['localization']['no_keypoint'] == 1
    assert summary['reference_availability']['coverage'] == 0.0


def test_presence_miss_stays_in_reference_and_joint_denominators():
    row = analyze(annotation(), observation(status='NOT_DETECTED'))
    assert row['presence_class'] == 'FN'
    assert row['reference_stage'] == pe.STAGE_AVAILABLE_PRESENCE_MISS
    assert row['joint_class'] == pe.JOINT_FAIL_PRESENCE
    summary = pe.aggregate([row])
    assert summary['presence']['recall'] == 0.0
    assert summary['reference_availability']['available_denominator'] == 1
    assert summary['localization']['denominator'] == 1
    assert summary['localization']['presence_miss'] == 1
    assert summary['joint']['narrow_denominator'] == 1
    assert summary['joint']['composite_rate'] == 0.0


def test_model_unknown_on_positive_is_a_miss_and_is_listed():
    row = analyze(annotation(), observation(status='UNKNOWN'))
    assert row['presence_class'] == 'FN'
    summary = pe.aggregate([row])
    assert summary['presence']['unknown_rejected']['on_positive'] == 1
    assert summary['audit']['uncertain_on_positive'] == 1


def test_absent_detection_is_fp_and_a_high_confidence_false_match():
    row = analyze(annotation(present=False), observation(score=0.9))
    assert row['presence_class'] == 'FP'
    assert row['reference_stage'] == pe.STAGE_ABSENT
    assert row['joint_class'] == pe.JOINT_NOT_ELIGIBLE
    summary = pe.aggregate([row])
    assert summary['presence']['fp'] == 1
    assert summary['identity']['high_confidence_false_matches'] == 1
    assert summary['identity']['false_match_rate'] == 1.0


def test_absent_not_detected_is_true_negative():
    row = analyze(annotation(present=False), observation(status='NOT_DETECTED'))
    assert row['presence_class'] == 'TN'
    summary = pe.aggregate([row])
    assert summary['presence']['tn'] == 1
    assert summary['presence']['negative_coverage'] == 1.0


def test_gt_unobservable_is_excluded_but_claims_are_reported_separately():
    ann = annotation(present=False, undecidable=True)
    row = analyze(ann, observation())
    assert row['gt_observable'] is False
    assert row['presence_class'] == pe.PRESENCE_GT_UNOBSERVABLE
    summary = pe.aggregate([row])
    assert summary['audit']['gt_unobservable'] == 1
    assert summary['audit']['counted_in_confusion'] == 0
    assert summary['identity']['claims_on_gt_unobservable'] == 1
    assert summary['joint']['narrow_denominator'] == 0


# --- aggregate decomposition ----------------------------------------------

def test_joint_decomposition_localized_plus_refusal():
    rows = [
        analyze(annotation('a'), observation('a')),
        analyze(annotation('b'), observation('b', keypoint=(140.0, 110.0))),
        analyze(annotation('c', reference_available=False, green_pixels=1),
                observation('c', keypoint=None, keypoint_confidence=None)),
        analyze(annotation('d'), observation('d', status='NOT_DETECTED')),
    ]
    summary = pe.aggregate(rows)
    joint = summary['joint']
    assert joint['narrow_denominator'] == 4
    assert joint['localized'] == 1
    assert joint['correct_refusal'] == 1
    assert joint['composite_tp'] == 2
    assert joint['composite_rate'] == 0.5
    assert joint['fail_presence'] == 1
    assert joint['fail_reference'] == 1
    assert summary['localization']['denominator'] == 3
    assert summary['localization']['correct'] == 1
    assert summary['localization']['wrong_anchor'] == 1
    assert summary['localization']['presence_miss'] == 1
    assert summary['localization']['coverage'] == pytest.approx(1 / 3)
    assert summary['joint']['localization_rate'] == pytest.approx(1 / 3)
    assert summary['joint']['refusal_rate'] == 1.0
    # the composite must not be explained as a localization rate
    assert joint['composite_rate'] != summary['localization']['coverage']


def test_aggregate_accounts_every_frame_and_status():
    rows = [
        analyze(annotation('a'), observation('a')),
        analyze(annotation('b', reference_available=False), observation(
            'b', keypoint=None, keypoint_confidence=None)),
        analyze(annotation('c'), observation('c', status='REJECTED',
                                            reject_reason='TARGET_AMBIGUOUS')),
        analyze(annotation('d', present=False), observation('d')),
        analyze(annotation('e', present=False), observation('e',
                                                            status='NOT_DETECTED')),
        analyze(annotation('f', present=False, undecidable=True),
                observation('f', status='NOT_DETECTED')),
    ]
    summary = pe.aggregate(rows)
    audit = summary['audit']
    assert audit['frames'] == 6
    assert audit['counted_in_confusion'] == 5
    assert audit['gt_unobservable'] == 1
    assert audit['frames'] == (audit['presence_tp'] + audit['presence_fp']
                               + audit['presence_fn'] + audit['presence_tn']
                               + audit['gt_unobservable'])


def test_wrong_bearing_can_pass_pixel_error_and_vice_versa():
    # 4 px vertical offset: 2D fails at tau_px=3 but the image bearing is exact.
    rows = [analyze(annotation('v'), observation('v', keypoint=(140.0, 104.0))),
            # 4 px horizontal offset: both fail at the 3 px-equivalent 1.074 deg.
            analyze(annotation('h'), observation('h', keypoint=(144.0, 100.0))),
            # 2 px horizontal offset: both pass.
            analyze(annotation('p'), observation('p', keypoint=(142.0, 100.0)))]
    flips = pe.bearing_flip_counts(rows, thresholds_deg=(0.414, 1.074, 5.0))
    at_1074 = flips['1.074']
    assert at_1074['both_pass'] == 1
    assert at_1074['pixel_fail_bearing_pass'] == 1
    assert at_1074['pixel_pass_bearing_fail'] == 0
    assert at_1074['flips'] == 1
    at_0414 = flips['0.414']
    assert at_0414['pixel_pass_bearing_fail'] == 1  # 2 px = 0.716 deg
    at_5 = flips['5.0']
    assert at_5['flips'] == 2  # both 4 px offsets: 2D fail, bearing pass


def test_signed_error_bias_is_reported():
    rows = [analyze(annotation('a'), observation('a', keypoint=(140.0, 104.0))),
            analyze(annotation('b'), observation('b', keypoint=(140.0, 106.0)))]
    summary = pe.aggregate(rows)
    loc = summary['localization']
    assert loc['signed_dy_px']['count'] == 2
    assert loc['signed_dy_px']['median_px'] == pytest.approx(5.0)
    assert loc['wrong_anchor_vertical'] == 2
    assert loc['wrong_anchor_lateral'] == 0


# --- green cue / annotation audit -----------------------------------------

def pixels_with_green_blob():
    width, height = 20, 12
    pixels = [[(10, 10, 10) for _ in range(width)] for _ in range(height)]
    # strict green blob 3x2 at x=4..6, y=3..4
    for y in range(3, 5):
        for x in range(4, 7):
            pixels[y][x] = (40, 200, 60)
    # sub-threshold green (too dark) must not count
    pixels[8][8] = (5, 40, 5)
    # a second valid blob of 1 px
    pixels[9][14] = (40, 200, 60)
    return pixels


def test_strict_green_mask_uses_the_frozen_rule():
    pixels = pixels_with_green_blob()
    mask = pe.strict_green_mask(pixels)
    assert mask[3][4] is True and mask[3][3] is False
    assert mask[8][8] is False


def test_green_components_are_ranked_and_centred():
    components = pe.green_components(pixels_with_green_blob())
    assert len(components) == 2
    assert components[0]['area'] == 6
    assert components[0]['centroid_x'] == pytest.approx(5.0)
    assert components[0]['centroid_y'] == pytest.approx(3.5)
    assert components[1]['area'] == 1


def test_green_anchor_audit_measures_label_vs_strict_centroid():
    pixels = pixels_with_green_blob()

    def loader(_path):
        return pixels

    anns = [annotation('a', keypoint=(5.0, 3.5)),
            annotation('b', keypoint=(5.0, 6.0))]  # 2.5 px away from the blob
    audit = pe.green_anchor_audit(anns, loader, radius_px=8.0)
    assert audit['count'] == 2
    assert audit['distance_px']['median_px'] == pytest.approx(1.25)
    assert audit['frames_without_component_within_radius'] == 0
    assert audit['frames_distance_gt_1_5_px'] == 1


def test_green_anchor_audit_flags_a_frame_without_a_strict_cue():
    def loader(_path):
        return [[(10, 10, 10)] * 4 for _ in range(4)]

    audit = pe.green_anchor_audit([annotation('a', keypoint=(2.0, 2.0))],
                                  loader, radius_px=8.0)
    assert audit['count'] == 1
    assert audit['matched_count'] == 0
    assert audit['frames_without_component_within_radius'] == 1


# --- tiny / blind re-annotation plan --------------------------------------

def tiny_docs():
    train = {'annotations': []}
    for i, side in enumerate((10.4, 9.3, 12.0, 40.0)):
        ann = annotation('train_%d' % i, bbox=(100.0, 60.0, side, side),
                         family='fam_south_A', reference_available=(i == 3))
        if not ann['geometry']['keypoint']:
            ann['geometry']['reference_status'] = 'MANUAL_APPROX'
            ann['geometry']['keypoint'] = {'name': 'green_roof_light_center',
                                           'x': 120.0, 'y': 70.0,
                                           'visible': True}
        train['annotations'].append(ann)
    val = {'annotations': [
        annotation('val_0', bbox=(100.0, 60.0, 10.8, 9.7), family='fam_north'),
        annotation('val_1', present=False, family='fam_north'),
        annotation('val_2', bbox=(100.0, 60.0, 30.0, 30.0), family='fam_north',
                   green_pixels=5),
    ]}
    return train, val


def test_tiny_reannotation_plan_is_deterministic_and_blind():
    train, val = tiny_docs()
    plan1 = pe.tiny_reannotation_plan(train, val, max_side_px=14.0,
                                      n_tiny=3, n_small_green=2,
                                      n_control=1)
    plan2 = pe.tiny_reannotation_plan(train, val, max_side_px=14.0,
                                      n_tiny=3, n_small_green=2,
                                      n_control=1)
    assert plan1 == plan2
    ids = [f['frame_id'] for f in plan1['frames']]
    assert len(ids) == len(set(ids))
    text = json_dumps(plan1['frames'])
    assert 'bbox' not in text
    assert 'keypoint' not in text
    assert plan1['criteria']['blind'] is True
    assert plan1['selection_rule']
    tiny = [f for f in plan1['frames'] if f['role'] == 'tiny_positive']
    assert len(tiny) == 3
    assert all(f['target_size_px'] <= 14.0 for f in tiny)
    assert any(f['role'] == 'control_absent' for f in plan1['frames'])


def json_dumps(value):
    import json
    return json.dumps(value, ensure_ascii=False)


# --- reproduction of the old (frozen) numbers -----------------------------

def test_reproduction_check_matches_recomputed_summary():
    rows = [analyze(annotation('a'), observation('a')),
            analyze(annotation('b'), observation('b', status='NOT_DETECTED'))]
    summary = pe.aggregate(rows)
    old = {'overall': summary['old_metrics_recomputed']}
    check = pe.reproduction_check(summary, old)
    assert check['match'] is True
    assert check['mismatches'] == []


def test_reproduction_check_reports_mismatch():
    rows = [analyze(annotation('a'), observation('a'))]
    summary = pe.aggregate(rows)
    old = {'overall': dict(summary['old_metrics_recomputed'])}
    old['overall']['joint'] = dict(old['overall']['joint'])
    old['overall']['joint']['narrow_tp'] = 99
    check = pe.reproduction_check(summary, old)
    assert check['match'] is False
    assert any('joint.narrow_tp' in m for m in check['mismatches'])

# --- consumer requirement traceability (task-24) --------------------------

def test_consumer_requirements_trace_to_v22_sections():
    req = pe.consumer_requirements()
    assert req['status'] == 'PROPOSED_NOT_FROZEN'
    assert req['schema_version'] == 'dsh.landmark_consumer_requirement.v1'
    items = req['items']
    for key in ('identity', 'reference_availability', 'horizontal_image_bearing',
                'freshness_and_validity'):
        assert key in items
        item = items[key]
        assert item['source_sections'], key
        assert item['consumer_need'], key
        assert item['testable_quantity'], key
        assert item['forbidden_inputs'], key
        assert item['status'] == 'PROPOSED', key
    assert 'world_bearing' in items['horizontal_image_bearing']['forbidden_inputs']
    assert 'distance' in items['reference_availability']['forbidden_inputs']
    assert 'ground_truth_position' in items['identity']['forbidden_inputs']
    assert req['protocol']['identity_rule']
    assert req['protocol']['bearing_budget_deg']['status'] == 'PROPOSED_NOT_FROZEN'


def test_appearance_gate_decision_and_unknown():
    assert pe.appearance_gate(0.70) == 'ACCEPT'
    assert pe.appearance_gate(0.30) == 'REJECT'
    assert pe.appearance_gate(None) == 'UNKNOWN'
    assert pe.appearance_gate(0.50) == 'ACCEPT'
    assert pe.appearance_gate(0.70, 0.10) == 'REJECT'
    assert pe.appearance_gate(0.70, 0.18) == 'ACCEPT'
    assert pe.appearance_gate(0.70, None) == 'ACCEPT'
    assert pe.appearance_gate(0.70, 0.10, rel_y_min=None) == 'ACCEPT'


def test_appearance_gate_cost_counts_false_and_miss_blocks():
    objects = [
        {'kind': 'TARGET', 'aspect_ratio': 1.2, 'green_rel_y': 0.25},
        {'kind': 'TARGET', 'aspect_ratio': 0.8, 'green_rel_y': None},
        {'kind': 'TARGET', 'aspect_ratio': 0.4, 'green_rel_y': 0.25},
        {'kind': 'MS1', 'aspect_ratio': 0.3, 'green_rel_y': 0.09},
        {'kind': 'MS1', 'aspect_ratio': 0.6, 'green_rel_y': None},  # miss block: no kpt, aspect-only
    ]
    cost = pe.appearance_gate_cost(objects)
    assert cost['target_n'] == 3
    assert cost['target_accept'] == 2
    assert cost['target_false_block'] == 1
    assert cost['ms1_n'] == 2
    assert cost['ms1_reject'] == 1
    assert cost['ms1_accept_miss_block'] == 1
    assert cost['zero_miss_upper_bound_95'] is None
    cost0 = pe.appearance_gate_cost([{'kind': 'MS1', 'aspect_ratio': 0.2}] * 20)
    assert cost0['ms1_accept_miss_block'] == 0
    assert cost0['zero_miss_upper_bound_95'] == pytest.approx(1 - 0.05 ** (1 / 20))
