"""Landmark dataset grouping, leakage checks and canonical freeze hashing.

The module treats the raw observations.jsonl shadow runs as read-only input.
It never writes to outputs/ and imports only the standard library.

Grouping protocol (GROUPING_PROTOCOL)
-------------------------------------
A *group* is one physical trajectory family x acquisition session x render
version.  A *family* is the physical trajectory / viewpoint cluster (for
example the south-A corridor or the north corridor) and may contain several
groups (one per session / render version).  Frames of one episode always stay
in one group, so consecutive frames can never cross a train/validation split.
Families are the leak boundary used by validate_freeze: groups of one family
must not appear in train and val/test at the same time.

Freeze file (FREEZE_SCHEMA)
---------------------------
The freeze stores the datasets used, their input hashes, the family/group
inventory, every frame id with its payload sha256 and accepted flag, the
split assignment, the label-file hashes and a canonical freeze_sha256.
generated_at and freeze_sha256 are excluded from the canonical hash so that the
file can be re-verified byte-identically after a re-save.

Status labels: these checks are data plumbing / format QA only.  Passing them
is not a model, board or navigation result and does not create a sealed test.
"""
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re

FREEZE_SCHEMA = 'dsh.landmark_split_freeze.v1'
GROUPING_PROTOCOL = 'dsh.landmark_dataset_grouping.v1'
SPLITS = ('train', 'val', 'test', 'excluded')
DEV_SPLITS = ('train', 'val')
#: Fields excluded from the canonical freeze hash (build metadata only).
VOLATILE_FREEZE_FIELDS = ('generated_at', 'freeze_sha256')
#: Historical label split names mapped onto the group split vocabulary.
LABEL_SPLIT_ALIASES = {
    'train': 'train',
    'development': 'train',
    'dev': 'train',
    'val': 'val',
    'validation': 'val',
    'test': 'test',
    'sealed_test': 'test',
    'sealed': 'test',
}
FRAME_PATTERN = re.compile(
    r'^(?P<episode>.+)-follow_only_g(?P<generation>\d+)_'
    r'(?P<sequence>\d+)\.png$')


class DatasetInputError(RuntimeError):
    """Raised when an observations or label file is missing, empty or corrupt."""


@dataclass(frozen=True)
class Frame:
    """One accepted or rejected front RGB shadow observation."""

    dataset: str
    frame_id: str
    ref: str
    sha256: str
    episode_id: str
    generation: int
    sequence: int
    accepted: bool


@dataclass(frozen=True)
class DatasetFrames:
    """Read-only view of one *_sensor/observations.jsonl file."""

    dataset: str
    observations: str
    observations_sha256: str
    frames: tuple
    images_present: int = 0
    images_missing: int = 0
    image_sha_mismatches: int = 0


@dataclass(frozen=True)
class Issue:
    """One validation finding; code is stable for tests and reports."""

    code: str
    message: str
    detail: dict = field(default_factory=dict)


class ValidationReport:
    """Errors, warnings and countable evidence produced by a freeze check."""

    def __init__(self):
        self.errors = []
        self.warnings = []
        self.stats = {
            'datasets': {},
            'groups': 0,
            'families': 0,
            'frame_total': 0,
            'accepted_frame_total': 0,
            'split_frame_counts': {split: 0 for split in SPLITS},
            'split_accepted_frame_counts': {split: 0 for split in SPLITS},
            'split_group_counts': {split: 0 for split in SPLITS},
            'duplicate_sha_groups': 0,
            'intra_group_duplicate_sha_groups': 0,
            'frames_unassigned': 0,
            'episode_split_conflicts': 0,
            'consecutive_frame_split_violations': 0,
            'family_split_leaks': 0,
            'sealed_groups_in_dev': 0,
            'label_frame_total': 0,
            'label_split_claim_counts': {},
            'label_split_claim_conflicts': 0,
            'view_cluster_split_warnings': 0,
            'images_verified': 0,
            'images_missing': 0,
            'image_sha_mismatches': 0,
        }

    def add_error(self, code, message, **detail):
        self.errors.append(Issue(code, message, detail))

    def add_warning(self, code, message, **detail):
        self.warnings.append(Issue(code, message, detail))

    @property
    def ok(self):
        return not self.errors

    @property
    def error_codes(self):
        return {issue.code for issue in self.errors}

    @property
    def warning_codes(self):
        return {issue.code for issue in self.warnings}

    def as_dict(self):
        return {
            'status': 'PASS' if self.ok else 'FAIL',
            'errors': [issue.__dict__ for issue in self.errors],
            'warnings': [issue.__dict__ for issue in self.warnings],
            'stats': self.stats,
        }


# ---------------------------------------------------------------------------
# deterministic helpers
# ---------------------------------------------------------------------------

def sha256_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def parse_frame_id(frame_id):
    """Parse <episode>-follow_only_g<generation>_<sequence>.png."""
    match = FRAME_PATTERN.match(frame_id or '')
    if match is None:
        return None
    return {
        'episode_id': match.group('episode'),
        'generation': int(match.group('generation')),
        'sequence': int(match.group('sequence')),
    }


