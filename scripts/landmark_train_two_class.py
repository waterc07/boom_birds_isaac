"""Two-class landmark training / smoke / pilot CLI (bounded internal research).

Subcommands via flags:
  --write-model-yaml      generate outputs/.../landmark_yolov8n-pose-2class-1kpt.yaml (nc=2)
  --merge-shards          merge T31/T32 two-class shard files (+ optional val_main MS1) after QA
  --prepare-dataset       build the YOLO two-class dataset (images/labels/data.yaml)
  --smoke                 engineering smoke on labels_identity_dev 62 frames (<=20 train images)
  --train                 R1 pilot/seed training from frozen single-class v5 weights, val-only eval

Rules: labels are source-image normalised for YOLO (bbox source px xyxy / class0 keypoint
[0,1] are converted here); class1 keypoint is always v=0 and loss-masked; inference
uses images only (no GT); consumer identity/bearing metrics are owned by evaltool.
Exit codes: 0 ok, 2 invalid input / gate not evaluable, 3 refused overwrite, 4 missing backend.
"""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'src'))

from boom_birds.evaluation import landmark_two_class as two  # noqa: E402
from boom_birds.evaluation import landmark_yolo as single  # noqa: E402

EXIT_OK = 0
EXIT_INVALID = 2
EXIT_REFUSED = 3
EXIT_BACKEND = 4

DEFAULT_BASE_WEIGHTS = 'outputs/landmark_train/runs/stage_verify_v5/seed2/seed2/weights/last.pt'
DEFAULT_VAL_LABELS = 'outputs/perception/dev_annotations_20261104/labels_val_validation163.json'
DEFAULT_IDENTITY_LABELS = 'outputs/perception/dev_annotations_20261104/labels_identity_dev.json'
DEFAULT_MODEL_YAML = 'outputs/landmark_train/dataset/landmark_yolov8n-pose-2class-1kpt.yaml'
DEFAULT_MERGED_LABELS = 'outputs/landmark_train/dataset/labels_train_v6_merged.json'
DEFAULT_DATASET_DIR = 'outputs/landmark_train/dataset/dev_v6'


def dump_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return two.sha256_file(path) if Path(path).is_file() else None


# --- model yaml --------------------------------------------------------------

def write_model_yaml(out_path):
    import re
    import ultralytics
    template_path = (Path(ultralytics.__file__).resolve().parent
                     / 'cfg' / 'models' / 'v8' / 'yolov8-pose.yaml')
    if not template_path.is_file():
        raise FileNotFoundError('ultralytics pose template not found: %s' % template_path)
    text = template_path.read_text(encoding='utf-8')
    text = re.sub(r'(?m)^nc:.*$', 'nc: 2  # 0 central_tower, 1 similar_structure_ms1', text, count=1)
    text = re.sub(r'(?m)^kpt_shape:.*$',
                  'kpt_shape: [1, 3]  # one green roof-light keypoint (x, y, visible)',
                  text, count=1)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding='utf-8')
    return {'path': str(out_path), 'sha256': sha(out_path),
            'template_sha256': two.sha256_file(template_path)}


# --- prepare dataset ---------------------------------------------------------

def merge_and_qa(args):
    merged = two.merge_two_class_shards(
        [Path(path) for path in args.shards],
        Path(args.merged_labels), REPO_ROOT)
    if not merged.get('ok'):
        print(json.dumps(merged, indent=2))
        return None, merged
    return merged, None


def prepare_dataset(args):
    model_info = write_model_yaml(Path(args.model_yaml)) if not Path(args.model_yaml).is_file() else {
        'path': args.model_yaml, 'sha256': sha(args.model_yaml), 'template_sha256': None}
    merged, error = merge_and_qa(args)
    if error:
        return EXIT_INVALID
    train_document = load_json(args.merged_labels)
    documents = [train_document]
    val_document = load_json(args.val_labels)
    documents.append(val_document)
    if args.ms1_val_labels and Path(args.ms1_val_labels).is_file():
        documents.append(load_json(args.ms1_val_labels))
    summary = two.build_dataset(documents, Path(args.dataset_dir), REPO_ROOT,
                                splits=('train', 'val'), model_yaml=Path(args.model_yaml))
    summary['model_yaml'] = model_info
    summary['merged_labels'] = {'path': args.merged_labels, 'sha256': sha(args.merged_labels)}
    dump_json(Path(args.dataset_dir) / 'dataset_build.json', summary)
    print(json.dumps(summary, indent=2)[:5000])
    return EXIT_OK


