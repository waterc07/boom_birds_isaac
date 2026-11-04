"""Executable toolchain tests: letterbox, YOLO-pose label conversion, decoding.

TDD order: these tests were written before
'src/boom_birds/evaluation/landmark_yolo.py' and the evaluation script existed.
They pin the conversion rules from
configs/perception/landmark_annotation_spec_v2.json (#derived_model_format) and
the v2.1 pilot feedback P1-P3 (four-edge truncation, green_pixels>=3 reference
criterion, TARGET_ABSENT + unverified confuser), plus the observation-record
decoding contract from
docs/reports/perception/LANDMARK_TASK_AND_EXPERIMENT_DEFINITION_20261104.md.
"""
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest
from PIL import Image

from boom_birds.evaluation import landmark_yolo as yolo


REPO_ROOT = Path(__file__).resolve().parents[2]


# --- fixtures ---------------------------------------------------------------

def annotation(frame_id='frame_001.png', **overrides):
    """A complete v2 annotation; nested dicts can be overridden by keyword."""
    doc = {
        'frame_id': frame_id,
        'image': 'images/' + frame_id,
        'image_sha256': 'deadbeef',
        'image_width': 320,
        'image_height': 240,
        'source': {'run': 'run1', 'family': 'lmf_sweep',
                   'group_id': 'g_lmf_sweep', 'split': 'test'},
        'target': {
            'landmark_id': 'RMUC2027_CENTRAL_TOWER_PROPOSED',
            'class': 'tower', 'present': True, 'undecidable': False,
            'visibility': 'FULL', 'truncated': False, 'occluded': False,
            'ambiguous': False, 'ambiguous_reason': None,
            'undecidable_reason': None,
        },
        'geometry': {
            'bbox_xywh': [97, 106, 83, 74],
            'keypoint': {'name': 'green_roof_light_center', 'x': 99.9,
                         'y': 109.9, 'visible': True},
            'reference_status': 'MANUAL_APPROX',
            'reference_unavailable_reason': None,
            'reference_source': 'MANUAL_VISUAL',
        },
        'candidates': [],
        'negative_type': None,
        'annotator': {'annotator_type': 'AGENT_PROXY', 'annotator_id': 't',
                      'independent_of_model_dev': True,
                      'independent_of_detector_cue': True,
                      'review_status': 'SELF_CHECKED'},
        'pixel_basis': {'image_width': 320, 'image_height': 240,
                        'fx_px': 160.0, 'cx_px': 160.0, 'cy_px': 120.0,
                        'projection_model': 'PINHOLE',
                        'bearing_formula': 'atan2(x - cx_px, fx_px)'},
        'notes': '',
    }
    for key, value in overrides.items():
        if key in ('target', 'geometry', 'source', 'annotator', 'pixel_basis'):
            doc[key].update(value)
        else:
            doc[key] = value
    return doc


def absent_annotation(frame_id='absent_001.png', negative_type='TARGET_ABSENT',
                      **overrides):
    doc = annotation(frame_id)
    doc['target'].update({'present': False, 'undecidable': False,
                          'visibility': 'ABSENT', 'truncated': False,
                          'occluded': False, 'ambiguous': False})
    doc['geometry'].update({'bbox_xywh': None, 'keypoint': None,
                            'reference_status': 'NOT_APPLICABLE',
                            'reference_source': 'NOT_APPLICABLE'})
    doc['negative_type'] = negative_type
    for key, value in overrides.items():
        if key in ('target', 'geometry', 'source'):
            doc[key].update(value)
        else:
            doc[key] = value
    return doc


INTRINSICS = {'fx_px': 160.0, 'cx_px': 160.0, 'cy_px': 120.0}


def candidate(bbox, score=0.9, keypoint=(120.0, 130.0), kpt_conf=0.9,
              **overrides):
    cand = {'bbox_xywh': list(bbox), 'score': score, 'class_id': 0,
            'keypoint_px': None if keypoint is None else list(keypoint),
            'keypoint_confidence': kpt_conf, 'green_pixels': None}
    cand.update(overrides)
    return cand


def decode(candidates, **kwargs):
    kwargs.setdefault('image_width', 320)
    kwargs.setdefault('image_height', 240)
    kwargs.setdefault('intrinsics', dict(INTRINSICS))
    kwargs.setdefault('frame_id', 'frame_001.png')
    return yolo.decode_candidates(candidates, **kwargs)


# --- letterbox forward / inverse -------------------------------------------

def test_letterbox_forward_scales_and_pads_320x240_to_640():
    lb = yolo.letterbox_params(320, 240, 640, 640)
    assert lb.scale == pytest.approx(2.0)
    assert lb.pad_x == pytest.approx(0.0)
    assert lb.pad_y == pytest.approx(80.0)
    assert yolo.point_to_model((10.0, 20.0), lb) == pytest.approx((20.0, 120.0))
    assert yolo.bbox_to_model([10.0, 20.0, 30.0, 40.0], lb) == pytest.approx(
        [20.0, 120.0, 60.0, 80.0])


