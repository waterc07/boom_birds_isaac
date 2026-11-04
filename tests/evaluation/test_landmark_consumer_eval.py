"""Failing-first tests for the landmark consumer-protocol evaluation.

Pins the pre-registered consumer protocol
(configs/perception/landmark_consumer_protocol_v1.json, sha bdcc9ccd...):

- success per GT-present frame = presence correct AND identity confirmed-correct
  AND reference handling correct AND horizontal bearing error <= tau_bearing (3
  deg) AND observation valid; 2D pixel error is diagnostic only;
- a confirmed central-tower ID may only be emitted with exactly one candidate
  surviving and an appearance gate pass; otherwise UNKNOWN/candidate and no
  region update;
- UNKNOWN/REJECTED/no-keypoint samples stay in the applicable success
  denominator;
- GT-unobservable frames are not scored for the observable domain but are kept
  in the all-positive denominator and their claims/keypoints are counted;
- wrong claims are broken out for MS1-only, same-frame, multi-candidate,
  full-occlusion and negative frames;
- the appearance gate uses image-only features, and its sweep reports
  false-block (target rejected) and miss-block (MS1 accepted) counts.
"""
import json
import math
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
from PIL import Image

from boom_birds.evaluation import landmark_consumer_eval as ce


REPO_ROOT = Path(__file__).resolve().parents[2]
TOWER = 'RMUC2027_CENTRAL_TOWER_PROPOSED'
PROTOCOL_PATH = REPO_ROOT / 'configs/perception/landmark_consumer_protocol_v1.json'


