"""Reproducible host-side ONNX export for the bounded landmark model.

Versioned replacement for the gitignored outputs/landmark_train/scripts/
export_onnx_check.py: real CLI, repo-relative config, no machine-private paths,
no dataset dependency, refuses to overwrite frozen artefacts unless --overwrite.

Usage (inside the isolated training venv):
    .venv/landmark-train/Scripts/python.exe scripts/landmark_export_onnx.py \
        --config configs/perception/landmark_export_v1.json \
        --json-out outputs/perception/onnx_parity_20261104/export_evidence.json \
        --verify

Exit codes: 0 = exported and verified, 2 = invalid input, 3 = overwrite refused,
4 = export or numeric verification failed.

Scope: host-side only.  RKNN conversion, board latency, accuracy and navigation
are out of scope; see configs/perception/landmark_export_v1.json.
"""
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault('TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD', '1')
os.environ.setdefault('TORCH_FORCE_NO_WEIGHT_ONLY_LOAD', '1')
os.environ.setdefault('YOLO_AUTOINSTALL', 'false')

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / 'src'
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from boom_birds.evaluation import landmark_onnx as parity  # noqa: E402

DEFAULT_CONFIG = REPO_ROOT / 'configs' / 'perception' / 'landmark_export_v1.json'
EXIT_OK = 0
EXIT_INVALID_INPUT = 2
EXIT_OVERWRITE_REFUSED = 3
EXIT_EXPORT_FAILED = 4


def resolve_repo_path(value, *, allow_absolute=False, what='path'):
    """Resolve a config/CLI path against the repository root."""
    if value is None or str(value).strip() == '':
        raise ValueError('%s is required' % what)
    path = Path(str(value))
    if path.is_absolute() and not allow_absolute:
        raise ValueError('%s must be repo-relative, got %r' % (what, value))
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def load_config(path=None):
    config_path = Path(path) if path else DEFAULT_CONFIG
    document = parity.load_json(config_path)
    if document.get('schema_version') != 'dsh.landmark_export.v1':
        raise ValueError('unexpected config schema: %r'
                         % document.get('schema_version'))
    return document, config_path


