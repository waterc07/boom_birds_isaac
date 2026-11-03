"""Unit tests for the green-seeded tower geometry detector (no Isaac, no truth)."""
import math
from pathlib import Path

import cv2
import numpy as np

from boom_birds.evaluation.tower_geometry import GreenGeometryDetector


def make_image(tmp_path, *, with_structure=True):
    image = np.full((240, 320, 3), 180, dtype=np.uint8)  # BGR gray floor
    if with_structure:
        # saturated structure below the green light; not a template and not truth
        cv2.rectangle(image, (70, 60), (250, 220), (180, 80, 40), -1)
        cv2.rectangle(image, (90, 80), (230, 200), (220, 160, 90), -1)
        cv2.line(image, (75, 60), (75, 220), (250, 250, 250), 3)
        cv2.line(image, (245, 60), (245, 220), (250, 250, 250), 3)
        cv2.line(image, (70, 218), (250, 218), (250, 250, 250), 3)
    # bright-green roof light
    cv2.rectangle(image, (154, 45), (166, 57), (40, 230, 60), -1)
    path = tmp_path / ('structure.png' if with_structure else 'green_only.png')
    cv2.imwrite(str(path), image)
    return path


def test_geometry_detects_green_on_structure_and_outputs_anchor(tmp_path):
    path = make_image(tmp_path)
    detector = GreenGeometryDetector(min_green_area=8)
    intrinsics = [[160.0, 0, 160.0], [0, 160.0, 120.0], [0, 0, 1.0]]
    detection = detector.detect(path, intrinsics)
    assert detection.status == 'DETECTED'
    assert detection.bbox_xywh is not None
    assert detection.anchor_xy is not None
    assert detection.distance_m is None
    assert detection.score is not None
    # green centroid is (160, 51), so the image bearing is ~0
    assert abs(detection.bearing_rad) < 0.02


def test_green_only_without_structure_is_not_accepted(tmp_path):
    path = make_image(tmp_path, with_structure=False)
    detector = GreenGeometryDetector(min_green_area=8)
    detection = detector.detect(path, [[160.0, 0, 160.0],
                                       [0, 160.0, 120.0], [0, 0, 1.0]])
    assert detection.status in ('UNKNOWN', 'NOT_DETECTED')
    assert detection.bbox_xywh is None
    assert detection.distance_m is None
