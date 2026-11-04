"""Dataset grouping, leakage-check and freeze-hash regression tests.

These tests use synthetic observation files; the committed freeze is verified
against real raw outputs only when those ignored outputs are present locally.
"""
import json
from pathlib import Path

import pytest

from boom_birds.evaluation.landmark_dataset import (
    FREEZE_SCHEMA, GROUPING_PROTOCOL, DatasetInputError, canonical_freeze_bytes,
    find_duplicate_shas, freeze_sha256, load_dataset_frames, parse_frame_id,
    validate_freeze)


REPO_ROOT = Path(__file__).resolve().parents[2]
FREEZE_PATH = REPO_ROOT / 'configs' / 'perception' / 'landmark_split_freeze_v1.json'
FREEZE_V2_PATH = (REPO_ROOT / 'configs' / 'perception'
                  / 'landmark_split_freeze_v2.json')
RAW_FORMAL6 = (REPO_ROOT / 'outputs' / 'sensor_shadow' / 'formal6_sensor'
               / 'observations.jsonl')


# ---------------------------------------------------------------------------
# synthetic fixtures
# ---------------------------------------------------------------------------

def frame_id(episode, generation=1, sequence=0):
    return '%s-follow_only_g%d_%d.png' % (episode, generation, sequence)


def write_dataset(root, dataset, frames):
    """Write a minimal observations.jsonl; frames are (frame_id, sha, accepted)."""
    directory = root / 'outputs' / 'sensor_shadow' / dataset
    directory.mkdir(parents=True, exist_ok=True)
    lines = []
    for name, sha, accepted in frames:
        ref = 'outputs/sensor_shadow/%s/images/%s' % (dataset, name)
        lines.append(json.dumps({
            'sensor_key': 'front_rgb',
            'payload': {'ref': ref, 'sha256': sha},
            'gate': {'accepted': accepted},
        }))
        lines.append(json.dumps({
            'sensor_key': 'front_depth',
            'payload': {'ref': '', 'sha256': None},
        }))
    path = directory / 'observations.jsonl'
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    import hashlib
    return path


def dataset_entry(root, dataset, frames, *, in_inventory=True, empty_capture=False):
    path = write_dataset(root, dataset, frames)
    import hashlib
    return {
        'root': 'outputs/sensor_shadow/%s' % dataset,
        'observations': 'outputs/sensor_shadow/%s/observations.jsonl' % dataset,
        'observations_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'in_inventory': in_inventory,
        'role': 'primary',
        'empty_capture': empty_capture,
        'rgb_frames': len(frames),
        'accepted_rgb_frames': sum(1 for item in frames if item[2]),
    }


def group(group_id, family_id, dataset, episodes, split, frames, sealed=False):
    return {
        'group_id': group_id,
        'family_id': family_id,
        'dataset': dataset,
        'session': dataset + '_session',
        'render_version': 'render_v1',
        'episodes': list(episodes),
        'split': split,
        'sealed': sealed,
        'frame_count': len(frames),
        'accepted_frame_count': sum(1 for item in frames if item[2]),
        'frames': [{'frame_id': item[0], 'sha256': item[1],
                    'accepted': bool(item[2])} for item in frames],
    }


def make_freeze(datasets, groups, splits, families=None, labels=None):
    if families is None:
        families = [
            {'family_id': item['family_id'], 'groups': [item['group_id']]}
            for item in groups
        ]
    # de-duplicate family ids while keeping every group
    by_family = {}
    for item in families:
        by_family.setdefault(item['family_id'], {
            'family_id': item['family_id'], 'groups': []})
        by_family[item['family_id']]['groups'].extend(item['groups'])
    freeze = {
        'schema_version': FREEZE_SCHEMA,
        'grouping_protocol': GROUPING_PROTOCOL,
        'generated_at': '2026-11-04T00:00:00+00:00',
        'datasets': datasets,
        'families': list(by_family.values()),
        'groups': groups,
        'splits': splits,
        'sealed': {'present': False},
        'labels': labels or {},
    }
    freeze['freeze_sha256'] = freeze_sha256(freeze)
    return freeze


def sha(char):
    return char * 64


def clean_fixture(tmp_path):
    frames_a = [
        (frame_id('ep_a', 1, 0), sha('a'), True),
        (frame_id('ep_a', 1, 1), sha('b'), True),
        (frame_id('ep_a', 1, 2), sha('c'), True),
    ]
    frames_b = [
        (frame_id('ep_b', 2, 0), sha('d'), True),
        (frame_id('ep_b', 2, 1), sha('e'), True),
    ]
    datasets = {
        'ds_a': dataset_entry(tmp_path, 'ds_a', frames_a),
        'ds_b': dataset_entry(tmp_path, 'ds_b', frames_b),
    }
    groups = [
        group('g1', 'fam_train', 'ds_a', ['ep_a'], 'train', frames_a),
        group('g2', 'fam_val', 'ds_b', ['ep_b'], 'val', frames_b),
    ]
    splits = {'train': ['g1'], 'val': ['g2'], 'test': [], 'excluded': []}
    return make_freeze(datasets, groups, splits), datasets, groups, splits


# ---------------------------------------------------------------------------
# frame parsing / loading
# ---------------------------------------------------------------------------

def test_parse_frame_id_extracts_episode_generation_sequence():
    parsed = parse_frame_id('dev_south_new-follow_only_g3_190.png')
    assert parsed == {'episode_id': 'dev_south_new', 'generation': 3,
                      'sequence': 190}


def test_parse_frame_id_returns_none_for_unrecognised_name():
    assert parse_frame_id('not-a-frame.png') is None
    assert parse_frame_id('x-follow_only_g1_1.jpg') is None


def test_load_dataset_frames_reads_only_rgb_and_parses_metadata(tmp_path):
    _, datasets, _, _ = clean_fixture(tmp_path)
    entry = datasets['ds_a']
    loaded = load_dataset_frames(tmp_path, 'ds_a', entry['root'],
                                 entry['observations'])
    assert len(loaded.frames) == 3
    assert loaded.frames[0].frame_id == frame_id('ep_a', 1, 0)
    assert loaded.frames[0].episode_id == 'ep_a'
    assert loaded.frames[0].generation == 1
    assert loaded.frames[0].sequence == 0
    assert loaded.frames[0].accepted is True
    import hashlib
    expected = hashlib.sha256(
        (tmp_path / entry['observations']).read_bytes()).hexdigest()
    assert loaded.observations_sha256 == expected