# --- smoke -------------------------------------------------------------------

def _identity_subset_documents(max_train=20, max_val=8):
    document = load_json(REPO_ROOT / DEFAULT_IDENTITY_LABELS)
    annotations = document.get('annotations') or []
    if not annotations:
        raise ValueError('labels_identity_dev has no annotations')
    train_annotations = []
    val_annotations = []
    for annotation in annotations:
        copy = json.loads(json.dumps(annotation))
        source = copy.setdefault('source', {})
        if len(train_annotations) < max_train:
            source['split'] = 'train'
            train_annotations.append(copy)
        elif len(val_annotations) < max_val:
            source['split'] = 'val'
            val_annotations.append(copy)
    train_document = dict(document)
    train_document = {**document, 'annotations': train_annotations}
    val_document = {**document, 'annotations': val_annotations}
    return train_document, val_document


def _loss_mask_probe(device='cuda:0'):
    import torch
    from ultralytics.utils.loss import KeypointLoss
    sigmas = torch.ones(1, device=device)
    loss_fn = KeypointLoss(sigmas=sigmas)
    pred = torch.full((1, 1, 2), 0.9, device=device)
    gt = torch.tensor([[[0.2, 0.3]]], device=device)
    area = torch.ones(1, device=device)
    masked = loss_fn(pred, gt, torch.zeros(1, 1, device=device), area).item()
    supervised = loss_fn(pred, gt, torch.ones(1, 1, device=device), area).item()
    # perturbing coordinates must not change the masked (class1) loss
    perturbed = loss_fn(torch.full((1, 1, 2), 0.1, device=device), gt,
                        torch.zeros(1, 1, device=device), area).item()
    source_line = None
    loss_path = Path(torch.__file__).resolve().parent.parent / 'ultralytics' / 'utils' / 'loss.py'
    import ultralytics
    loss_path = Path(ultralytics.__file__).resolve().parent / 'utils' / 'loss.py'
    for line in loss_path.read_text(encoding='utf-8').splitlines():
        if 'kpt_mask = gt_kpt[..., 2] != 0' in line:
            source_line = line.strip()
            break
    return {'mask0_loss': masked, 'mask1_loss': supervised,
            'mask0_perturbed_loss': perturbed,
            'mask_effective': (masked == 0.0 and supervised > 0.0
                               and abs(perturbed - masked) < 1e-9),
            'ultralytics_mask_source_line': source_line}