@pytest.mark.parametrize('source,model', [
    ((320, 240), (640, 640)),
    ((1280, 720), (640, 640)),
    ((640, 480), (960, 544)),
    ((97, 61), (640, 640)),
])
def test_letterbox_bbox_and_keypoint_roundtrip(source, model):
    lb = yolo.letterbox_params(source[0], source[1], model[0], model[1])
    bbox = [12.5, 33.25, 41.0, 70.5]
    keypoint = (55.5, 61.25)
    model_bbox = yolo.bbox_to_model(bbox, lb)
    model_point = yolo.point_to_model(keypoint, lb)
    assert yolo.bbox_from_model(model_bbox, lb) == pytest.approx(bbox)
    assert yolo.point_from_model(model_point, lb) == pytest.approx(keypoint)


def test_letterbox_rejects_degenerate_source_size():
    with pytest.raises(yolo.LandmarkYoloError):
        yolo.letterbox_params(0, 240, 640, 640)


# --- label conversion -------------------------------------------------------

def test_present_visible_label_has_one_tower_box_and_one_visible_keypoint():
    text, sidecar = yolo.yolo_pose_label(annotation())
    fields = text.split()
    assert len(fields) == 8  # class cx cy w h kx ky v
    assert int(fields[0]) == 0
    values = [float(v) for v in fields[1:]]
    # YOLO txt labels are normalized to the SOURCE image (320x240), not to the
    # 640 letterbox canvas; the ultralytics loader applies the letterbox itself.
    cx = (97 + 83 / 2) / 320
    cy = (106 + 74 / 2) / 240
    w = 83 / 320
    h = 74 / 240
    kx = 99.9 / 320
    ky = 109.9 / 240
    assert values == pytest.approx([cx, cy, w, h, kx, ky, 1.0], abs=1e-6)
    assert sidecar['label_kind'] == 'POSITIVE_KEYPOINT'
    assert sidecar['reference_usable'] is True
    assert sidecar['included_in_training'] is True
    assert sidecar['included_in_anchor_denominator'] is True
    assert sidecar['letterbox'] == pytest.approx(
        {'scale': 2.0, 'pad_x': 0.0, 'pad_y': 80.0})
    assert sidecar['truncated'] is False
    assert sidecar['truncated_edges'] == []


def test_label_normalization_is_source_relative_not_model_canvas():
    """Regression: the 640 letterbox canvas must never leak into the txt label.

    ultralytics LetterBox._update_labels denormalizes labels with the source
    image size and applies scale/pad itself.  Writing model-canvas normalized
    values shifted y by (pad_y - src_h*(scale-1)/2)/model_h, i.e. up to tens of
    pixels, and shrank bbox h by h/w factor.
    """
    text, _ = yolo.yolo_pose_label(annotation())
    _cls, cx, cy, w, h, _kx, _ky, _v = [float(v) for v in text.split()]
    assert (cx, cy) == pytest.approx((138.5 / 320, 143.0 / 240), abs=1e-6)
    assert (w, h) == pytest.approx((83.0 / 320, 74.0 / 240), abs=1e-6)
    # the old (wrong) model-canvas normalization for cy would be 366/640
    assert cy != pytest.approx(366.0 / 640, abs=1e-6)


def test_exported_labels_survive_the_loader_letterbox_roundtrip():
    """Simulate the ultralytics loader: denormalize to source px, then letterbox."""
    text, _ = yolo.yolo_pose_label(annotation())
    _cls, cx, cy, w, h, kx, ky, _v = [float(v) for v in text.split()]
    source = (320, 240)
    letterbox = yolo.letterbox_params(source[0], source[1], 640, 640)
    model_bbox_center = yolo.point_to_model((cx * source[0], cy * source[1]),
                                           letterbox)
    assert model_bbox_center == pytest.approx((277.0, 366.0), abs=1e-3)
    assert (w * source[0] * letterbox.scale,
            h * source[1] * letterbox.scale) == pytest.approx((166.0, 148.0),
                                                              abs=1e-3)
    model_keypoint = yolo.point_to_model((kx * source[0], ky * source[1]),
                                         letterbox)
    assert model_keypoint == pytest.approx((199.8, 299.8), abs=1e-3)


def test_exported_label_roundtrips_back_to_source_pixel_geometry():
    text, _ = yolo.yolo_pose_label(annotation())
    _cls, cx, cy, w, h, kx, ky, _v = [float(v) for v in text.split()]
    src_w, src_h = 320.0, 240.0
    assert (cx * src_w, cy * src_h, w * src_w, h * src_h) == pytest.approx(
        (138.5, 143.0, 83.0, 74.0), abs=1e-3)
    assert (kx * src_w, ky * src_h) == pytest.approx((99.9, 109.9), abs=1e-3)


def test_non_square_letterbox_padding_keeps_bbox_and_keypoint_source_relative():
    # 160x120 -> 640x640: scale 4, pad_y = (640 - 480)/2 = 80
    ann = annotation(image_width=160, image_height=120,
                     geometry={'bbox_xywh': [20, 30, 40, 50],
                               'keypoint': {'x': 25.5, 'y': 33.5,
                                            'visible': True}})
    text, _ = yolo.yolo_pose_label(ann)
    _cls, cx, cy, w, h, kx, ky, _v = [float(v) for v in text.split()]
    assert (cx, cy, w, h) == pytest.approx((40.0 / 160, 55.0 / 120,
                                            40.0 / 160, 50.0 / 120), abs=1e-6)
    assert (kx, ky) == pytest.approx((25.5 / 160, 33.5 / 120), abs=1e-6)
    letterbox = yolo.letterbox_params(160, 120, 640, 640)
    assert yolo.point_to_model((kx * 160, ky * 120), letterbox) == pytest.approx(
        (102.0, 214.0), abs=1e-3)

