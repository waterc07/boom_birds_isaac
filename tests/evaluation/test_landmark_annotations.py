"""Annotation schema and coordinate-transform tests."""
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from boom_birds.evaluation.landmark_annotations import (
    ANNOTATION_VERSION, ANNOTATION_VERSION_V2, hflip_annotation,
    letterbox_annotation, roundtrip_letterbox, validate_document,
    yolo_pose_target)


def base_annotation():
    return {
        'schema_version': ANNOTATION_VERSION,
        'annotations': [{
            'frame_id': 'f1',
            'image': 'images/f1.png',
            'image_sha256': '0' * 64,
            'image_width': 320,
            'image_height': 240,
            'source': {'split': 'development'},
            'target': {'class': 'tower', 'present': True,
                       'visibility': 'FULL'},
            'geometry': {
                'bbox_xywh': [100, 50, 80, 100],
                'keypoint': {'name': 'green_roof_light_center',
                             'x': 140, 'y': 55, 'visible': True},
                'reference_status': 'MANUAL_APPROX',
            },
            'negative_type': None,
            'annotator': 'agent',
        }],
    }


def test_letterbox_transform_bbox_and_keypoint():
    annotation = base_annotation()['annotations'][0]
    transformed = letterbox_annotation(annotation, 320, 240, 640, 640)
    # scale=2, y pad=80
    assert transformed['scale'] == pytest.approx(2.0)
    assert transformed['bbox_xywh'] == pytest.approx([200, 180, 160, 200])
    assert transformed['keypoint'] == pytest.approx([280, 190])


def test_letterbox_roundtrip_restores_source_coordinates():
    annotation = base_annotation()['annotations'][0]
    restored = roundtrip_letterbox(annotation, 320, 240, 960, 960)
    assert restored['bbox_xywh'] == pytest.approx([100, 50, 80, 100])
    assert restored['keypoint'] == pytest.approx([140, 55])


def test_hflip_keeps_keypoint_inside_box():
    annotation = base_annotation()['annotations'][0]
    transformed = hflip_annotation(annotation, 320)
    assert transformed['bbox_xywh'] == pytest.approx([140, 50, 80, 100])
    assert transformed['keypoint'] == pytest.approx([180, 55])


def prepared_doc(tmp_path):
    doc = base_annotation()
    image_path = tmp_path / 'images' / 'f1.png'
    image_path.parent.mkdir(parents=True)
    Image.new('RGB', (320, 240), (128, 128, 128)).save(image_path)
    doc['annotations'][0]['image_sha256'] = hashlib.sha256(
        image_path.read_bytes()).hexdigest()
    return doc


def test_absent_target_rejects_bbox(tmp_path):
    doc = prepared_doc(tmp_path)
    doc['annotations'][0]['target']['present'] = False
    doc['annotations'][0]['negative_type'] = 'TARGET_ABSENT'
    errors, warnings = validate_document(doc, tmp_path)
    assert any('absent target has bbox' in error for error in errors)


def test_sealed_claim_is_rejected(tmp_path):
    doc = prepared_doc(tmp_path)
    doc['annotations'][0]['source']['split'] = 'sealed_test'
    errors, _ = validate_document(doc, tmp_path)
    assert any('must not claim sealed_test' in error for error in errors)


# ---------------------------------------------------------------------------
# schema v2 (dsh.tower_annotation.v2): bbox scope, visibility/truncation
# precedence, reference-unavailable reasons, undecidable presence, candidates,
# annotator provenance, pixel basis and the YOLO 1-keypoint export mapping.
# ---------------------------------------------------------------------------

V2 = ANNOTATION_VERSION_V2