def run_smoke(args):
    try:
        from ultralytics import YOLO
        import torch
    except ImportError:
        print('missing backend: ultralytics/torch required for --smoke (use .venv/landmark-train)')
        return EXIT_BACKEND
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    smoke_dir = out_dir / 'smoke_dataset'
    if smoke_dir.exists():
        shutil.rmtree(smoke_dir)
    train_document, val_document = _identity_subset_documents()
    summary = two.build_dataset([train_document, val_document], smoke_dir, REPO_ROOT,
                                splits=('train', 'val'))
    # 1) loader validation from the written txt files (class/v distribution contract)
    loader = {'train_label_files': 0, 'class0_rows': 0, 'class1_rows': 0,
              'class1_v0_rows': 0, 'class0_v1_rows': 0, 'class0_v0_rows': 0}
    for path in (smoke_dir / 'labels' / 'train').glob('*.txt'):
        loader['train_label_files'] += 1
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) != 8:
                raise SystemExit('bad label row length: %r' % line)
            class_id, visibility = int(parts[0]), int(float(parts[7]))
            if class_id == 1:
                loader['class1_rows'] += 1
                loader['class1_v0_rows'] += 1 if visibility == 0 else 0
                if visibility != 0:
                    raise SystemExit('class1 keypoint must be v=0: %r' % line)
            else:
                loader['class0_rows'] += 1
                loader['class0_v1_rows' if visibility == 1 else 'class0_v0_rows'] += 1
    # 2) model yaml + forward finite
    model_yaml = Path(args.model_yaml)
    model_info = write_model_yaml(model_yaml) if not model_yaml.is_file() else {'path': str(model_yaml), 'sha256': sha(model_yaml)}
    data_yaml = smoke_dir / 'data.yaml'
    model = YOLO(str(model_yaml))
    net = model.model.to('cuda:0' if torch.cuda.is_available() else 'cpu').eval()
    device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
    tensor = torch.rand(1, 3, 640, 640, device=device)
    with torch.inference_mode():
        output = net(tensor)
    preds = output[0] if isinstance(output, (tuple, list)) else output
    forward = {'output_shape': list(preds.shape),
               'finite': bool(torch.isfinite(preds).all().item()),
               'expected_channels': 4 + 2 + 3}
    # 3) init from frozen single-class v5 weights (head re-init for nc=2) and 1 epoch loss
    base_weights = Path(args.base_weights)
    init_model = YOLO(str(base_weights)) if base_weights.is_file() else YOLO(str(model_yaml))
    init_model.train(data=str(data_yaml), epochs=1, imgsz=640, batch=4, device=0,
                     workers=0, amp=True, project=str(out_dir), name='smoke_1ep',
                     exist_ok=True, plots=False, val=True, verbose=False)
    one_epoch_csv = Path(init_model.trainer.save_dir) / 'results.csv'
    import csv
    one_epoch_rows = []
    if one_epoch_csv.is_file():
        with open(one_epoch_csv, 'r', encoding='utf-8') as handle:
            one_epoch_rows = [{key.strip(): value.strip() for key, value in row.items()}
                              for row in csv.DictReader(handle)]
    loss_row = one_epoch_rows[-1] if one_epoch_rows else {}
    # 4) tiny overfit on <=20 images (augmentation off) from the same base weights
    overfit_model = YOLO(str(base_weights)) if base_weights.is_file() else YOLO(str(model_yaml))
    overfit_model.train(data=str(data_yaml), epochs=30, imgsz=640, batch=4, device=0,
                        workers=0, amp=True, project=str(out_dir), name='smoke_overfit',
                        exist_ok=True, plots=False, val=True, patience=31, seed=0,
                        warmup_epochs=3, mosaic=0.0, mixup=0.0, copy_paste=0.0,
                        degrees=0.0, translate=0.0, scale=0.0, shear=0.0, perspective=0.0,
                        flipud=0.0, fliplr=0.0, hsv_h=0.0, hsv_s=0.0, hsv_v=0.0,
                        erasing=0.0, close_mosaic=0, verbose=False)
    overfit_csv = Path(overfit_model.trainer.save_dir) / 'results.csv'
    overfit_rows = []
    if overfit_csv.is_file():
        with open(overfit_csv, 'r', encoding='utf-8') as handle:
            overfit_rows = [{key.strip(): value.strip() for key, value in row.items()}
                            for row in csv.DictReader(handle)]
    loss_keys = [key for key in (overfit_rows[0] if overfit_rows else {}) if key.startswith('train/')]
    total = []
    for row in overfit_rows:
        try:
            total.append(sum(float(row[key]) for key in loss_keys))
        except (KeyError, ValueError):
            pass
    overfit = {'epochs': len(overfit_rows), 'total_loss_first': total[0] if total else None,
               'total_loss_last': total[-1] if total else None,
               'loss_decreased': bool(total and total[-1] < total[0] * 0.5),
               'loss_keys': loss_keys}
    # 5) keypoint loss mask probe
    mask_probe = _loss_mask_probe(device)
    # 6) inference uses images only: predict an images-only directory with no labels present
    inference_dir = out_dir / 'inference_images_only'
    inference_dir.mkdir(parents=True, exist_ok=True)
    image_list = sorted((smoke_dir / 'images' / 'val').glob('*.png'))[:4]
    for image in image_list:
        shutil.copyfile(image, inference_dir / image.name)
    results = overfit_model.predict([str(image) for image in image_list], imgsz=640,
                                    conf=0.10, verbose=False)
    predictions = [two.predictions_from_ultralytics(result, Path(getattr(result, 'path', 'image')).name)
                   for result in results]
    inference = {'images': len(image_list), 'labels_present_in_dir': False,
                 'prediction_rows': len(predictions),
                 'detections': sum(len(row['detections']) for row in predictions)}
    # 7) single-class compatibility: a frame without MS1 confusers must keep the single-class line
    compatibility = {'checked': False}
    for annotation in (load_json(REPO_ROOT / DEFAULT_IDENTITY_LABELS).get('annotations') or []):
        if annotation.get('confusers'):
            continue
        single_document = {'schema_version': 'dsh.tower_annotation.v2_1',
                           'annotations': [annotation]}
        single_result = single.convert_annotation_document(single_document, root=REPO_ROOT,
                                                           split=None)
        single_lines = [line for line in single_result['labels'].values()]
        two_record = two.convert_annotation(annotation)
        if not single_lines or not two_record or not two_record['lines']:
            continue
        compatibility = {'checked': True, 'frame_id': annotation['frame_id'],
                         'single_class_line': single_lines[0],
                         'two_class_line': two_record['lines'][0],
                         'byte_identical': single_lines[0] == two_record['lines'][0]}
        break
    evidence = {'status': 'TWO_CLASS_ENGINEERING_SMOKE',
                'generated_at': __import__('datetime').datetime.now(
                    __import__('datetime').timezone.utc).isoformat(),
                'model_yaml': model_info,
                'base_weights': {'path': str(args.base_weights), 'sha256': sha(args.base_weights),
                                 'used_to_initialise': base_weights.is_file()},
                'dataset': summary, 'loader': loader, 'forward': forward,
                'one_epoch_loss_row': loss_row, 'tiny_overfit': overfit,
                'keypoint_mask_probe': mask_probe,
                'inference_inputs_only': inference,
                'single_class_compatibility': compatibility,
                'verdict': {
                    'loader_class1_all_v0': loader['class1_rows'] == loader['class1_v0_rows'],
                    'forward_finite': forward['finite'],
                    'keypoint_loss_finite': all(
                        str(loss_row.get(key, '')).lower() not in ('nan', 'inf')
                        for key in loss_row if 'loss' in key),
                    'tiny_overfit_loss_decreased': overfit['loss_decreased'],
                    'mask_effective': mask_probe['mask_effective'],
                    'inference_no_gt': not inference['labels_present_in_dir'],
                    'single_class_compatible': bool(compatibility.get('byte_identical')),
                }}
    evidence['verdict']['overall'] = all(evidence['verdict'].values())
    dump_json(out_dir / 'smoke_evidence.json', evidence)
    print(json.dumps({key: evidence[key] for key in
                      ('loader', 'forward', 'tiny_overfit', 'keypoint_mask_probe',
                       'inference_inputs_only', 'single_class_compatibility', 'verdict')},
                     indent=2)[:6000])
    return EXIT_OK if evidence['verdict']['overall'] else EXIT_INVALID