def test_upstream_declared_model_canvas_space_is_converted_and_recorded():
    # annot clarified (2026-11-04) that yolo_pose_target declares
    # coordinate_space=MODEL_CANVAS_NORMALIZED and deliberately does not set
    # label_normalization, so the exporter must still do the inverse letterbox.
    target, _sidecar, _reason = yolo.yolo_pose_target(annotation(), 640, 640)
    assert target['coordinate_space'] == 'MODEL_CANVAS_NORMALIZED'
    assert 'label_normalization' not in target
    text, sidecar = yolo.yolo_pose_label(annotation())
    assert sidecar['source_target_coordinate_space'] == 'MODEL_CANVAS_NORMALIZED'
    assert sidecar['label_normalization'] == 'SOURCE_IMAGE_PX_OVER_SOURCE_SIZE'
    assert float(text.split()[2]) == pytest.approx(143.0 / 240, abs=1e-6)


def test_unknown_upstream_coordinate_space_fails_loud():
    target, _sidecar, _reason = yolo.yolo_pose_target(annotation(), 640, 640)
    target['coordinate_space'] = 'SOURCE_IMAGE_NORMALIZED'
    with pytest.raises(yolo.LabelConversionError):
        yolo.source_normalized_target(target, annotation())

def test_source_normalized_target_never_transforms_twice():
    # forward compatibility with a future yolo_pose_target that returns
    # source-normalized values and sets the marker itself
    target, _sidecar, _reason = yolo.yolo_pose_target(annotation(), 640, 640)
    normalized = yolo.source_normalized_target(target, annotation())
    assert normalized['label_normalization'] == 'SOURCE_IMAGE_PX_OVER_SOURCE_SIZE'
    again = yolo.source_normalized_target(normalized, annotation())
    assert again['bbox_norm'] == normalized['bbox_norm']
    assert again['keypoint_norm'] == normalized['keypoint_norm']
    text, _ = yolo.yolo_pose_label(annotation())
    assert yolo.format_yolo_pose_line(normalized) == text

def test_reference_invisible_uses_bbox_centre_placeholder_and_visibility_zero():
    ann = annotation(geometry={
        'keypoint': None, 'reference_status': 'UNAVAILABLE',
        'reference_unavailable_reason': 'REFERENCE_OUT_OF_FRAME'})
    text, sidecar = yolo.yolo_pose_label(ann)
    values = [float(v) for v in text.split()[1:]]
    # placeholder is the bbox centre (source-normalized), never a reference
    cx = (97 + 83 / 2) / 320
    cy = (106 + 74 / 2) / 240
    assert values[-3:] == pytest.approx([cx, cy, 0.0], abs=1e-6)
    assert sidecar['label_kind'] == 'POSITIVE_NO_REFERENCE'
    assert sidecar['reference_usable'] is False
    assert sidecar['included_in_anchor_denominator'] is False
    assert sidecar['reference_status'] == 'UNAVAILABLE'
    assert sidecar['reference_unavailable_reason'] == 'REFERENCE_OUT_OF_FRAME'


def test_reference_visible_but_green_pixels_below_threshold_downgrades_to_v0():
    ann = annotation(geometry={'green_pixels': 2})
    text, sidecar = yolo.yolo_pose_label(ann)
    assert float(text.split()[-1]) == 0.0
    assert sidecar['green_pixels'] == 2
    assert sidecar['reference_downgraded'] == 'REFERENCE_TOO_SMALL'
    assert sidecar['reference_usable'] is False
    assert sidecar['included_in_anchor_denominator'] is False


def test_reference_visible_with_recorded_green_pixels_keeps_visibility_one():
    ann = annotation(geometry={'green_pixels': 12})
    text, sidecar = yolo.yolo_pose_label(ann)
    assert float(text.split()[-1]) == 1.0
    assert sidecar['green_pixels'] == 12
    assert sidecar['reference_downgraded'] is None
    assert sidecar['included_in_anchor_denominator'] is True


def test_absent_target_gets_an_empty_label_and_is_listed_explicitly():
    text, sidecar = yolo.yolo_pose_label(absent_annotation())
    assert text == ''
    assert sidecar['label_kind'] == 'EMPTY_NEGATIVE'
    assert sidecar['included_in_training'] is True
    assert sidecar['negative_type'] == 'TARGET_ABSENT'


def test_absent_target_with_unverified_confuser_keeps_candidates_in_sidecar():
    cand = {'candidate_id': 'c1', 'bbox_xywh': [10, 20, 30, 40],
            'green_cue': {'x': 20.0, 'y': 30.0}, 'source': 'ANNOTATOR',
            'note': 'unverified similar structure'}
    ann = absent_annotation(candidates=[cand], confuser_verified=False)
    text, sidecar = yolo.yolo_pose_label(ann)
    assert text == ''
    assert sidecar['negative_type'] == 'TARGET_ABSENT'
    assert sidecar['confuser_verified'] is False
    assert len(sidecar['confusers']) == 1
    assert sidecar['confusers'][0]['candidate_id'] == 'c1'