def frame_ref(dataset_root, frame_id):
    """Repository-relative image path for one frame id."""
    return (dataset_root.rstrip('/') + '/images/' + frame_id)


def _normalise_ref(ref):
    return str(ref).replace('\\', '/').strip()


def canonical_payload(freeze):
    """Return the freeze content that the canonical hash covers."""
    return {key: value for key, value in freeze.items()
            if key not in VOLATILE_FREEZE_FIELDS}


def canonical_freeze_bytes(freeze):
    """Canonical JSON bytes: sorted keys, compact separators, UTF-8."""
    return json.dumps(canonical_payload(freeze), sort_keys=True,
                      separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def freeze_sha256(freeze):
    return sha256_bytes(canonical_freeze_bytes(freeze))


def find_duplicate_shas(dataset_frames):
    """Map payload sha256 -> frames when the same bytes appear more than once."""
    by_sha = {}
    for loaded in dataset_frames.values():
        for frame in loaded.frames:
            by_sha.setdefault(frame.sha256, []).append(frame)
    return {sha: frames for sha, frames in by_sha.items() if len(frames) > 1}


# ---------------------------------------------------------------------------
# input loading
# ---------------------------------------------------------------------------

def load_dataset_frames(repo_root, dataset, dataset_root, observations,
                        *, allow_empty=False, require_images=False,
                        verify_images=True):
    """Load front-RGB frames from one shadow observations JSONL.

    Depth records (empty payload.ref) are ignored.  Missing, empty or malformed
    inputs raise DatasetInputError; returning partial data would hide exactly
    the failure this tool exists to catch.
    """
    root = Path(repo_root)
    observations_path = root / observations
    if not observations_path.is_file():
        raise DatasetInputError(
            'observations file missing for %s: %s' % (dataset, observations))
    raw_bytes = observations_path.read_bytes()
    observations_sha = sha256_bytes(raw_bytes)
    frames = []
    seen_refs = set()
    for line_number, line in enumerate(raw_bytes.decode('utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise DatasetInputError(
                '%s line %d is not valid JSON: %s' % (dataset, line_number, error))
        if not isinstance(record, dict):
            raise DatasetInputError(
                '%s line %d is not a JSON object' % (dataset, line_number))
        if record.get('sensor_key') != 'front_rgb':
            continue
        payload = record.get('payload') or {}
        ref = _normalise_ref(payload.get('ref') or '')
        if not ref:
            raise DatasetInputError(
                '%s line %d is front_rgb but has no payload.ref'
                % (dataset, line_number))
        frame_id = Path(ref).name
        parsed = parse_frame_id(frame_id)
        if parsed is None:
            raise DatasetInputError(
                '%s line %d has unparsable frame id: %s'
                % (dataset, line_number, frame_id))
        expected_ref = frame_ref(dataset_root, frame_id)
        if ref != expected_ref:
            raise DatasetInputError(
                '%s line %d ref %s is outside declared dataset root %s'
                % (dataset, line_number, ref, dataset_root))
        if ref in seen_refs:
            raise DatasetInputError(
                '%s frame %s appears twice in observations' % (dataset, ref))
        seen_refs.add(ref)
        sha = payload.get('sha256')
        if not sha:
            raise DatasetInputError(
                '%s frame %s has no payload.sha256' % (dataset, ref))
        gate = record.get('gate') or {}
        frames.append(Frame(
            dataset=dataset,
            frame_id=frame_id,
            ref=ref,
            sha256=sha,
            episode_id=parsed['episode_id'],
            generation=parsed['generation'],
            sequence=parsed['sequence'],
            accepted=bool(gate.get('accepted')),
        ))
    if not frames:
        if not allow_empty:
            raise DatasetInputError('no front_rgb frames in %s' % dataset)
        return DatasetFrames(dataset, _normalise_ref(observations),
                             observations_sha, ())
    frames.sort(key=lambda item: (item.episode_id, item.sequence))
    images_present = 0
    images_missing = 0
    image_sha_mismatches = 0
    if verify_images:
        for frame in frames:
            image_path = root / frame.ref
            if not image_path.is_file():
                images_missing += 1
                if require_images:
                    raise DatasetInputError(
                        'image missing for %s: %s' % (dataset, frame.ref))
                continue
            images_present += 1
            if sha256_bytes(image_path.read_bytes()) != frame.sha256:
                image_sha_mismatches += 1
    return DatasetFrames(dataset, _normalise_ref(observations), observations_sha,
                         tuple(frames), images_present, images_missing,
                         image_sha_mismatches)


# ---------------------------------------------------------------------------
# freeze validation
# ---------------------------------------------------------------------------

def validate_freeze(freeze, repo_root, *, verify_input_hashes=True,
                    require_images=False, verify_images=True,
                    check_labels=True):
    """Cross-check a freeze document against the present raw observations."""
    root = Path(repo_root)
    report = ValidationReport()

    if freeze.get('schema_version') != FREEZE_SCHEMA:
        report.add_error('SCHEMA_VERSION',
                         'expected %s, found %r' % (FREEZE_SCHEMA,
                                                    freeze.get('schema_version')))
    if freeze.get('grouping_protocol') != GROUPING_PROTOCOL:
        report.add_error('GROUPING_PROTOCOL',
                         'expected %s, found %r'
                         % (GROUPING_PROTOCOL, freeze.get('grouping_protocol')))

    stored_hash = freeze.get('freeze_sha256')
    if stored_hash is None:
        report.add_warning('FREEZE_HASH_MISSING', 'freeze has no freeze_sha256')
    elif stored_hash != freeze_sha256(freeze):
        report.add_error('FREEZE_HASH_MISMATCH',
                         'canonical freeze hash does not match stored value')

    datasets = freeze.get('datasets') or {}
    if not isinstance(datasets, dict):
        report.add_error('FREEZE_SCHEMA', 'datasets must be an object')
        datasets = {}

    # ---- split table -----------------------------------------------------
    splits_table = freeze.get('splits') or {}
    group_split = {}
    for split in SPLITS:
        for group_id in splits_table.get(split) or []:
            if group_id in group_split:
                report.add_error('GROUP_IN_MULTIPLE_SPLITS',
                                 'group %s listed in both %s and %s'
                                 % (group_id, group_split[group_id], split))
            else:
                group_split[group_id] = split
    for split in splits_table:
        if split not in SPLITS:
            report.add_warning('UNKNOWN_SPLIT', 'unknown split %r' % split)

    # ---- groups ----------------------------------------------------------
    groups = freeze.get('groups') or []
    group_by_id = {}
    for group in groups:
        group_id = group.get('group_id')
        if not group_id:
            report.add_error('FREEZE_SCHEMA', 'group without group_id')
            continue
        if group_id in group_by_id:
            report.add_error('DUPLICATE_GROUP_ID',
                             'group id %s appears more than once' % group_id)
            continue
        group_by_id[group_id] = group
    report.stats['groups'] = len(group_by_id)

    for group_id, group in group_by_id.items():
        assigned = group_split.get(group_id)
        if assigned is None:
            report.add_error('GROUP_UNASSIGNED',
                             'group %s is not listed in any split' % group_id)
            continue
        if group.get('split') != assigned:
            report.add_error('GROUP_SPLIT_MISMATCH',
                             'group %s declares split %r but splits table says %r'
                             % (group_id, group.get('split'), assigned))
        if group.get('sealed'):
            if assigned in DEV_SPLITS:
                report.add_error(
                    'SEALED_GROUP_IN_DEV',
                    'sealed group %s is assigned to %s' % (group_id, assigned))
                report.stats['sealed_groups_in_dev'] += 1
            elif assigned != 'test':
                report.add_warning(
                    'SEALED_GROUP_NOT_IN_TEST',
                    'sealed group %s is assigned to %s' % (group_id, assigned))
        report.stats['split_group_counts'][assigned] += 1

    sealed_table = freeze.get('sealed') or {}
    for group_id in sealed_table.get('groups') or []:
        if group_split.get(group_id) in DEV_SPLITS:
            report.add_error('SEALED_GROUP_IN_DEV',
                             'sealed group %s from sealed table assigned to %s'
                             % (group_id, group_split.get(group_id)))
            report.stats['sealed_groups_in_dev'] += 1
    if sealed_table.get('present'):
        if not any(split == 'test' for split in group_split.values()):
            report.add_warning(
                'SEALED_DECLARED_WITHOUT_TEST_GROUP',
                'sealed.present is true but no group is assigned to test')

    # ---- families --------------------------------------------------------
    families = freeze.get('families') or []
    family_by_id = {}
    for family in families:
        family_id = family.get('family_id')
        if not family_id:
            report.add_error('FREEZE_SCHEMA', 'family without family_id')
            continue
        if family_id in family_by_id:
            report.add_error('DUPLICATE_FAMILY_ID',
                             'family id %s appears more than once' % family_id)
            continue
        family_by_id[family_id] = family
    report.stats['families'] = len(family_by_id)

    for group_id, group in group_by_id.items():
        family_id = group.get('family_id')
        if family_id not in family_by_id:
            report.add_error('UNKNOWN_FAMILY',
                             'group %s references unknown family %r'
                             % (group_id, family_id))
        elif group_id not in (family_by_id[family_id].get('groups') or []):
            report.add_error('GROUP_FAMILY_MISMATCH',
                             'group %s is missing from family %s group list'
                             % (group_id, family_id))

    for family_id, family in family_by_id.items():
        family_splits = {
            group_split[group_id]
            for group_id in (family.get('groups') or [])
            if group_id in group_split and group_split[group_id] != 'excluded'
        }
        if 'train' in family_splits and family_splits & {'val', 'test'}:
            report.add_error(
                'FAMILY_SPLIT_LEAKAGE',
                'family %s is split across train and held-out groups %s'
                % (family_id, sorted(family_splits)))
            report.stats['family_split_leaks'] += 1
        if 'val' in family_splits and 'test' in family_splits:
            report.add_warning(
                'FAMILY_VAL_TEST_OVERLAP',
                'family %s appears in both val and test' % family_id)

    # ---- load raw observations ------------------------------------------
    loaded_by_dataset = {}
    for dataset_name, dataset in datasets.items():
        dataset_root = dataset.get('root') or (
            'outputs/sensor_shadow/' + dataset_name)
        observations = dataset.get('observations') or (
            'outputs/sensor_shadow/' + dataset_name + '/observations.jsonl')
        try:
            loaded = load_dataset_frames(
                root, dataset_name, dataset_root, observations,
                allow_empty=bool(dataset.get('empty_capture')),
                require_images=require_images,
                verify_images=verify_images)
        except DatasetInputError as error:
            report.add_error('DATASET_INPUT_ERROR',
                             '%s: %s' % (dataset_name, error))
            continue
        loaded_by_dataset[dataset_name] = loaded
        report.stats['images_verified'] += loaded.images_present
        report.stats['images_missing'] += loaded.images_missing
        report.stats['image_sha_mismatches'] += loaded.image_sha_mismatches
        if loaded.image_sha_mismatches:
            report.add_error(
                'IMAGE_SHA_MISMATCH',
                '%s: %d image file(s) do not match payload sha256'
                % (dataset_name, loaded.image_sha_mismatches))
        if verify_input_hashes and dataset.get('observations_sha256'):
            if dataset['observations_sha256'] != loaded.observations_sha256:
                report.add_error(
                    'OBSERVATIONS_SHA_MISMATCH',
                    '%s: observations.jsonl hash changed' % dataset_name)
        if dataset.get('rgb_frames') is not None:
            if dataset['rgb_frames'] != len(loaded.frames):
                report.add_error(
                    'DATASET_FRAME_COUNT_MISMATCH',
                    '%s: freeze says %d frames, file has %d'
                    % (dataset_name, dataset['rgb_frames'], len(loaded.frames)))
        accepted = sum(1 for frame in loaded.frames if frame.accepted)
        if dataset.get('accepted_rgb_frames') is not None:
            if dataset['accepted_rgb_frames'] != accepted:
                report.add_error(
                    'DATASET_ACCEPTED_COUNT_MISMATCH',
                    '%s: freeze says %d accepted frames, file has %d'
                    % (dataset_name, dataset['accepted_rgb_frames'], accepted))
        for kind in ('summary', 'manifest'):
            relative = dataset.get(kind)
            expected = dataset.get(kind + '_sha256')
            if not relative or not expected:
                continue
            path = root / relative
            if not path.is_file():
                report.add_error('INPUT_FILE_MISSING',
                                 '%s: %s file missing' % (dataset_name, kind))
            elif sha256_bytes(path.read_bytes()) != expected:
                report.add_error('INPUT_FILE_SHA_MISMATCH',
                                 '%s: %s file hash changed'
                                 % (dataset_name, kind))
        if not loaded.frames:
            report.add_warning('EMPTY_CAPTURE',
                               '%s: declared empty capture has no frames'
                               % dataset_name)
        report.stats['datasets'][dataset_name] = {
            'rgb_frames': len(loaded.frames),
            'accepted_rgb_frames': accepted,
            'empty_capture': not loaded.frames,
            'observations_sha256': loaded.observations_sha256,
        }

    actual_by_ref = {}
    for loaded in loaded_by_dataset.values():
        for frame in loaded.frames:
            actual_by_ref[frame.ref] = frame

    # ---- reconcile declared group frames with observations --------------
    claimed = {}
    episode_groups = {}
    for group_id, group in group_by_id.items():
        dataset_name = group.get('dataset')
        if dataset_name not in datasets:
            report.add_error('GROUP_UNKNOWN_DATASET',
                             'group %s references unknown dataset %r'
                             % (group_id, dataset_name))
            continue
        dataset_root = datasets[dataset_name].get('root') or (
            'outputs/sensor_shadow/' + dataset_name)
        declared_frames = group.get('frames') or []
        if group.get('frame_count') is not None:
            if group['frame_count'] != len(declared_frames):
                report.add_error(
                    'GROUP_FRAME_COUNT_MISMATCH',
                    'group %s says %d frames, lists %d'
                    % (group_id, group['frame_count'], len(declared_frames)))
        accepted = sum(1 for item in declared_frames if item.get('accepted'))
        if group.get('accepted_frame_count') is not None:
            if group['accepted_frame_count'] != accepted:
                report.add_error(
                    'GROUP_ACCEPTED_COUNT_MISMATCH',
                    'group %s says %d accepted frames, lists %d'
                    % (group_id, group['accepted_frame_count'], accepted))
        declared_episodes = set(group.get('episodes') or [])
        for item in declared_frames:
            frame_id = item.get('frame_id')
            parsed = parse_frame_id(frame_id)
            if parsed is None:
                report.add_error('FRAME_ID_UNPARSABLE',
                                 'group %s lists unparsable frame %r'
                                 % (group_id, frame_id))
                continue
            ref = frame_ref(dataset_root, frame_id)
            if ref in claimed:
                report.add_error(
                    'GROUP_NOT_MUTUALLY_EXCLUSIVE',
                    'frame %s appears in groups %s and %s'
                    % (frame_id, claimed[ref], group_id))
                continue
            claimed[ref] = group_id
            episode = parsed['episode_id']
            if episode not in declared_episodes:
                report.add_error(
                    'EPISODE_NOT_DECLARED',
                    'group %s lists frame of undeclared episode %s'
                    % (group_id, episode))
            episode_groups.setdefault((dataset_name, episode), set()).add(
                group_id)
            actual = actual_by_ref.get(ref)
            if actual is None:
                report.add_error('FRAME_MISSING_IN_OBSERVATIONS',
                                 'group %s frame %s is not in observations'
                                 % (group_id, frame_id))
                continue
            if actual.sha256 != item.get('sha256'):
                report.add_error('FRAME_SHA_MISMATCH',
                                 'group %s frame %s sha256 mismatch'
                                 % (group_id, frame_id))
            if actual.accepted != bool(item.get('accepted')):
                report.add_error('FRAME_ACCEPTED_FLAG_MISMATCH',
                                 'group %s frame %s accepted flag mismatch'
                                 % (group_id, frame_id))
            report.stats['frame_total'] += 1
            report.stats['accepted_frame_total'] += int(actual.accepted)
            assigned = group_split.get(group_id)
            if assigned in SPLITS:
                report.stats['split_frame_counts'][assigned] += 1
                if actual.accepted:
                    report.stats['split_accepted_frame_counts'][assigned] += 1

    for ref in actual_by_ref:
        if ref not in claimed:
            report.add_error('FRAME_UNASSIGNED',
                             'observed frame %s is not in any group' % ref)
            report.stats['frames_unassigned'] += 1

    for (dataset_name, episode), group_ids in episode_groups.items():
        if len(group_ids) > 1:
            report.add_error(
                'EPISODE_SPLIT_ACROSS_GROUPS',
                'episode %s of %s appears in groups %s'
                % (episode, dataset_name, sorted(group_ids)))
            report.stats['episode_split_conflicts'] += 1

    # ---- consecutive frames cannot cross a split ------------------------
    frames_by_episode = {}
    for frame in actual_by_ref.values():
        frames_by_episode.setdefault((frame.dataset, frame.episode_id),
                                     []).append(frame)
    for key, frames in frames_by_episode.items():
        frames.sort(key=lambda item: item.sequence)
        for previous, current in zip(frames, frames[1:]):
            if current.sequence != previous.sequence + 1:
                continue
            previous_group = claimed.get(previous.ref)
            current_group = claimed.get(current.ref)
            if previous_group is None or current_group is None:
                continue
            if group_split.get(previous_group) != group_split.get(current_group):
                report.add_error(
                    'CONSECUTIVE_FRAME_SPLIT',
                    'consecutive frames of %s/%s cross splits: %s (%s) -> %s (%s)'
                    % (key[0], key[1], previous.frame_id,
                       group_split.get(previous_group), current.frame_id,
                       group_split.get(current_group)))
                report.stats['consecutive_frame_split_violations'] += 1
            elif previous_group != current_group:
                report.add_warning(
                    'CONSECUTIVE_FRAME_GROUP_CHANGE',
                    'consecutive frames of %s/%s change group inside one split'
                    % (key[0], key[1]))

    # ---- duplicate payload hashes ---------------------------------------
    duplicates = find_duplicate_shas(loaded_by_dataset)
    for sha, frames in duplicates.items():
        group_ids = {claimed.get(frame.ref) for frame in frames} - {None}
        split_set = {group_split.get(group_id) for group_id in group_ids
                     if group_split.get(group_id) is not None}
        if len(group_ids) > 1:
            report.add_error(
                'DUPLICATE_SHA_ACROSS_GROUPS',
                'payload sha256 %s appears in groups %s'
                % (sha, sorted(group_ids)))
            report.stats['duplicate_sha_groups'] += 1
        elif len(split_set) > 1:
            report.add_error(
                'DUPLICATE_SHA_ACROSS_SPLITS',
                'payload sha256 %s appears in splits %s'
                % (sha, sorted(split_set)))
            report.stats['duplicate_sha_groups'] += 1
        else:
            report.add_warning(
                'DUPLICATE_SHA_WITHIN_GROUP',
                'payload sha256 %s repeats inside group %s (%d frames)'
                % (sha, sorted(group_ids), len(frames)))
            report.stats['intra_group_duplicate_sha_groups'] += 1

    # ---- view clusters (static pose similarity) -------------------------
    view_cluster_splits = {}
    for group_id, group in group_by_id.items():
        cluster = group.get('view_cluster')
        assigned = group_split.get(group_id)
        if cluster and assigned in DEV_SPLITS:
            view_cluster_splits.setdefault(cluster, set()).add(assigned)
    for cluster, split_set in view_cluster_splits.items():
        if 'train' in split_set and 'val' in split_set:
            report.add_warning(
                'VIEW_CLUSTER_SPLIT',
                'view cluster %s has groups in train and val; poses are not '
                'byte-identical but share the same physical viewpoint family'
                % cluster)
            report.stats['view_cluster_split_warnings'] += 1

    # ---- labels ---------------------------------------------------------
    if check_labels:
        for label_id, entry in (freeze.get('labels') or {}).items():
            relative = entry.get('path')
            if not relative:
                report.add_error('LABEL_INPUT_ERROR',
                                 'label %s has no path' % label_id)
                continue
            path = root / relative
            if not path.is_file():
                report.add_error('LABEL_INPUT_ERROR',
                                 'label %s file missing: %s'
                                 % (label_id, relative))
                continue
            raw = path.read_bytes()
            try:
                document = json.loads(raw.decode('utf-8'))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                report.add_error('LABEL_INPUT_ERROR',
                                 'label %s is not valid JSON: %s'
                                 % (label_id, error))
                continue
            expected = entry.get('sha256')
            if expected and expected != sha256_bytes(raw):
                report.add_error('LABEL_SHA_MISMATCH',
                                 'label %s file hash changed' % label_id)
            labels = document.get('labels')
            if not isinstance(labels, list):
                report.add_error('LABEL_SCHEMA',
                                 'label %s has no labels list' % label_id)
                continue
            if entry.get('frame_count') is not None:
                if entry['frame_count'] != len(labels):
                    report.add_warning(
                        'LABEL_FRAME_COUNT_MISMATCH',
                        'label %s says %d frames, file has %d'
                        % (label_id, entry['frame_count'], len(labels)))
            for item in labels:
                ref = _normalise_ref(item.get('ref') or '')
                if not ref or ref not in actual_by_ref:
                    report.add_error(
                        'LABEL_FRAME_UNKNOWN',
                        'label %s references unknown frame %r'
                        % (label_id, item.get('frame_id') or ref or '?'))
                    continue
                actual = actual_by_ref[ref]
                if item.get('payload_sha256'):
                    if item['payload_sha256'] != actual.sha256:
                        report.add_error(
                            'LABEL_FRAME_SHA_MISMATCH',
                            'label %s frame %s payload sha256 mismatch'
                            % (label_id, actual.frame_id))
                group_id = claimed.get(ref)
                if group_id is None:
                    report.add_warning(
                        'LABEL_FRAME_NOT_IN_SPLIT',
                        'label %s frame %s is not assigned to a split'
                        % (label_id, actual.frame_id))
                    continue
                assigned = group_split.get(group_id)
                claim = item.get('split')
                claim_counts = report.stats['label_split_claim_counts']
                claim_counts[claim] = claim_counts.get(claim, 0) + 1
                report.stats['label_frame_total'] += 1
                normalised = LABEL_SPLIT_ALIASES.get(claim, claim)
                if assigned in SPLITS and normalised != assigned:
                    report.add_warning(
                        'LABEL_SPLIT_CLAIM_CONFLICT',
                        'label %s frame %s claims %r but group %s is %s'
                        % (label_id, actual.frame_id, claim, group_id, assigned))
                    report.stats['label_split_claim_conflicts'] += 1

    return report


# ---------------------------------------------------------------------------
# exposure registry (T12)
# ---------------------------------------------------------------------------

EXPOSURE_SCHEMA = 'dsh.landmark_exposure_registry.v1'
EXPOSURE_PROTOCOL = 'landmark_exposure_group_level_v1'
EXPOSURE_STATUSES = ('exposed_development', 'annotation_calibration',
                     'exploratory_eval_candidate', 'untouched',
                     'excluded_debug', 'empty_capture')
EXPOSURE_TOUCH_EVIDENCE = ('annotation_calibration',
                           'exploratory_eval_candidate')


def validate_exposure_registry(registry, freeze_documents, repo_root, *,
                               verify_evidence=True):
    """Validate an exposure registry against the frozen split documents.

    The registry is the honest record of what was viewed, annotated or used.
    It must never claim sealed/untouched for a group that has exposure events.
    """
    root = Path(repo_root)
    report = ValidationReport()
    if registry.get('schema_version') != EXPOSURE_SCHEMA:
        report.add_error('EXPOSURE_SCHEMA',
                         'expected %s, found %r'
                         % (EXPOSURE_SCHEMA, registry.get('schema_version')))
    statuses = set((registry.get('policy') or {}).get('statuses')
                   or EXPOSURE_STATUSES)
    unknown_statuses = statuses - set(EXPOSURE_STATUSES)
    if unknown_statuses:
        report.add_error('EXPOSURE_STATUS_UNKNOWN',
                         'registry policy has unknown statuses: %s'
                         % sorted(unknown_statuses))

    events = {}
    for event in registry.get('events') or []:
        event_id = event.get('event_id')
        if not event_id:
            report.add_error('EXPOSURE_EVENT_MALFORMED',
                             'event without event_id')
            continue
        if event_id in events:
            report.add_error('EXPOSURE_EVENT_DUPLICATE',
                             'duplicate event id %s' % event_id)
            continue
        events[event_id] = event
        for field_name in ('type', 'date', 'executor'):
            if not event.get(field_name):
                report.add_error('EXPOSURE_EVENT_MALFORMED',
                                 'event %s missing %s' % (event_id, field_name))
        if event.get('frames_touched') is None:
            report.add_error('EXPOSURE_EVENT_MALFORMED',
                             'event %s missing frames_touched' % event_id)
        if verify_evidence:
            relative = event.get('evidence_path')
            expected = event.get('evidence_sha256')
            if not relative:
                report.add_error('EXPOSURE_EVIDENCE_MISSING',
                                 'event %s has no evidence_path' % event_id)
            else:
                path = root / relative
                if not path.is_file():
                    report.add_error('EXPOSURE_EVIDENCE_MISSING',
                                     'event %s evidence missing: %s'
                                     % (event_id, relative))
                elif expected and sha256_bytes(path.read_bytes()) != expected:
                    report.add_error('EXPOSURE_EVIDENCE_SHA_MISMATCH',
                                     'event %s evidence hash changed: %s'
                                     % (event_id, relative))
    report.stats['events'] = len(events)

    groups_doc = {}
    for entry in registry.get('groups') or []:
        group_id = entry.get('group_id')
        if group_id:
            groups_doc[group_id] = entry

    verify_evidence_checked = 0
    for source, freeze in freeze_documents.items():
        frozen_groups = {}
        frozen_frame_ids = set()
        for item in freeze.get('groups') or []:
            frozen_groups[item['group_id']] = item
            for frame in item.get('frames') or []:
                frozen_frame_ids.add(frame.get('frame_id'))
        registered = {group_id: entry for group_id, entry in groups_doc.items()
                      if entry.get('source') == source}
        missing = set(frozen_groups) - set(registered)
        extra = set(registered) - set(frozen_groups)
        if missing:
            report.add_error('EXPOSURE_GROUP_MISSING',
                             '%s groups missing from registry: %s'
                             % (source, sorted(missing)))
        if extra:
            report.add_error('EXPOSURE_GROUP_UNKNOWN',
                             '%s registry groups not in freeze: %s'
                             % (source, sorted(extra)))
        for group_id, entry in registered.items():
            status = entry.get('status')
            if status not in statuses or status not in EXPOSURE_STATUSES:
                report.add_error('EXPOSURE_STATUS_INVALID',
                                 'group %s has invalid status %r'
                                 % (group_id, status))
            event_ids = entry.get('exposure_events') or []
            for event_id in event_ids:
                if event_id not in events:
                    report.add_error('EXPOSURE_EVENT_UNKNOWN',
                                     'group %s references unknown event %s'
                                     % (group_id, event_id))
            if event_ids and status == 'untouched':
                report.add_error('EXPOSURE_TOUCHED_MARKED_UNTOUCHED',
                                 'group %s has exposure events but is marked '
                                 'untouched' % group_id)
            if status in EXPOSURE_TOUCH_EVIDENCE and not event_ids:
                report.add_warning('EXPOSURE_TERMINAL_WITHOUT_EVENT',
                                   'group %s is %s but lists no event'
                                   % (group_id, status))
            if entry.get('certification') == 'SEALED':
                report.add_error('EXPOSURE_SEALED_CLAIM',
                                 'group %s is certified SEALED although the '
                                 'registry records exposure risk' % group_id)
            if not isinstance(entry.get('contamination'), dict):
                report.add_warning('EXPOSURE_CONTAMINATION_MISSING',
                                   'group %s has no contamination record'
                                   % group_id)
        # frame-level overrides
        overrides = [item for item in registry.get('frame_overrides') or []
                     if item.get('source') == source]
        for index, override in enumerate(overrides):
            frame_id = override.get('frame_id')
            if frame_id not in frozen_frame_ids:
                report.add_error('EXPOSURE_FRAME_UNKNOWN',
                                 '%s override frame %r is not in the freeze'
                                 % (source, frame_id))
                continue
            event_id = override.get('event_id')
            if event_id not in events:
                report.add_error('EXPOSURE_EVENT_UNKNOWN',
                                 'frame override %s references unknown event %r'
                                 % (frame_id, event_id))
            group_id = override.get('group_id')
            entry = registered.get(group_id)
            if entry is None:
                report.add_error('EXPOSURE_FRAME_GROUP_MISMATCH',
                                 'frame %s override group %r is not in %s'
                                 % (frame_id, group_id, source))
            elif entry.get('status') == 'untouched':
                report.add_error('EXPOSURE_TOUCHED_MARKED_UNTOUCHED',
                                 'frame %s is overridden but its group is '
                                 'untouched' % frame_id)
            status = override.get('status')
            if status not in EXPOSURE_STATUSES:
                report.add_error('EXPOSURE_STATUS_INVALID',
                                 'frame override %s invalid status %r'
                                 % (frame_id, status))
            verify_evidence_checked += 1
    report.stats['group_overrides'] = verify_evidence_checked

    # any freeze whose namespace is the final sealed pool must be downgraded
    for source, freeze in freeze_documents.items():
        if source != 'final_seal':
            continue
        final_entries = [entry for entry in groups_doc.values()
                         if entry.get('source') == source]
        not_downgraded = [entry['group_id'] for entry in final_entries
                          if entry.get('status') not in
                          ('exploratory_eval_candidate', 'excluded_debug',
                           'empty_capture')]
        if not_downgraded:
            report.add_error('EXPOSURE_FINAL_NOT_DOWNGRADED',
                             'final seal groups not downgraded to exploratory: '
                             '%s' % sorted(not_downgraded))
    certification = registry.get('certification') or {}
    if certification.get('can_claim_sealed'):
        report.add_error('EXPOSURE_SEALED_CLAIM',
                         'registry still claims a sealed data pool')
    if certification.get('conclusion') != 'INCOMPLETE':
        report.add_warning('EXPOSURE_CONCLUSION',
                           'registry conclusion should be INCOMPLETE while '
                           'any exposure exists')
    report.stats['groups'] = len(groups_doc)
    report.stats['sources'] = sorted(freeze_documents)
    return report


# ---------------------------------------------------------------------------
# split leakage audit (T12)
# ---------------------------------------------------------------------------

def _frame_meta(freeze):
    group_split = {}
    for split in SPLITS:
        for group_id in (freeze.get('splits') or {}).get(split) or []:
            group_split[group_id] = split
    meta = []
    for group in freeze.get('groups') or []:
        group_id = group.get('group_id')
        split = group_split.get(group_id)
        dataset = group.get('dataset')
        for frame in group.get('frames') or []:
            parsed = parse_frame_id(frame.get('frame_id'))
            meta.append({
                'group_id': group_id,
                'family_id': group.get('family_id'),
                'split': split,
                'dataset': dataset,
                'episode_id': parsed['episode_id'] if parsed else None,
                'sequence': parsed['sequence'] if parsed else None,
                'sha256': frame.get('sha256'),
                'frame_id': frame.get('frame_id'),
            })
    return meta


def audit_split_leakage(freeze):
    """Return structural leakage findings for one freeze document."""
    meta = _frame_meta(freeze)
    issues = []
    group_splits = {}
    family_splits = {}
    sha_splits = {}
    episode_splits = {}
    for item in meta:
        group_splits.setdefault(item['group_id'], set()).add(item['split'])
        family_splits.setdefault(item['family_id'], set()).add(item['split'])
        sha_splits.setdefault(item['sha256'], set()).add(item['split'])
        episode_splits.setdefault(
            (item['dataset'], item['episode_id']), set()).add(item['split'])
    for group_id, split_set in group_splits.items():
        if len(split_set) > 1:
            issues.append({'code': 'GROUP_CROSS_SPLIT', 'group_id': group_id,
                           'splits': sorted(split_set)})
    family_leaks = 0
    for family_id, split_set in family_splits.items():
        if 'train' in split_set and split_set & {'val', 'test'}:
            issues.append({'code': 'FAMILY_CROSS_SPLIT',
                           'family_id': family_id,
                           'splits': sorted(split_set)})
            family_leaks += 1
    sha_leaks = 0
    for sha, split_set in sha_splits.items():
        if len(split_set) > 1:
            issues.append({'code': 'SHA_CROSS_SPLIT', 'sha256': sha,
                           'splits': sorted(split_set)})
            sha_leaks += 1
    trajectory_leaks = 0
    for (dataset, episode), split_set in episode_splits.items():
        if len(split_set) > 1:
            issues.append({'code': 'TRAJECTORY_CROSS_SPLIT',
                           'dataset': dataset, 'episode_id': episode,
                           'splits': sorted(split_set)})
            trajectory_leaks += 1
    # adjacent frames of one trajectory must share a split
    ordered = {}
    for item in meta:
        if item['episode_id'] is None:
            continue
        ordered.setdefault((item['dataset'], item['episode_id']),
                          []).append(item)
    for key, frames in ordered.items():
        frames.sort(key=lambda item: item['sequence'])
        for previous, current in zip(frames, frames[1:]):
            if current['sequence'] != previous['sequence'] + 1:
                continue
            if previous['split'] != current['split']:
                issues.append({'code': 'ADJACENT_FRAME_CROSS_SPLIT',
                               'frame_id': current['frame_id'],
                               'splits': [previous['split'], current['split']]})
    return {
        'ok': not issues,
        'issues': issues,
        'stats': {
            'groups': len(group_splits),
            'frames': len(meta),
            'families': len(family_splits),
            'group_leaks': sum(1 for issue in issues
                               if issue['code'] == 'GROUP_CROSS_SPLIT'),
            'family_leaks': family_leaks,
            'sha_leaks': sha_leaks,
            'trajectory_leaks': trajectory_leaks,
            'adjacent_leaks': sum(1 for issue in issues
                                  if issue['code'] == 'ADJACENT_FRAME_CROSS_SPLIT'),
        },
    }
