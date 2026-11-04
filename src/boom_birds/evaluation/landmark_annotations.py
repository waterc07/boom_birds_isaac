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
ANNOTATION_VERSION_V2 = 'dsh.tower_annotation.v2'
ANNOTATION_VERSION_V2_1 = 'dsh.tower_annotation.v2_1'
BBOX_FORMAT = 'xywh_pixels_origin_top_left'

VISIBILITY_VALUES = ('FULL', 'PARTIAL', 'OCCLUDED', 'ABSENT', 'UNKNOWN')
REFERENCE_STATUS_VALUES = ('MANUAL_APPROX', 'UNAVAILABLE', 'NOT_APPLICABLE')
REFERENCE_SOURCES = ('MANUAL_VISUAL', 'COLOR_CUE_ASSISTED', 'PROJECTION_AID',
                     'TEMPLATE_ANCHOR', 'NOT_APPLICABLE')
REFERENCE_UNAVAILABLE_REASONS = ('REFERENCE_OCCLUDED', 'REFERENCE_OUT_OF_FRAME',
                                 'REFERENCE_TOO_SMALL', 'REFERENCE_NOT_PRESENT',
                                 'ANNOTATOR_UNDECIDABLE')
AMBIGUOUS_REASONS = ('MULTIPLE_SIMILAR_STRUCTURES', 'IDENTITY_UNRESOLVED',
                     'OTHER_LANDMARK_POSSIBLE', 'OCCLUSION_IDENTITY', 'NONE')
CANDIDATE_SOURCES = ('ANNOTATOR', 'COLOR_CUE')
NEGATIVE_TYPES_V2 = ('TARGET_ABSENT', 'SIMILAR_STRUCTURE', 'OTHER_LANDMARK', 'NONE')
UNDECIDABLE_REASONS = ('SIMILAR_STRUCTURE_CANDIDATE', 'IDENTITY_UNRESOLVED',
                       'OCCLUSION', 'IMAGE_QUALITY', 'ANNOTATOR_UNDECIDABLE')
ANNOTATOR_TYPES = ('AGENT_PROXY', 'HUMAN')
REVIEW_STATUSES = ('UNREVIEWED', 'SELF_CHECKED', 'HUMAN_REVIEWED', 'ADJUDICATED')
PIXEL_PROJECTION_MODELS = ('PINHOLE',)
TRUNCATION_SOURCES = ('ANNOTATOR_VISUAL', 'CAPTURE_METADATA', 'BOTH')
TRUNCATION_EDGES = ('left', 'right', 'top', 'bottom')
BBOX_SOURCES = ('ANNOTATOR_VISUAL', 'ANNOTATOR_VISUAL_WITH_PROJECTION_AID',
                'PROJECTION_AID_CALIBRATED')
ANNOTATION_MODES = ('FRAME_BY_FRAME_VISUAL', 'BULK_CALIBRATED_WITH_FULL_VISUAL_QA')
DATASET_ROLES = ('EXPLORATORY_EVAL', 'DEVELOPMENT', 'ANNOTATION_CALIBRATION',
                 'TRAIN', 'VALIDATION')
CONFLUSER_SOURCES = ('ANNOTATOR', 'COLOR_CUE')
CONFLUSER_VERIFICATION_SOURCES = ('WORLD_POSE_OR_MAP_DB', 'HUMAN_ADJUDICATION',
                                  'EXTERNAL_EVIDENCE')


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_document(document, root: Path):
    """Validate a v1 or v2 annotation document; v1 documents stay supported."""
    version = document.get('schema_version')
    if version == ANNOTATION_VERSION_V2:
        return _validate_common(document, root, v21=False)
    if version == ANNOTATION_VERSION_V2_1:
        return _validate_common(document, root, v21=True)
    if version == ANNOTATION_VERSION:
        return _validate_v1(document, root)
    return ['unsupported schema_version'], []


