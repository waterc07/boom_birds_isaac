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