def v2_annotation():
    return {
        'frame_id': 'f1',
        'image': 'images/f1.png',
        'image_sha256': '0' * 64,
        'image_width': 320,
        'image_height': 240,
        'source': {
            'run': 'sensor_shadow',
            'family': 'geo_north_test',
            'group_id': 'geo_north_test_g1',
            'split': 'exposed_development',
            'generation': 1,
            'sequence': 182,
        },
        'target': {
            'landmark_id': 'RMUC2027_CENTRAL_TOWER_PROPOSED',
            'class': 'tower',
            'present': True,
            'undecidable': False,
            'visibility': 'FULL',
            'truncated': False,
            'occluded': False,
            'ambiguous': False,
            'ambiguous_reason': None,
        },
        'geometry': {
            'bbox_xywh': [100, 50, 80, 100],
            'keypoint': {'name': 'green_roof_light_center',
                         'x': 140, 'y': 55, 'visible': True},
            'reference_status': 'MANUAL_APPROX',
            'reference_unavailable_reason': None,
            'reference_source': 'MANUAL_VISUAL',
        },
        'candidates': [],
        'negative_type': None,
        'annotator': {
            'annotator_type': 'AGENT_PROXY',
            'annotator_id': 'test-agent',
            'independent_of_model_dev': True,
            'independent_of_detector_cue': False,
            'review_status': 'UNREVIEWED',
        },
        'pixel_basis': {
            'image_width': 320,
            'image_height': 240,
            'fx_px': 160,
            'cx_px': 160,
            'cy_px': 120,
            'projection_model': 'PINHOLE',
            'bearing_formula': 'atan2(x - cx_px, fx_px)',
        },
        'notes': '',
    }


def v2_doc():
    return {'schema_version': V2, 'annotations': [v2_annotation()]}


def prepared_v2(tmp_path):
    doc = v2_doc()
    image_path = tmp_path / 'images' / 'f1.png'
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (320, 240), (128, 128, 128)).save(image_path)
    doc['annotations'][0]['image_sha256'] = hashlib.sha256(
        image_path.read_bytes()).hexdigest()
    return doc


def errors_of(doc, tmp_path):
    errors, _ = validate_document(doc, tmp_path)
    return errors


def test_v2_valid_document_passes(tmp_path):
    errors = errors_of(prepared_v2(tmp_path), tmp_path)
    assert errors == []


def test_v2_strict_reference_status_rejects_free_text(tmp_path):
    doc = prepared_v2(tmp_path)
    doc['annotations'][0]['geometry']['reference_status'] = \
        'UNAVAILABLE_GREEN_LIGHT_NOT_VISIBLE'
    assert any('reference_status' in error for error in errors_of(doc, tmp_path))


def test_v2_unavailable_reference_requires_reason_enum(tmp_path):
    doc = prepared_v2(tmp_path)
    ann = doc['annotations'][0]
    ann['geometry']['keypoint'] = None
    ann['geometry']['reference_status'] = 'UNAVAILABLE'
    ann['geometry']['reference_unavailable_reason'] = None
    errors = errors_of(doc, tmp_path)
    assert any('reference_unavailable_reason' in error for error in errors)


def test_v2_unknown_unavailable_reason_rejected(tmp_path):
    doc = prepared_v2(tmp_path)
    ann = doc['annotations'][0]
    ann['geometry']['keypoint'] = None
    ann['geometry']['reference_status'] = 'UNAVAILABLE'
    ann['geometry']['reference_unavailable_reason'] = 'BECAUSE_I_SAID_SO'
    assert any('reference_unavailable_reason' in error for error in errors_of(doc, tmp_path))


def test_v2_absent_target_rejects_bbox_and_requires_negative_type(tmp_path):
    doc = prepared_v2(tmp_path)
    ann = doc['annotations'][0]
    ann['target']['present'] = False
    ann['target']['visibility'] = 'ABSENT'
    ann['geometry']['keypoint'] = None
    ann['geometry']['bbox_xywh'] = [100, 50, 80, 100]
    ann['negative_type'] = None
    errors = errors_of(doc, tmp_path)
    assert any('absent target has bbox' in error for error in errors)
    assert any('negative_type' in error for error in errors)


def test_v2_partial_visibility_requires_truncated_or_occluded(tmp_path):
    doc = prepared_v2(tmp_path)
    ann = doc['annotations'][0]
    ann['target']['visibility'] = 'PARTIAL'
    ann['target']['truncated'] = False
    ann['target']['occluded'] = False
    errors = errors_of(doc, tmp_path)
    assert any('PARTIAL' in error for error in errors)


