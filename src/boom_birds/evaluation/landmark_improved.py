"""Limited multi-view improvement over the tower-template baseline.

Exactly two declared improvements:
1. a development-only multi-view template library (max NCC over templates/scales);
2. a template-anchor reference point (green roof light) for image bearing.

No learned model and no new large framework; the detector never reads truth.
"""
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

IMPROVED_VERSION = 'dsh.tower_multiview_anchor.v1'
SCORE_DEFINITION = 'max_multiscale_multitemplate_TM_CCOEFF_NORMED_grayscale'


@dataclass(frozen=True)
class ImprovedDetection:
    status: str
    score: float
    bbox_xywh: tuple | None
    bearing_rad: float | None
    distance_m: float | None
    distance_status: str
    scale: float | None
    template_id: str | None
    anchor_xy: tuple | None
    bearing_source: str


class MultiViewAnchorDetector:
    def __init__(self, templates_meta_path: Path, *, threshold: float,
                 scales=(0.5, 0.65, 0.8, 1.0, 1.15)):
        meta = json.loads(Path(templates_meta_path).read_text(encoding='utf-8'))
        if not 0.0 <= float(threshold) <= 1.0:
            raise ValueError('threshold must be in [0,1]')
        self.meta_path = Path(templates_meta_path)
        self.threshold = float(threshold)
        self.scales = tuple(float(v) for v in scales)
        self.entries = []
        for entry in meta['entries']:
            gray = cv2.imread(entry['path'], cv2.IMREAD_GRAYSCALE)
            if gray is None:
                raise ValueError('cannot read template: ' + entry['path'])
            self.entries.append({**entry, 'gray': gray.astype(np.float32)})
        if not self.entries:
            raise ValueError('empty template library')

    def detect(self, image_path: Path, intrinsics: list | None):
        image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if image is None or image.size == 0:
            return ImprovedDetection('UNKNOWN', 0.0, None, None, None,
                                     'UNAVAILABLE_INVALID_IMAGE', None,
                                     None, None, 'NONE')
        image = image.astype(np.float32)
        height, width = image.shape
        best = (-1.0, None, None, None, None)  # score, bbox, scale, entry, anchor
        for entry in self.entries:
            template0 = entry['gray']
            for scale in self.scales:
                template = cv2.resize(template0, None, fx=scale, fy=scale,
                                      interpolation=cv2.INTER_AREA)
                th, tw = template.shape
                if th > height or tw > width:
                    continue
                scores = cv2.matchTemplate(image, template,
                                           cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(scores)
                if float(max_val) <= best[0]:
                    continue
                bbox = (int(max_loc[0]), int(max_loc[1]), int(tw), int(th))
                anchor = None
                if entry.get('anchor_fraction_xy') is not None:
                    anchor = (bbox[0] + float(entry['anchor_fraction_xy'][0]) * tw,
                              bbox[1] + float(entry['anchor_fraction_xy'][1]) * th)
                best = (float(max_val), bbox, scale, entry, anchor)
        score, bbox, scale, entry, anchor = best
        if bbox is None:
            return ImprovedDetection('UNKNOWN', 0.0, None, None, None,
                                     'UNAVAILABLE_TEMPLATE_LARGER_THAN_IMAGE',
                                     None, None, None, 'NONE')
        bearing = None
        bearing_source = 'NONE'
        if intrinsics is not None:
            try:
                fx = float(intrinsics[0][0])
                cx0 = float(intrinsics[0][2])
                if anchor is not None:
                    bearing = math.atan2(anchor[0] - cx0, fx)
                    bearing_source = 'TEMPLATE_ANCHOR_GREEN_LIGHT'
                else:
                    cx = bbox[0] + bbox[2] / 2.0
                    bearing = math.atan2(cx - cx0, fx)
                    bearing_source = 'BBOX_CENTER_FALLBACK'
            except (TypeError, ValueError, IndexError):
                bearing = None
        if score < self.threshold:
            return ImprovedDetection('NOT_DETECTED', score, bbox, bearing, None,
                                     'UNAVAILABLE_DISTANCE_ONLY_CENTER_DEPTH',
                                     scale, entry['template_id'], anchor,
                                     bearing_source)
        return ImprovedDetection('DETECTED', score, bbox, bearing, None,
                                 'UNAVAILABLE_DISTANCE_ONLY_CENTER_DEPTH',
                                 scale, entry['template_id'], anchor,
                                 bearing_source)

    def metadata(self):
        return {
            'detector_version': IMPROVED_VERSION,
            'score_definition': SCORE_DEFINITION,
            'score_is_probability': False,
            'templates_meta': self.meta_path.as_posix(),
            'templates_meta_sha256': hashlib.sha256(
                self.meta_path.read_bytes()).hexdigest(),
            'template_hashes': {entry['template_id']: entry['sha256']
                                for entry in self.entries},
            'threshold': self.threshold,
            'scales': list(self.scales),
            'bearing_source': 'TEMPLATE_ANCHOR_GREEN_LIGHT',
            'distance': 'UNAVAILABLE for arbitrary detection boxes',
        }