def test_load_dataset_frames_missing_file_raises_dataset_input_error(tmp_path):
    with pytest.raises(DatasetInputError):
        load_dataset_frames(tmp_path, 'ghost', 'outputs/sensor_shadow/ghost',
                            'outputs/sensor_shadow/ghost/observations.jsonl')


def test_load_dataset_frames_corrupt_line_raises_dataset_input_error(tmp_path):
    directory = tmp_path / 'outputs' / 'sensor_shadow' / 'bad'
    directory.mkdir(parents=True)
    (directory / 'observations.jsonl').write_text('{not json}\n',
                                                  encoding='utf-8')
    with pytest.raises(DatasetInputError):
        load_dataset_frames(tmp_path, 'bad', 'outputs/sensor_shadow/bad',
                            'outputs/sensor_shadow/bad/observations.jsonl')


def test_load_dataset_frames_empty_dataset_raises_unless_allowed(tmp_path):
    path = write_dataset(tmp_path, 'empty_ds', [])
    with pytest.raises(DatasetInputError):
        load_dataset_frames(tmp_path, 'empty_ds', 'outputs/sensor_shadow/empty_ds',
                            'outputs/sensor_shadow/empty_ds/observations.jsonl')
    loaded = load_dataset_frames(
        tmp_path, 'empty_ds', 'outputs/sensor_shadow/empty_ds',
        'outputs/sensor_shadow/empty_ds/observations.jsonl', allow_empty=True)
    assert loaded.frames == ()


# ---------------------------------------------------------------------------
# clean freeze + invariants
# ---------------------------------------------------------------------------