def test_ambiguous_target_is_excluded_and_sidecar_keeps_the_reason():
    cand = {'candidate_id': 'c1', 'bbox_xywh': [10, 20, 30, 40],
            'source': 'ANNOTATOR'}
    ann = annotation(candidates=[cand], target={
        'ambiguous': True,
        'ambiguous_reason': 'MULTIPLE_SIMILAR_STRUCTURES'})
    text, sidecar = yolo.yolo_pose_label(ann)
    assert text is None
    assert sidecar['exclusion_reason'] == 'AMBIGUOUS'
    assert sidecar['label_kind'] == 'EXCLUDED'
    assert sidecar['included_in_training'] is False
    assert len(sidecar['confusers']) == 1


def test_undecidable_target_is_excluded_from_positives():
    ann = annotation(target={'present': False, 'undecidable': True,
                             'visibility': 'UNKNOWN',
                             'undecidable_reason': 'IDENTITY_UNRESOLVED'})
    ann['geometry'].update({'bbox_xywh': None, 'keypoint': None,
                            'reference_status': 'NOT_APPLICABLE',
                            'reference_source': 'NOT_APPLICABLE'})
    text, sidecar = yolo.yolo_pose_label(ann)
    assert text is None
    assert sidecar['exclusion_reason'] == 'UNDECIDABLE'
    assert sidecar['gt_unobservable'] is True


def test_fully_occluded_present_target_without_bbox_is_excluded_as_unobservable():
    ann = annotation(target={'visibility': 'OCCLUDED', 'occluded': True,
                             'truncated': False},
                     geometry={'bbox_xywh': None, 'keypoint': None,
                               'reference_status': 'UNAVAILABLE',
                               'reference_unavailable_reason': 'REFERENCE_OCCLUDED'})
    text, sidecar = yolo.yolo_pose_label(ann)
    assert text is None
    assert sidecar['exclusion_reason'] == 'GT_UNOBSERVABLE'
    assert sidecar['gt_unobservable'] is True


def test_truncated_frame_clips_box_and_records_four_edge_metadata():
    ann = annotation(target={'truncated': True, 'truncated_edges': ['right', 'bottom'],
                             'visibility': 'PARTIAL'},
                     geometry={'bbox_xywh': [240, 180, 80, 60]})
    text, sidecar = yolo.yolo_pose_label(ann)
    values = [float(v) for v in text.split()[1:5]]
    assert values[2] == pytest.approx(80 / 320)   # clipped width, source-normalized
    assert sidecar['truncated'] is True
    assert sidecar['truncated_edges'] == ['bottom', 'right']
    assert sidecar['visibility'] == 'PARTIAL'


def test_truncated_edges_are_inferred_from_border_touching_boxes_when_absent():
    ann = annotation(target={'truncated': True, 'visibility': 'PARTIAL'},
                     geometry={'bbox_xywh': [240, 10, 80, 60]})
    _, sidecar = yolo.yolo_pose_label(ann)
    assert sidecar['truncated_edges'] == ['right']


def test_label_conversion_requires_image_dimensions():
    ann = annotation()
    del ann['image_width']
    with pytest.raises(yolo.LabelConversionError):
        yolo.yolo_pose_label(ann)


def test_truncated_edges_accepts_the_v2_1_boolean_object():
    ann = annotation(target={'truncated': True, 'visibility': 'PARTIAL',
                             'truncated_edges': {'left': False, 'right': True,
                                                 'top': False, 'bottom': False}},
                     geometry={'bbox_xywh': [240, 100, 80, 60]})
    _, sidecar = yolo.yolo_pose_label(ann)
    assert sidecar['truncated_edges'] == ['right']
    assert sidecar['truncated_edges_flags'] == {
        'left': False, 'right': True, 'top': False, 'bottom': False}
    assert sidecar['truncated'] is True


def test_v2_1_document_schema_is_supported():
    doc = {'schema_version': 'dsh.tower_annotation.v2_1',
           'annotations': [annotation('a.png')]}
    result = yolo.convert_annotation_document(doc)
    assert result['annotation_schema_version'] == 'dsh.tower_annotation.v2_1'
    assert result['counts']['positive_labels'] == 1


def test_v2_1_unverified_confusers_are_recorded_on_a_target_absent_negative():
    confusers = [{'confuser_id': 'cf1',
                  'description': 'unverified similar structure',
                  'bbox_xywh': [10, 20, 30, 40], 'green_cue': None,
                  'verified': False, 'verification_source': None,
                  'verification_note': None, 'source': 'ANNOTATOR'}]
    ann = absent_annotation()
    ann['confusers'] = confusers
    text, sidecar = yolo.yolo_pose_label(ann)
    assert text == ''
    assert sidecar['confuser_verified'] is False
    assert [c['confuser_id'] for c in sidecar['confusers']] == ['cf1']
    assert sidecar['negative_type'] == 'TARGET_ABSENT'


def test_v2_1_verified_confuser_sets_confuser_verified_true():
    ann = absent_annotation(negative_type='SIMILAR_STRUCTURE')
    ann['confusers'] = [{'confuser_id': 'cf1', 'description': 'different tower',
                         'bbox_xywh': [10, 20, 30, 40],
                         'verified': True,
                         'verification_source': 'WORLD_POSE_OR_MAP_DB',
                         'verification_note': 'matches a different landmark id',
                         'source': 'ANNOTATOR'}]
    text, sidecar = yolo.yolo_pose_label(ann)
    assert text == ''
    assert sidecar['confuser_verified'] is True
    assert sidecar['confusers'][0]['verified'] is True


