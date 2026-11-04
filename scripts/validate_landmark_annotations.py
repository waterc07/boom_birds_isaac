"""Validate the small annotation sample and render a QA contact sheet."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from boom_birds.evaluation.landmark_annotations import (
    render_annotation_overlay, validate_document)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--annotations', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--overlay-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    document = json.loads(args.annotations.read_text(encoding='utf-8'))
    errors, warnings = validate_document(document, args.root)
    args.overlay_dir.mkdir(parents=True, exist_ok=True)
    overlays = []
    for item in document.get('annotations', []):
        source = args.root / item['image']
        target = args.overlay_dir / item['frame_id']
        try:
            render_annotation_overlay(item, source, target)
            overlays.append({'frame_id': item['frame_id'],
                             'overlay_sha256': sha(target)})
        except Exception as error:  # noqa: BLE001
            errors.append(item.get('frame_id', '?') + ': overlay ' + repr(error))
    report = {
        'schema_version': 'dsh.annotation_qa.v1',
        'document_schema_version': document.get('schema_version'),
        'annotations': str(args.annotations),
        'annotations_sha256': sha(args.annotations),
        'root': str(args.root),
        'count': len(document.get('annotations', [])),
        'errors': errors,
        'warnings': warnings,
        'overlays': overlays,
        'status': 'PASS' if not errors else 'FAIL',
        'limits': 'schema v1/v2 data QA only (coordinates, enums, combination rules); agent proxy annotations are not expert or human independent review; not a sealed test',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n',
                           encoding='utf-8')
    print(json.dumps({'status': report['status'], 'errors': errors,
                      'warnings': warnings[:5], 'count': report['count']},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
