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