def test_v2_1_truncation_source_and_bbox_source_reach_the_sidecar():
    ann = annotation(target={'truncated': True, 'visibility': 'PARTIAL',
                             'truncated_edges': {'left': False, 'right': False,
                                                 'top': False, 'bottom': True},
                             'truncation_source': {'bottom': 'BOTH'}},
                     geometry={'bbox_xywh': [240, 180, 80, 60],
                               'bbox_source': 'ANNOTATOR_VISUAL'})
    _, sidecar = yolo.yolo_pose_label(ann)
    assert sidecar['truncated_edges'] == ['bottom']
    assert sidecar['truncation_source'] == {'bottom': 'BOTH'}
    assert sidecar['bbox_source'] == 'ANNOTATOR_VISUAL'

def test_convert_document_splits_labels_negatives_and_excluded_frames():
    doc = {'schema_version': 'dsh.tower_annotation.v2', 'annotations': [
        annotation('a.png'),
        annotation('b.png', geometry={'keypoint': None,
                                      'reference_status': 'UNAVAILABLE',
                                      'reference_unavailable_reason':
                                          'REFERENCE_OUT_OF_FRAME'}),
        absent_annotation('c.png'),
        absent_annotation('d.png', negative_type='TARGET_ABSENT',
                          candidates=[{'candidate_id': 'c1',
                                       'bbox_xywh': [5, 6, 7, 8],
                                       'source': 'ANNOTATOR'}],
                          confuser_verified=False),
        annotation('e.png', target={'present': False, 'undecidable': True,
                                    'visibility': 'UNKNOWN',
                                    'undecidable_reason': 'IMAGE_QUALITY'},
                   geometry={'bbox_xywh': None, 'keypoint': None,
                             'reference_status': 'NOT_APPLICABLE',
                             'reference_source': 'NOT_APPLICABLE'}),
        annotation('f.png', target={'ambiguous': True,
                                    'ambiguous_reason': 'IDENTITY_UNRESOLVED'},
                   candidates=[{'candidate_id': 'c1',
                                'bbox_xywh': [10, 20, 30, 40],
                                'source': 'ANNOTATOR'}]),
        annotation('g.png', target={'visibility': 'OCCLUDED', 'occluded': True},
                   geometry={'bbox_xywh': None, 'keypoint': None,
                             'reference_status': 'UNAVAILABLE',
                             'reference_unavailable_reason': 'REFERENCE_OCCLUDED'}),
        annotation('h.png', geometry={'green_pixels': 1}),
    ]}
    result = yolo.convert_annotation_document(doc)
    assert result['counts'] == {
        'frames': 8, 'positive_labels': 3, 'negative_empty_labels': 2,
        'excluded': 3, 'reference_available': 1, 'reference_unavailable': 3,
        'gt_unobservable': 2, 'truncated': 0, 'occluded': 0,
        'undecidable': 1, 'ambiguous': 1,
    }
    assert set(result['labels']) == {'a.png', 'b.png', 'c.png', 'd.png', 'h.png'}
    assert result['labels']['c.png'] == ''
    assert result['absent_frames'] == ['c.png', 'd.png']
    assert [item['frame_id'] for item in result['excluded']] == ['e.png', 'f.png', 'g.png']
    assert len(result['sidecars']) == 8
    assert result['counts_by_family'] == {'lmf_sweep': 8}


def test_convert_document_can_filter_by_split():
    doc = {'schema_version': 'dsh.tower_annotation.v2', 'annotations': [
        annotation('a.png', source={'split': 'val'}),
        annotation('b.png', source={'split': 'train'}),
    ]}
    result = yolo.convert_annotation_document(doc, split='val')
    assert set(result['labels']) == {'a.png'}
    assert result['counts']['frames'] == 2


def test_convert_document_propagates_annotation_errors_when_root_is_given(tmp_path):
    doc = {'schema_version': 'dsh.tower_annotation.v2',
           'annotations': [annotation('missing.png')]}
    with pytest.raises(yolo.LabelConversionError):
        yolo.convert_annotation_document(doc, root=tmp_path)


def test_write_yolo_dataset_writes_txt_labels_and_manifest(tmp_path):
    doc = {'schema_version': 'dsh.tower_annotation.v2', 'annotations': [
        annotation('a.png'), absent_annotation('c.png')]}
    result = yolo.convert_annotation_document(doc)
    manifest = yolo.write_yolo_dataset(result, tmp_path / 'labels')
    assert (tmp_path / 'labels' / 'a.txt').is_file()
    empty = (tmp_path / 'labels' / 'c.txt')
    assert empty.is_file() and empty.read_text(encoding='utf-8') == ''
    assert manifest['label_count'] == 2
    assert set(manifest['label_sha256']) == {'a.png', 'c.png'}
    assert manifest['negatives'] == ['c.png']


def test_write_sidecar_is_one_json_line_per_frame(tmp_path):
    doc = {'schema_version': 'dsh.tower_annotation.v2',
           'annotations': [annotation('a.png'), absent_annotation('c.png')]}
    result = yolo.convert_annotation_document(doc)
    path = yolo.write_sidecar(result, tmp_path / 'sidecar.jsonl')
    lines = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    assert len(lines) == 2
    assert {line['frame_id'] for line in lines} == {'a.png', 'c.png'}


# --- decoding ---------------------------------------------------------------