def _validate_v1(document, root: Path):
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
    geometry = annotation.get('geometry', {})
    for candidate in annotation.get('candidates') or []:
        bbox = candidate.get('bbox_xywh')
        if bbox is not None:
            cid = str(candidate.get('candidate_id', 'candidate'))
            draw.rectangle([bbox[0], bbox[1], bbox[0] + bbox[2], bbox[1] + bbox[3]],
                           outline=(255, 128, 0), width=1)
            draw.text((bbox[0] + 1, bbox[1] + 1), cid, fill=(255, 128, 0))
        green_cue = candidate.get('green_cue')
        if green_cue is not None:
            draw.ellipse([green_cue['x'] - 2, green_cue['y'] - 2,
                          green_cue['x'] + 2, green_cue['y'] + 2],
                         outline=(0, 200, 255), width=1)
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


def _valid_bbox(bbox, width, height):
    if not isinstance(bbox, list) or len(bbox) != 4:
        return 'missing or malformed bbox_xywh'
    x, y, w, h = [float(v) for v in bbox]
    if w <= 0 or h <= 0:
        return 'bbox non-positive size'
    if not (0 <= x < width and 0 <= y < height
            and x + w <= width + 1e-6 and y + h <= height + 1e-6):
        return 'bbox out of bounds'
    return None


def _valid_point(point, width, height, what):
    if not isinstance(point, dict):
        return what + ' must be an object'
    try:
        x, y = float(point.get('x')), float(point.get('y'))
    except (TypeError, ValueError):
        return what + ' has non-numeric coordinates'
    if not (0 <= x < width and 0 <= y < height):
        return what + ' out of bounds'
    return None


