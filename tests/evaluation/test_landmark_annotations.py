"""Annotation schema and coordinate-transform tests."""
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from boom_birds.evaluation.landmark_annotations import (
    ANNOTATION_VERSION, hflip_annotation, letterbox_annotation,
    roundtrip_letterbox, validate_document)


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