def test_decoded_single_candidate_claims_identity_and_reference():
    record = decode([candidate([100, 100, 60, 80], score=0.9,
                               keypoint=(150.0, 135.0), kpt_conf=0.9)])
    assert record['schema_version'] == 'dsh.landmark_observation.v1'
    assert record['status'] == 'DETECTED'
    assert record['landmark_class'] == 'tower'
    assert record['landmark_id'] == 'RMUC2027_CENTRAL_TOWER_PROPOSED'
    assert record['identity_claimed'] is True
    assert record['bbox_xywh'] == pytest.approx([100.0, 100.0, 60.0, 80.0])
    assert record['keypoint_px'] == pytest.approx([150.0, 135.0])
    assert record['reference_status'] == 'VISIBLE'
    assert record['image_bearing_deg'] == pytest.approx(
        math.degrees(math.atan2(-10.0, 160.0)))
    assert record['visibility'] == 'FULL'
    assert record['reject_reason'] is None
    assert record['valid'] is True
    assert record['appearance_check'] == 'NOT_EVALUATED'


def test_multiple_candidates_without_margin_reject_identity_but_keep_class():
    record = decode([candidate([100, 100, 60, 80], score=0.90),
                     candidate([200, 100, 40, 60], score=0.85)])
    assert record['status'] == 'DETECTED'
    assert record['candidate_count'] == 2
    assert record['landmark_id'] is None
    assert record['identity_claimed'] is False
    assert record['reject_reason'] == 'MULTIPLE_CANDIDATES'
    assert record['reject_reasons'] == ['MULTIPLE_CANDIDATES']
    assert record['bbox_xywh'] == pytest.approx([100.0, 100.0, 60.0, 80.0])
    assert record['valid'] is True


def test_multiple_candidates_with_clear_margin_selects_the_top_one():
    record = decode([candidate([100, 100, 60, 80], score=0.9),
                     candidate([200, 100, 40, 60], score=0.5)])
    assert record['landmark_id'] == 'RMUC2027_CENTRAL_TOWER_PROPOSED'
    assert record['reject_reason'] is None
    assert record['bbox_xywh'] == pytest.approx([100.0, 100.0, 60.0, 80.0])


def test_candidates_below_tau_det_do_not_count_for_multiplicity():
    record = decode([candidate([100, 100, 60, 80], score=0.9),
                     candidate([200, 100, 40, 60], score=0.10)])
    assert record['candidate_count'] == 1
    assert record['landmark_id'] == 'RMUC2027_CENTRAL_TOWER_PROPOSED'


def test_empty_candidate_list_is_a_not_detected_observation():
    record = decode([])
    assert record['status'] == 'NOT_DETECTED'
    assert record['landmark_id'] is None
    assert record['bbox_xywh'] is None
    assert record['keypoint_px'] is None
    assert record['valid'] is True
    assert record['reject_reason'] is None


def test_low_keypoint_confidence_declares_reference_unavailable_but_keeps_identity():
    record = decode([candidate([100, 100, 60, 80], score=0.9,
                               keypoint=(150.0, 135.0), kpt_conf=0.1)])
    assert record['status'] == 'DETECTED'
    assert record['reference_status'] == 'UNAVAILABLE'
    assert record['keypoint_px'] is None
    assert record['image_bearing_deg'] is None
    assert record['reject_reason'] == 'REFERENCE_UNAVAILABLE'
    # spec v2 derived_model_format: identity claim is still allowed when the
    # reference point is correctly declared unavailable (U1 condition met).
    assert record['landmark_id'] == 'RMUC2027_CENTRAL_TOWER_PROPOSED'


def test_border_touching_box_is_flagged_truncated_with_four_edge_metadata():
    record = decode([candidate([240, 100, 80, 60], score=0.9,
                               keypoint=(280.0, 120.0))])
    assert record['truncated_edges'] == ['right']
    assert record['visibility'] == 'PARTIAL'
    assert record['truncated'] is True
    assert record['reject_reason'] == 'TRUNCATED'
    # the visible portion is large enough -> identity is still allowed
    assert record['landmark_id'] == 'RMUC2027_CENTRAL_TOWER_PROPOSED'


def test_tiny_border_sliver_withholds_identity_as_truncated():
    record = decode([candidate([312, 100, 8, 60], score=0.9,
                               keypoint=(316.0, 120.0))])
    assert record['reject_reason'] == 'TRUNCATED'
    assert record['landmark_id'] is None
    assert record['truncated_edges'] == ['right']


def test_green_pixels_prior_withholds_identity_as_ambiguous():
    record = decode([candidate([100, 100, 60, 80], score=0.9,
                               green_pixels=1)])
    assert record['landmark_id'] is None
    assert record['reject_reason'] == 'TARGET_AMBIGUOUS'
    assert record['appearance_check'] == 'GREEN_LIGHT_BELOW_MINIMUM'


def test_bbox_is_clipped_to_the_image_and_extent_flag_is_recorded():
    record = decode([candidate([300, 90, 60, 80], score=0.9,
                               keypoint=(310.0, 120.0))])
    assert record['bbox_xywh'] == pytest.approx([300.0, 90.0, 20.0, 80.0])
    assert record['bbox_extent_clipped'] is True


def test_missing_calibration_rejects_the_observation():
    record = decode([candidate([100, 100, 60, 80])], intrinsics=None)
    assert record['status'] == 'REJECTED'
    assert record['reject_reason'] == 'MISSING_CALIBRATION'
    assert record['valid'] is False
    assert record['landmark_id'] is None