def test_v2_truncated_flag_must_match_partial(tmp_path):
    doc = prepared_v2(tmp_path)
    ann = doc['annotations'][0]
    ann['target']['truncated'] = True
    errors = errors_of(doc, tmp_path)
    assert any('truncated' in error for error in errors)


def test_v2_full_occlusion_may_hide_geometry_but_needs_reason(tmp_path):
    doc = prepared_v2(tmp_path)
    ann = doc['annotations'][0]
    ann['target']['visibility'] = 'OCCLUDED'
    ann['target']['occluded'] = True
    ann['geometry']['bbox_xywh'] = None
    ann['geometry']['keypoint'] = None
    ann['geometry']['reference_status'] = 'UNAVAILABLE'
    ann['geometry']['reference_unavailable_reason'] = 'REFERENCE_OCCLUDED'
    errors = errors_of(doc, tmp_path)
    assert errors == []


def test_v2_undecidable_presence_has_no_geometry_and_needs_reason(tmp_path):
    doc = prepared_v2(tmp_path)
    ann = doc['annotations'][0]
    ann['target']['present'] = False
    ann['target']['undecidable'] = True
    ann['target']['visibility'] = 'UNKNOWN'
    ann['target']['undecidable_reason'] = 'SIMILAR_STRUCTURE_CANDIDATE'
    ann['geometry'] = {'bbox_xywh': None, 'keypoint': None,
                       'reference_status': 'NOT_APPLICABLE',
                       'reference_unavailable_reason': None,
                       'reference_source': 'NOT_APPLICABLE'}
    ann['negative_type'] = None
    errors = errors_of(doc, tmp_path)
    assert errors == []
    # "uncertain" must never be written as a confirmed absence
    ann['negative_type'] = 'TARGET_ABSENT'
    assert any('negative_type' in error for error in errors_of(doc, tmp_path))


def test_v2_ambiguous_requires_candidates_and_reason(tmp_path):
    doc = prepared_v2(tmp_path)
    ann = doc['annotations'][0]
    ann['target']['ambiguous'] = True
    ann['target']['ambiguous_reason'] = 'MULTIPLE_SIMILAR_STRUCTURES'
    ann['candidates'] = []
    errors = errors_of(doc, tmp_path)
    assert any('candidates' in error for error in errors)
    ann['candidates'] = [{
        'candidate_id': 'c1', 'bbox_xywh': [10, 10, 20, 30],
        'keypoint': None, 'green_cue': {'x': 20, 'y': 12},
        'source': 'COLOR_CUE', 'note': '',
    }]
    assert errors_of(doc, tmp_path) == []


def test_v2_candidate_source_enum_and_bounds(tmp_path):
    doc = prepared_v2(tmp_path)
    ann = doc['annotations'][0]
    ann['target']['ambiguous'] = True
    ann['target']['ambiguous_reason'] = 'IDENTITY_UNRESOLVED'
    ann['candidates'] = [{
        'candidate_id': 'c1', 'bbox_xywh': [10, 10, 400, 30],
        'keypoint': None, 'green_cue': None,
        'source': 'DETECTOR', 'note': '',
    }]
    errors = errors_of(doc, tmp_path)
    assert any('candidate' in error for error in errors)


def test_v2_annotator_provenance_required(tmp_path):
    doc = prepared_v2(tmp_path)
    del doc['annotations'][0]['annotator']['annotator_type']
    assert any('annotator' in error for error in errors_of(doc, tmp_path))
    doc = prepared_v2(tmp_path)
    doc['annotations'][0]['annotator']['annotator_type'] = 'ROBOT'
    assert any('annotator' in error for error in errors_of(doc, tmp_path))


def test_v2_pixel_basis_required_and_consistent(tmp_path):
    doc = prepared_v2(tmp_path)
    ann = doc['annotations'][0]
    ann['pixel_basis']['image_width'] = 640
    errors = errors_of(doc, tmp_path)
    assert any('pixel_basis' in error for error in errors)
    doc = prepared_v2(tmp_path)
    del doc['annotations'][0]['pixel_basis']
    assert any('pixel_basis' in error for error in errors_of(doc, tmp_path))