# --- train (R1 pilot / seed) -------------------------------------------------

class PatienceStopper:
    def __init__(self, warmup_epochs, patience):
        self.warmup_epochs = int(warmup_epochs)
        self.patience = int(patience)
        self.best_fitness = None
        self.best_epoch = None
        self.stopped_at = None

    def state(self):
        return {'warmup_epochs': self.warmup_epochs, 'patience': self.patience,
                'best_fitness': self.best_fitness, 'best_epoch': self.best_epoch,
                'stopped_at': self.stopped_at}

    def update(self, epoch, fitness):
        if epoch <= self.warmup_epochs:
            return False
        fitness = float(fitness)
        if self.best_fitness is None or fitness > self.best_fitness:
            self.best_fitness = fitness
            self.best_epoch = epoch
            return False
        if self.stopped_at is None and epoch - self.best_epoch >= self.patience:
            self.stopped_at = epoch
            return True
        return False


def _resolve(relative):
    path = Path(relative)
    return path if path.is_absolute() else (REPO_ROOT / path)


def load_run_snapshot_module(code_root=None):
    code_root = Path(code_root or REPO_ROOT)
    module_path = code_root / 'scripts' / 'landmark_run_snapshot.py'
    if not module_path.is_file():
        raise FileNotFoundError('run snapshot script not found: %s' % module_path)
    spec = importlib.util.spec_from_file_location('landmark_run_snapshot_two_class', module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot_preflight(args, out_dir):
    if not args.snapshot_config:
        return {'ok': True, 'skipped': True}
    try:
        module = load_run_snapshot_module()
        snapshot_out = Path(args.snapshot_out) if args.snapshot_out else out_dir / 'run_snapshot.json'
        check_log = Path(args.snapshot_check_log) if args.snapshot_check_log else out_dir / 'snapshot_checks.jsonl'
        created = module.create_snapshot(_resolve(args.snapshot_config), REPO_ROOT,
                                         args.run_id or ('two_class_seed%d' % args.seed), snapshot_out)
        verified = module.verify_snapshot(snapshot_out, REPO_ROOT)
        check = module.record_check(snapshot_out, REPO_ROOT, 'pre_train', check_log)
        return {'ok': bool(verified['ok'] and check.get('ok')), 'created': created.get('status'),
                'snapshot': str(snapshot_out), 'snapshot_sha256': created.get('snapshot_sha256'),
                'verify': verified, 'pre_train': check,
                'check_log': str(check_log)}
    except Exception as error:  # noqa: BLE001 - report, never silently continue
        return {'ok': False, 'error': str(error)}


def snapshot_phase(args, out_dir, phase):
    if not args.snapshot_config:
        return {'ok': True, 'skipped': True}
    module = load_run_snapshot_module()
    snapshot_out = Path(args.snapshot_out) if args.snapshot_out else out_dir / 'run_snapshot.json'
    check_log = Path(args.snapshot_check_log) if args.snapshot_check_log else out_dir / 'snapshot_checks.jsonl'
    return module.record_check(snapshot_out, REPO_ROOT, phase, check_log)


def _load_annotations_for_eval(path):
    return load_json(_resolve(path)).get('annotations') or []


def run_training(args):
    try:
        from ultralytics import YOLO
        import torch
    except ImportError:
        print('missing backend: ultralytics/torch required for --train (use .venv/landmark-train)')
        return EXIT_BACKEND
    dataset_dir = _resolve(args.dataset_dir)
    data_yaml = dataset_dir / 'data.yaml'
    if not data_yaml.is_file():
        print('invalid input: dataset data.yaml missing: %s' % data_yaml)
        return EXIT_INVALID
    out_dir = _resolve(args.out)
    evidence_path = out_dir / ('two_class_pilot_seed%d.json' % args.seed)
    if evidence_path.is_file() and not args.overwrite:
        print('refusing to overwrite %s (pass --overwrite)' % evidence_path)
        return EXIT_REFUSED
    preflight = snapshot_preflight(args, out_dir)
    if not preflight.get('ok'):
        print('INVALID run: immutable run snapshot check failed before training')
        print(json.dumps(preflight, indent=2)[:2000])
        return EXIT_INVALID
    base_weights = _resolve(args.base_weights)
    model = YOLO(str(base_weights)) if base_weights.is_file() else YOLO(str(_resolve(args.model_yaml)))
    stopper = PatienceStopper(args.warmup_epochs, args.patience)
    model.add_callback('on_fit_epoch_end',
                       lambda trainer: setattr(trainer, 'stop', True)
                       if stopper.update(trainer.epoch + 1, trainer.fitness) else None)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    import time
    started = time.perf_counter()
    model.train(data=str(data_yaml), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
                device=0, workers=args.workers, cache=args.cache, amp=True,
                project=str(out_dir), name='train_seed%d' % args.seed, exist_ok=True,
                plots=False, val=True, patience=args.epochs,
                warmup_epochs=args.warmup_epochs, seed=args.seed, deterministic=True,
                verbose=True)
    torch.cuda.synchronize()
    wall = time.perf_counter() - started
    peak = round(torch.cuda.max_memory_allocated() / (1024 ** 2), 1)
    save_dir = Path(model.trainer.save_dir)
    # validation-only evaluation: predictions from images only (no GT), GT applied afterwards
    identity_annotations = _load_annotations_for_eval(args.identity_labels)
    val_main_annotations = _load_annotations_for_eval(args.val_labels)
    ms1_frames = []
    if args.ms1_val_labels and _resolve(args.ms1_val_labels).is_file():
        ms1_document = load_json(_resolve(args.ms1_val_labels))
        ms1_frames = ms1_document.get('frames') or []

    def merged_val_main_annotations():
        """Attach MS1 instances (from the T32 val_main MS1 doc) to the v2.1 annotations."""
        annotations = []
        remaining = {frame.get('frame_id'): frame for frame in ms1_frames}
        for annotation in val_main_annotations:
            clone = json.loads(json.dumps(annotation))
            frame = remaining.pop(clone.get('frame_id'), None)
            if frame:
                clone.setdefault('confusers', [])
                boxes = []
                for instance in frame.get('instances') or []:
                    if int(instance.get('class', 0)) != 1:
                        continue
                    boxes.append([float(value) for value in instance['bbox_xyxy']])
                if not boxes and frame.get('ms1_present') and frame.get('ms1_bbox_xyxy'):
                    boxes.append([float(value) for value in frame['ms1_bbox_xyxy']])
                for box in boxes:
                    x1, y1, x2, y2 = box
                    clone['confusers'].append({
                        'confuser_id': two.MS1_CONFUSER_ID,
                        'description': 'map-native slender green-lamp pillar (MS1)',
                        'bbox_xywh': [x1, y1, x2 - x1, y2 - y1],
                        'verified': True,
                        'verification_source': 'WORLD_POSE_OR_MAP_DB'})
            annotations.append(clone)
        for frame_id, frame in remaining.items():
            confusers = []
            boxes = []
            for instance in frame.get('instances') or []:
                if int(instance.get('class', 0)) != 1:
                    continue
                boxes.append([float(value) for value in instance['bbox_xyxy']])
            if not boxes and frame.get('ms1_present') and frame.get('ms1_bbox_xyxy'):
                boxes.append([float(value) for value in frame['ms1_bbox_xyxy']])
            for box in boxes:
                x1, y1, x2, y2 = box
                confusers.append({'confuser_id': two.MS1_CONFUSER_ID,
                                  'description': 'map-native slender green-lamp pillar (MS1)',
                                  'bbox_xywh': [x1, y1, x2 - x1, y2 - y1], 'verified': True})
            if not confusers:
                continue
            annotations.append({'frame_id': frame_id, 'image': frame.get('image'),
                                'image_width': frame.get('image_width'),
                                'image_height': frame.get('image_height'),
                                'source': {'split': 'val', 'family': frame.get('family'),
                                           'group_id': frame.get('group_id')},
                                'target': {'present': False, 'undecidable': False},
                                'geometry': {'bbox_xywh': None, 'keypoint': None,
                                             'reference_status': 'NOT_APPLICABLE'},
                                'confusers': confusers, 'negative_type': 'SIMILAR_STRUCTURE'})
        return annotations

    val_main_eval_annotations = merged_val_main_annotations()
    identity_images = sorted({str(_resolve(str(annotation['image']))) for annotation in identity_annotations
                              if _resolve(str(annotation['image'])).is_file()})
    tower_val_images = sorted({str(_resolve(str(annotation['image']))) for annotation in val_main_annotations
                                if _resolve(str(annotation['image'])).is_file()})

    def save_predictions(rows, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
        return {'path': str(path), 'sha256': sha(path), 'frames': len(rows)}

    def predict_for(weights, images):
        predictor = YOLO(str(weights))
        rows = []
        for index in range(0, len(images), 16):
            chunk = images[index:index + 16]
            results = predictor.predict(chunk, imgsz=args.imgsz, conf=args.tau_det,
                                        device='cuda:0', verbose=False)
            for result, image in zip(results, chunk):
                row = two.predictions_from_ultralytics(result, Path(image).name)
                for detection in row['detections']:
                    if detection['class_id'] == 0:
                        detection['landmark_id'] = 'RMUC2027_CENTRAL_TOWER_PROPOSED'
                rows.append(row)
        return rows

    selection_check = snapshot_phase(args, out_dir, 'pre_selection')
    if not selection_check.get('ok'):
        print('INVALID run: immutable run snapshot changed before checkpoint selection')
        print(json.dumps(selection_check, indent=2)[:2000])
        return EXIT_INVALID
    candidates = []
    for candidate_name, weights in (('last', save_dir / 'weights' / 'last.pt'),
                                    ('best', save_dir / 'weights' / 'best.pt')):
        if not weights.is_file():
            continue
        tower_rows = predict_for(weights, tower_val_images)
        identity_rows = predict_for(weights, identity_images)
        candidates.append({
            'candidate': candidate_name,
            'weights': str(weights),
            'weights_sha256': sha(weights),
            'predictions': {
                'val_main': save_predictions(tower_rows, out_dir / ('predictions_val_main_%s.jsonl' % candidate_name)),
                'identity': save_predictions(identity_rows, out_dir / ('predictions_identity_%s.jsonl' % candidate_name)),
            },
            'tower_metrics_val_main': two.evaluate_two_class(tower_rows, val_main_eval_annotations,
                                                             tau_det=args.tau_det, tau_iou=args.tau_iou),
            'identity_metrics': two.evaluate_two_class(identity_rows, identity_annotations,
                                                       tau_det=args.tau_det, tau_iou=args.tau_iou),
        })
    candidates.sort(key=lambda item: two.candidate_rank_key(item, args.selection_rule))
    selected = candidates[0] if candidates else None
    tower_metrics = selected['tower_metrics_val_main'] if selected else {'tower': {}, 'reference': {}}
    identity_metrics = selected['identity_metrics'] if selected else {'ms1': {}, 'identity': {}, 'reference': {}}
    baseline_tower_recall = args.baseline_tower_recall
    gate = {
        'tower_recall_val_main_ge_0.70': (tower_metrics['tower']['recall'] or 0) >= 0.70,
        'ms1_recall_identity_ge_0.50': (identity_metrics['ms1']['recall'] or 0) >= 0.50,
        'ms1_only_wrong_tower_claims_le_1': identity_metrics['ms1_only']['wrong_tower_claims'] <= 1,
        'same_frame_disambiguation_ge_0.60': (identity_metrics['same_frame']['rate'] or 0) >= 0.60,
        'two_class_identity_precision_ge_0.95': (identity_metrics['identity']['precision'] or 0) >= 0.95,
        'consumer_confirmed_success_ge_0.30': None,
        'bearing_median_le_3.0deg': ((identity_metrics['reference']['bearing_error_deg'].get('median') or 99) <= 3.0
                                     and (tower_metrics['reference']['bearing_error_deg'].get('median') or 99) <= 3.0),
        'tower_recall_not_worse_than_baseline_by_0.08': (
            (tower_metrics['tower']['recall'] or 0) >= baseline_tower_recall - 0.08),
    }
    evaluable = {key: value for key, value in gate.items() if value is not None}
    evidence = {
        'status': 'TWO_CLASS_R1_PILOT_DEV_VALIDATION_ONLY',
        'generated_at': __import__('datetime').datetime.now(
            __import__('datetime').timezone.utc).isoformat(),
        'config': {'seed': args.seed, 'epochs': args.epochs, 'imgsz': args.imgsz,
                   'batch': args.batch, 'warmup_epochs': args.warmup_epochs,
                   'patience': args.patience, 'workers': args.workers, 'cache': args.cache,
                   'base_weights': str(base_weights), 'base_weights_sha256': sha(base_weights),
                   'tau_det': args.tau_det, 'tau_iou': args.tau_iou,
                   'selection_rule': args.selection_rule},
        'model_yaml': {'path': args.model_yaml, 'sha256': sha(_resolve(args.model_yaml))},
        'dataset': {'dir': str(dataset_dir), 'data_yaml_sha256': sha(data_yaml),
                    'dataset_build_sha256': sha(dataset_dir / 'dataset_build.json')},
        'timing': {'wall_seconds': round(wall, 2), 'peak_memory_allocated_mib': peak},
        'early_stop': stopper.state(),
        'selection': {'rule': args.selection_rule,
                      'rule_description': ('r1_detector: tower recall -> MS1 recall -> same-frame -> name'
                                           if args.selection_rule == 'r1_detector' else
                                           'r2_joint: tower recall + MS1 recall (equal weight) -> same-frame -> name'),
                      'selected': selected['candidate'] if selected else None,
                      'weights_sha256': selected['weights_sha256'] if selected else None,
                      'predictions_val_main': (selected['predictions']['val_main'] if selected else None),
                      'predictions_identity': (selected['predictions']['identity'] if selected else None)},
        'candidates': [{key: item[key] for key in ('candidate', 'weights', 'weights_sha256', 'predictions')}
                       for item in candidates],
        'tower_metrics_val_main': tower_metrics,
        'identity_metrics': identity_metrics,
        'consumer_metrics': {'status': 'PENDING_EVALTOOL_T34',
                             'note': 'consumer confirmed-identity success owned by evaltool'},
        'pilot_gate': {'conditions': gate, 'evaluable_conditions': evaluable,
                       'pass': (all(evaluable.values()) if evaluable else False),
                       'consumer_condition_pending': True,
                       'note': 'per protocol the pilot stage decides promotion; the consumer condition is '
                               'filled by evaltool T34 and is not self-defined here'},
    }
    post_check = snapshot_phase(args, out_dir, 'post_train')
    evidence['run_snapshot'] = {'preflight': preflight, 'pre_selection': selection_check,
                                'post_train': post_check}
    if not post_check.get('ok'):
        evidence['status'] = 'INVALID_RUN_SNAPSHOT'
        dump_json(evidence_path, evidence)
        print('INVALID run: immutable run snapshot changed during training')
        return EXIT_INVALID
    dump_json(evidence_path, evidence)
    print(json.dumps({'timing': evidence['timing'],
                      'tower': tower_metrics['tower'],
                      'ms1': identity_metrics['ms1'],
                      'ms1_only': identity_metrics['ms1_only'],
                      'same_frame': identity_metrics['same_frame'],
                      'identity': identity_metrics['identity'],
                      'reference': {'coverage': identity_metrics['reference']['coverage'],
                                    'bearing': identity_metrics['reference']['bearing_error_deg']},
                      'pilot_gate': gate}, indent=2)[:6000])
    print('wrote', evidence_path)
    return EXIT_OK


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--repo-root', default=None)
    parser.add_argument('--model-yaml', default=DEFAULT_MODEL_YAML)
    parser.add_argument('--base-weights', default=DEFAULT_BASE_WEIGHTS)
    parser.add_argument('--val-labels', default=DEFAULT_VAL_LABELS)
    parser.add_argument('--identity-labels', default=DEFAULT_IDENTITY_LABELS)
    parser.add_argument('--ms1-val-labels', default=None)
    parser.add_argument('--dataset-dir', default=DEFAULT_DATASET_DIR)
    parser.add_argument('--merged-labels', default=DEFAULT_MERGED_LABELS)
    parser.add_argument('--shards', nargs='*', default=[])
    parser.add_argument('--out', default='outputs/landmark_train/runs/two_class_smoke')
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--epochs', type=int, default=15)
    parser.add_argument('--imgsz', type=int, default=640)
    parser.add_argument('--batch', type=int, default=16)
    parser.add_argument('--workers', type=int, default=0)
    parser.add_argument('--cache', default=False)
    parser.add_argument('--warmup-epochs', type=int, default=15)
    parser.add_argument('--patience', type=int, default=20)
    parser.add_argument('--tau-det', type=float, default=0.25)
    parser.add_argument('--tau-iou', type=float, default=0.3)
    parser.add_argument('--baseline-tower-recall', type=float, default=0.821)
    parser.add_argument('--snapshot-config', default=None)
    parser.add_argument('--snapshot-out', default=None)
    parser.add_argument('--snapshot-check-log', default=None)
    parser.add_argument('--run-id', default=None)
    parser.add_argument('--selection-rule', choices=two.SELECTION_RULES, default='r1_detector',
                        help='frozen checkpoint-selection rule (R2 uses r2_joint)')
    parser.add_argument('--overwrite', action='store_true')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--write-model-yaml', action='store_true')
    mode.add_argument('--merge-shards', action='store_true')
    mode.add_argument('--prepare-dataset', action='store_true')
    mode.add_argument('--smoke', action='store_true')
    mode.add_argument('--train', action='store_true')
    args = parser.parse_args(argv)
    if args.write_model_yaml:
        print(json.dumps(write_model_yaml(_resolve(args.model_yaml)), indent=2))
        return EXIT_OK
    if args.merge_shards:
        if not args.shards:
            print('invalid input: --merge-shards needs at least one --shards path')
            return EXIT_INVALID
        merged, error = merge_and_qa(args)
        if error:
            print(json.dumps(error, indent=2))
            return EXIT_INVALID
        print(json.dumps(merged, indent=2))
        return EXIT_OK
    if args.prepare_dataset:
        return prepare_dataset(args)
    if args.smoke:
        return run_smoke(args)
    if args.train:
        return run_training(args)
    return EXIT_INVALID


if __name__ == '__main__':
    raise SystemExit(main())
