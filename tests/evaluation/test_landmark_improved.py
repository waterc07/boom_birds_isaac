"""Tests for the limited multi-view/anchor detector (no Isaac, no truth)."""
import json
import math
from pathlib import Path

import cv2
import numpy as np

from boom_birds.evaluation.landmark_improved import MultiViewAnchorDetector


def write_meta(tmp_path, *, anchor_frac=(0.5, 0.1)):
    template = np.zeros((50, 40), dtype=np.uint8)
    template[10:45, 5:35] = 200
    template[5:9, 17:23] = 255
    template_path = tmp_path / 't.png'
    cv2.imwrite(str(template_path), template)
    meta = {
        'entries': [{
            'template_id': 'dev_view',
            'path': str(template_path),
            'sha256': __import__('hashlib').sha256(
                template_path.read_bytes()).hexdigest(),
            'anchor_fraction_xy': list(anchor_frac),
            'anchor_px_in_template': [20.0, 5.0],
        }],
    }
    meta_path = tmp_path / 'templates.json'
    meta_path.write_text(json.dumps(meta), encoding='utf-8')
    return meta_path, template


def test_multiview_detector_uses_anchor_for_bearing(tmp_path):
    meta_path, template = write_meta(tmp_path)
    image = np.zeros((160, 200), dtype=np.uint8)
    image[40:90, 70:110] = template
    image_path = tmp_path / 'image.png'
    cv2.imwrite(str(image_path), image)
    detector = MultiViewAnchorDetector(meta_path, threshold=0.8, scales=(1.0,))
    detection = detector.detect(image_path, [[100.0, 0, 100.0],
                                             [0, 100.0, 80.0], [0, 0, 1.0]])
    assert detection.status == 'DETECTED'
    assert detection.template_id == 'dev_view'
    assert detection.bbox_xywh is not None
    assert detection.anchor_xy is not None
    assert detection.bearing_source == 'TEMPLATE_ANCHOR_GREEN_LIGHT'
    expected = math.atan2((70 + 0.5 * 40) - 100.0, 100.0)
    assert abs(detection.bearing_rad - expected) < 0.02
    assert detection.distance_m is None


def test_multiview_detector_reports_not_detected_below_threshold(tmp_path):
    meta_path, _ = write_meta(tmp_path)
    image_path = tmp_path / 'blank.png'
    cv2.imwrite(str(image_path), np.zeros((160, 200), dtype=np.uint8))
    detector = MultiViewAnchorDetector(meta_path, threshold=0.7, scales=(1.0,))
    detection = detector.detect(image_path, [[100.0, 0, 100.0],
                                             [0, 100.0, 80.0], [0, 0, 1.0]])
    assert detection.status in ('NOT_DETECTED', 'UNKNOWN')
    assert detection.distance_m is None


import pytest


@pytest.mark.parametrize('scale', [0.5, 0.8, 1.0])
def test_anchor_mapping_is_scaled_with_template(tmp_path, scale):
    """Full-image bbox + scaled template anchor must stay on the same feature."""
    meta_path, template = write_meta(tmp_path)
    scaled = cv2.resize(template, None, fx=scale, fy=scale,
                        interpolation=cv2.INTER_AREA)
    th, tw = scaled.shape
    image = np.zeros((240, 300), dtype=np.uint8)
    image[50:50 + th, 70:70 + tw] = scaled
    image_path = tmp_path / ('scale_%s.png' % scale)
    cv2.imwrite(str(image_path), image)
    detector = MultiViewAnchorDetector(meta_path, threshold=0.8,
                                       scales=(scale,))
    intrinsics = [[100.0, 0, 100.0], [0, 100.0, 80.0], [0, 0, 1.0]]
    detection = detector.detect(image_path, intrinsics)
    assert detection.status == 'DETECTED'
    assert detection.bbox_xywh[0] == pytest.approx(70, abs=1)
    assert detection.anchor_xy[0] == pytest.approx(
        70 + 0.5 * tw, abs=1)
    assert detection.anchor_xy[1] == pytest.approx(
        50 + 0.1 * th, abs=1)