def test_v2_similar_structure_negative_requires_candidate(tmp_path):
    doc = prepared_v2(tmp_path)
    ann = doc['annotations'][0]
    ann['target']['present'] = False
    ann['target']['visibility'] = 'ABSENT'
    ann['geometry'] = {'bbox_xywh': None, 'keypoint': None,
                       'reference_status': 'NOT_APPLICABLE',
                       'reference_unavailable_reason': None,
                       'reference_source': 'NOT_APPLICABLE'}
    ann['negative_type'] = 'SIMILAR_STRUCTURE'
    ann['candidates'] = []
    errors = errors_of(doc, tmp_path)
    assert any('candidate' in error for error in errors)


def test_v1_documents_still_validate(tmp_path):
    errors = errors_of(prepared_doc(tmp_path), tmp_path)
    assert errors == []


def test_yolo_export_visible_keypoint():
    target, sidecar, reason = yolo_pose_target(
        v2_annotation(), model_width=640, model_height=640)
    assert reason is None
    # letterbox: scale 2, pad_y 80 -> bbox (200,180,160,200), kp (280,190)
    assert target['bbox_norm'] == pytest.approx([0.4375, 0.4375, 0.25, 0.3125])
    assert target['keypoint_norm'] == pytest.approx([0.4375, 0.296875])
    assert target['keypoint_visibility'] == 1
    assert sidecar['reference_status'] == 'MANUAL_APPROX'


def test_yolo_export_invisible_reference_uses_bbox_center_with_v0():
    ann = v2_annotation()
    ann['geometry']['keypoint'] = None
    ann['target']['visibility'] = 'PARTIAL'
    ann['target']['truncated'] = True
    ann['geometry']['reference_status'] = 'UNAVAILABLE'
    ann['geometry']['reference_unavailable_reason'] = 'REFERENCE_OUT_OF_FRAME'
    target, sidecar, reason = yolo_pose_target(ann, 640, 640)
    assert reason is None
    assert target['keypoint_visibility'] == 0
    # placeholder = bbox centre (280, 280) in the 640x640 model input
    assert target['keypoint_norm'] == pytest.approx([0.4375, 0.4375])
    assert sidecar['reference_unavailable_reason'] == 'REFERENCE_OUT_OF_FRAME'


def test_yolo_export_absent_and_ambiguous_are_excluded():
    ann = v2_annotation()
    ann['target'].update({'present': False, 'visibility': 'ABSENT'})
    ann['geometry'].update({'bbox_xywh': None, 'keypoint': None,
                            'reference_status': 'NOT_APPLICABLE',
                            'reference_source': 'NOT_APPLICABLE'})
    ann['negative_type'] = 'TARGET_ABSENT'
    target, sidecar, reason = yolo_pose_target(ann, 640, 640)
    assert target is None
    assert reason == 'TARGET_ABSENT'
    ann['target'].update({'present': True, 'visibility': 'FULL',
                          'ambiguous': True,
                          'ambiguous_reason': 'MULTIPLE_SIMILAR_STRUCTURES'})
    ann['geometry'].update({'bbox_xywh': [100, 50, 80, 100],
                            'reference_status': 'MANUAL_APPROX'})
    ann['negative_type'] = None
    target, sidecar, reason = yolo_pose_target(ann, 640, 640)
    assert target is None
    assert reason == 'AMBIGUOUS'


def test_yolo_export_undecidable_is_excluded():
    ann = v2_annotation()
    ann['target'].update({'present': False, 'undecidable': True,
                          'visibility': 'UNKNOWN',
                          'undecidable_reason': 'SIMILAR_STRUCTURE_CANDIDATE'})
    target, sidecar, reason = yolo_pose_target(ann, 640, 640)
    assert target is None
    assert reason == 'UNDECIDABLE'


def test_yolo_sidecar_keeps_hidden_annotation_fields():
    ann = v2_annotation()
    ann['target'].update({'truncated': True, 'visibility': 'PARTIAL'})
    _, sidecar, _ = yolo_pose_target(ann, 640, 640)
    for field in ('truncated', 'occluded', 'ambiguous', 'reference_status',
                  'reference_unavailable_reason', 'group_id', 'split'):
        assert field in sidecar