def test_invalid_image_size_rejects_the_observation():
    record = decode([candidate([100, 100, 60, 80])], image_width=0)
    assert record['status'] == 'REJECTED'
    assert record['reject_reason'] == 'INVALID_IMAGE'
    assert record['valid'] is False


def test_detector_failure_becomes_an_unknown_observation():
    record = yolo.unknown_observation(frame_id='x.png', reason='DETECTOR_ERROR')
    assert record['status'] == 'UNKNOWN'
    assert record['valid'] is False
    assert record['reject_reason'] == 'DETECTOR_ERROR'


def test_observation_maps_to_the_metric_prediction_record():
    record = decode([candidate([100, 100, 60, 80], score=0.9,
                               keypoint=(150.0, 135.0))])
    pred = yolo.observation_to_metric_prediction(record)
    assert pred == {
        'status': 'DETECTED',
        'landmark_id': 'RMUC2027_CENTRAL_TOWER_PROPOSED',
        'bbox_xywh': pytest.approx([100.0, 100.0, 60.0, 80.0]),
        'score': 0.9,
        'keypoint_px': pytest.approx([150.0, 135.0]),
        'reject_reason': None,
    }


def test_observation_rejects_unavailable_intrinsics_shape():
    with pytest.raises(yolo.LandmarkYoloError):
        decode([candidate([1, 2, 3, 4])], intrinsics={'fx_px': 160.0})


# --- model-output adapters --------------------------------------------------

class _Boxes:
    def __init__(self, xyxy, conf, cls):
        self.xyxy = xyxy
        self.conf = conf
        self.cls = cls


class _Keypoints:
    def __init__(self, xy, conf):
        self.xy = xy
        self.conf = conf


class _Result:
    def __init__(self, boxes, keypoints):
        self.boxes = boxes
        self.keypoints = keypoints


def test_ultralytics_adapter_reads_source_coordinate_results():
    result = _Result(
        _Boxes([[150.0, 150.0, 200.0, 220.0]], [0.9], [0.0]),
        _Keypoints([[[160.0, 160.0]]], [[0.8]]))
    record = yolo.decode_ultralytics_result(
        result, image_width=320, image_height=240, intrinsics=dict(INTRINSICS),
        frame_id='a.png')
    assert record['bbox_xywh'] == pytest.approx([150.0, 150.0, 50.0, 70.0])
    assert record['keypoint_px'] == pytest.approx([160.0, 160.0])
    assert record['landmark_id'] == 'RMUC2027_CENTRAL_TOWER_PROPOSED'


def test_ultralytics_adapter_can_invert_model_space_coordinates():
    lb = yolo.letterbox_params(320, 240, 640, 640)
    result = _Result(
        _Boxes([[300.0, 300.0, 400.0, 440.0]], [0.9], [0.0]),
        _Keypoints([[[320.0, 400.0]]], [[0.8]]))
    record = yolo.decode_ultralytics_result(
        result, image_width=320, image_height=240, letterbox=lb,
        coordinates='model', intrinsics=dict(INTRINSICS), frame_id='a.png')
    assert record['bbox_xywh'] == pytest.approx([150.0, 110.0, 50.0, 70.0])
    assert record['keypoint_px'] == pytest.approx([160.0, 160.0])


def test_onnx_pose_output_is_decoded_and_unletterboxed():
    lb = yolo.letterbox_params(320, 240, 640, 640)
    # (1, 4 + num_classes + 3*keypoints = 8, anchors)
    output = [[
        [321.0],          # cx
        [338.0],          # cy
        [41.0],           # w
        [37.0],           # h
        [0.80],           # class 0 score
        [300.0],          # kpt x
        [350.0],          # kpt y
        [0.90],           # kpt confidence
    ]]
    record = yolo.decode_onnx_pose_output(
        output, image_width=320, image_height=240, letterbox=lb,
        intrinsics=dict(INTRINSICS), frame_id='a.png')
    assert record['status'] == 'DETECTED'
    assert record['bbox_xywh'] == pytest.approx([150.25, 119.75, 20.5, 18.5])
    assert record['keypoint_px'] == pytest.approx([150.0, 135.0])
    assert record['score'] == pytest.approx(0.80)


def test_onnx_pose_output_below_threshold_is_not_detected():
    lb = yolo.letterbox_params(320, 240, 640, 640)
    output = [[[100.0], [110.0], [20.0], [30.0], [0.01],
              [100.0], [100.0], [0.5]]]
    record = yolo.decode_onnx_pose_output(
        output, image_width=320, image_height=240, letterbox=lb,
        intrinsics=dict(INTRINSICS), frame_id='a.png')
    assert record['status'] == 'NOT_DETECTED'


# --- ground truth extraction for evaluation ---------------------------------

def test_ground_truth_from_annotation_maps_reference_and_strata():
    gt, reference_px, strata = yolo.ground_truth_from_annotation(annotation())
    assert gt['present'] is True
    assert gt['reference'] == 'VISIBLE'
    assert gt['bbox_xywh'] == [97.0, 106.0, 83.0, 74.0]
    assert reference_px == pytest.approx([99.9, 109.9])
    assert strata['family'] == 'lmf_sweep'
    assert strata['group_id'] == 'g_lmf_sweep'
    assert strata['visibility'] == 'FULL'
    assert strata['scale'] == 'MEDIUM'
    assert strata['truncation'] == 'NOT_TRUNCATED'