def test_clean_freeze_passes(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    report = validate_freeze(freeze, tmp_path)
    assert report.ok, [issue.code for issue in report.errors]
    assert report.stats['frame_total'] == 5
    assert report.stats['split_frame_counts']['train'] == 3
    assert report.stats['split_frame_counts']['val'] == 2


def test_group_mutual_exclusion_rejects_frame_in_two_groups(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    duplicate = dict(freeze['groups'][0])
    duplicate['group_id'] = 'g1_dup'
    duplicate['split'] = 'val'
    duplicate['family_id'] = 'fam_val'
    freeze['groups'].append(duplicate)
    freeze['splits']['val'].append('g1_dup')
    freeze['families'].append({'family_id': 'fam_val', 'groups': ['g2', 'g1_dup']})
    freeze['freeze_sha256'] = freeze_sha256(freeze)
    report = validate_freeze(freeze, tmp_path)
    assert 'GROUP_NOT_MUTUALLY_EXCLUSIVE' in report.error_codes


def test_episode_must_not_span_two_groups(tmp_path):
    frames = [(frame_id('ep_shared', 1, i), sha(chr(ord('a') + i)), True)
              for i in range(4)]
    datasets = {'ds_a': dataset_entry(tmp_path, 'ds_a', frames)}
    groups = [
        group('g1', 'fam_one', 'ds_a', ['ep_shared'], 'train', frames[:2]),
        group('g2', 'fam_two', 'ds_a', ['ep_shared'], 'val', frames[2:]),
    ]
    splits = {'train': ['g1'], 'val': ['g2'], 'test': [], 'excluded': []}
    freeze = make_freeze(datasets, groups, splits)
    report = validate_freeze(freeze, tmp_path)
    assert 'EPISODE_SPLIT_ACROSS_GROUPS' in report.error_codes


def test_consecutive_frames_must_not_cross_splits(tmp_path):
    frames = [(frame_id('ep_shared', 1, i), sha(chr(ord('a') + i)), True)
              for i in range(4)]
    datasets = {'ds_a': dataset_entry(tmp_path, 'ds_a', frames)}
    groups = [
        group('g1', 'fam_one', 'ds_a', ['ep_shared'], 'train', frames[:2]),
        group('g2', 'fam_two', 'ds_a', ['ep_shared'], 'val', frames[2:]),
    ]
    splits = {'train': ['g1'], 'val': ['g2'], 'test': [], 'excluded': []}
    freeze = make_freeze(datasets, groups, splits)
    report = validate_freeze(freeze, tmp_path)
    assert 'CONSECUTIVE_FRAME_SPLIT' in report.error_codes


def test_duplicate_frame_sha_across_groups_is_error(tmp_path):
    frames_a = [(frame_id('ep_a', 1, 0), sha('a'), True)]
    frames_b = [(frame_id('ep_b', 2, 0), sha('a'), True)]
    datasets = {
        'ds_a': dataset_entry(tmp_path, 'ds_a', frames_a),
        'ds_b': dataset_entry(tmp_path, 'ds_b', frames_b),
    }
    groups = [
        group('g1', 'fam_train', 'ds_a', ['ep_a'], 'train', frames_a),
        group('g2', 'fam_val', 'ds_b', ['ep_b'], 'val', frames_b),
    ]
    splits = {'train': ['g1'], 'val': ['g2'], 'test': [], 'excluded': []}
    freeze = make_freeze(datasets, groups, splits)
    report = validate_freeze(freeze, tmp_path)
    assert 'DUPLICATE_SHA_ACROSS_GROUPS' in report.error_codes


def test_duplicate_frame_sha_within_group_is_warning(tmp_path):
    frames = [
        (frame_id('ep_a', 1, 0), sha('a'), True),
        (frame_id('ep_a', 1, 1), sha('a'), True),
    ]
    datasets = {'ds_a': dataset_entry(tmp_path, 'ds_a', frames)}
    groups = [group('g1', 'fam_train', 'ds_a', ['ep_a'], 'train', frames)]
    splits = {'train': ['g1'], 'val': [], 'test': [], 'excluded': []}
    freeze = make_freeze(datasets, groups, splits)
    report = validate_freeze(freeze, tmp_path)
    assert report.ok, [issue.code for issue in report.errors]
    assert 'DUPLICATE_SHA_WITHIN_GROUP' in report.warning_codes


def test_sealed_group_listed_in_dev_split_is_error(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    freeze['groups'][1]['sealed'] = True
    freeze['sealed'] = {'present': True}
    freeze['freeze_sha256'] = freeze_sha256(freeze)
    report = validate_freeze(freeze, tmp_path)
    assert 'SEALED_GROUP_IN_DEV' in report.error_codes


def test_family_split_across_train_and_val_is_error(tmp_path):
    freeze, _, groups, splits = clean_fixture(tmp_path)
    freeze['families'] = [{'family_id': 'fam_shared',
                           'groups': ['g1', 'g2']}]
    freeze['groups'][0]['family_id'] = 'fam_shared'
    freeze['groups'][1]['family_id'] = 'fam_shared'
    freeze['freeze_sha256'] = freeze_sha256(freeze)
    report = validate_freeze(freeze, tmp_path)
    assert 'FAMILY_SPLIT_LEAKAGE' in report.error_codes


def test_frame_sha_mismatch_against_observations_is_error(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    freeze['groups'][0]['frames'][0]['sha256'] = sha('f')
    freeze['freeze_sha256'] = freeze_sha256(freeze)
    report = validate_freeze(freeze, tmp_path)
    assert 'FRAME_SHA_MISMATCH' in report.error_codes


def test_accepted_flag_mismatch_is_error(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    freeze['groups'][0]['frames'][0]['accepted'] = False
    freeze['freeze_sha256'] = freeze_sha256(freeze)
    report = validate_freeze(freeze, tmp_path)
    assert 'FRAME_ACCEPTED_FLAG_MISMATCH' in report.error_codes


def test_observations_sha_mismatch_is_error(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    freeze['datasets']['ds_a']['observations_sha256'] = sha('0')
    freeze['freeze_sha256'] = freeze_sha256(freeze)
    report = validate_freeze(freeze, tmp_path)
    assert 'OBSERVATIONS_SHA_MISMATCH' in report.error_codes


def test_missing_observations_file_is_reported(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    freeze['datasets']['ds_a']['observations'] = (
        'outputs/sensor_shadow/ds_a/observations_missing.jsonl')
    freeze['freeze_sha256'] = freeze_sha256(freeze)
    report = validate_freeze(freeze, tmp_path)
    assert 'DATASET_INPUT_ERROR' in report.error_codes


def test_unassigned_actual_frame_is_error(tmp_path):
    frames = [
        (frame_id('ep_a', 1, 0), sha('a'), True),
        (frame_id('ep_a', 1, 1), sha('b'), True),
    ]
    datasets = {'ds_a': dataset_entry(tmp_path, 'ds_a', frames)}
    groups = [group('g1', 'fam_train', 'ds_a', ['ep_a'], 'train', frames[:1])]
    splits = {'train': ['g1'], 'val': [], 'test': [], 'excluded': []}
    freeze = make_freeze(datasets, groups, splits)
    report = validate_freeze(freeze, tmp_path)
    assert 'FRAME_UNASSIGNED' in report.error_codes


def test_group_split_field_must_match_splits_table(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    freeze['groups'][0]['split'] = 'val'
    freeze['freeze_sha256'] = freeze_sha256(freeze)
    report = validate_freeze(freeze, tmp_path)
    assert 'GROUP_SPLIT_MISMATCH' in report.error_codes


# ---------------------------------------------------------------------------
# canonical freeze hash
# ---------------------------------------------------------------------------

def test_freeze_hash_is_canonical_across_key_order_and_timestamp(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    reordered = json.loads(json.dumps(freeze, sort_keys=False))
    reordered = {key: reordered[key] for key in reversed(list(reordered))}
    reordered['generated_at'] = '2026-11-05T12:00:00+00:00'
    assert freeze_sha256(reordered) == freeze_sha256(freeze)
    assert canonical_freeze_bytes(reordered) == canonical_freeze_bytes(freeze)


def test_freeze_hash_detects_content_change(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    before = freeze_sha256(freeze)
    freeze['groups'][0]['frames'][0]['sha256'] = sha('b')
    assert freeze_sha256(freeze) != before


def test_stored_freeze_hash_is_verified(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    freeze['groups'][0]['frames'][0]['sha256'] = sha('b')
    report = validate_freeze(freeze, tmp_path)
    assert 'FREEZE_HASH_MISMATCH' in report.error_codes


# ---------------------------------------------------------------------------
# labels
# ---------------------------------------------------------------------------

def write_labels(tmp_path, name, labels):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        'schema_version': 'dsh.landmark_labels.v1',
        'labels': labels,
    }), encoding='utf-8')
    return path


def label_fixture(tmp_path):
    freeze, datasets, groups, splits = clean_fixture(tmp_path)
    frame = groups[0]['frames'][0]
    ref = 'outputs/sensor_shadow/ds_a/images/' + frame['frame_id']
    path = write_labels(tmp_path, 'configs/labels.json', [{
        'frame_id': frame['frame_id'],
        'ref': ref,
        'payload_sha256': frame['sha256'],
        'split': 'sealed_test',
    }])
    import hashlib
    freeze['labels'] = {'labels_v1': {
        'path': 'configs/labels.json',
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'frame_count': 1,
    }}
    freeze['freeze_sha256'] = freeze_sha256(freeze)
    return freeze, path, frame, ref


def test_label_file_verifies_and_split_claim_conflict_is_warning(tmp_path):
    freeze, _, _, _ = label_fixture(tmp_path)
    report = validate_freeze(freeze, tmp_path)
    assert report.ok, [issue.code for issue in report.errors]
    # label says 'development' but group is 'train': historical claim conflict
    assert 'LABEL_SPLIT_CLAIM_CONFLICT' in report.warning_codes
    assert report.stats['label_frame_total'] == 1


def test_label_sha_mismatch_is_error(tmp_path):
    freeze, path, _, _ = label_fixture(tmp_path)
    freeze['labels']['labels_v1']['sha256'] = sha('0')
    freeze['freeze_sha256'] = freeze_sha256(freeze)
    report = validate_freeze(freeze, tmp_path)
    assert 'LABEL_SHA_MISMATCH' in report.error_codes


def test_label_frame_sha_mismatch_is_error(tmp_path):
    freeze, path, frame, _ = label_fixture(tmp_path)
    document = json.loads(path.read_text(encoding='utf-8'))
    document['labels'][0]['payload_sha256'] = sha('f')
    path.write_text(json.dumps(document), encoding='utf-8')
    import hashlib
    freeze['labels']['labels_v1']['sha256'] = hashlib.sha256(
        path.read_bytes()).hexdigest()
    freeze['freeze_sha256'] = freeze_sha256(freeze)
    report = validate_freeze(freeze, tmp_path)
    assert 'LABEL_FRAME_SHA_MISMATCH' in report.error_codes


def test_label_frame_not_in_freeze_is_error(tmp_path):
    freeze, path, frame, ref = label_fixture(tmp_path)
    document = json.loads(path.read_text(encoding='utf-8'))
    document['labels'][0]['frame_id'] = frame_id('ep_unknown', 1, 0)
    document['labels'][0]['ref'] = 'outputs/sensor_shadow/ds_a/images/' + \
        frame_id('ep_unknown', 1, 0)
    path.write_text(json.dumps(document), encoding='utf-8')
    import hashlib
    freeze['labels']['labels_v1']['sha256'] = hashlib.sha256(
        path.read_bytes()).hexdigest()
    freeze['freeze_sha256'] = freeze_sha256(freeze)
    report = validate_freeze(freeze, tmp_path)
    assert 'LABEL_FRAME_UNKNOWN' in report.error_codes


def test_missing_label_file_is_reported(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    freeze['labels'] = {'labels_v1': {'path': 'configs/absent.json',
                                      'sha256': sha('0')}}
    freeze['freeze_sha256'] = freeze_sha256(freeze)
    report = validate_freeze(freeze, tmp_path)
    assert 'LABEL_INPUT_ERROR' in report.error_codes


def test_empty_capture_dataset_must_be_declared(tmp_path):
    frames = []
    datasets = {'ds_empty': dataset_entry(tmp_path, 'ds_empty', frames,
                                          in_inventory=False,
                                          empty_capture=True)}
    groups = []
    splits = {'train': [], 'val': [], 'test': [], 'excluded': []}
    freeze = make_freeze(datasets, groups, splits)
    report = validate_freeze(freeze, tmp_path)
    assert report.ok, [issue.code for issue in report.errors]
    assert 'EMPTY_CAPTURE' in report.warning_codes


# ---------------------------------------------------------------------------
# duplicate detection helper
# ---------------------------------------------------------------------------

def test_find_duplicate_shas_groups_identical_frames():
    from boom_birds.evaluation.landmark_dataset import DatasetFrames, Frame
    frames = (
        Frame('ds', 'ep_a-follow_only_g1_0.png',
              'outputs/sensor_shadow/ds/images/ep_a-follow_only_g1_0.png',
              sha('a'), 'ep_a', 1, 0, True),
        Frame('ds', 'ep_a-follow_only_g1_1.png',
              'outputs/sensor_shadow/ds/images/ep_a-follow_only_g1_1.png',
              sha('a'), 'ep_a', 1, 1, True),
        Frame('ds', 'ep_a-follow_only_g1_2.png',
              'outputs/sensor_shadow/ds/images/ep_a-follow_only_g1_2.png',
              sha('b'), 'ep_a', 1, 2, True),
    )
    duplicates = find_duplicate_shas(dataset_frames={'ds': DatasetFrames(
        'ds', 'observations.jsonl', sha('0'), frames)})
    assert sha('a') in duplicates
    assert len(duplicates[sha('a')]) == 2
    assert sha('b') not in duplicates


# ---------------------------------------------------------------------------
# committed freeze against real raw outputs (only when outputs exist)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not (FREEZE_PATH.is_file() and RAW_FORMAL6.is_file()),
                    reason='raw sensor outputs are ignored and absent here')
def test_committed_freeze_verifies_against_present_raw_data():
    freeze = json.loads(FREEZE_PATH.read_text(encoding='utf-8'))
    report = validate_freeze(freeze, REPO_ROOT, verify_input_hashes=True,
                             require_images=False)
    assert report.ok, [issue.code + ': ' + issue.message
                       for issue in report.errors]
    assert freeze['splits']['test'] == []
    assert freeze['sealed']['present'] is False
    assert report.stats['sealed_groups_in_dev'] == 0
    assert report.stats['family_split_leaks'] == 0
    # frozen inventory must cover every exposed shadow capture exactly once
    assert len(freeze['datasets']) == 13
    assert report.stats['frame_total'] == 3002
    assert report.stats['split_frame_counts']['test'] == 0
    assert report.stats['split_frame_counts']['train'] == 1290
    assert report.stats['split_frame_counts']['val'] == 605
    assert report.stats['split_frame_counts']['excluded'] == 1107
    assert report.stats['images_verified'] == 3002
    assert report.stats['images_missing'] == 0
    assert report.stats['image_sha_mismatches'] == 0


@pytest.mark.skipif(not (FREEZE_V2_PATH.is_file() and RAW_FORMAL6.is_file()),
                    reason='raw sensor outputs are ignored and absent here')
def test_conservative_freeze_v2_keeps_only_north_in_val():
    freeze = json.loads(FREEZE_V2_PATH.read_text(encoding='utf-8'))
    report = validate_freeze(freeze, REPO_ROOT, verify_input_hashes=True,
                             require_images=False)
    assert report.ok, [issue.code + ': ' + issue.message
                       for issue in report.errors]
    assert freeze['split_profile']['name'] == 'conservative'
    assert freeze['supersedes']['canonical_sha256'] == freeze_sha256(
        json.loads(FREEZE_PATH.read_text(encoding='utf-8')))
    groups = {item['group_id']: item for item in freeze['groups']}
    val_groups = freeze['splits']['val']
    assert set(val_groups) == {'g_lm_ind_north', 'g_geo_north',
                               'g_lm_pilot_north'}
    for group_id in val_groups:
        assert groups[group_id]['family_id'] == 'fam_north'
    assert report.stats['split_frame_counts']['val'] == 575
    assert report.stats['split_frame_counts']['train'] == 1320
    assert 'VIEW_CLUSTER_SPLIT' not in report.warning_codes


# ---------------------------------------------------------------------------
# exposure registry + split leakage audit (T12)
# ---------------------------------------------------------------------------

from boom_birds.evaluation.landmark_dataset import (
    EXPOSURE_SCHEMA, EXPOSURE_STATUSES, audit_split_leakage,
    validate_exposure_registry)


def make_registry(freeze, source='dev_freeze', events=None,
                  group_status='exposed_development', certification=None,
                  frame_overrides=None, groups=None):
    events = events or []
    if groups is None:
        groups = []
        for item in freeze['groups']:
            groups.append({
                'group_id': item['group_id'],
                'source': source,
                'family_id': item['family_id'],
                'status': group_status,
                'exposure_events': [event['event_id'] for event in events],
                'certification': 'EXPOSED',
                'contamination': {'group_level': bool(events)},
            })
    return {
        'schema_version': EXPOSURE_SCHEMA,
        'policy': {'statuses': list(EXPOSURE_STATUSES)},
        'freezes': {source: {
            'path': 'freeze.json',
            'canonical_sha256': freeze_sha256(freeze),
            'groups': len(freeze['groups']),
        }},
        'groups': groups,
        'events': events,
        'frame_overrides': frame_overrides or [],
        'certification': certification or {
            'can_claim_sealed': False, 'conclusion': 'INCOMPLETE'},
    }


def test_exposure_registry_clean_passes(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    registry = make_registry(freeze)
    report = validate_exposure_registry(registry, {'dev_freeze': freeze},
                                        tmp_path, verify_evidence=False)
    assert report.ok, [issue.code for issue in report.errors]
    assert report.stats['groups'] == 2


def test_exposure_registry_requires_every_freeze_group(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    registry = make_registry(freeze)
    registry['groups'] = registry['groups'][:-1]
    report = validate_exposure_registry(registry, {'dev_freeze': freeze},
                                        tmp_path, verify_evidence=False)
    assert 'EXPOSURE_GROUP_MISSING' in report.error_codes


def test_exposure_registry_rejects_touched_group_marked_untouched(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    event = {'event_id': 'ev1', 'type': 'annotation_calibration',
             'date': '2026-11-04', 'executor': 'agent',
             'frames_touched': 1}
    registry = make_registry(freeze, events=[event],
                             group_status='untouched')
    report = validate_exposure_registry(registry, {'dev_freeze': freeze},
                                        tmp_path, verify_evidence=False)
    assert 'EXPOSURE_TOUCHED_MARKED_UNTOUCHED' in report.error_codes


def test_exposure_registry_rejects_sealed_claim(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    registry = make_registry(freeze)
    registry['groups'][0]['certification'] = 'SEALED'
    report = validate_exposure_registry(registry, {'dev_freeze': freeze},
                                        tmp_path, verify_evidence=False)
    assert 'EXPOSURE_SEALED_CLAIM' in report.error_codes


def test_exposure_registry_verifies_event_evidence_hash(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    evidence = tmp_path / 'docs' / 'evidence.json'
    evidence.parent.mkdir(parents=True)
    evidence.write_text('{"ok": true}', encoding='utf-8')
    event = {'event_id': 'ev1', 'type': 'development_use',
             'date': '2026-11-04', 'executor': 'agent',
             'evidence_path': 'docs/evidence.json',
             'evidence_sha256': sha('0'), 'frames_touched': 1}
    registry = make_registry(freeze, events=[event])
    report = validate_exposure_registry(registry, {'dev_freeze': freeze},
                                        tmp_path, verify_evidence=True)
    assert 'EXPOSURE_EVIDENCE_SHA_MISMATCH' in report.error_codes


def test_exposure_registry_frame_override_must_exist(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    event = {'event_id': 'ev1', 'type': 'annotation_calibration',
             'date': '2026-11-04', 'executor': 'agent', 'frames_touched': 1}
    registry = make_registry(freeze, events=[event], frame_overrides=[{
        'frame_id': 'nope-follow_only_g1_0.png',
        'group_id': freeze['groups'][0]['group_id'],
        'source': 'dev_freeze', 'status': 'annotation_calibration',
        'event_id': 'ev1',
    }])
    report = validate_exposure_registry(registry, {'dev_freeze': freeze},
                                        tmp_path, verify_evidence=False)
    assert 'EXPOSURE_FRAME_UNKNOWN' in report.error_codes


def test_exposure_registry_final_pool_must_be_downgraded(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    event = {'event_id': 'ev_pilot', 'type': 'annotation_calibration',
             'date': '2026-11-04', 'executor': 'agent', 'frames_touched': 1}
    registry = make_registry(freeze, source='final_seal', events=[event],
                             group_status='untouched')
    report = validate_exposure_registry(registry,
                                        {'final_seal': freeze}, tmp_path,
                                        verify_evidence=False)
    assert 'EXPOSURE_TOUCHED_MARKED_UNTOUCHED' in report.error_codes
    assert 'EXPOSURE_FINAL_NOT_DOWNGRADED' in report.error_codes


def test_audit_split_leakage_clean_freeze(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    result = audit_split_leakage(freeze)
    assert result['ok'] is True
    assert result['stats']['family_leaks'] == 0
    assert result['stats']['sha_leaks'] == 0
    assert result['stats']['trajectory_leaks'] == 0


def test_audit_split_leakage_detects_family_cross_split(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    freeze['families'] = [{'family_id': 'fam_shared',
                           'groups': ['g1', 'g2']}]
    freeze['groups'][0]['family_id'] = 'fam_shared'
    freeze['groups'][1]['family_id'] = 'fam_shared'
    result = audit_split_leakage(freeze)
    assert result['ok'] is False
    assert result['stats']['family_leaks'] == 1


def test_audit_split_leakage_detects_duplicate_sha_across_split(tmp_path):
    freeze, _, _, _ = clean_fixture(tmp_path)
    freeze['groups'][1]['frames'][0]['sha256'] = \
        freeze['groups'][0]['frames'][0]['sha256']
    result = audit_split_leakage(freeze)
    assert result['ok'] is False
    assert result['stats']['sha_leaks'] == 1


def test_audit_split_leakage_detects_same_trajectory_cross_split(tmp_path):
    frames = [(frame_id('ep_shared', 1, i), sha(chr(ord('a') + i)), True)
              for i in range(4)]
    datasets = {'ds_a': dataset_entry(tmp_path, 'ds_a', frames)}
    groups = [
        group('g1', 'fam_one', 'ds_a', ['ep_shared'], 'train', frames[:2]),
        group('g2', 'fam_two', 'ds_a', ['ep_shared'], 'val', frames[2:]),
    ]
    splits = {'train': ['g1'], 'val': ['g2'], 'test': [], 'excluded': []}
    freeze = make_freeze(datasets, groups, splits)
    result = audit_split_leakage(freeze)
    assert result['ok'] is False
    assert result['stats']['trajectory_leaks'] >= 1


# ---------------------------------------------------------------------------
# committed v3 freeze + exposure registry (T12)
# ---------------------------------------------------------------------------

FREEZE_V3_PATH = (REPO_ROOT / 'configs' / 'perception'
                  / 'landmark_split_freeze_v3.json')
EXPOSURE_REGISTRY_PATH = (REPO_ROOT / 'configs' / 'perception'
                          / 'landmark_exposure_registry_v1.json')
SEAL_PATH = (REPO_ROOT / 'configs' / 'perception'
             / 'landmark_final_pool_seal_v1.json')


@pytest.mark.skipif(not (FREEZE_V3_PATH.is_file() and RAW_FORMAL6.is_file()),
                    reason='raw sensor outputs are ignored and absent here')
def test_committed_v3_freeze_verifies_and_matches_annot2_lists():
    freeze = json.loads(FREEZE_V3_PATH.read_text(encoding='utf-8'))
    report = validate_freeze(freeze, REPO_ROOT, verify_input_hashes=True,
                             require_images=False)
    assert report.ok, [issue.code + ': ' + issue.message
                       for issue in report.errors]
    assert freeze['freeze_id'] == 'landmark_split_freeze_v3'
    assert len(freeze['datasets']) == 15
    assert report.stats['frame_total'] == 3398
    assert report.stats['split_frame_counts']['train'] == 1475
    assert report.stats['split_frame_counts']['val'] == 816
    assert report.stats['split_frame_counts']['excluded'] == 1107
    assert report.stats['split_frame_counts']['test'] == 0
    val_groups = freeze['splits']['val']
    assert set(val_groups) == {
        'g_lm_ind_north', 'g_geo_north', 'g_lm_pilot_north',
        'g_lmf_dev_inner_north', 'g_lmf_dev_static_low',
        'g_lmf_dev_hn1_confuser', 'g_lmf_dev_hn2_occluder'}
    val_families = {item['family_id'] for item in freeze['groups']
                    if item['split'] == 'val'}
    assert {'fam_north', 'fam_inner_north', 'fam_static_low_oblique',
            'fam_HN1_confuser', 'fam_HN2_occluder'} <= val_families
    alignment = freeze['annotation_frame_lists']
    assert alignment['status'] == 'PASS'
    assert alignment['checked_frames'] == 294
    assert alignment['hn_val_pending'] is False
    assert alignment['config']['sha256'] == (
        'befbbea1b587261ed861a081706fe44a8a761aa90b04743fb137ddbd85c27701')
    assert alignment['labels']['train']['sha256'].startswith('01977b9f')
    assert alignment['labels']['val']['sha256'].startswith('c3944e08')
    assert freeze['delta_from_v2']['new_frames'] == 396
    assert audit_split_leakage(freeze)['ok'] is True


@pytest.mark.skipif(not (EXPOSURE_REGISTRY_PATH.is_file()
                         and FREEZE_V3_PATH.is_file()
                         and SEAL_PATH.is_file()),
                    reason='registry/freezes absent')
def test_exposure_registry_marks_final_pool_exploratory():
    registry = json.loads(EXPOSURE_REGISTRY_PATH.read_text(encoding='utf-8'))
    freeze_documents = {
        'dev_v3': json.loads(FREEZE_V3_PATH.read_text(encoding='utf-8')),
        'final_seal': json.loads(SEAL_PATH.read_text(encoding='utf-8')),
    }
    # v1 registry is historical: its evidence hash points to a pre-T16 copy of
    # the dev label-list config, so only the structural record is re-verified.
    report = validate_exposure_registry(registry, freeze_documents, REPO_ROOT,
                                        verify_evidence=False)
    assert report.ok, [issue.code + ': ' + issue.message
                       for issue in report.errors]
    assert registry['certification']['can_claim_sealed'] is False
    assert registry['certification']['conclusion'] == 'INCOMPLETE'
    assert registry['summary']['untouched_groups'] == 0
    assert registry['summary']['final_groups_contaminated'] == 6
    groups = {item['group_id']: item for item in registry['groups']}
    assert groups['g_lmf_dev_hn1_confuser']['status'] == 'exposed_development'
    assert groups['g_lmf_sweep']['status'] == 'exploratory_eval_candidate'
    assert 'ev_final_exploratory_labels_279_20261104' in {
        event['event_id'] for event in registry['events']}
    assert 'ev_map_native_ms1_identity_conflict_20261104' in {
        event['event_id'] for event in registry['events']}
    identity = registry['identity_certification']
    assert identity['U1_at_most_one_tower_like_instance'] == 'FALSIFIED'
    assert identity['U2_central_tower_is_only_green_light_tower'] == 'FALSIFIED'
    assert identity['identity_status'] == 'INCOMPLETE'
    assert len(registry['frame_overrides']) == 328



FREEZE_V4_PATH = (REPO_ROOT / 'configs' / 'perception'
                  / 'landmark_split_freeze_v4.json')
REGISTRY_V2_PATH = (REPO_ROOT / 'configs' / 'perception'
                    / 'landmark_exposure_registry_v2.json')
FREEZE_V4_1_PATH = (REPO_ROOT / 'configs' / 'perception'
                    / 'landmark_split_freeze_v4_1.json')
FREEZE_V4_2_PATH = (REPO_ROOT / 'configs' / 'perception'
                    / 'landmark_split_freeze_v4_2.json')
FREEZE_V5_PATH = (REPO_ROOT / 'configs' / 'perception'
                  / 'landmark_split_freeze_v5.json')
HOLDOUT_V2_PATH = (REPO_ROOT / 'configs' / 'perception'
                   / 'landmark_holdout_freeze_v2.json')
SNAPSHOT_V5_PATH = (REPO_ROOT / 'configs' / 'perception'
                    / 'landmark_run_snapshot_v5.json')
HOLDOUT_PATH = (REPO_ROOT / 'configs' / 'perception'
                / 'landmark_holdout_freeze_v1.json')


@pytest.mark.skipif(not (FREEZE_V4_PATH.is_file() and RAW_FORMAL6.is_file()),
                    reason='raw sensor outputs are ignored and absent here')
def test_committed_v4_freeze_keeps_v3_structure_with_hn_labels():
    freeze = json.loads(FREEZE_V4_PATH.read_text(encoding='utf-8'))
    report = validate_freeze(freeze, REPO_ROOT, verify_input_hashes=True,
                             require_images=False)
    assert report.ok, [issue.code + ': ' + issue.message
                       for issue in report.errors]
    assert freeze['freeze_id'] == 'landmark_split_freeze_v4'
    assert report.stats['frame_total'] == 3398
    assert report.stats['split_frame_counts']['train'] == 1475
    assert report.stats['split_frame_counts']['val'] == 816
    assert report.stats['split_frame_counts']['excluded'] == 1107
    assert freeze['delta_from_v3']['new_groups'] == []
    assert freeze['delta_from_v3']['new_frames'] == 0
    alignment = freeze['annotation_frame_lists']
    assert alignment['status'] == 'PASS'
    assert alignment['checked_frames'] == 323
    assert alignment['hn_val_pending'] is False
    assert alignment['config']['sha256'] == (
        '0c1c75aed2fdddd6de3773180f93dc643192d2c119eeccbbaea39f2bd23d6488')
    assert alignment['labels']['train']['sha256'].startswith('01977b9f')
    assert alignment['labels']['val']['sha256'].startswith('8c215597')
    assert freeze['identity_cases_pending'] is True
    assert audit_split_leakage(freeze)['ok'] is True


@pytest.mark.skipif(not (REGISTRY_V2_PATH.is_file()
                         and FREEZE_V4_PATH.is_file()
                         and SEAL_PATH.is_file()),
                    reason='registry/freezes absent')
def test_exposure_registry_v2_downgrades_old_final_to_development():
    registry = json.loads(REGISTRY_V2_PATH.read_text(encoding='utf-8'))
    freeze_documents = {
        'dev_v5': json.loads(FREEZE_V5_PATH.read_text(encoding='utf-8')),
    }
    report = validate_exposure_registry(registry, freeze_documents, REPO_ROOT,
                                        verify_evidence=True)
    assert report.ok, [issue.code + ': ' + issue.message
                       for issue in report.errors]
    assert registry['registry_version'] == 'v2'
    summary = registry['summary']
    assert summary['exploratory_eval_candidate_groups'] == 0
    assert summary['untouched_groups'] == 0
    assert summary['old_final_groups_downgraded'] == 6
    assert summary['reused_exploratory_train_groups'] == 6
    assert summary['reused_exploratory_accepted_frames'] == 279
    assert summary['identity_dev_groups'] == 7
    assert summary['identity_train_groups'] == 3
    assert summary['identity_val_groups'] == 4
    assert summary['val_identity_groups'] == 4
    assert summary['t26_labels_status'] == 'PROVISIONAL_DIAGNOSTIC_ONLY'
    assert summary['t26_ingested_in_v5'] is False
    assert summary['identity_cases_pending'] is False
    assert summary['hn_val_complete'] is True
    assert registry['certification']['can_claim_sealed'] is False
    assert registry['certification']['conclusion'] == 'INCOMPLETE'
    groups = {item['group_id']: item for item in registry['groups']}
    assert groups['g_reuse_lmf_sweep']['status'] == 'exposed_development'
    assert groups['g_reuse_lmf_sweep']['dataset_role'] == 'DEVELOPMENT_TRAIN'
    assert groups['g_devid_ms1_alone']['status'] == 'exposed_development'
    assert groups['g_devid_ms1_alone']['dataset_role'] == 'DEVELOPMENT_TRAIN'
    assert groups['g_devid_both_same_bearing']['dataset_role'] == 'DEVELOPMENT'
    assert groups['g_lmf_dev_hn1_confuser']['status'] == 'exposed_development'
    event_ids = {event['event_id'] for event in registry['events']}
    assert 'ev_exploratory_one_shot_eval_20261104' in event_ids
    assert 'ev_posteval_diag_view_20261104' in event_ids
    assert 'ev_exploratory_reused_as_train_20261104' in event_ids
    assert 'ev_identity_dev_annotation_20261104' in event_ids
    assert 'ev_t25_identity_capture_failed_20261104' in event_ids
    assert 'ev_t26_identity_t25_provisional_20261104' in event_ids
    identity = registry['identity_certification']
    assert identity['U1_at_most_one_tower_like_instance'] == 'FALSIFIED'
    assert identity['identity_status'] == 'INCOMPLETE'


@pytest.mark.skipif(not HOLDOUT_PATH.is_file(), reason='holdout freeze absent')
def test_holdout_freeze_is_not_triggered_placeholder():
    document = json.loads(HOLDOUT_PATH.read_text(encoding='utf-8'))
    assert document['schema_version'] == 'dsh.landmark_holdout_freeze.v1'
    assert document['status'] == 'NOT_TRIGGERED'
    assert document['triggered'] is False
    assert document['captured'] is False
    assert document['gate']['sha256']
    rules = document['frozen_sampling_rules']
    assert rules['min_new_families'] >= 3
    assert rules['frames_range'] == [200, 400]
    assert rules['no_selection_by_prediction_quality'] is True
    assert len(rules['required_conditions']) >= 5



@pytest.mark.skipif(not (FREEZE_V4_1_PATH.is_file() and RAW_FORMAL6.is_file()),
                    reason='raw sensor outputs are ignored and absent here')
def test_committed_v4_1_reuses_exploratory_pool_as_development_train():
    freeze = json.loads(FREEZE_V4_1_PATH.read_text(encoding='utf-8'))
    report = validate_freeze(freeze, REPO_ROOT, verify_input_hashes=True,
                             require_images=False)
    assert report.ok, [issue.code + ': ' + issue.message
                       for issue in report.errors]
    assert freeze['freeze_id'] == 'landmark_split_freeze_v4_1'
    assert report.stats['frame_total'] == 3695
    assert report.stats['split_frame_counts']['train'] == 1772
    assert report.stats['split_frame_counts']['val'] == 816
    assert report.stats['split_frame_counts']['excluded'] == 1107
    assert report.stats['split_accepted_frame_counts']['train'] == 1697
    reuse = freeze['development_train_reuse']
    assert reuse['dataset_role'] == 'DEVELOPMENT_TRAIN'
    assert reuse['reused_accepted_frames'] == 279
    assert reuse['labels']['sha256'].startswith('7115ee04')
    assert reuse['train_label_frames']['total'] == 439
    assert reuse['val_label_frames'] == 163
    assert len(freeze['delta_from_v4']['new_groups']) == 6
    assert freeze['delta_from_v4']['new_frames'] == 297
    reused_groups = {item['group_id'] for item in freeze['groups']
                     if str(item.get('dataset')).startswith(
                         'lm_final_candidate')}
    assert len(reused_groups) == 6
    val_groups = set(freeze['splits']['val'])
    assert not (reused_groups & val_groups)
    assert audit_split_leakage(freeze)['ok'] is True



@pytest.mark.skipif(not (FREEZE_V4_2_PATH.is_file() and RAW_FORMAL6.is_file()),
                    reason='raw sensor outputs are ignored and absent here')
def test_committed_v4_2_adds_identity_val_subset():
    freeze = json.loads(FREEZE_V4_2_PATH.read_text(encoding='utf-8'))
    report = validate_freeze(freeze, REPO_ROOT, verify_input_hashes=True,
                             require_images=False)
    assert report.ok, [issue.code + ': ' + issue.message
                       for issue in report.errors]
    assert freeze['freeze_id'] == 'landmark_split_freeze_v4_2'
    assert report.stats['frame_total'] == 3885
    assert report.stats['split_frame_counts']['train'] == 1772
    assert report.stats['split_frame_counts']['val'] == 1006
    assert report.stats['split_frame_counts']['excluded'] == 1107
    assert report.stats['split_accepted_frame_counts']['val'] == 964
    assert freeze['delta_from_v4_1']['new_frames'] == 190
    assert len(freeze['delta_from_v4_1']['new_groups']) == 7
    subset = freeze['splits_subset']
    assert len(subset['val_main']['groups']) == 7
    assert len(subset['val_identity']['groups']) == 7
    identity = freeze['identity_dev_batch']
    assert identity['resolved_frames'] == 62
    assert identity['sha_mismatches'] == 0
    assert identity['labels']['sha256'].startswith('79fd1745')
    assert freeze['identity_cases_pending'] is False
    sources = freeze['annotation_label_sources']
    assert sources['val_main']['frames'] == 163
    assert sources['val_main']['labels']['sha256'].startswith('a9bfda8f')
    assert sources['val_identity']['frames'] == 62
    assert audit_split_leakage(freeze)['ok'] is True



@pytest.mark.skipif(not (FREEZE_V5_PATH.is_file() and RAW_FORMAL6.is_file()),
                    reason='raw sensor outputs are ignored and absent here')
def test_committed_v5_splits_identity_train_val_without_frame_leak():
    freeze = json.loads(FREEZE_V5_PATH.read_text(encoding='utf-8'))
    report = validate_freeze(freeze, REPO_ROOT, verify_input_hashes=True,
                             require_images=False)
    assert report.ok, [issue.code + ': ' + issue.message
                       for issue in report.errors]
    assert freeze['freeze_id'] == 'landmark_split_freeze_v5'
    assert report.stats['split_group_counts']['train'] == 19
    assert report.stats['split_frame_counts']['train'] == 1857
    assert report.stats['split_frame_counts']['val'] == 921
    assert report.stats['split_frame_counts']['excluded'] == 1107
    identity = freeze['identity_split']
    assert len(identity['train_groups']) == 3
    assert set(identity['train_groups']) == {
        'g_devid_target_alone', 'g_devid_target_near_trunc',
        'g_devid_ms1_alone'}
    assert len(identity['val_groups']) == 4
    assert set(identity['val_groups']) == {
        'g_devid_both_scale_lateral', 'g_devid_both_mid_similar_scale',
        'g_devid_both_same_bearing', 'g_devid_full_occlusion'}
    assert not (set(identity['train_groups']) & set(identity['val_groups']))
    subset = freeze['splits_subset']
    assert len(subset['val_main']['groups']) == 7
    assert identity['labels_train_identity_frames'] == 27
    moves = {item['group_id'] for item in
             freeze['delta_from_v4_2']['split_changes']}
    assert moves == set(identity['train_groups'])
    assert freeze['run_snapshot_reference']['path'] == (
        'configs/perception/landmark_run_snapshot_v5.json')
    assert freeze['holdout_reference']['path'] == (
        'configs/perception/landmark_holdout_freeze_v2.json')
    extra = freeze['identity_extra_cases']
    assert extra['status'] == 'EXCLUDED_T25_PENDING_CAPTURE_CONFIRMATION'
    assert extra['mutual_occlusion_case_present'] is True
    assert extra['far_ms1_case_present'] is True
    assert extra['t26_provisional_diagnostic_only'] is True
    assert extra['t25_formal_run_status'] == 'FAILED_CUDA_OOM_NO_RUN_COMPLETE'


@pytest.mark.skipif(not HOLDOUT_V2_PATH.is_file(), reason='holdout v2 absent')
def test_holdout_v2_spec_is_frozen_but_not_triggered():
    document = json.loads(HOLDOUT_V2_PATH.read_text(encoding='utf-8'))
    assert document['schema_version'] == 'dsh.landmark_holdout_freeze.v2'
    assert document['status'] == 'SPEC_FROZEN_NOT_TRIGGERED'
    assert document['captured'] is False
    spec = document['specification']
    assert spec['min_new_families'] >= 3
    assert spec['frames_range'] == [200, 400]
    conditions = {item['condition'] for item in spec['required_conditions']}
    assert {'near_range_large_target', 'far_small_target',
            'edge_truncation', 'ms1_confuser_alone',
            'same_frame_ambiguity', 'target_absent'} <= conditions
    assert sum(item['min_frames'] for item in spec['required_conditions']) == 200
    sampling = spec['sampling_rule']
    assert sampling['frozen_before_capture'] is True
    assert sampling['no_prediction_based_selection'] is True
    assert spec['evaluation_rule']['runs'] == 1
    assert spec['evaluation_rule']['no_rerun'] is True


@pytest.mark.skipif(not SNAPSHOT_V5_PATH.is_file(), reason='snapshot v5 absent')
def test_snapshot_v5_manifest_covers_frozen_inputs():
    document = json.loads(SNAPSHOT_V5_PATH.read_text(encoding='utf-8'))
    assert document['schema_version'] == 'dsh.landmark_run_snapshot.v1'
    assert document['checks']['phases'] == [
        'pre_train', 'pre_selection', 'post_train']
    artifacts = {item['id']: item for item in document['tracked_artifacts']}
    assert artifacts['split_freeze_v5']['path'] == (
        'configs/perception/landmark_split_freeze_v5.json')
    assert artifacts['val_main_labels']['path'].endswith(
        'labels_val_validation163.json')
    assert artifacts['identity_train_labels']['path'].endswith(
        'labels_identity_dev.json')
    for item in document['tracked_artifacts']:
        assert not item['path'].startswith(('C:', '/', '\\\\'))
        assert item['kind']