def _validate_common(document, root: Path, v21: bool = False):
    """Strict validation for dsh.tower_annotation.v2 and v2_1."""
    errors = []
    warnings = []
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

        source = item.get('source', {})
        for field in ('run', 'family', 'group_id', 'split'):
            if not source.get(field):
                errors.append(prefix + ': source missing ' + field)
        if source.get('split') == 'sealed_test':
            errors.append(prefix + ': annotation sample must not claim sealed_test')

        annotator = item.get('annotator', {})
        if annotator.get('annotator_type') not in ANNOTATOR_TYPES:
            errors.append(prefix + ': annotator_type must be one of ' +
                          ', '.join(ANNOTATOR_TYPES))
        if not annotator.get('annotator_id'):
            errors.append(prefix + ': annotator missing annotator_id')
        if not isinstance(annotator.get('independent_of_model_dev'), bool):
            errors.append(prefix + ': annotator missing boolean independent_of_model_dev')
        if annotator.get('review_status') not in REVIEW_STATUSES:
            errors.append(prefix + ': annotator review_status must be one of ' +
                          ', '.join(REVIEW_STATUSES))

        pixel_basis = item.get('pixel_basis')
        if not isinstance(pixel_basis, dict):
            errors.append(prefix + ': pixel_basis missing')
        else:
            if [pixel_basis.get('image_width'), pixel_basis.get('image_height')] != [width, height]:
                errors.append(prefix + ': pixel_basis image_width/image_height does not match image')
            if pixel_basis.get('projection_model') not in PIXEL_PROJECTION_MODELS:
                errors.append(prefix + ': pixel_basis projection_model must be one of ' +
                              ', '.join(PIXEL_PROJECTION_MODELS))
            for field in ('fx_px', 'cx_px', 'cy_px'):
                value = pixel_basis.get(field)
                if not isinstance(value, (int, float)) or float(value) <= 0:
                    errors.append(prefix + ': pixel_basis ' + field + ' must be a positive number')
            if not pixel_basis.get('bearing_formula'):
                errors.append(prefix + ': pixel_basis bearing_formula missing')

        target = item.get('target', {})
        if target.get('class') != 'tower':
            errors.append(prefix + ': unsupported target class')
        if not target.get('landmark_id'):
            errors.append(prefix + ': target missing landmark_id')
        present = target.get('present')
        undecidable = target.get('undecidable')
        visibility = target.get('visibility')
        if not isinstance(present, bool):
            errors.append(prefix + ': target.present must be boolean')
        if not isinstance(undecidable, bool):
            errors.append(prefix + ': target.undecidable must be boolean')
        if visibility not in VISIBILITY_VALUES:
            errors.append(prefix + ': visibility must be one of ' + ', '.join(VISIBILITY_VALUES))
        truncated = target.get('truncated')
        occluded = target.get('occluded')
        ambiguous = target.get('ambiguous')
        for name, flag in (('truncated', truncated), ('occluded', occluded),
                           ('ambiguous', ambiguous)):
            if not isinstance(flag, bool):
                errors.append(prefix + ': target.' + name + ' must be boolean')

        geometry = item.get('geometry', {})
        bbox = geometry.get('bbox_xywh')
        keypoint = geometry.get('keypoint')
        reference_status = geometry.get('reference_status')
        unavailable_reason = geometry.get('reference_unavailable_reason')
        reference_source = geometry.get('reference_source')
        if reference_status not in REFERENCE_STATUS_VALUES:
            errors.append(prefix + ': reference_status must be one of ' +
                          ', '.join(REFERENCE_STATUS_VALUES))
        if reference_source not in REFERENCE_SOURCES:
            errors.append(prefix + ': reference_source must be one of ' +
                          ', '.join(REFERENCE_SOURCES))
        if bbox is not None:
            problem = _valid_bbox(bbox, width, height)
            if problem:
                errors.append(prefix + ': ' + problem)
        if keypoint is not None:
            problem = _valid_point(keypoint, width, height, 'keypoint')
            if problem:
                errors.append(prefix + ': ' + problem)
            elif bbox is not None:
                kx, ky = float(keypoint['x']), float(keypoint['y'])
                bx, by, bw, bh = [float(v) for v in bbox]
                if not (bx - 2 <= kx <= bx + bw + 2 and by - 2 <= ky <= by + bh + 2):
                    warnings.append(prefix + ': keypoint outside bbox (verify)')
        negative_type = item.get('negative_type')
        candidates = item.get('candidates', [])

        if present is True and undecidable is True:
            errors.append(prefix + ': present=true cannot be combined with undecidable=true '
                          '(use present/undecidable states from spec v2)')
        if present is False and undecidable is False:
            if bbox is not None:
                errors.append(prefix + ': absent target has bbox')
            if keypoint is not None:
                errors.append(prefix + ': absent target has keypoint')
            if visibility != 'ABSENT':
                errors.append(prefix + ': absent target visibility must be ABSENT')
            if not negative_type:
                errors.append(prefix + ': absent target lacks negative_type')
            elif negative_type not in NEGATIVE_TYPES_V2:
                errors.append(prefix + ': negative_type must be one of ' +
                              ', '.join(NEGATIVE_TYPES_V2))
            if negative_type in ('SIMILAR_STRUCTURE', 'OTHER_LANDMARK'):
                if v21:
                    if not any(isinstance(c, dict) and c.get('verified') is True
                               for c in (item.get('confusers') or [])):
                        errors.append(prefix + ': negative_type=' + negative_type +
                                      ' requires at least one verified confuser '
                                      '(unverified structures use TARGET_ABSENT + confusers)')
                elif not candidates:
                    errors.append(prefix + ': negative_type=' + negative_type +
                                  ' requires candidates (record the competing structure)')
            if reference_status != 'NOT_APPLICABLE':
                errors.append(prefix + ': absent target reference_status must be NOT_APPLICABLE')
        elif present is False and undecidable is True:
            if bbox is not None or keypoint is not None:
                errors.append(prefix + ': undecidable target must not carry bbox/keypoint')
            if negative_type is not None:
                errors.append(prefix + ': undecidable target must not carry negative_type '
                              '(never write uncertainty as absence)')
            if visibility != 'UNKNOWN':
                errors.append(prefix + ': undecidable target visibility must be UNKNOWN')
            if target.get('undecidable_reason') not in UNDECIDABLE_REASONS:
                errors.append(prefix + ': undecidable target needs undecidable_reason in ' +
                              ', '.join(UNDECIDABLE_REASONS))
            if reference_status != 'NOT_APPLICABLE':
                errors.append(prefix + ': undecidable target reference_status must be NOT_APPLICABLE')
        elif present is True and undecidable is False:
            if negative_type is not None:
                errors.append(prefix + ': positive has negative_type')
            if visibility == 'ABSENT':
                errors.append(prefix + ': present target cannot be ABSENT')
            if reference_status == 'MANUAL_APPROX':
                if keypoint is None:
                    errors.append(prefix + ': MANUAL_APPROX requires a keypoint')
                elif keypoint.get('visible') is not True:
                    errors.append(prefix + ': MANUAL_APPROX keypoint must be visible=true')
                if unavailable_reason is not None:
                    errors.append(prefix + ': MANUAL_APPROX must not carry reference_unavailable_reason')
            elif reference_status == 'UNAVAILABLE':
                if keypoint is not None:
                    errors.append(prefix + ': UNAVAILABLE requires keypoint=null')
                if unavailable_reason not in REFERENCE_UNAVAILABLE_REASONS:
                    errors.append(prefix + ': reference_unavailable_reason must be one of ' +
                                  ', '.join(REFERENCE_UNAVAILABLE_REASONS))
            elif reference_status == 'NOT_APPLICABLE':
                errors.append(prefix + ': present target cannot use NOT_APPLICABLE reference_status')
            if visibility == 'OCCLUDED':
                if occluded is not True:
                    errors.append(prefix + ': visibility OCCLUDED requires occluded=true')
                if reference_status != 'UNAVAILABLE':
                    errors.append(prefix + ': visibility OCCLUDED requires UNAVAILABLE reference_status')
            else:
                if bbox is None:
                    errors.append(prefix + ': present target missing bbox')
            if visibility == 'FULL' and truncated is True:
                errors.append(prefix + ': truncated=true requires visibility PARTIAL')
            if visibility == 'FULL' and occluded is True:
                errors.append(prefix + ': occluded=true requires visibility PARTIAL or OCCLUDED')
            if visibility == 'PARTIAL' and not (truncated or occluded):
                errors.append(prefix + ': visibility PARTIAL requires truncated=true or occluded=true')
            if truncated is True and visibility != 'PARTIAL':
                errors.append(prefix + ': truncated=true requires visibility PARTIAL')
            if occluded is True and visibility not in ('PARTIAL', 'OCCLUDED'):
                errors.append(prefix + ': occluded=true requires visibility PARTIAL or OCCLUDED')

        ambiguous_reason = target.get('ambiguous_reason')
        if not isinstance(candidates, list):
            errors.append(prefix + ': candidates must be a list')
            candidates = []
        for cindex, candidate in enumerate(candidates):
            cprefix = prefix + ': candidates[%d]' % cindex
            if not isinstance(candidate, dict):
                errors.append(cprefix + ': candidate must be an object')
                continue
            if not candidate.get('candidate_id'):
                errors.append(cprefix + ': candidate missing candidate_id')
            if candidate.get('source') not in CANDIDATE_SOURCES:
                errors.append(cprefix + ': candidate source must be one of ' +
                              ', '.join(CANDIDATE_SOURCES))
            if candidate.get('bbox_xywh') is not None:
                problem = _valid_bbox(candidate['bbox_xywh'], width, height)
                if problem:
                    errors.append(cprefix + ': ' + problem)
            elif candidate.get('green_cue') is None:
                errors.append(cprefix + ': candidate needs bbox_xywh or green_cue')
            if candidate.get('green_cue') is not None:
                problem = _valid_point(candidate['green_cue'], width, height,
                                       'candidate green_cue')
                if problem:
                    errors.append(cprefix + ': ' + problem)
            if candidate.get('keypoint') is not None:
                problem = _valid_point(candidate['keypoint'], width, height,
                                       'candidate keypoint')
                if problem:
                    errors.append(cprefix + ': ' + problem)
        if ambiguous is True:
            if ambiguous_reason not in AMBIGUOUS_REASONS or ambiguous_reason == 'NONE':
                errors.append(prefix + ': ambiguous=true requires ambiguous_reason in ' +
                              ', '.join(AMBIGUOUS_REASONS))
            if not candidates:
                errors.append(prefix + ': ambiguous=true requires non-empty candidates list')
        else:
            if ambiguous_reason not in (None, 'NONE'):
                errors.append(prefix + ': ambiguous_reason must be null/NONE when ambiguous=false')
            if candidates and negative_type not in ('SIMILAR_STRUCTURE', 'OTHER_LANDMARK'):
                errors.append(prefix + ': candidates are only allowed for ambiguous frames '
                              'or SIMILAR_STRUCTURE/OTHER_LANDMARK negatives')

        if v21:
            edges = target.get('truncated_edges')
            if not isinstance(edges, dict) or set(edges) != set(TRUNCATION_EDGES):
                errors.append(prefix + ': truncated_edges must have exactly left/right/top/bottom')
                edges = {}
            else:
                for edge in TRUNCATION_EDGES:
                    if not isinstance(edges.get(edge), bool):
                        errors.append(prefix + ': truncated_edges.' + edge + ' must be boolean')
                if isinstance(truncated, bool) and truncated != any(
                        edges.get(edge) is True for edge in TRUNCATION_EDGES):
                    errors.append(prefix + ': truncated must equal any(truncated_edges)')
            source_map = target.get('truncation_source') or {}
            if not isinstance(source_map, dict):
                errors.append(prefix + ': truncation_source must be an object')
                source_map = {}
            for edge, value in source_map.items():
                if edge not in TRUNCATION_EDGES:
                    errors.append(prefix + ': truncation_source has unknown edge ' + str(edge))
                if value not in TRUNCATION_SOURCES:
                    errors.append(prefix + ': truncation_source[' + str(edge) +
                                  '] must be one of ' + ', '.join(TRUNCATION_SOURCES))
            if isinstance(edges, dict):
                for edge in TRUNCATION_EDGES:
                    if edges.get(edge) is True and edge not in source_map:
                        errors.append(prefix + ': truncation_source missing for true edge ' + edge)
                    if edges.get(edge) is False and edge in source_map:
                        errors.append(prefix + ': truncation_source set for non-truncated edge ' + edge)
            conflicts = target.get('truncation_conflicts') or []
            if not isinstance(conflicts, list):
                errors.append(prefix + ': truncation_conflicts must be a list')
            else:
                for cindex, conflict in enumerate(conflicts):
                    cprefix = prefix + ': truncation_conflicts[%d]' % cindex
                    if not isinstance(conflict, dict):
                        errors.append(cprefix + ': conflict must be an object')
                        continue
                    if conflict.get('edge') not in TRUNCATION_EDGES:
                        errors.append(cprefix + ': edge must be one of ' + ', '.join(TRUNCATION_EDGES))
                    if not isinstance(conflict.get('capture'), bool) or \
                            not isinstance(conflict.get('annotator'), bool):
                        errors.append(cprefix + ': capture/annotator must be booleans')
                    if conflict.get('resolution') != 'ANNOTATOR_OVER_CAPTURE':
                        errors.append(cprefix + ': resolution must be ANNOTATOR_OVER_CAPTURE')
            green_pixels = geometry.get('green_pixels')
            if present is True and not isinstance(green_pixels, int):
                errors.append(prefix + ': green_pixels required for present frames')
            if isinstance(green_pixels, int):
                if green_pixels < 0:
                    errors.append(prefix + ': green_pixels must be >= 0')
                if keypoint is not None and green_pixels < 3:
                    errors.append(prefix + ': keypoint requires green_pixels >= 3 '
                                  '(reference availability criterion)')
            if geometry.get('bbox_source') not in BBOX_SOURCES:
                errors.append(prefix + ': bbox_source must be one of ' +
                              ', '.join(BBOX_SOURCES))
            if annotator.get('annotation_mode') not in ANNOTATION_MODES:
                errors.append(prefix + ': annotation_mode must be one of ' +
                              ', '.join(ANNOTATION_MODES))
            if item.get('dataset_role') not in DATASET_ROLES:
                errors.append(prefix + ': dataset_role must be one of ' +
                              ', '.join(DATASET_ROLES))
            confusers = item.get('confusers') or []
            if not isinstance(confusers, list):
                errors.append(prefix + ': confusers must be a list')
                confusers = []
            for kindex, confuser in enumerate(confusers):
                kprefix = prefix + ': confusers[%d]' % kindex
                if not isinstance(confuser, dict):
                    errors.append(kprefix + ': confuser must be an object')
                    continue
                if not confuser.get('confuser_id'):
                    errors.append(kprefix + ': confuser missing confuser_id')
                if not confuser.get('description'):
                    errors.append(kprefix + ': confuser missing description')
                if confuser.get('source') not in CONFLUSER_SOURCES:
                    errors.append(kprefix + ': confuser source must be one of ' +
                                  ', '.join(CONFLUSER_SOURCES))
                if not isinstance(confuser.get('verified'), bool):
                    errors.append(kprefix + ': confuser verified must be boolean')
                if confuser.get('verified') is True:
                    if confuser.get('verification_source') not in CONFLUSER_VERIFICATION_SOURCES:
                        errors.append(kprefix + ': verified confuser requires verification_source in ' +
                                      ', '.join(CONFLUSER_VERIFICATION_SOURCES))
                    if not confuser.get('verification_note'):
                        errors.append(kprefix + ': verified confuser requires verification_note')
                elif confuser.get('verification_source') is not None:
                    errors.append(kprefix + ': unverified confuser must not carry verification_source')
                if confuser.get('bbox_xywh') is not None:
                    problem = _valid_bbox(confuser['bbox_xywh'], width, height)
                    if problem:
                        errors.append(kprefix + ': ' + problem)
                if confuser.get('green_cue') is not None:
                    problem = _valid_point(confuser['green_cue'], width, height,
                                           'confuser green_cue')
                    if problem:
                        errors.append(kprefix + ': ' + problem)
                if confuser.get('bbox_xywh') is None and confuser.get('green_cue') is None:
                    errors.append(kprefix + ': confuser needs bbox_xywh or green_cue')
            if negative_type in ('SIMILAR_STRUCTURE', 'OTHER_LANDMARK'):
                if not any(isinstance(c, dict) and c.get('verified') is True
                           for c in confusers):
                    errors.append(prefix + ': negative_type=' + negative_type +
                                  ' requires at least one verified confuser')

    return errors, warnings



