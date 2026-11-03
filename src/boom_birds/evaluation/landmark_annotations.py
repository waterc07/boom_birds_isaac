"""Annotation schema validation and deterministic coordinate transforms.

No model, detector or training code lives here.  Source annotations are pixels
in the original image; model preprocessing must be explicit and reversible.
"""
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

ANNOTATION_VERSION = 'dsh.tower_annotation.v1'
BBOX_FORMAT = 'xywh_pixels_origin_top_left'


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_document(document, root: Path):
    errors = []
    warnings = []
    if document.get('schema_version') != ANNOTATION_VERSION:
        errors.append('unsupported schema_version')
    root = Path(root)
    seen = set()
    for index, item in enumerate(document.get('annotations', [])):
        prefix = 'annotations[%d]' % index
        frame = item.get('frame_id')
        if not frame:
            errors.append(prefix + ': missing frame_id')
            continue
        if frame in seen:
            errors.append(prefix + ': duplicate frame_id')
        seen.add(frame)
        image_path = root / item.get('image', '')
        if not image_path.is_file():
            errors.append(prefix + ': image missing')
            continue
        if item.get('image_sha256') != _sha(image_path):
            errors.append(prefix + ': image sha mismatch')
        with Image.open(image_path) as image:
            width, height = image.size
        if [width, height] != [item.get('image_width'), item.get('image_height')]:
            errors.append(prefix + ': image dimensions mismatch')
        target = item.get('target', {})
        if target.get('class') != 'tower':
            errors.append(prefix + ': unsupported target class')
        if target.get('present'):
            geometry = item.get('geometry', {})
            bbox = geometry.get('bbox_xywh')
            if item.get('negative_type') is not None:
                errors.append(prefix + ': positive has negative_type')
            if not isinstance(bbox, list) or len(bbox) != 4:
                errors.append(prefix + ': positive missing bbox')
            else:
                x, y, w, h = [float(v) for v in bbox]
                if w <= 0 or h <= 0:
                    errors.append(prefix + ': bbox non-positive size')
                if not (0 <= x < width and 0 <= y < height
                        and x + w <= width + 1e-6 and y + h <= height + 1e-6):
                    errors.append(prefix + ': bbox out of bounds')
            keypoint = geometry.get('keypoint')
            if keypoint is not None:
                kx, ky = float(keypoint.get('x')), float(keypoint.get('y'))
                if not (0 <= kx < width and 0 <= ky < height):
                    errors.append(prefix + ': keypoint out of bounds')
                if bbox is not None:
                    bx, by, bw, bh = [float(v) for v in bbox]
                    if not (bx - 2 <= kx <= bx + bw + 2
                            and by - 2 <= ky <= by + bh + 2):
                        warnings.append(prefix + ': keypoint outside bbox (verify)')
            elif geometry.get('reference_status') != 'UNAVAILABLE':
                warnings.append(prefix + ': positive without keypoint not marked UNAVAILABLE')
        else:
            if item.get('geometry', {}).get('bbox_xywh') is not None:
                errors.append(prefix + ': absent target has bbox')
            if item.get('geometry', {}).get('keypoint') is not None:
                errors.append(prefix + ': absent target has keypoint')
            if not item.get('negative_type'):
                warnings.append(prefix + ': absent target lacks negative_type')
        if item.get('source', {}).get('split') == 'sealed_test':
            errors.append(prefix + ': annotation sample must not claim sealed_test')
        if not item.get('annotator'):
            errors.append(prefix + ': missing annotator')
    return errors, warnings


def letterbox_annotation(annotation, source_width, source_height,
                         model_width, model_height):
    """Return bbox/keypoint transformed to a letterboxed model image."""
    scale = min(model_width / float(source_width),
                model_height / float(source_height))
    pad_x = (model_width - source_width * scale) / 2.0
    pad_y = (model_height - source_height * scale) / 2.0
    geometry = annotation['geometry']
    result = {'scale': scale, 'pad_x': pad_x, 'pad_y': pad_y}
    if geometry.get('bbox_xywh') is not None:
        x, y, w, h = [float(v) for v in geometry['bbox_xywh']]
        result['bbox_xywh'] = [x * scale + pad_x, y * scale + pad_y,
                               w * scale, h * scale]
    if geometry.get('keypoint') is not None:
        keypoint = geometry['keypoint']
        result['keypoint'] = [float(keypoint['x']) * scale + pad_x,
                              float(keypoint['y']) * scale + pad_y]
    return result


def hflip_annotation(annotation, width):
    geometry = annotation['geometry']
    result = {}
    if geometry.get('bbox_xywh') is not None:
        x, y, w, h = [float(v) for v in geometry['bbox_xywh']]
        result['bbox_xywh'] = [width - (x + w), y, w, h]
    if geometry.get('keypoint') is not None:
        keypoint = geometry['keypoint']
        result['keypoint'] = [width - float(keypoint['x']), float(keypoint['y'])]
    return result


def roundtrip_letterbox(annotation, source_width, source_height,
                        model_width, model_height):
    transformed = letterbox_annotation(annotation, source_width, source_height,
                                       model_width, model_height)
    scale = transformed['scale']
    pad_x = transformed['pad_x']
    pad_y = transformed['pad_y']
    geometry = annotation['geometry']
    restored = {}
    if 'bbox_xywh' in transformed:
        x, y, w, h = transformed['bbox_xywh']
        restored['bbox_xywh'] = [(x - pad_x) / scale, (y - pad_y) / scale,
                                 w / scale, h / scale]
    if 'keypoint' in transformed:
        x, y = transformed['keypoint']
        restored['keypoint'] = [(x - pad_x) / scale, (y - pad_y) / scale]
    return restored


def render_annotation_overlay(annotation, image_path, out_path):
    image = Image.open(image_path).convert('RGB')
    draw = ImageDraw.Draw(image)
    geometry = annotation['geometry']
    if geometry.get('bbox_xywh') is not None:
        x, y, w, h = geometry['bbox_xywh']
        draw.rectangle([x, y, x + w, y + h], outline=(0, 255, 0), width=2)
    if geometry.get('keypoint') is not None:
        x, y = geometry['keypoint']['x'], geometry['keypoint']['y']
        draw.ellipse([x - 3, y - 3, x + 3, y + 3], outline=(255, 255, 0), width=2)
    draw.rectangle([0, 0, 319, 14], fill=(0, 0, 0))
    draw.text((3, 2), annotation['frame_id'], fill=(255, 255, 0))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    return out_path