def protocol_doc(**overrides):
    doc = {
        'schema_version': 'dsh.landmark_consumer_protocol.v1',
        'status': 'TEST_PROTOCOL',
        'consumer_contract': {
            'observation_valid': 'stale/duplicate/generation-mismatch invalid',
            'identity_policy': 'confirmed id only with gate pass and exactly one candidate',
            'reference_policy': 'visible -> keypoint; unavailable -> refusal',
            'bearing_definition': 'atan2(kx - cx, fx)',
        },
        'success_definition': {
            'per_gt_present_frame': 'presence AND identity AND reference AND bearing',
            'per_gt_absent_frame': 'no confirmed claim',
        },
        'thresholds': {
            'tau_bearing_deg': 3.0,
            'tau_px_diagnostic': 3.0,
            'tau_iou_diagnostic': 0.3,
            'appearance_gate': 'image features only',
        },
        'denominators': {
            'all_positive': 'all GT present',
            'observable_positive': 'GT present excluding GT_UNOBSERVABLE',
            'reference_available': 'GT present with visible reference',
            'negatives': 'GT absent / MS1-only',
            'unknown_policy': 'kept in denominator',
        },
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(doc.get(key), dict):
            doc[key].update(value)
        else:
            doc[key] = value
    return doc


def annotation(frame_id='f.png', *, present=True, reference='VISIBLE',
               unobservable=False, bbox=(97, 106, 83, 74),
               keypoint=(99.9, 109.9), family='fam_test', ms1_boxes=(),
               truncated=False):
    if unobservable:
        target = {'landmark_id': TOWER, 'class': 'tower', 'present': True,
                  'undecidable': False, 'visibility': 'OCCLUDED',
                  'truncated': False, 'occluded': True, 'ambiguous': False,
                  'truncated_edges': {'left': False, 'right': False,
                                      'top': False, 'bottom': False},
                  'truncation_source': {}}
        geometry = {'bbox_xywh': None, 'keypoint': None, 'green_pixels': None,
                    'reference_status': 'UNAVAILABLE',
                    'reference_unavailable_reason': 'REFERENCE_OCCLUDED',
                    'reference_source': 'NOT_APPLICABLE'}
    elif present:
        target = {'landmark_id': TOWER, 'class': 'tower', 'present': True,
                  'undecidable': False,
                  'visibility': 'PARTIAL' if truncated else 'FULL',
                  'truncated': truncated, 'occluded': False, 'ambiguous': False,
                  'truncated_edges': {'left': False, 'right': bool(truncated),
                                      'top': False, 'bottom': False},
                  'truncation_source': {'right': 'ANNOTATOR_VISUAL'}
                  if truncated else {}}
        geometry = {
            'bbox_xywh': list(bbox),
            'keypoint': ({'name': 'green_roof_light_center',
                          'x': keypoint[0], 'y': keypoint[1], 'visible': True}
                         if reference == 'VISIBLE' else None),
            'green_pixels': 12 if reference == 'VISIBLE' else 2,
            'reference_status': ('MANUAL_APPROX' if reference == 'VISIBLE'
                                 else 'UNAVAILABLE'),
            'reference_unavailable_reason': (None if reference == 'VISIBLE'
                                             else 'REFERENCE_TOO_SMALL'),
            'reference_source': 'COLOR_CUE_ASSISTED',
        }
    else:
        target = {'landmark_id': TOWER, 'class': 'tower', 'present': False,
                  'undecidable': False, 'visibility': 'ABSENT',
                  'truncated': False, 'occluded': False, 'ambiguous': False,
                  'truncated_edges': {'left': False, 'right': False,
                                      'top': False, 'bottom': False},
                  'truncation_source': {}}
        geometry = {'bbox_xywh': None, 'keypoint': None, 'green_pixels': 0,
                    'reference_status': 'NOT_APPLICABLE',
                    'reference_unavailable_reason': None,
                    'reference_source': 'NOT_APPLICABLE'}
    return {
        'frame_id': frame_id, 'image': 'images/' + frame_id,
        'image_sha256': 'x', 'image_width': 320, 'image_height': 240,
        'source': {'run': 'r', 'family': family, 'group_id': 'g_' + family,
                   'split': 'val'},
        'target': target, 'geometry': geometry,
        'confusers': [{'confuser_id': 'MAP_NATIVE_MS1',
                       'bbox_xywh': list(box), 'green_cue': {'x': 10.0, 'y': 10.0},
                       'verified': True,
                       'verification_source': 'WORLD_POSE_OR_MAP_DB'}
                      for box in ms1_boxes],
        'candidates': [], 'negative_type': (None if present
                                            else 'SIMILAR_STRUCTURE'),
        'annotator': {'annotator_type': 'AGENT_PROXY', 'annotator_id': 't'},
        'pixel_basis': {'image_width': 320, 'image_height': 240,
                        'fx_px': 160.0, 'cx_px': 160.0, 'cy_px': 120.0,
                        'projection_model': 'PINHOLE'},
        'dataset_role': 'DEVELOPMENT', 'notes': '',
    }


def prediction(status='DETECTED', *, landmark_id=TOWER, bbox=(97, 106, 83, 74),
               keypoint=(99.9, 109.9), score=0.9, reject_reason=None,
               candidate_count=1):
    return {
        'status': status,
        'landmark_id': landmark_id,
        'bbox_xywh': list(bbox) if bbox is not None else None,
        'score': score if status == 'DETECTED' else None,
        'keypoint_px': list(keypoint) if keypoint is not None else None,
        'reject_reason': reject_reason,
        'candidate_count': candidate_count,
    }


def evaluate(annotation_doc, pred, *, protocol=None, decision=None, gate=None):
    protocol = protocol or ce.merge_protocol(protocol_doc())
    truth = ce.truth_from_annotation(annotation_doc, decision=decision)
    return ce.evaluate_frame(pred, truth, protocol, gate=gate)


# --- protocol loading -------------------------------------------------------

def test_load_protocol_reads_the_registered_file_and_records_sha():
    protocol = ce.load_protocol(PROTOCOL_PATH)
    assert protocol['schema_version'] == 'dsh.landmark_consumer_protocol.v1'
    assert protocol['thresholds']['tau_bearing_deg'] == 3
    assert protocol['_source']['sha256'].startswith('bdcc9ccd')
    assert protocol['_source']['status'].startswith('PRE_REGISTERED')


def test_protocol_requires_positive_bearing_tolerance(tmp_path):
    bad = protocol_doc()
    bad['thresholds']['tau_bearing_deg'] = 0
    path = tmp_path / 'bad.json'
    path.write_text(json.dumps(bad), encoding='utf-8')
    with pytest.raises(ce.ConsumerEvalError):
        ce.load_protocol(path)


def test_merge_protocol_fills_defaults_and_keeps_protocol_status():
    protocol = ce.merge_protocol(protocol_doc())
    assert protocol['thresholds']['tau_bearing_deg'] == 3.0
    assert protocol['_source']['status'] == 'TEST_PROTOCOL'
    assert protocol['_source']['sha256'] is None


# --- truth building ---------------------------------------------------------

def test_truth_from_annotation_marks_reference_and_unobservable():
    truth = ce.truth_from_annotation(annotation('a.png'))
    assert truth['present'] is True
    assert truth['observable'] is True
    assert truth['reference'] == 'VISIBLE'
    assert truth['gt_keypoint'] == [99.9, 109.9]
    unobservable = ce.truth_from_annotation(annotation('b.png', unobservable=True))
    assert unobservable['observable'] is False
    assert unobservable['gt_unobservable'] is True
    assert unobservable['reference'] == 'UNAVAILABLE'


def test_truth_from_decision_adds_ms1_and_same_frame_flags():
    decision = {'frame_id': 'c.png', 'case_id': 'lmf_devid_both_mid_similar_scale_0',
                'identity_condition': 'both_in_frame_similar_scale',
                'decision': 'BOTH_TARGET_IDENTIFIED',
                'target_bbox': [200.0, 60.0, 60.0, 120.0],
                'target_keypoint': [230.0, 70.0],
                'confusers': [{'confuser_id': 'MAP_NATIVE_MS1',
                               'bbox_xywh': [20.0, 40.0, 40.0, 150.0]}]}
    truth = ce.truth_from_annotation(annotation('c.png'), decision=decision)
    assert truth['same_frame'] is True
    assert truth['ms1_boxes'] == [[20.0, 40.0, 40.0, 150.0]]
    assert truth['gt_bbox'] == [200.0, 60.0, 60.0, 120.0]
    ms1_only = ce.truth_from_annotation(
        annotation('d.png', present=False),
        decision={'identity_condition': 'map_native_confuser_alone',
                  'decision': 'CONFUSER_ONLY', 'target_bbox': None,
                  'target_keypoint': None,
                  'confusers': [{'confuser_id': 'MAP_NATIVE_MS1',
                                 'bbox_xywh': [131.0, 47.0, 57.0, 192.0]}]})
    assert ms1_only['ms1_only'] is True
    assert ms1_only['present'] is False


# --- success criteria -------------------------------------------------------

def test_success_requires_presence_identity_reference_and_bearing():
    protocol = ce.merge_protocol(protocol_doc())
    good = evaluate(annotation(), prediction(), protocol=protocol)
    assert good['success'] is True
    assert good['bearing_ok'] is True
    assert good['identity_correct'] is True
    wrong_identity = evaluate(annotation(), prediction(landmark_id='OTHER'), protocol=protocol)
    assert wrong_identity['identity_correct'] is False
    assert wrong_identity['success'] is False
    far_bearing = evaluate(annotation(), prediction(keypoint=(130.0, 109.9)),
                           protocol=protocol)
    assert far_bearing['bearing_error_deg'] > 3.0
    assert far_bearing['success'] is False
    no_keypoint = evaluate(annotation(), prediction(keypoint=None), protocol=protocol)
    assert no_keypoint['reference_correct'] is False
    assert no_keypoint['success'] is False


def test_2d_error_is_diagnostic_only_and_bearing_gate_decides():
    protocol = ce.merge_protocol(protocol_doc())
    # dx tiny (bearing ok), dy large -> 2D error > 3 px but consumer success ok
    row = evaluate(annotation(), prediction(keypoint=(99.9, 121.0)), protocol=protocol)
    assert row['px_2d_error'] > 3.0
    assert row['bearing_error_deg'] <= 3.0
    assert row['success'] is True
    assert row['diagnostics_only']['px_2d_error'] > 3.0


def test_gt_reference_unavailable_requires_correct_refusal():
    protocol = ce.merge_protocol(protocol_doc())
    truth = annotation('u.png', reference='UNAVAILABLE')
    refused = evaluate(truth, prediction(keypoint=None), protocol=protocol)
    assert refused['reference_correct'] is True
    assert refused['success'] is True
    emitted = evaluate(truth, prediction(keypoint=(120.0, 100.0)), protocol=protocol)
    assert emitted['reference_correct'] is False
    assert emitted['false_reference'] is True
    assert emitted['success'] is False


def test_unconfirmed_identity_claim_is_wrong_and_negative_success_is_no_claim():
    protocol = ce.merge_protocol(protocol_doc())
    ms1 = evaluate(annotation('m.png', present=False, ms1_boxes=([131, 47, 57, 192],)),
                   prediction(bbox=(131, 47, 57, 192)), protocol=protocol)
    assert ms1['identity_claimed'] is True
    assert ms1['wrong_claim'] is True
    assert ms1['wrong_claim_category'] == 'MS1_ONLY'
    assert ms1['success'] is False
    absent_ok = evaluate(annotation('n.png', present=False),
                         prediction(status='NOT_DETECTED', landmark_id=None,
                                    bbox=None, keypoint=None), protocol=protocol)
    assert absent_ok['wrong_claim'] is False
    assert absent_ok['success'] is True


def test_same_frame_claim_must_match_the_target_box():
    protocol = ce.merge_protocol(protocol_doc())
    decision = {'identity_condition': 'both_in_frame_similar_scale',
                'decision': 'BOTH_TARGET_IDENTIFIED',
                'target_bbox': [200.0, 60.0, 60.0, 120.0],
                'target_keypoint': [230.0, 70.0],
                'confusers': [{'confuser_id': 'MAP_NATIVE_MS1',
                               'bbox_xywh': [20.0, 40.0, 40.0, 150.0]}]}
    truth = annotation('s.png', bbox=(200, 60, 60, 120), keypoint=(230.0, 70.0))
    right = evaluate(truth, prediction(bbox=(200, 60, 60, 120),
                                       keypoint=(230.0, 70.0)),
                     protocol=protocol, decision=decision)
    assert right['same_frame'] is True
    assert right['identity_correct'] is True
    picked_ms1 = evaluate(truth, prediction(bbox=(20, 40, 40, 150),
                                            keypoint=(230.0, 70.0)),
                          protocol=protocol, decision=decision)
    assert picked_ms1['identity_correct'] is False
    assert picked_ms1['wrong_claim_category'] == 'SAME_FRAME'


def test_gt_unobservable_is_not_scored_but_claim_is_counted():
    protocol = ce.merge_protocol(protocol_doc())
    row = evaluate(annotation('o.png', unobservable=True),
                   prediction(bbox=(100, 50, 80, 120), keypoint=(140.0, 60.0)),
                   protocol=protocol)
    assert row['domain_flags']['observable_positive'] is False
    assert row['domain_flags']['all_positive'] is True
    assert row['success'] is False
    assert row['wrong_claim'] is True
    assert row['wrong_claim_category'] == 'FULL_OCCLUSION'
    assert row['gt_unobservable_keypoint'] is True


def test_multi_candidate_claim_violates_the_exactly_one_candidate_contract():
    protocol = ce.merge_protocol(protocol_doc())
    row = evaluate(annotation(), prediction(candidate_count=2), protocol=protocol)
    assert row['identity_claimed'] is True
    assert row['identity_correct'] is False
    assert row['wrong_claim'] is True
    assert row['wrong_claim_category'] == 'MULTI_CANDIDATE'


def test_unknown_and_gate_rejection_stay_in_the_success_denominator():
    protocol = ce.merge_protocol(protocol_doc())
    unknown = evaluate(annotation(), prediction(status='UNKNOWN', landmark_id=None,
                                                bbox=None, keypoint=None,
                                                reject_reason='DETECTOR_ERROR'),
                       protocol=protocol)
    assert unknown['valid'] is False
    assert unknown['success'] is False
    assert unknown['domain_flags']['all_positive'] is True
    reject_gate = lambda features: {'accepted': False, 'reason': 'APPEARANCE'}
    gated = evaluate(annotation(), prediction(), protocol=protocol,
                     gate=reject_gate)
    # a gate rejection is a compliant refusal (UNKNOWN), not a wrong claim; it
    # costs availability and must be counted as a gate false-block
    assert gated['gate_blocked'] is True
    assert gated['gate_blocked_correct_target'] is True
    assert gated['identity_claimed'] is False
    assert gated['identity_correct'] is False
    assert gated['wrong_claim'] is False
    assert gated['success'] is False


# --- frozen-threshold re-decode of saved observations -----------------------

def test_redecode_predictions_applies_frozen_tau_det():
    truth = ce.truth_from_annotation(annotation('a.png'))
    frames = {'a.png': truth}

    def saved(score):
        return {'frame_id': 'a.png', 'observation': {
            'status': 'DETECTED', 'candidates': [
                {'bbox_xywh': [97.0, 106.0, 83.0, 74.0], 'score': score,
                 'keypoint_px': [99.9, 109.9],
                 'keypoint_confidence': 0.9, 'green_pixels': None}]}}
    below = ce.redecode_predictions([saved(0.40)], frames, tau_det=0.605476,
                                    tau_margin=0.1, tau_kpt=0.5)
    assert below['a.png']['status'] == 'NOT_DETECTED'
    assert below['a.png']['landmark_id'] is None
    above = ce.redecode_predictions([saved(0.90)], frames, tau_det=0.605476,
                                    tau_margin=0.1, tau_kpt=0.5)
    assert above['a.png']['status'] == 'DETECTED'
    assert above['a.png']['landmark_id'] == TOWER
    unchanged = ce.redecode_predictions(
        [{'frame_id': 'a.png', 'prediction': prediction()}], frames,
        tau_det=0.605476, tau_margin=0.1, tau_kpt=0.5)
    assert unchanged['a.png']['status'] == 'DETECTED'

# --- identity policies (raw upper bound vs strict UNKNOWN) ------------------

def test_strict_unknown_policy_makes_present_success_zero():
    protocol = ce.merge_protocol(protocol_doc())
    row = evaluate(annotation(), prediction(), protocol=protocol)
    strict = ce.evaluate_frame(prediction(), ce.truth_from_annotation(annotation()),
                               protocol, identity_policy='strict_unknown')
    assert strict['identity_policy'] == 'strict_unknown'
    assert strict['identity_claim_raw'] is True
    assert strict['identity_claimed'] is False
    assert strict['identity_correct'] is False
    assert strict['wrong_claim'] is False
    assert strict['success'] is False
    negative = ce.evaluate_frame(
        prediction(status='NOT_DETECTED', landmark_id=None, bbox=None,
                   keypoint=None),
        ce.truth_from_annotation(annotation('neg.png', present=False)),
        protocol, identity_policy='strict_unknown')
    assert negative['success'] is True
    summary = ce.summarize_consumer([strict, negative], protocol=protocol,
                                    identity_policy='strict_unknown')
    assert summary['domains']['all_positive']['success'] == 0
    assert summary['domains']['all_positive']['denominator'] == 1
    assert summary['domains']['negatives']['success'] == 1
    assert summary['identity']['confirmed_claims'] == 0
    assert summary['identity']['raw_claims'] == 1
    assert 'success ceiling' in summary['identity_policy_note']


def test_raw_claim_upper_bound_policy_flags_unvalidated_identity():
    protocol = ce.merge_protocol(protocol_doc())
    row = ce.evaluate_frame(prediction(), ce.truth_from_annotation(annotation()),
                            protocol, identity_policy='raw_claim_upper_bound')
    assert row['identity_policy'] == 'raw_claim_upper_bound'
    assert row['identity_claim_unvalidated'] is True
    assert row['identity_claimed'] is True
    assert row['identity_correct'] is True
    assert row['success'] is True
    summary = ce.summarize_consumer([row], protocol=protocol,
                                    identity_policy='raw_claim_upper_bound')
    assert summary['identity_policy'] == 'raw_claim_upper_bound'
    assert summary['identity_claim_unvalidated'] is True
    assert summary['identity']['claims'] == 1


def test_unknown_identity_policy_raises():
    protocol = ce.merge_protocol(protocol_doc())
    with pytest.raises(ce.ConsumerEvalError):
        ce.evaluate_frame(prediction(), ce.truth_from_annotation(annotation()),
                          protocol, identity_policy='NOT_A_POLICY')

# --- aggregation ------------------------------------------------------------

def _rows():
    protocol = ce.merge_protocol(protocol_doc())
    return [
        evaluate(annotation('a.png'), prediction(), protocol=protocol),
        evaluate(annotation('b.png', reference='UNAVAILABLE'),
                 prediction(keypoint=None), protocol=protocol),
        evaluate(annotation('c.png'), prediction(keypoint=(130.0, 109.9)),
                 protocol=protocol),
        evaluate(annotation('d.png', present=False),
                 prediction(status='NOT_DETECTED', landmark_id=None,
                            bbox=None, keypoint=None), protocol=protocol),
        evaluate(annotation('e.png', unobservable=True),
                 prediction(bbox=(100, 50, 80, 120), keypoint=(140.0, 60.0)),
                 protocol=protocol),
    ]


def test_summarize_reports_three_domains_and_rates():
    protocol = ce.merge_protocol(protocol_doc())
    summary = ce.summarize_consumer(_rows(), protocol=protocol)
    domains = summary['domains']
    assert domains['all_positive']['denominator'] == 4      # a,b,c,e
    assert domains['observable_positive']['denominator'] == 3  # a,b,c
    assert domains['reference_available']['denominator'] == 2  # a,c
    assert domains['negatives']['denominator'] == 1         # d
    assert domains['all_positive']['success'] == 2          # a + b (correct refusal)
    assert domains['observable_positive']['success'] == 2
    assert domains['reference_available']['success'] == 1
    assert domains['negatives']['success'] == 1
    identity = summary['identity']
    # global claim accounting includes the GT_UNOBSERVABLE frame (e) so its
    # claim cannot disappear; it is a wrong claim in its own category
    assert identity['confirmed_claims'] == 4
    assert identity['correct_claims'] == 3
    assert identity['wrong_claims'] == 1
    assert identity['wrong_claim_categories'] == {'FULL_OCCLUSION': 1}
    assert identity['precision'] == pytest.approx(0.75)
    assert identity['recall'] == pytest.approx(1.0)
    reference = summary['reference']
    assert reference['emitted'] == 2
    assert reference['false_reference'] == 0
    bearing = summary['bearing']
    assert bearing['count'] == 2
    assert bearing['tau_bearing_deg'] == 3.0
    assert summary['gt_unobservable']['frames'] == 1
    assert summary['gt_unobservable']['claims'] == 1
    assert summary['gt_unobservable']['keypoints'] == 1
    assert summary['rejection']['unknown_or_rejected'] == 0
    assert summary['accounting']['frames'] == 5


def test_strata_reporting_covers_family_and_scale():
    protocol = ce.merge_protocol(protocol_doc())
    summary = ce.summarize_consumer(_rows(), protocol=protocol)
    assert 'family' in summary['strata']
    assert 'scale' in summary['strata']


# --- appearance gate --------------------------------------------------------

def _tower_image():
    array = np.full((240, 320, 3), 40, dtype=np.uint8)
    # wide tapered tower body with a symmetric top light rack, green centre light
    array[80:200, 120:200] = (120, 120, 120)
    array[76:90, 110:210] = (130, 130, 130)
    array[80:90, 150:170] = (40, 200, 60)
    return array


def _ms1_image():
    array = np.full((240, 320, 3), 40, dtype=np.uint8)
    # slender column, asymmetric flat top module, side-mounted green lamp
    array[40:220, 150:190] = (110, 110, 110)
    array[40:52, 148:200] = (120, 120, 120)
    array[60:70, 150:158] = (40, 200, 60)
    return array


def test_appearance_features_are_image_only_and_separate_tower_from_ms1():
    tower = ce.appearance_features(_tower_image(), [110.0, 76.0, 100.0, 124.0])
    ms1 = ce.appearance_features(_ms1_image(), [148.0, 40.0, 52.0, 180.0])
    assert tower['aspect_ratio'] < ms1['aspect_ratio']
    assert tower['green_pixels'] >= 3 and ms1['green_pixels'] >= 3
    assert tower['green_rel_x_offset'] < ms1['green_rel_x_offset']
    assert tower['silhouette_symmetry'] > ms1['silhouette_symmetry']
    assert 'frame_id' not in tower  # image-only features, no filename/GT fields


def test_appearance_gate_accepts_target_and_rejects_ms1():
    tower_feat = ce.appearance_features(_tower_image(), [110.0, 76.0, 100.0, 124.0])
    ms1_feat = ce.appearance_features(_ms1_image(), [148.0, 40.0, 52.0, 180.0])
    gate = ce.make_appearance_gate()
    assert gate(tower_feat)['accepted'] is True
    assert gate(ms1_feat)['accepted'] is False


def test_appearance_gate_does_not_require_green_when_absent():
    # far target: no strict green pixels but wide tapered body; the gate must not
    # reject it purely for missing green (MS1 is separated by aspect/silhouette)
    far_target = {'aspect_ratio': 1.2, 'height_px': 18.0, 'width_px': 15.0,
                  'green_pixels': 0, 'green_rel_x_offset': None,
                  'green_rel_y': None, 'green_top_band_ratio': 0.0,
                  'silhouette_symmetry': 0.75, 'fill_ratio': 0.4}
    ms1 = {'aspect_ratio': 3.2, 'height_px': 120.0, 'width_px': 38.0,
           'green_pixels': 0, 'green_rel_x_offset': None, 'green_rel_y': None,
           'green_top_band_ratio': 0.0, 'silhouette_symmetry': 0.80,
           'fill_ratio': 0.3}
    gate = ce.make_appearance_gate(dict(ce.DEFAULT_GATE_THRESHOLDS))
    assert gate(far_target)['accepted'] is True
    assert gate(ms1)['accepted'] is False

def test_appearance_gate_v2_uses_width_over_height_and_green_rel_y():
    target = {'aspect_ratio': 0.68, 'aspect_ratio_w_over_h': 1.46,
              'height_px': 36.0, 'width_px': 53.0, 'green_pixels': 4,
              'green_rel_x_offset': 0.05, 'green_rel_y': 0.24,
              'green_top_band_ratio': 0.4, 'silhouette_symmetry': 0.82,
              'fill_ratio': 0.4, 'keypoint_emitted': True}
    ms1 = dict(target, aspect_ratio=3.06, aspect_ratio_w_over_h=0.33,
               green_rel_y=0.09, height_px=121.0)
    far_target = {'aspect_ratio': 1.5, 'aspect_ratio_w_over_h': 0.67,
                  'height_px': 22.0, 'width_px': 15.0, 'green_pixels': 0,
                  'green_rel_x_offset': None, 'green_rel_y': None,
                  'green_top_band_ratio': 0.0, 'silhouette_symmetry': 0.75,
                  'fill_ratio': 0.3, 'keypoint_emitted': False}
    tiny = dict(far_target, height_px=12.0)
    assert ce.appearance_gate_v2(target)['accepted'] is True
    assert ce.appearance_gate_v2(ms1)['accepted'] is False
    assert ce.appearance_gate_v2(far_target)['accepted'] is True
    assert ce.appearance_gate_v2(tiny)['accepted'] is False
    # gate_v2 must read the emitted-keypoint flag from the features when the
    # wrapper is used; green_rel_y is only meaningful for keypoint emissions
    gate = ce.make_appearance_gate_v2()
    assert gate(dict(target))['accepted'] is True
    assert gate(dict(ms1))['accepted'] is False

def test_appearance_gate_sweep_reports_false_block_and_miss_block():
    tower_feat = ce.appearance_features(_tower_image(), [110.0, 76.0, 100.0, 124.0])
    ms1_feat = ce.appearance_features(_ms1_image(), [148.0, 40.0, 52.0, 180.0])
    proposals = [
        {'kind': 'TARGET', 'features': tower_feat},
        {'kind': 'TARGET', 'features': dict(tower_feat, aspect_ratio=2.6)},
        {'kind': 'MS1', 'features': ms1_feat},
        {'kind': 'MS1', 'features': dict(ms1_feat, aspect_ratio=1.1)},
    ]
    sweep = ce.sweep_appearance_gate(proposals)
    assert 'points' in sweep and sweep['points']
    assert sweep['recommended']['status'] in ('PROPOSED',
                                               'PROPOSED_WEAK_SEPARATION')
    assert sweep['recommended']['false_block'] >= 0
    assert sweep['recommended']['miss_block'] >= 0
    assert 'false_block_rate' in sweep['recommended']
    cost = ce.measure_feature_cost([_tower_image(), _ms1_image()], [110.0, 76.0, 100.0, 124.0])
    assert cost['frames'] == 2
    assert cost['median_ms'] >= 0


# --- saved predictions path -------------------------------------------------

def _write_saved(tmp_path):
    labels = {'schema_version': 'dsh.tower_annotation.v2_1', 'annotations': [
        annotation('a.png'),
        annotation('b.png', reference='UNAVAILABLE'),
        annotation('c.png', present=False),
    ]}
    labels_path = tmp_path / 'labels.json'
    labels_path.write_text(json.dumps(labels), encoding='utf-8')
    rows = [
        {'frame_id': 'a.png', 'prediction': prediction()},
        {'frame_id': 'b.png', 'prediction': prediction(keypoint=None)},
        {'frame_id': 'c.png', 'prediction': prediction(status='NOT_DETECTED',
                                                       landmark_id=None,
                                                       bbox=None, keypoint=None)},
    ]
    preds_path = tmp_path / 'predictions.jsonl'
    preds_path.write_text(''.join(json.dumps(r) + '\n' for r in rows),
                          encoding='utf-8')
    return labels_path, preds_path


def test_evaluate_from_saved_predictions_and_cli(tmp_path):
    labels_path, preds_path = _write_saved(tmp_path)
    protocol_path = tmp_path / 'protocol.json'
    protocol_path.write_text(json.dumps(protocol_doc()), encoding='utf-8')
    result = ce.evaluate_saved(labels_path, preds_path, protocol_path)
    assert result['summary']['domains']['all_positive']['denominator'] == 2
    assert result['summary']['domains']['all_positive']['success'] == 2
    out = tmp_path / 'out'
    completed = subprocess.run(
        [sys.executable,
         str(REPO_ROOT / 'scripts' / 'evaluate_landmark_consumer.py'),
         '--labels', str(labels_path), '--predictions', str(preds_path),
         '--protocol', str(protocol_path), '--output-dir', str(out)],
        cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert (out / 'consumer_metrics.json').is_file()
    assert (out / 'rows.jsonl').is_file()
    again = subprocess.run(
        [sys.executable,
         str(REPO_ROOT / 'scripts' / 'evaluate_landmark_consumer.py'),
         '--labels', str(labels_path), '--predictions', str(preds_path),
         '--protocol', str(protocol_path), '--output-dir', str(out)],
        cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert again.returncode == 3


def test_parity_evidence_parser_counts_decision_layers(tmp_path):
    evidence = {
        'pairs': {
            'pt_vs_onnx': {
                'observation_flips': 2,
                'joint_flips': 1,
                'identity_flips': 3,
                'rejection_flips': 1,
                'bearing_flips_over_tau': 4,
                'frames': 10,
            }
        }
    }
    path = tmp_path / 'parity.json'
    path.write_text(json.dumps(evidence), encoding='utf-8')
    summary = ce.parse_parity_evidence(path)
    assert summary['layers']['observation_flips'] == 2
    assert summary['layers']['identity_flips'] == 3
    assert summary['layers']['bearing_flips_over_tau'] == 4
    assert summary['frames'] == 10