def yolo_pose_target(annotation, model_width=640, model_height=640):
    """Map one v2 annotation to a 1-keypoint pose target in MODEL-CANVAS space.

    .. warning::
       The returned bbox_norm / keypoint_norm are normalized to the
       letterboxed MODEL CANVAS (e.g. 640x640 after scale+pad), which is an
       intermediate representation.  They are **NOT a YOLO txt label**.  A
       YOLO txt file needs coordinates normalized by the SOURCE image size;
       writing this dict directly as YOLO labels double-applies the
       letterbox transform.  For dataset export use the source-normalized
       converter in boom_birds.evaluation.landmark_yolo (source_normalized_target)
       or an equivalent inverse-letterbox step, and keep its
       label_normalization='SOURCE_IMAGE_PX_OVER_SOURCE_SIZE' marker.

    Returns (target, sidecar, exclusion_reason).  target is None when no
    positive label may be written (absent/ambiguous/undecidable), with
    exclusion_reason saying why.  The returned target carries
    coordinate_space='MODEL_CANVAS_NORMALIZED' as an explicit marker; it
    deliberately does NOT carry label_normalization so that exporters
    applying the source-normalization step are not skipped.  When the
    reference point is unavailable the keypoint is written with visibility=0
    and a placeholder coordinate (the bbox centre in model input space); v=0
    targets must be excluded from anchor/coverage denominators and never used
    as keypoint regression targets.
    """
    target = annotation.get('target', {})
    geometry = annotation.get('geometry', {})
    source = annotation.get('source', {})
    annotator = annotation.get('annotator', {})
    sidecar = {
        'frame_id': annotation.get('frame_id'),
        'image': annotation.get('image'),
        'image_sha256': annotation.get('image_sha256'),
        'run': source.get('run'),
        'family': source.get('family'),
        'group_id': source.get('group_id'),
        'split': source.get('split'),
        'present': target.get('present'),
        'undecidable': target.get('undecidable'),
        'visibility': target.get('visibility'),
        'truncated': target.get('truncated'),
        'occluded': target.get('occluded'),
        'ambiguous': target.get('ambiguous'),
        'ambiguous_reason': target.get('ambiguous_reason'),
        'negative_type': annotation.get('negative_type'),
        'reference_status': geometry.get('reference_status'),
        'reference_unavailable_reason': geometry.get('reference_unavailable_reason'),
        'reference_source': geometry.get('reference_source'),
        'annotator_type': annotator.get('annotator_type'),
        'independent_of_model_dev': annotator.get('independent_of_model_dev'),
        'review_status': annotator.get('review_status'),
        'dataset_role': annotation.get('dataset_role'),
        'truncated_edges': target.get('truncated_edges'),
        'truncation_source': target.get('truncation_source'),
        'green_pixels': geometry.get('green_pixels'),
        'bbox_source': geometry.get('bbox_source'),
        'annotation_mode': annotator.get('annotation_mode'),
        'included_in_training': False,
        'exclusion_reason': None,
    }
    if target.get('undecidable') is True:
        sidecar['exclusion_reason'] = 'UNDECIDABLE'
        return None, sidecar, 'UNDECIDABLE'
    if target.get('ambiguous') is True:
        sidecar['exclusion_reason'] = 'AMBIGUOUS'
        return None, sidecar, 'AMBIGUOUS'
    if target.get('present') is not True:
        sidecar['exclusion_reason'] = annotation.get('negative_type') or 'TARGET_ABSENT'
        return None, sidecar, sidecar['exclusion_reason']
    bbox = geometry.get('bbox_xywh')
    if bbox is None:
        sidecar['exclusion_reason'] = 'NO_BBOX'
        return None, sidecar, 'NO_BBOX'
    width = float(annotation['image_width'])
    height = float(annotation['image_height'])
    transformed = letterbox_annotation(annotation, width, height, model_width, model_height)
    x, y, w, h = transformed['bbox_xywh']
    cx, cy = x + w / 2.0, y + h / 2.0
    bbox_norm = [cx / model_width, cy / model_height, w / model_width, h / model_height]
    keypoint = geometry.get('keypoint')
    reference_visible = (keypoint is not None
                         and keypoint.get('visible') is True
                         and geometry.get('reference_status') == 'MANUAL_APPROX')
    if reference_visible:
        kx, ky = transformed['keypoint']
        visibility = 1
    else:
        kx, ky = cx, cy  # placeholder only; never a reference estimate
        visibility = 0
    sidecar['included_in_training'] = True
    return {
        'class_id': 0,
        # model-canvas normalized intermediate representation; NOT a YOLO txt
        # label (source-image normalization happens in the exporter, see
        # landmark_yolo.source_normalized_target)
        'coordinate_space': 'MODEL_CANVAS_NORMALIZED',
        'bbox_norm': [round(v, 6) for v in bbox_norm],
        'keypoint_norm': [round(kx / model_width, 6), round(ky / model_height, 6)],
        'keypoint_visibility': visibility,
        'letterbox': {'scale': transformed['scale'],
                      'pad_x': transformed['pad_x'],
                      'pad_y': transformed['pad_y']},
    }, sidecar, None