def test_ground_truth_from_unavailable_reference_has_no_reference_px():
    ann = annotation(geometry={'keypoint': None,
                               'reference_status': 'UNAVAILABLE',
                               'reference_unavailable_reason': 'REFERENCE_OCCLUDED'})
    gt, reference_px, strata = yolo.ground_truth_from_annotation(ann)
    assert gt['reference'] == 'UNAVAILABLE'
    assert reference_px is None
    assert strata['scale'] == 'MEDIUM'


def test_ground_truth_from_absent_annotation_is_a_negative():
    gt, reference_px, strata = yolo.ground_truth_from_annotation(absent_annotation())
    assert gt['present'] is False
    assert gt['negative_type'] == 'TARGET_ABSENT'
    assert gt['reference'] is None
    assert reference_px is None
    assert strata['scale'] == 'NO_BBOX'
    assert strata['negative_type'] == 'TARGET_ABSENT'


def test_scale_bucket_thresholds_are_explicit():
    assert yolo.scale_bucket([0.0, 0.0, 10.0, 10.0]) == 'TINY'
    assert yolo.scale_bucket([0.0, 0.0, 50.0, 50.0]) == 'SMALL'
    assert yolo.scale_bucket([0.0, 0.0, 100.0, 100.0]) == 'MEDIUM'
    assert yolo.scale_bucket([0.0, 0.0, 200.0, 200.0]) == 'LARGE'


# --- evaluation script (precomputed predictions, no ML dependency) ---------

def _write_eval_fixture(tmp_path):
    images = tmp_path / 'images'
    images.mkdir()
    for name in ('a.png', 'c.png'):
        Image.new('RGB', (320, 240), (20, 20, 20)).save(images / name)
    doc = {'schema_version': 'dsh.tower_annotation.v2', 'annotations': [
        annotation('a.png'), absent_annotation('c.png')]}
    labels = tmp_path / 'labels.json'
    labels.write_text(json.dumps(doc), encoding='utf-8')
    predictions = tmp_path / 'predictions_in.jsonl'
    rows = [
        {'frame_id': 'a.png', 'status': 'DETECTED',
         'landmark_id': 'RMUC2027_CENTRAL_TOWER_PROPOSED',
         'bbox_xywh': [97.0, 106.0, 83.0, 74.0], 'score': 0.9,
         'keypoint_px': [99.9, 109.9], 'reject_reason': None},
        {'frame_id': 'c.png', 'status': 'NOT_DETECTED', 'landmark_id': None,
         'bbox_xywh': None, 'score': None, 'keypoint_px': None,
         'reject_reason': None},
    ]
    predictions.write_text(''.join(json.dumps(r) + '\n' for r in rows),
                           encoding='utf-8')
    return images, labels, predictions


def _run_eval(*args):
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / 'scripts' / 'evaluate_landmark_yolo.py'),
         *[str(a) for a in args]],
        cwd=str(REPO_ROOT), capture_output=True, text=True)


def test_evaluate_script_with_precomputed_predictions_writes_metrics(tmp_path):
    images, labels, predictions = _write_eval_fixture(tmp_path)
    out = tmp_path / 'eval'
    result = _run_eval('--predictions', predictions, '--images', images,
                       '--labels', labels, '--split', 'test',
                       '--output-dir', out)
    assert result.returncode == 0, result.stderr
    metrics = json.loads((out / 'metrics.json').read_text(encoding='utf-8'))
    assert metrics['overall']['denominators']['positives'] == 1
    assert metrics['overall']['denominators']['negatives'] == 1
    assert metrics['overall']['presence']['recall'] == pytest.approx(1.0)
    assert metrics['overall']['joint']['narrow_rate'] == pytest.approx(1.0)
    assert metrics['status'] == 'COMPUTED'
    assert 'family' in metrics['strata']
    assert 'scale' in metrics['strata']
    assert 'worst_conditions' in metrics
    lines = (out / 'predictions.jsonl').read_text(encoding='utf-8').splitlines()
    assert len(lines) == 2
    record = json.loads(lines[0])
    assert record['frame_id'] == 'a.png'
    assert record['gt_frame_id'] == 'a.png'
    assert record['strata']['family'] == 'lmf_sweep'


def test_evaluate_script_refuses_to_overwrite_a_frozen_metrics_file(tmp_path):
    images, labels, predictions = _write_eval_fixture(tmp_path)
    out = tmp_path / 'eval'
    first = _run_eval('--predictions', predictions, '--images', images,
                      '--labels', labels, '--split', 'test',
                      '--output-dir', out)
    assert first.returncode == 0, first.stderr
    second = _run_eval('--predictions', predictions, '--images', images,
                       '--labels', labels, '--split', 'test',
                       '--output-dir', out)
    assert second.returncode == 3
    assert 'overwrite' in (second.stderr + second.stdout).lower()


def test_evaluate_script_fails_clearly_when_the_model_backend_is_missing(tmp_path):
    images, labels, _ = _write_eval_fixture(tmp_path)
    model = tmp_path / 'best.pt'
    model.write_bytes(b'not a real model')
    out = tmp_path / 'eval'
    result = _run_eval('--model', model, '--images', images, '--labels', labels,
                       '--split', 'test', '--output-dir', out)
    assert result.returncode == 2
    assert 'ultralytics' in (result.stderr + result.stdout).lower()