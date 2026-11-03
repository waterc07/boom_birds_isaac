"""Classic, explainable tower-template landmark detector (no learned model).

The detector consumes only an RGB image, camera intrinsics and a static template
prior.  It never reads simulator truth, robot pose, labels or target coordinates.
The score is normalized cross-correlation, not a calibrated probability.
"""
from dataclasses import asdict, dataclass
import math
from pathlib import Path

import cv2
import numpy as np

DETECTOR_VERSION = 'dsh.tower_template.v1'
SCORE_DEFINITION = 'max_multiscale_TM_CCOEFF_NORMED_grayscale'


@dataclass(frozen=True)
class Detection:
    status: str
    score: float
    bbox_xywh: tuple | None
    bearing_rad: float | None
    distance_m: float | None
    distance_status: str
    scale: float | None


class TowerTemplateDetector:
    def __init__(self, template_path: Path, *, threshold: float,
                 scales=(0.5, 0.65, 0.8, 1.0, 1.15)):
        if not 0.0 <= float(threshold) <= 1.0:
            raise ValueError('threshold must be in [0,1]')
        self.threshold = float(threshold)
        self.scales = tuple(float(value) for value in scales)
        template = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
        if template is None:
            raise ValueError('cannot read template: ' + str(template_path))
        self.template_path = Path(template_path)
        self.template_gray = template.astype(np.float32)

    def detect(self, image_path: Path, intrinsics: list | None) -> Detection:
        image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if image is None or image.size == 0:
            return Detection('UNKNOWN', 0.0, None, None, None,
                             'UNAVAILABLE_INVALID_IMAGE', None)
        image = image.astype(np.float32)
        height, width = image.shape
        best = (-1.0, None, None)
        for scale in self.scales:
            template = cv2.resize(
                self.template_gray, None, fx=scale, fy=scale,
                interpolation=cv2.INTER_AREA)
            th, tw = template.shape
            if th > height or tw > width:
                continue
            scores = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(scores)
            if float(max_val) > best[0]:
                best = (float(max_val), (int(max_loc[0]), int(max_loc[1]),
                                         int(tw), int(th)), scale)
        score, bbox, scale = best
        if bbox is None:
            return Detection('UNKNOWN', 0.0, None, None, None,
                             'UNAVAILABLE_TEMPLATE_LARGER_THAN_IMAGE', None)
        bearing = None
        if intrinsics is not None:
            try:
                fx = float(intrinsics[0][0])
                cx0 = float(intrinsics[0][2])
                cx = bbox[0] + bbox[2] / 2.0
                bearing = math.atan2(cx - cx0, fx)
            except (TypeError, ValueError, IndexError):
                bearing = None
        if score < self.threshold:
            return Detection('NOT_DETECTED', score, bbox, bearing, None,
                             'UNAVAILABLE_DISTANCE_ONLY_CENTER_DEPTH', scale)
        return Detection('DETECTED', score, bbox, bearing, None,
                         'UNAVAILABLE_DISTANCE_ONLY_CENTER_DEPTH', scale)

    def metadata(self):
        return {'detector_version': DETECTOR_VERSION,
                'score_definition': SCORE_DEFINITION,
                'template_sha256': __import__('hashlib').sha256(
                    self.template_path.read_bytes()).hexdigest(),
                'template_shape': list(self.template_gray.shape),
                'threshold': self.threshold,
                'scales': list(self.scales),
                'distance': 'UNAVAILABLE; single center depth is not valid '
                            'for arbitrary detection boxes',
                'scope': 'natural map tower; classic template, no learned model'}