def _deterministic_image(width=320, height=240):
    """Synthetic BGR image so the numeric check never depends on the dataset."""
    import numpy as np
    image = np.zeros((height, width, 3), dtype=np.uint8)
    rows = np.linspace(0, 255, height, dtype=np.uint8)[:, None]
    cols = np.linspace(0, 255, width, dtype=np.uint8)[None, :]
    image[:, :, 0] = rows
    image[:, :, 1] = cols
    image[height // 2 - 5:height // 2 + 5, width // 2 - 5:width // 2 + 5] = (0, 255, 0)
    return image


def _package_versions():
    versions = {}
    for name in ('torch', 'ultralytics', 'onnx', 'onnxruntime', 'numpy'):
        try:
            module = __import__(name)
            versions[name] = getattr(module, '__version__', None)
        except Exception as error:  # pragma: no cover - environment specific
            versions[name] = 'UNAVAILABLE: %r' % (error,)
    return versions


def _raw_numeric_check(weights_path, onnx_path, imgsz):
    """Compare torch and onnxruntime raw outputs on the same shared canvas."""
    import numpy as np
    from ultralytics import YOLO
    tensor, spec, _ = parity.preprocess(_deterministic_image(), imgsz)
    model = YOLO(str(weights_path), task='pose')
    import torch
    network = model.model.float().eval()
    with torch.no_grad():
        output = network(torch.from_numpy(tensor))
    if isinstance(output, (tuple, list)):
        output = output[0]
    reference = output.detach().cpu().numpy()
    import onnxruntime
    session = onnxruntime.InferenceSession(str(onnx_path),
                                           providers=['CPUExecutionProvider'])
    input_name = session.get_inputs()[0].name
    candidate = session.run(None, {input_name: tensor})[0]
    reference = np.asarray(reference, dtype=np.float32)
    candidate = np.asarray(candidate, dtype=np.float32)
    if reference.shape != candidate.shape:
        return {'performed': True, 'shape_match': False,
                'torch_shape': list(reference.shape),
                'onnx_shape': list(candidate.shape),
                'max_abs_diff': None, 'passed': False,
                'preprocess': spec.as_dict()}
    difference = float(np.max(np.abs(reference - candidate)))
    return {
        'performed': True,
        'shape_match': True,
        'torch_shape': list(reference.shape),
        'onnx_shape': list(candidate.shape),
        'max_abs_diff': difference,
        'mean_abs_diff': float(np.mean(np.abs(reference - candidate))),
        'all_finite': bool(np.isfinite(reference).all()
                           and np.isfinite(candidate).all()),
        'preprocess': spec.as_dict(),
    }


def export_onnx(weights_path, output_path, *, config=None, opset=None,
                imgsz=None, simplify=None, device=None, overwrite=False,
                verify=True):
    """Export a .pt pose model to ONNX and return an evidence dictionary."""
    if isinstance(config, tuple):
        config = config[0]
    if config is None:
        config, _ = load_config()
    export_cfg = config.get('export') or {}
    opset = int(opset if opset is not None else export_cfg.get('opset', 18))
    imgsz = int(imgsz if imgsz is not None else export_cfg.get('imgsz', 640))
    simplify = bool(export_cfg.get('simplify', True) if simplify is None
                    else simplify)
    device = device or export_cfg.get('device', 'cpu')
    weights_path = Path(weights_path).resolve()
    output_path = Path(output_path)
    if not output_path.is_absolute():
        output_path = (REPO_ROOT / output_path).resolve()
    if not weights_path.is_file():
        raise FileNotFoundError('weights not found: %s' % weights_path)
    if output_path.exists() and not overwrite:
        raise FileExistsError('refusing to overwrite %s (pass --overwrite only '
                              'for a deliberate new export)' % output_path)
    started = time.perf_counter()
    from ultralytics import YOLO
    exporter = YOLO(str(weights_path), task='pose')
    exported = Path(str(exporter.export(format='onnx', opset=opset,
                                        imgsz=imgsz, simplify=simplify,
                                        device=device)))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(exported, output_path)
    export_seconds = time.perf_counter() - started
    import onnx
    model_onnx = onnx.load(str(output_path))
    opsets = {(item.domain or 'ai.onnx'): int(item.version)
              for item in model_onnx.opset_import}
    evidence = {
        'schema_version': 'dsh.landmark_onnx_export.v1',
        'status': 'EXPORTED_HOST_SIDE',
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'generated_by': 'scripts/landmark_export_onnx.py',
        'weights': {'path': str(weights_path),
                    'repo_relative': str(weights_path.relative_to(REPO_ROOT))
                    if str(weights_path).startswith(str(REPO_ROOT)) else None,
                    'sha256': parity.sha256_file(weights_path)},
        'onnx': {'path': str(output_path),
                 'repo_relative': str(output_path.relative_to(REPO_ROOT))
                 if str(output_path).startswith(str(REPO_ROOT)) else None,
                 'sha256': parity.sha256_file(output_path),
                 'size_bytes': output_path.stat().st_size,
                 'opset_import': opsets,
                 'requested_opset': opset,
                 'requested_imgsz': imgsz,
                 'simplify_requested': simplify,
                 'graph_nodes': len(model_onnx.graph.node),
                 'inputs': [[item.name,
                             [dim.dim_value for dim in
                              item.type.tensor_type.shape.dim]]
                            for item in model_onnx.graph.input],
                 'outputs': [[item.name,
                              [dim.dim_value for dim in
                               item.type.tensor_type.shape.dim]]
                             for item in model_onnx.graph.output]},
        'timing': {'export_seconds': round(export_seconds, 2)},
        'environment': _package_versions(),
        'requested': {'opset': opset, 'imgsz': imgsz, 'simplify': simplify,
                      'device': device},
    }
    verdict = {'opset_expected': opsets.get('ai.onnx') == opset}
    if verify:
        numeric = _raw_numeric_check(weights_path, output_path, imgsz)
        verification = (config.get('export') or {}).get('verification') or {}
        relative_atol = float(verification.get(
            'raw_torch_vs_onnxruntime_max_abs_diff_relative', 1e-3))
        # Absolute differences are dominated by the coordinate channels whose
        # values span 0..imgsz; a relative criterion (diff / imgsz) is the
        # meaningful host-side check (1e-3 = 0.64 input px).
        relative = (float(numeric['max_abs_diff']) / float(imgsz)
                    if numeric.get('max_abs_diff') is not None else None)
        numeric['relative_atol'] = relative_atol
        numeric['max_abs_diff_relative_to_input_px'] = relative
        numeric['passed'] = bool(
            numeric.get('shape_match') and relative is not None
            and relative <= relative_atol and numeric.get('all_finite'))
        evidence['numeric_check'] = numeric
        verdict['numeric_pass'] = numeric['passed']
    evidence['verdict'] = verdict
    evidence['verdict']['overall'] = bool(verdict['opset_expected']
                                          and verdict.get('numeric_pass', True))
    return evidence


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='Export the bounded landmark YOLOv8n-pose checkpoint to '
                    'ONNX (host-side only) and optionally verify torch vs '
                    'onnxruntime raw numerics.')
    parser.add_argument('--config', default=str(DEFAULT_CONFIG))
    parser.add_argument('--model', default=None,
                        help='source .pt (default: config export.source_weights)')
    parser.add_argument('--out', default=None,
                        help='target .onnx (default: config export.output)')
    parser.add_argument('--opset', type=int, default=None)
    parser.add_argument('--imgsz', type=int, default=None)
    parser.add_argument('--device', default=None)
    parser.add_argument('--simplify', dest='simplify', action='store_true',
                        default=None)
    parser.add_argument('--no-simplify', dest='simplify', action='store_false')
    parser.add_argument('--overwrite', action='store_true',
                        help='allow replacing an existing ONNX file')
    parser.add_argument('--verify', dest='verify', action='store_true',
                        default=True)
    parser.add_argument('--no-verify', dest='verify', action='store_false')
    parser.add_argument('--json-out', default=None,
                        help='write the evidence JSON here')
    parser.add_argument('--quiet', action='store_true')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        config, config_path = load_config(args.config)
        export_cfg = config.get('export') or {}
        weights = resolve_repo_path(args.model or export_cfg.get('source_weights'),
                                    allow_absolute=True and args.model is not None,
                                    what='model')
        output = resolve_repo_path(args.out or export_cfg.get('output'),
                                   allow_absolute=args.out is not None,
                                   what='out')
        evidence = export_onnx(weights, output, config=config,
                               opset=args.opset, imgsz=args.imgsz,
                               simplify=args.simplify, device=args.device,
                               overwrite=args.overwrite, verify=args.verify)
        evidence['config'] = {'path': str(config_path),
                              'sha256': parity.sha256_file(config_path)}
        if args.json_out:
            json_path = resolve_repo_path(args.json_out, allow_absolute=True,
                                          what='json-out')
            parity.dump_json(json_path, evidence)
            evidence['json_out'] = str(json_path)
        if not args.quiet:
            summary = {
                'status': evidence['status'],
                'weights_sha256': evidence['weights']['sha256'],
                'onnx_sha256': evidence['onnx']['sha256'],
                'opset': evidence['onnx']['opset_import'],
                'numeric': evidence.get('numeric_check'),
                'verdict': evidence['verdict'],
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        return EXIT_OK if evidence['verdict']['overall'] else EXIT_EXPORT_FAILED
    except FileExistsError as error:
        print(str(error), file=sys.stderr)
        return EXIT_OVERWRITE_REFUSED
    except (ValueError, FileNotFoundError, KeyError) as error:
        print('invalid input: %s' % (error,), file=sys.stderr)
        return EXIT_INVALID_INPUT
    except Exception as error:  # pragma: no cover - backend failures
        print('export failed: %r' % (error,), file=sys.stderr)
        return EXIT_EXPORT_FAILED


if __name__ == '__main__':
    raise SystemExit(main())
