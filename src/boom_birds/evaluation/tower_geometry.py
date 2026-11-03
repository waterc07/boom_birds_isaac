"""Green-light-seeded tower geometry detector (classical CV, no learned model).

This is a development candidate for the natural tower.  It uses only the RGB
image and camera intrinsics; no ground truth, pose, map labels or target world
coordinates are read.  Rules confirmed from the current synthetic asset:

* the target has a small bright-green roof light on top of a tower body;
* the body has a broad, mostly gray structure below the light;
* other green structures exist in the map, so color alone is not sufficient.

The bbox is a saturation-supported structure region around the green candidate;
it is not a learned object box and no distance is emitted.
"""
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path

import cv2
import numpy as np

GEOMETRY_VERSION = 'dsh.tower_green_geometry.v1'
SCORE_DEFINITION = 'green_seed_saturation_structure_v1'


@dataclass(frozen=True)
class GeometryDetection:
    status: str
    reason: str
    bbox_xywh: tuple | None
    bearing_rad: float | None
    distance_m: float | None
    distance_status: str
    anchor_xy: tuple | None
    green_area_px: int | None
    score: float | None
    geometry_score: float | None
    candidates: int
    intermediate: dict


class GreenGeometryDetector:
    def __init__(self, *, min_green_area=10, max_green_area=300,
                 min_bbox_side=30, min_sat_pixels=20,
                 min_edge_density=0.03, max_symmetry=0.97,
                 green_rgb=(100.0, 1.25, 1.15), sat_min=70,
                 sat_val_min=35, max_anchor_top_fraction=0.45,
                 ambiguity_ratio=0.97):
        self.min_green_area = int(min_green_area)
        self.max_green_area = int(max_green_area)
        self.min_bbox_side = int(min_bbox_side)
        self.min_sat_pixels = int(min_sat_pixels)
        self.min_edge_density = float(min_edge_density)
        self.max_symmetry = float(max_symmetry)
        self.green_rgb = tuple(float(v) for v in green_rgb)
        self.sat_min = int(sat_min)
        self.sat_val_min = int(sat_val_min)
        self.max_anchor_top_fraction = float(max_anchor_top_fraction)
        self.ambiguity_ratio = float(ambiguity_ratio)

    def detect(self, image_path: Path, intrinsics: list | None):
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None or image.size == 0:
            return GeometryDetection('UNKNOWN', 'INVALID_IMAGE', None, None,
                                     None, 'UNAVAILABLE', None, None, None,
                                     None, 0, {})
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)
        height, width = gray.shape
        b, g, r = [channel.astype(np.float32) for channel in cv2.split(image)]
        green = ((g > self.green_rgb[0])
                 & (g > r * self.green_rgb[1])
                 & (g > b * self.green_rgb[2])).astype(np.uint8)
        # Merge small green fragments of the same light; keep the light compact.
        green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        count, labels, stats, centroids = cv2.connectedComponentsWithStats(green)
        sat_mask = (s > self.sat_min) & (v > self.sat_val_min)
        edges = cv2.Canny(gray, 40, 100)
        candidates = []
        rejects = []
        for index in range(1, count):
            area = int(stats[index, cv2.CC_STAT_AREA])
            if area < self.min_green_area or area > self.max_green_area:
                continue
            gx, gy = (float(centroids[index][0]), float(centroids[index][1]))
            x0 = max(0, int(gx - 180))
            x1 = min(width, int(gx + 180))
            y0 = max(0, int(gy - 30))
            y1 = min(height, int(gy + 230))
            ys, xs = np.where(sat_mask)
            keep = (xs >= x0) & (xs < x1) & (ys >= y0) & (ys < y1)
            xs, ys = xs[keep], ys[keep]
            if len(xs) < self.min_sat_pixels:
                rejects.append({'green_anchor': [gx, gy], 'reason': 'LOW_STRUCTURE_SUPPORT'})
                continue
            bx, by = int(xs.min()), int(ys.min())
            bw, bh = int(xs.max() - bx + 1), int(ys.max() - by + 1)
            if bw < self.min_bbox_side or bh < self.min_bbox_side:
                rejects.append({'green_anchor': [gx, gy],
                                'reason': 'STRUCTURE_TOO_SMALL'})
                continue
            if not (by - 2 <= gy <= by + self.max_anchor_top_fraction * bh):
                rejects.append({'green_anchor': [gx, gy],
                                'reason': 'GREEN_NOT_TOP_OF_STRUCTURE'})
                continue
            # Symmetry of edge support in the lower structure; a rectangle/robot
            # with very different halves is not accepted as a tower candidate.
            yy0 = min(height - 1, int(by + bh * 0.25))
            roi = edges[yy0:min(height, by + bh), bx:min(width, bx + bw)]
            if roi.size == 0:
                continue
            edge_density = float((roi > 0).mean())
            if edge_density < self.min_edge_density:
                rejects.append({'green_anchor': [gx, gy],
                                'reason': 'LOW_EDGE_SUPPORT'})
                continue
            half = max(1, roi.shape[1] // 2)
            left = float((roi[:, :half] > 0).mean())
            right = float((roi[:, half:] > 0).mean())
            symmetry = 1.0 - abs(left - right) / max(left + right, 1e-6)
            if symmetry > self.max_symmetry:
                rejects.append({'green_anchor': [gx, gy],
                                'reason': 'DEGENERATE_SYMMETRY'})
                continue
            aspect = bh / float(bw)
            if not 0.35 <= aspect <= 3.0:
                rejects.append({'green_anchor': [gx, gy],
                                'reason': 'INVALID_ASPECT'})
                continue
            score = (float(len(xs)) * float(edge_density)
                     * (0.5 + 0.5 * symmetry))
            candidates.append({
                'bbox_xywh': [bx, by, bw, bh],
                'anchor_xy': [gx, gy],
                'green_area_px': area,
                'sat_pixels': int(len(xs)),
                'edge_density': edge_density,
                'symmetry': symmetry,
                'aspect': aspect,
                'score': score,
            })
        if not candidates:
            return GeometryDetection('UNKNOWN', 'NO_GEOMETRY_CANDIDATE', None,
                                     None, None, 'UNAVAILABLE', None, None,
                                     None, None, 0, {'rejects': rejects[:8]})
        candidates.sort(key=lambda item: item['score'], reverse=True)
        best = candidates[0]
        if len(candidates) > 1 and candidates[1]['score'] >= (
                self.ambiguity_ratio * best['score']):
            return GeometryDetection(
                'UNKNOWN', 'AMBIGUOUS_GREEN_CANDIDATES', None, None, None,
                'UNAVAILABLE', None, None, None, None, len(candidates),
                {'candidates': candidates[:5], 'rejects': rejects[:8]})
        anchor = tuple(best['anchor_xy'])
        bearing = None
        if intrinsics is not None:
            try:
                bearing = math.atan2(anchor[0] - float(intrinsics[0][2]),
                                     float(intrinsics[0][0]))
            except (TypeError, ValueError, IndexError):
                bearing = None
        intermediate = {
            'candidates': candidates[:5],
            'rejects': rejects[:8],
            'green_rgb': list(self.green_rgb),
            'sat_min': self.sat_min,
            'max_symmetry': self.max_symmetry,
            'scope': 'current synthetic map asset; green roof light is a visual prior, not a rules guarantee',
        }
        return GeometryDetection('DETECTED', 'GREEN_GEOMETRY_TARGET',
                                 tuple(best['bbox_xywh']), bearing, None,
                                 'UNAVAILABLE_SINGLE_CENTER_DEPTH', anchor,
                                 best['green_area_px'], best['score'],
                                 best['score'], len(candidates), intermediate)

    def metadata(self):
        return {
            'detector_version': GEOMETRY_VERSION,
            'score_definition': SCORE_DEFINITION,
            'score_is_probability': False,
            'bbox_definition': 'saturation-supported structure region around green candidate',
            'anchor_definition': 'green roof-light centroid in image pixels',
            'bearing_definition': 'atan2(anchor_x - cx0, fx)',
            'green_prior': 'current synthetic asset; not a rules guarantee',
            'distance': 'UNAVAILABLE for arbitrary bbox',
        }
