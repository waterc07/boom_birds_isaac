"""Build / verify the landmark dataset split freeze and emit JSON evidence.

Read-only with respect to outputs/: the raw shadow runs are opened but never
modified.  Two modes:

  --build   scan the present raw observations, write the freeze JSON and then
            verify it (used once to create the committed freeze)
  (default) load the committed freeze, verify it against the present raw
            observations and write evidence JSON

The script never runs Isaac and never trains anything.  It imports only the
standard library plus boom_birds.evaluation.landmark_dataset.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from boom_birds.evaluation.landmark_dataset import (  # noqa: E402
    FREEZE_SCHEMA, GROUPING_PROTOCOL, DatasetInputError, freeze_sha256,
    load_dataset_frames, parse_frame_id, sha256_bytes, validate_freeze)


DEFAULT_FREEZE = 'configs/perception/landmark_split_freeze_v1.json'
DEFAULT_OUTPUT = ('docs/reports/perception/dataset_freeze_20261104/'
                  'landmark_dataset_verify_20261104.json')
INVENTORY = 'docs/reports/perception/dsh_landmark_data_inventory_20261104.json'
SPLIT_V1 = 'configs/perception/landmark_data_split_v1.json'
LABEL_FILES = [
    'configs/perception/landmark_labels_v1.json',
    'configs/perception/landmark_independent_labels_v1.json',
    'configs/perception/geometry_test_labels_v2.json',
]

# ---------------------------------------------------------------------------
# final sealed pool (T5): outputs/sensor_shadow/lm_final_candidate_20261104
# ---------------------------------------------------------------------------
FINAL_POOL_RUN = 'lm_final_candidate_20261104'
FINAL_POOL_SENSOR = 'lm_final_candidate_20261104_sensor'
FINAL_POOL_CASES = 'configs/scenarios/landmark_final_cases_v1.json'
FINAL_POOL_DEV_FREEZE = 'configs/perception/landmark_split_freeze_v2.json'
FINAL_POOL_T1_REPORT = ('docs/reports/perception/capture_20261104/'
                        'CAPTURE_20261104.md')
FINAL_POOL_CONDITION_SOURCE = ('docs/reports/perception/capture_20261104/'
                               'frame_conditions.json')
FINAL_POOL_ANNOTATION_PLAN = ('outputs/perception/'
                              'landmark_final_annotations_20261104/'
                              'labels_v1.json')
DEFAULT_FINAL_POOL_FREEZE = 'configs/perception/landmark_final_pool_seal_v1.json'
DEFAULT_FINAL_POOL_OUTPUT = ('docs/reports/perception/dataset_freeze_20261104/'
                             'landmark_final_pool_verify_20261104.json')

FINAL_POOL_FAMILIES = [
    {'family_id': 'lmf_sweep', 'group_id': 'g_lmf_sweep',
     'case_id': 'lmf_sweep_0', 'episode_id': 'lmf_sweep_0', 'condition_episode_id': 'lmf_sweep_0-follow_only',
     'description': 'east-area lateral serpentine facing +X, 7 waypoints '
                    '15.16 m; new family, not a south/north corridor route',
     'route': 'E serpentine [8.6,-1.3,1] -> [6,-1.3,1] -> [6,1.3,1.05] -> '
              '[8.4,1.3,1.05] -> [8.4,-1.3,1.1] -> [6.2,0,1.15] -> [8.6,0,1.2]'},
    {'family_id': 'lmf_backoff', 'group_id': 'g_lmf_backoff',
     'case_id': 'lmf_backoff_0', 'episode_id': 'lmf_backoff_0', 'condition_episode_id': 'lmf_backoff_0-follow_only',
     'description': 'scale/distance family: reverse flight from near tower to '
                    'mid-field facing +X, 8 waypoints 8.29 m',
     'route': 'E -> MID [9.4,-0.4,0.95] -> [8.2,-0.5,1.05] -> [6.8,-0.3,1.15] '
              '-> [5.2,0.1,1.3] -> [4.2,0.5,1.4] -> [3.4,0.1,1.5] -> '
              '[3,-0.6,1.55] -> [4.2,-0.4,1.55]'},
    {'family_id': 'lmf_near', 'group_id': 'g_lmf_near',
     'case_id': 'lmf_near_0', 'episode_id': 'lmf_near_0', 'condition_episode_id': 'lmf_near_0-follow_only',
     'description': 'near/close-range box patrol around the east approach, '
                    '5 waypoints 2.05 m; near/out-of-frame family',
     'route': 'E box [9.8,-0.35,0.9] -> [9.8,0.35,0.95] -> [10,0.35,1.05] -> '
              '[10,-0.35,1.05] -> [9.6,-0.35,0.9]'},
    {'family_id': 'lmf_edge', 'group_id': 'g_lmf_edge',
     'case_id': 'lmf_edge_0', 'episode_id': 'lmf_edge_0', 'condition_episode_id': 'lmf_edge_0-follow_only',
     'description': 'yaw/lateral + right-edge truncation family, fixed +0.6 '
                    'rad yaw offset, 5 waypoints 2.31 m',
     'route': 'E patrol [8.2,0,1] -> [8.8,0.2,1.1] -> [8.6,-0.2,1] -> '
              '[9,0,1.15] -> [8.4,-0.4,1]'},
    {'family_id': 'lmf_similar_negative', 'group_id': 'g_lmf_similar_negative',
     'case_id': 'lmf_similar_negative_0',
     'episode_id': 'lmf_similar_negative_0',
     'condition_episode_id': 'lmf_similar_negative_0-follow_only',
     'description': 'target absent (behind camera, yaw pi) while a central-'
                    'field structure is in view; NOT a verified similar '
                    'structure negative',
     'route': 'E -> MID [8,0,1.2] -> [7,-0.4,1.3] -> [6,0.2,1.4] -> '
              '[5.2,0.5,1.5] -> [5.4,-0.2,1.45]'},
    {'family_id': 'lmf_side_negative', 'group_id': 'g_lmf_side_negative',
     'case_id': 'lmf_side_negative_0',
     'episode_id': 'lmf_side_negative_0',
     'condition_episode_id': 'lmf_side_negative_0-follow_only',
     'description': 'static pose yaw +pi/2: tower physically present but '
                    'fully outside the camera FOV; target-absent negative',
     'route': 'static [9.6,0.6,1] yaw +pi/2'},
]

FINAL_POOL_PROVENANCE_FILES = [
    FINAL_POOL_CASES,
    'configs/sensors/sensor_shadow_v1.json',
    'outputs/sensor_shadow/lm_final_candidate_20261104/manifest.json',
    'outputs/sensor_shadow/lm_final_candidate_20261104/summary.json',
    'outputs/sensor_shadow/lm_final_candidate_20261104/episodes.jsonl',
    'outputs/sensor_shadow/lm_final_candidate_20261104/run.complete.json',
    'outputs/sensor_shadow/lm_final_candidate_20261104/gui.log',
    'outputs/sensor_shadow/lm_final_candidate_20261104/gui.exit.txt',
    'outputs/sensor_shadow/lm_final_candidate_20261104/_evidence/desktop_full_run.png',
    'outputs/sensor_shadow/lm_final_candidate_20261104/_evidence/desktop_smoke_run_1815.png',
    'outputs/sensor_shadow/lm_final_candidate_20261104/_evidence/window_check/desktop_full_run_view.png',
    'outputs/sensor_shadow/lm_final_candidate_20261104/_evidence/window_check/desktop_smoke_run_1815_view.png',
    'outputs/sensor_shadow/lm_final_candidate_20261104/_evidence/duplicate_hash_check.json',
    'outputs/sensor_shadow/lm_final_candidate_20261104/_evidence/overlap_check.json',
    'outputs/sensor_shadow/lm_final_candidate_20261104/_evidence/frame_conditions.json',
    'outputs/sensor_shadow/lm_final_candidate_20261104/_evidence/episode_condition_summary.json',
    'outputs/sensor_shadow/lm_final_candidate_20261104_sensor/observations.jsonl',
    'outputs/sensor_shadow/lm_final_candidate_20261104_sensor/summary.json',
    'docs/reports/perception/capture_20261104/CAPTURE_20261104.md',
    'docs/reports/perception/capture_20261104/frame_conditions.json',
    'docs/reports/perception/capture_20261104/overlap_check.json',
    'docs/reports/perception/capture_20261104/duplicate_hash_check.json',
    'configs/perception/landmark_split_freeze_v2.json',
]

#: Every directory under outputs/sensor_shadow that holds a shadow capture.
#: Datasets absent from the 2026-11-04 inventory are still listed so that no
#: exposed frame is silently usable for training.
DATASETS = [
    {'dataset': 'formal6_sensor', 'run': 'formal6', 'role': 'primary',
     'in_inventory': True, 'empty_capture': False,
     'description': 'formal 6-episode shadow run, 2026-11-03 20:49'},
    {'dataset': 'lm_pilot_sensor', 'run': 'lm_pilot', 'role': 'primary',
     'in_inventory': True, 'empty_capture': False,
     'description': 'static E pilot views, 2026-11-03 22:32'},
    {'dataset': 'lm_independence_sensor', 'run': 'lm_independence',
     'role': 'primary', 'in_inventory': True, 'empty_capture': False,
     'description': 'independent landmark run plus north pilot, 2026-11-03 22:40'},
    {'dataset': 'geo_test_sensor', 'run': 'geo_test', 'role': 'primary',
     'in_inventory': True, 'empty_capture': False,
     'description': 'geometry test run, 2026-11-04 00:14'},
    {'dataset': 'lm_pilot_north_sensor', 'run': 'lm_pilot_north',
     'role': 'duplicate_family_session', 'in_inventory': False,
     'empty_capture': False,
     'description': 'exposed north pilot (dynamic_A_north_0), absent from '
                    'inventory and split v1'},
    {'dataset': 'debug_all6_sensor', 'run': 'debug_all6',
     'role': 'duplicate_session_older_render', 'in_inventory': False,
     'empty_capture': False,
     'description': 'debug rerun of the six formal episodes with an older '
                    'sensor config version'},
    {'dataset': 'gui_evidence2_sensor', 'run': 'gui_evidence2',
     'role': 'duplicate_session', 'in_inventory': False,
     'empty_capture': False,
     'description': 'GUI evidence rerun of sensor_route_0 only'},
    {'dataset': 'gui_evidence_sensor', 'run': 'gui_evidence',
     'role': 'duplicate_session', 'in_inventory': False,
     'empty_capture': False,
     'description': 'GUI evidence rerun of sensor_static_0 only'},
    {'dataset': 'debug_static4_sensor', 'run': 'debug_static4',
     'role': 'debug_probe', 'in_inventory': False, 'empty_capture': False,
     'description': 'single static debug probe'},
    {'dataset': 'debug_static5_sensor', 'run': 'debug_static5',
     'role': 'debug_probe', 'in_inventory': False, 'empty_capture': False,
     'description': 'single static debug probe'},
    {'dataset': 'debug_static6_sensor', 'run': 'debug_static6',
     'role': 'debug_probe', 'in_inventory': False, 'empty_capture': False,
     'description': 'single static debug probe'},
    {'dataset': 'debug_static7_sensor', 'run': 'debug_static7',
     'role': 'debug_probe', 'in_inventory': False, 'empty_capture': False,
     'description': 'single static debug probe'},
    {'dataset': 'debug_static3_sensor', 'run': 'debug_static3',
     'role': 'empty_capture', 'in_inventory': False, 'empty_capture': True,
     'description': 'failed/empty capture: observations.jsonl has no records'},
]

#: dataset episode-id -> group id.  Every episode must be mapped exactly once.
EPISODE_GROUPS = {
    'formal6_sensor': {
        'sensor_static_0': 'g_formal6_staticW',
        'sensor_static_1': 'g_formal6_staticW',
        'sensor_route_0': 'g_formal6_southA',
        'sensor_route_1': 'g_formal6_southA',
        'sensor_reset_0': 'g_formal6_southA',
        'sensor_reset_1': 'g_formal6_southA',
    },
    'lm_pilot_sensor': {
        'pilot_east_center': 'g_lm_pilot_staticE',
        'pilot_east_left': 'g_lm_pilot_staticE',
        'pilot_east_away': 'g_lm_pilot_staticE',
    },
    'lm_independence_sensor': {
        'dev_south_new': 'g_lm_ind_devSouth',
        'test_reverse_south': 'g_lm_ind_reverseSouth',
        'test_north_0': 'g_lm_ind_north',
        'test_static_oblique': 'g_lm_ind_staticEtest',
        'test_static_away': 'g_lm_ind_staticEtest',
    },
    'geo_test_sensor': {
        'geo_test_north_0': 'g_geo_north',
        'geo_test_static_a': 'g_geo_staticE',
        'geo_test_static_b': 'g_geo_staticE',
        'geo_test_static_c': 'g_geo_staticE',
    },
    'lm_pilot_north_sensor': {'dynamic_A_north_0': 'g_lm_pilot_north'},
    'debug_all6_sensor': {
        'sensor_static_0': 'g_debug_all6_staticW',
        'sensor_static_1': 'g_debug_all6_staticW',
        'sensor_route_0': 'g_debug_all6_southA',
        'sensor_route_1': 'g_debug_all6_southA',
        'sensor_reset_0': 'g_debug_all6_southA',
        'sensor_reset_1': 'g_debug_all6_southA',
    },
    'gui_evidence2_sensor': {'sensor_route_0': 'g_gui_evidence2_route0'},
    'gui_evidence_sensor': {'sensor_static_0': 'g_gui_evidence_static'},
    'debug_static4_sensor': {'sensor_static_0': 'g_debug_static4'},
    'debug_static5_sensor': {'sensor_static_0': 'g_debug_static5'},
    'debug_static6_sensor': {'sensor_static_0': 'g_debug_static6'},
    'debug_static7_sensor': {'sensor_static_0': 'g_debug_static7'},
    'debug_static3_sensor': {},
}

GROUP_DEFS = [
    {'group_id': 'g_formal6_southA', 'family_id': 'fam_south_A',
     'dataset': 'formal6_sensor', 'split': 'train', 'view_cluster': None,
     'route': 'dynamic_A_south_0 waypoints [-10.2,0.5] -> [-10,-4] -> '
              '[-6,-6.2] -> [6,-6.2] -> [9.5,-4] -> [9.6,0.5]',
     'notes': 'route_0 g3 + route_1 g4 (stop/wait/resume variant) + reset_0 g5 '
              '+ reset_1 g6: same route repeated by reset, one physical family'},
    {'group_id': 'g_formal6_staticW', 'family_id': 'fam_static_W_start',
     'dataset': 'formal6_sensor', 'split': 'train', 'view_cluster': None,
     'route': 'static W start [-10.2,0.5,0.512] yaw 0',
     'notes': 'static_0 g1 + static_1 g2: same static render recipe'},
    {'group_id': 'g_lm_pilot_staticE', 'family_id': 'fam_static_E_dev',
     'dataset': 'lm_pilot_sensor', 'split': 'train',
     'view_cluster': 'static_E_roof_view',
     'route': 'static E [8.5,0,1] yaw 0 / 0.45 / pi',
     'notes': 'pilot center/left/away development views'},
    {'group_id': 'g_lm_ind_devSouth', 'family_id': 'fam_south_A',
     'dataset': 'lm_independence_sensor', 'split': 'train',
     'view_cluster': None,
     'route': 'dynamic_A_south_1 waypoints [-9.4,-1] -> ... -> [9.8,-0.8]',
     'notes': 'south-A corridor with a new west start'},
    {'group_id': 'g_lm_ind_reverseSouth', 'family_id': 'fam_south_A',
     'dataset': 'lm_independence_sensor', 'split': 'train',
     'view_cluster': None,
     'route': 'reverse of the south-A corridor (E -> W)',
     'notes': 'exposed former test family; same south corridor, so it can only '
              'be train/development data now'},
    {'group_id': 'g_lm_ind_north', 'family_id': 'fam_north',
     'dataset': 'lm_independence_sensor', 'split': 'val', 'view_cluster': None,
     'route': 'dynamic_A_north_0 waypoints [-10.2,0.5] -> [-10,3.5] -> '
              '[-6,5.8] -> [5.5,5.8] -> [9.5,3.5] -> [9.6,0.5]',
     'notes': 'north corridor, held out from train'},
    {'group_id': 'g_lm_ind_staticEtest', 'family_id': 'fam_static_E_test',
     'dataset': 'lm_independence_sensor', 'split': 'val',
     'view_cluster': 'static_E_roof_view',
     'route': 'static E [9.2,1.1,1.0] yaw -0.3 / [9.2,0,1.0] yaw pi',
     'notes': 'exposed former test views; same E roof viewpoint cluster as the '
              'pilot but different yaw/position'},
    {'group_id': 'g_geo_north', 'family_id': 'fam_north',
     'dataset': 'geo_test_sensor', 'split': 'val', 'view_cluster': None,
     'route': 'north corridor variant [-9.8,0.8] -> [-9.6,3.6] -> '
              '[-5.8,5.4] -> [5.8,5.4] -> [9.6,3.2] -> [9.7,0.2]',
     'notes': 'not a new trajectory family: same north corridor as '
              'test_north_0, so split v1 putting it in train was a leak'},
    {'group_id': 'g_geo_staticE', 'family_id': 'fam_static_E_test',
     'dataset': 'geo_test_sensor', 'split': 'val',
     'view_cluster': 'static_E_roof_view',
     'route': 'static E [8.0,-0.8,0.8] / [9.8,1.2,1.2] / [9.0,-1.2,1.0]',
     'notes': 'exposed former sealed geometry test poses'},
    {'group_id': 'g_lm_pilot_north', 'family_id': 'fam_north',
     'dataset': 'lm_pilot_north_sensor', 'split': 'val',
     'view_cluster': None,
     'route': 'dynamic_A_north_0 (identical case to test_north_0)',
     'notes': 'exposed but unlisted north pilot; must never be used for train'},
    {'group_id': 'g_debug_all6_staticW', 'family_id': 'fam_static_W_start',
     'dataset': 'debug_all6_sensor', 'split': 'excluded', 'view_cluster': None,
     'route': 'static W start', 'notes': 'duplicate session, older render '
              'config version; not independent data'},
    {'group_id': 'g_debug_all6_southA', 'family_id': 'fam_south_A',
     'dataset': 'debug_all6_sensor', 'split': 'excluded', 'view_cluster': None,
     'route': 'same six formal episodes re-run', 'notes': 'duplicate session, '
              'older render config version; not independent data'},
    {'group_id': 'g_gui_evidence2_route0', 'family_id': 'fam_south_A',
     'dataset': 'gui_evidence2_sensor', 'split': 'excluded',
     'view_cluster': None, 'route': 'sensor_route_0 re-run',
     'notes': 'GUI evidence rerun of a train-corridor episode'},
    {'group_id': 'g_gui_evidence_static', 'family_id': 'fam_static_W_start',
     'dataset': 'gui_evidence_sensor', 'split': 'excluded',
     'view_cluster': None, 'route': 'sensor_static_0 re-run',
     'notes': 'GUI evidence rerun of a train static episode'},
    {'group_id': 'g_debug_static4', 'family_id': 'fam_static_W_start',
     'dataset': 'debug_static4_sensor', 'split': 'excluded',
     'view_cluster': None, 'route': 'sensor_static_0 probe',
     'notes': 'ad-hoc debug probe'},
    {'group_id': 'g_debug_static5', 'family_id': 'fam_static_W_start',
     'dataset': 'debug_static5_sensor', 'split': 'excluded',
     'view_cluster': None, 'route': 'sensor_static_0 probe',
     'notes': 'ad-hoc debug probe'},
    {'group_id': 'g_debug_static6', 'family_id': 'fam_static_W_start',
     'dataset': 'debug_static6_sensor', 'split': 'excluded',
     'view_cluster': None, 'route': 'sensor_static_0 probe',
     'notes': 'ad-hoc debug probe'},
    {'group_id': 'g_debug_static7', 'family_id': 'fam_static_W_start',
     'dataset': 'debug_static7_sensor', 'split': 'excluded',
     'view_cluster': None, 'route': 'sensor_static_0 probe',
     'notes': 'ad-hoc debug probe'},
    {'group_id': 'g_debug_static3_empty', 'family_id': 'fam_debug_empty',
     'dataset': 'debug_static3_sensor', 'split': 'excluded',
     'view_cluster': None, 'route': 'none',
     'notes': 'failed/empty capture; observations.jsonl has no records'},
]

#: Named dev-split profiles.  'v1' keeps the original split; 'conservative'
#: moves the whole E static viewpoint cluster into train so that val contains
#: only the held-out north corridor family.
PROFILE_OVERRIDES = {
    'v1': {},
    'conservative': {
        'g_lm_ind_staticEtest': 'train',
        'g_geo_staticE': 'train',
    },
}
PROFILE_DESCRIPTIONS = {
    'v1': 'val = north corridor family + E static test viewpoint cluster '
          '(view-cluster overlap warning retained)',
    'conservative': 'val = north corridor family only; the whole E static '
                    'viewpoint cluster is moved into train to remove the '
                    'train/val viewpoint overlap',
}
PROFILE_FREEZE_IDS = {
    'v1': 'landmark_split_freeze_v1',
    'conservative': 'landmark_split_freeze_v2',
}
#: Why the conservative profile moves the whole E static cluster into train.
#: Poses come from the frozen case files (configs/scenarios/*.json); the
#: deltas are simple Euclidean/yaw differences, not model or image evidence.
PROFILE_EVIDENCE = {
    'conservative': {
        'view_cluster': 'static_E_roof_view',
        'static_poses': [
            {'case_id': 'pilot_east_center', 'group_id': 'g_lm_pilot_staticE',
             'position_world_m': [8.5, 0.0, 1.0], 'yaw_rad': 0.0},
            {'case_id': 'pilot_east_left', 'group_id': 'g_lm_pilot_staticE',
             'position_world_m': [8.5, 0.0, 1.0], 'yaw_rad': 0.45},
            {'case_id': 'pilot_east_away', 'group_id': 'g_lm_pilot_staticE',
             'position_world_m': [8.5, 0.0, 1.0], 'yaw_rad': 3.141592653589793},
            {'case_id': 'test_static_oblique',
             'group_id': 'g_lm_ind_staticEtest',
             'position_world_m': [9.2, 1.1, 1.0], 'yaw_rad': -0.3},
            {'case_id': 'test_static_away', 'group_id': 'g_lm_ind_staticEtest',
             'position_world_m': [9.2, 0.0, 1.0], 'yaw_rad': 3.141592653589793},
            {'case_id': 'geo_test_static_a', 'group_id': 'g_geo_staticE',
             'position_world_m': [8.0, -0.8, 0.8], 'yaw_rad': 0.1},
            {'case_id': 'geo_test_static_b', 'group_id': 'g_geo_staticE',
             'position_world_m': [9.8, 1.2, 1.2], 'yaw_rad': -0.25},
            {'case_id': 'geo_test_static_c', 'group_id': 'g_geo_staticE',
             'position_world_m': [9.0, -1.2, 1.0], 'yaw_rad': 3.141592653589793},
        ],
        'closest_cross_group_pairs': [
            {'pair': ['geo_test_static_b', 'test_static_oblique'],
             'position_delta_m': 0.64, 'yaw_delta_rad': 0.05},
            {'pair': ['geo_test_static_c', 'test_static_away'],
             'position_delta_m': 1.22, 'yaw_delta_rad': 0.0},
            {'pair': ['geo_test_static_a', 'pilot_east_center'],
             'position_delta_m': 0.96, 'yaw_delta_rad': 0.10},
        ],
        'conclusion': 'the E static poses are the same physical scene and roof '
                      'view with overlapping yaw/position; geo_b/geo_c are '
                      'near-duplicate viewpoints of the previously val static '
                      'poses, so the whole cluster is kept in train in v2',
        'decision_source': 'team decision (Lead, 2026-11-04); no user decision '
                           'required',
    },
}

FAMILY_DEFS = [
    {'family_id': 'fam_south_A',
     'description': 'south-A corridor W -> E (and its reverse / new start); '
                    'same physical route family across sessions',
     'physical_trajectory': 'south corridor'},
    {'family_id': 'fam_static_W_start',
     'description': 'static W start pose used by the formal six-episode run'},
    {'family_id': 'fam_static_E_dev',
     'description': 'static E roof views used as development templates'},
    {'family_id': 'fam_static_E_test',
     'description': 'static E roof views previously used as test poses'},
    {'family_id': 'fam_north',
     'description': 'north corridor W -> E (dynamic_A_north_0 and the geo_test '
                    'north variant)',
     'physical_trajectory': 'north corridor'},
    {'family_id': 'fam_debug_empty',
     'description': 'empty / failed debug capture placeholder'},
]


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def read_manifest(repo_root, run):
    relative = 'outputs/sensor_shadow/%s/manifest.json' % run
    path = Path(repo_root) / relative
    if not path.is_file():
        return None
    return load_json(path)


def cases_path_from_command(command):
    if not command:
        return None
    match = re.search(r'--cases[ =](\S+)', command)
    if match is None:
        return None
    return match.group(1).replace('\\', '/')


def build_datasets(repo_root):
    root = Path(repo_root)
    datasets_doc = {}
    loaded_frames = {}
    for spec in DATASETS:
        name = spec['dataset']
        dataset_root = 'outputs/sensor_shadow/' + name
        observations = dataset_root + '/observations.jsonl'
        try:
            loaded = load_dataset_frames(
                root, name, dataset_root, observations,
                allow_empty=spec['empty_capture'], verify_images=True)
        except DatasetInputError as error:
            raise SystemExit('input error for %s: %s' % (name, error))
        loaded_frames[name] = loaded
        entry = {
            'root': dataset_root,
            'observations': observations,
            'observations_sha256': loaded.observations_sha256,
            'in_inventory': spec['in_inventory'],
            'role': spec['role'],
            'empty_capture': spec['empty_capture'],
            'description': spec['description'],
            'rgb_frames': len(loaded.frames),
            'accepted_rgb_frames': sum(1 for frame in loaded.frames
                                       if frame.accepted),
            'images_present': loaded.images_present,
            'images_missing': loaded.images_missing,
        }
        manifest = read_manifest(root, spec['run'])
        if manifest is not None:
            run_manifest = 'outputs/sensor_shadow/%s/manifest.json' % spec['run']
            entry['run'] = 'outputs/sensor_shadow/' + spec['run']
            entry['manifest'] = run_manifest
            entry['manifest_sha256'] = sha256_file(root / run_manifest)
            entry['gui_mode'] = manifest.get('gui_mode')
            entry['renderer'] = manifest.get('renderer')
            entry['code_commit'] = manifest.get('code_commit')
            entry['working_tree'] = manifest.get('working_tree')
            entry['started_at'] = manifest.get('started_at')
            entry['cases_sha256_recorded'] = manifest.get('cases_sha256')
            sensor = manifest.get('sensor_shadow') or {}
            entry['sensor_config_path'] = sensor.get('config')
            entry['sensor_config_sha256_recorded'] = sensor.get('config_sha256')
            cases_path = cases_path_from_command(manifest.get('command'))
            if cases_path:
                entry['cases_path'] = cases_path
                cases_file = root / cases_path
                if cases_file.is_file():
                    entry['cases_sha256_current'] = sha256_file(cases_file)
            config_path = sensor.get('config')
            if config_path and (root / config_path).is_file():
                entry['sensor_config_sha256_current'] = sha256_file(
                    root / config_path)
        summary = 'outputs/sensor_shadow/%s_sensor/summary.json' % spec['run']
        if (root / summary).is_file():
            entry['summary'] = summary
            entry['summary_sha256'] = sha256_file(root / summary)
        datasets_doc[name] = entry
    return datasets_doc, loaded_frames


def render_version_for(entry):
    recorded = entry.get('sensor_config_sha256_recorded')
    if recorded:
        return 'sensor_config_' + recorded[:12]
    return 'unknown'


def build_groups(repo_root, datasets_doc, loaded_frames, profile='v1'):
    overrides = PROFILE_OVERRIDES.get(profile, {})
    group_by_id = {}
    for definition in GROUP_DEFS:
        group = dict(definition)
        group['session'] = group['dataset']
        group['render_version'] = render_version_for(
            datasets_doc[group['dataset']])
        group['sealed'] = False
        group['split'] = overrides.get(group['group_id'], definition['split'])
        group['frames'] = []
        group['episodes'] = []
        group_by_id[group['group_id']] = group
    for dataset_name, loaded in loaded_frames.items():
        mapping = EPISODE_GROUPS.get(dataset_name, {})
        for frame in loaded.frames:
            group_id = mapping.get(frame.episode_id)
            if group_id is None:
                raise SystemExit('unmapped episode %s in %s'
                                 % (frame.episode_id, dataset_name))
            group = group_by_id[group_id]
            if group['dataset'] != dataset_name:
                raise SystemExit('group %s dataset mismatch' % group_id)
            group['frames'].append({
                'frame_id': frame.frame_id,
                'sha256': frame.sha256,
                'accepted': frame.accepted,
            })
            if frame.episode_id not in group['episodes']:
                group['episodes'].append(frame.episode_id)
    groups = []
    for definition in GROUP_DEFS:
        group = group_by_id[definition['group_id']]
        group['frames'].sort(key=lambda item: (
            parse_frame_id(item['frame_id'])['episode_id'],
            parse_frame_id(item['frame_id'])['sequence']))
        group['episodes'] = sorted(group['episodes'])
        group['frame_count'] = len(group['frames'])
        group['accepted_frame_count'] = sum(
            1 for item in group['frames'] if item['accepted'])
        groups.append(group)
    return groups


def build_labels(repo_root, frame_index):
    labels_doc = {}
    root = Path(repo_root)
    for relative in LABEL_FILES:
        path = root / relative
        if not path.is_file():
            raise SystemExit('label file missing: %s' % relative)
        document = load_json(path)
        labels = document.get('labels') or []
        split_claims = {}
        matched = 0
        unknown = 0
        sha_mismatch = 0
        for item in labels:
            split_claims[item.get('split')] = split_claims.get(
                item.get('split'), 0) + 1
            ref = str(item.get('ref') or '').replace('\\', '/')
            frame = frame_index.get(ref)
            if frame is None:
                unknown += 1
                continue
            matched += 1
            if item.get('payload_sha256') and item['payload_sha256'] != frame.sha256:
                sha_mismatch += 1
        labels_doc[path.stem] = {
            'path': relative,
            'sha256': sha256_file(path),
            'frame_count': len(labels),
            'split_claims': split_claims,
            'frames_matched_to_observations': matched,
            'frames_unknown': unknown,
            'frames_with_sha_mismatch': sha_mismatch,
            'status': 'HISTORICAL_LABEL_SPLIT_NAMES_NOT_A_SEALED_GUARANTEE',
        }
    return labels_doc


def build_freeze(repo_root, profile='v1'):
    root = Path(repo_root)
    datasets_doc, loaded_frames = build_datasets(repo_root)
    groups = build_groups(repo_root, datasets_doc, loaded_frames, profile)
    frame_index = {}
    for loaded in loaded_frames.values():
        for frame in loaded.frames:
            frame_index[frame.ref] = frame
    labels_doc = build_labels(repo_root, frame_index)

    splits = {'train': [], 'val': [], 'test': [], 'excluded': []}
    family_groups = {}
    for group in groups:
        splits[group['split']].append(group['group_id'])
        family_groups.setdefault(group['family_id'], []).append(
            group['group_id'])
    families = []
    for definition in FAMILY_DEFS:
        family = dict(definition)
        family['groups'] = family_groups.get(definition['family_id'], [])
        families.append(family)
    for family_id, group_ids in family_groups.items():
        if family_id not in {item['family_id'] for item in families}:
            raise SystemExit('group references undeclared family %s' % family_id)

    inventory = None
    inventory_path = root / INVENTORY
    if inventory_path.is_file():
        inventory_doc = load_json(inventory_path)
        listed = inventory_doc.get('datasets') or {}
        listed_frames = sum(int(item.get('accepted_rgb') or 0)
                            for item in listed.values())
        listed_records = sum(int(item.get('records') or 0)
                             for item in listed.values())
        actual_frames = sum(len(loaded.frames)
                            for loaded in loaded_frames.values())
        inventory = {
            'path': INVENTORY,
            'sha256': sha256_file(inventory_path),
            'listed_datasets': sorted(listed),
            'listed_records': listed_records,
            'listed_accepted_rgb': listed_frames,
            'actual_exposed_rgb_frames': actual_frames,
            'unlisted_datasets': sorted(
                name for name, entry in datasets_doc.items()
                if not entry['in_inventory']),
            'unlisted_exposed_rgb_frames': actual_frames - sum(
                len(loaded.frames) for name, loaded in loaded_frames.items()
                if datasets_doc[name]['in_inventory']),
            'claim_vs_actual': 'the inventory claims all current data are '
                               'exposed but lists only 4 of 13 shadow '
                               'datasets; unlisted frames are recorded as '
                               'excluded groups in this freeze',
        }

    split_v1 = None
    split_v1_path = root / SPLIT_V1
    if split_v1_path.is_file():
        split_v1 = {
            'path': SPLIT_V1,
            'sha256': sha256_file(split_v1_path),
            'corrections': [
                {'change': 'move g_geo_north from train to val',
                 'reason': 'geo_test_north_0 uses the same north corridor as '
                           'test_north_0 (dynamic_A_north_0 family); split v1 '
                           'putting geo north in train and lm north in val is '
                           'a family leak'},
                {'change': 'add g_lm_pilot_north to val',
                 'reason': 'outputs/sensor_shadow/lm_pilot_north_sensor '
                           '(dynamic_A_north_0) is exposed but absent from '
                           'inventory and split v1; it belongs to the north '
                           'family and must never be train data'},
                {'change': 'add excluded groups for 9 unlisted datasets',
                 'reason': 'duplicate sessions / debug probes / empty capture '
                           'must not be silently reused as independent data'},
            ],
            'v1_proposed_train_groups': [
                'g_formal6_south_A', 'g_formal6_static', 'g_lm_pilot_static',
                'g_lm_dev_south', 'g_geo_north'],
            'v1_proposed_validation_groups': [
                'g_lm_north', 'g_lm_static_test', 'g_geo_static'],
        }

    freeze = {
        'schema_version': FREEZE_SCHEMA,
        'grouping_protocol': GROUPING_PROTOCOL,
        'freeze_id': PROFILE_FREEZE_IDS[profile],
        'status': 'DEV_SPLIT_ONLY_NO_SEALED_TEST',
        'generated_at': datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        'generated_by': 'scripts/verify_landmark_dataset.py --build --profile '
                        + profile,
        'scope': 'existing exposed shadow RGB data only; no new capture; no '
                 'training; no Isaac run',
        'hash_algorithm': {
            'name': 'sha256',
            'canonicalisation': 'json_sort_keys_utf8_compact_v1',
            'excluded_fields': ['generated_at', 'freeze_sha256'],
            'covers': 'this freeze document only; raw file hashes are listed '
                      'under datasets and labels',
        },
        'group_rule': {
            'unit': 'physical trajectory family x acquisition session x '
                    'render version',
            'family': 'physical corridor / viewpoint cluster; a family must '
                      'not span train and val/test',
            'no_frame_random_split': True,
            'no_consecutive_frame_crossing': True,
            'reset_or_near_identical_static_is_one_group': True,
            'test_must_be_new_family': True,
            'current_sealed_test': 'NONE',
        },
        'sealed': {
            'present': False,
            'groups': [],
            'note': 'the 49-frame and 30-frame label files still carry the '
                    'historical split name sealed_test, but those frames have '
                    'been inspected and reused; a hash does not make them '
                    'sealed. A sealed final pool requires new trajectory '
                    'families captured after this freeze.',
        },
        'datasets': datasets_doc,
        'families': families,
        'groups': groups,
        'splits': splits,
        'labels': labels_doc,
        'references': {
            'data_inventory': inventory,
            'split_v1': split_v1,
            'training_plan': 'configs/perception/landmark_training_plan_v2.json',
        },
        'access_boundary': {
            'all_current_data_exposed': True,
            'annotators_may_view_test_frames': True,
            'test_content_must_not_drive_model_or_threshold_decisions': True,
            'hash_does_not_imply_sealed': True,
            'same_person_annotation_and_development': 'if the same executor '
                'annotates the final sealed pool and develops the model, that '
                'must be stated explicitly; the hash audit cannot prove '
                'blindness',
        },
        'raw_data_boundary': {
            'gitignored': 'outputs/ is ignored by .gitignore; raw images, '
                          'observations and run logs are not versioned',
            'freeze_role': 'the freeze records payload sha256 per frame and '
                           'input file hashes so the raw directory can be '
                           'identified or regenerated',
            'images_verified': 'scripts/verify_landmark_dataset.py verifies '
                               'PNG bytes against payload sha256 when present',
        },
        'notes': [
            'This is a dev split of already-exposed data, not a test result.',
            'PASS here means grouping/hash QA only; it is not model, board or '
            'navigation evidence.',
            'old landmark_labels_v1.json split (route_0 train vs route_1/'
            'reset_0/reset_1 test) splits one physical south-A family and is '
            'not an independent split.',
        ],
    }
    if profile != 'v1':
        v1_path = root / DEFAULT_FREEZE
        supersedes = None
        if v1_path.is_file():
            supersedes = {
                'path': DEFAULT_FREEZE,
                'canonical_sha256': freeze_sha256(load_json(v1_path)),
                'reason': 'conservative variant: the E static viewpoint '
                          'cluster is moved into train so val keeps only the '
                          'held-out north corridor family; v1 is retained as '
                          'history and must not be used for new training',
            }
        freeze['split_profile'] = {
            'name': profile,
            'description': PROFILE_DESCRIPTIONS[profile],
        }
        if profile in PROFILE_EVIDENCE:
            freeze['split_profile']['evidence'] = PROFILE_EVIDENCE[profile]
        freeze['supersedes'] = supersedes
        freeze['access_boundary']['final_pool'] = {
            'freeze_registers_exposed_data_only': True,
            'final_pool_labels_location': 'ignored external directory; the '
                'repository stores only the frame manifest and sha256 values',
            'same_executor_claim': 'process isolation + hash commitment only',
            'blindness_not_proven_by_hash': True,
        }
        freeze['notes'].append(
            'conservative v2: val keeps only the north corridor family; the '
            'E static viewpoint cluster is train data.')
    freeze['freeze_sha256'] = freeze_sha256(freeze)
    return freeze


def _provenance_entry(repo_root, relative):
    path = Path(repo_root) / relative
    return {
        'path': relative.replace('\\', '/'),
        'sha256': sha256_file(path) if path.is_file() else None,
        'exists': path.is_file(),
    }


def _condition_coverage(repo_root, loaded, families):
    source = Path(repo_root) / FINAL_POOL_CONDITION_SOURCE
    if not source.is_file():
        raise SystemExit('condition source missing: ' + FINAL_POOL_CONDITION_SOURCE)
    document = load_json(source)
    by_episode = {}
    for item in document:
        by_episode.setdefault(item.get('episode_id'), []).append(item)
    accepted_frames = {frame.frame_id for frame in loaded.frames
                       if frame.accepted}
    condition_frames = {item.get('frame_id') for item in document}
    if accepted_frames != condition_frames:
        raise SystemExit(
            'condition evidence does not match the independently recounted '
            'accepted frames: %d accepted vs %d condition rows'
            % (len(accepted_frames), len(condition_frames)))
    rows = []
    total_truncated = 0
    total_absent = 0
    total_green_clues = 0
    total_positive_small_green = 0
    all_bearings = []
    for spec in families:
        items = by_episode.get(
            spec.get('condition_episode_id') or spec['episode_id'], [])
        distances = [float(item['distance_to_tower_m']) for item in items]
        bearings = [float(item['bearing_relative_deg']) for item in items]
        truncated = sum(1 for item in items
                        if item.get('truncated_right') or item.get('truncated_left'))
        green_clues = sum(1 for item in items
                          if 0 < int(item.get('green_pixels') or 0) <= 3)
        green_pixels = [int(item.get('green_pixels') or 0) for item in items]
        total_truncated += truncated
        all_bearings.extend(bearings)
        negative = spec['family_id'] in ('lmf_similar_negative',
                                         'lmf_side_negative')
        if negative:
            total_absent += len(items)
            total_green_clues += green_clues
        else:
            total_positive_small_green += green_clues
        rows.append({
            'family_id': spec['family_id'],
            'case_id': spec['case_id'],
            'accepted_frames_recounted': len([frame for frame in loaded.frames
                                              if frame.episode_id == spec['episode_id']
                                              and frame.accepted]),
            'condition_rows': len(items),
            'distance_min_m': min(distances) if distances else None,
            'distance_max_m': max(distances) if distances else None,
            'bearing_min_deg': min(bearings) if bearings else None,
            'bearing_max_deg': max(bearings) if bearings else None,
            'truncated_frames': truncated,
            'green_pixel_min': min(green_pixels) if green_pixels else None,
            'green_pixel_max': max(green_pixels) if green_pixels else None,
            'small_green_frames_le3px': green_clues,
            'target_absent_family': negative,
        })
    return {
        'source': {
            'path': FINAL_POOL_CONDITION_SOURCE,
            'sha256': sha256_file(source),
            'nature': 'capture-derived camera pose / distance / bearing / '
                      'green-pixel geometry, independently aggregated here; '
                      'the frame set is cross-checked against the accepted '
                      'frames recounted from observations.jsonl',
        },
        'by_family': rows,
        'aggregate': {
            'accepted_frames': sum(row['accepted_frames_recounted']
                                   for row in rows),
            'distance_min_m': min(row['distance_min_m'] for row in rows
                                  if row['distance_min_m'] is not None),
            'distance_max_m': max(row['distance_max_m'] for row in rows
                                  if row['distance_max_m'] is not None),
            'truncated_frames': total_truncated,
            'target_absent_frames': total_absent,
            'similar_structure_verified_frames': 0,
            'small_green_false_clue_frames_le3px_negatives_only': total_green_clues,
            'small_green_frames_le3px_positive_families': total_positive_small_green,
            'bearing_min_deg': min(all_bearings),
            'bearing_max_deg': max(all_bearings),
            'occlusion_frames': 0,
        },
        'condition_matrix': [
            {'condition': 'normal / target in view',
             'families': ['lmf_sweep'],
             'accepted_frames': next((row['accepted_frames_recounted']
                                      for row in rows
                                      if row['family_id'] == 'lmf_sweep'), 0)},
            {'condition': 'scale / distance',
             'families': ['lmf_near', 'lmf_backoff', 'lmf_sweep'],
             'distance_range_m': [min(row['distance_min_m'] for row in rows),
                                  max(row['distance_max_m'] for row in rows)]},
            {'condition': 'yaw / lateral',
             'families': ['lmf_sweep', 'lmf_edge'],
             'bearing_range_deg': [min(row['bearing_min_deg'] for row in rows
                                       if row['family_id'] in
                                       ('lmf_sweep', 'lmf_edge')),
                                   max(row['bearing_max_deg'] for row in rows
                                       if row['family_id'] in
                                       ('lmf_sweep', 'lmf_edge'))]},
            {'condition': 'truncation (right frame edge)',
             'families': ['lmf_edge'],
             'accepted_frames': next((row['accepted_frames_recounted']
                                      for row in rows
                                      if row['family_id'] == 'lmf_edge'), 0),
             'truncated_frames': total_truncated},
            {'condition': 'target absent (behind camera / outside FOV)',
             'families': ['lmf_similar_negative', 'lmf_side_negative'],
             'accepted_frames': total_absent},
            {'condition': 'similar structure hard negative (HN1)',
             'families': ['lmf_similar_negative'],
             'verified_frames': 0,
             'status': 'MISSING: the negative is target-absent with <=3 px '
                       'green false clues; no verified similar-structure label '
                       'exists, so it must not be reported as HN1-covered'},
            {'condition': 'occlusion by scene structure',
             'families': [],
             'verified_frames': 0,
             'status': 'NOT CONSTRUCTED'},
        ],
        'far_range_note': 'around 7-8.4 m the green light is 0-1 px; T6 '
                          'should allow UNAVAILABLE reference labels there',
    }


def _sampling_block(loaded):
    total = len(loaded.frames)
    accepted = sum(1 for frame in loaded.frames if frame.accepted)
    required = accepted > 400
    selected = accepted if not required else None
    return {
        'required': required,
        'rule_id': 'all_included_N1' if not required else 'fixed_step_k',
        'k': None if not required else -(-accepted // 400),
        'original_rgb_frames': total,
        'original_accepted_frames': accepted,
        'selected_accepted_frames': selected,
        'rule': 'N=1: all accepted frames are included because the '
                'independently recounted accepted total is <= 400; the 18 '
                'WARMUP frames stay in the manifest with accepted=false and '
                'are excluded from training/evaluation' if not required
                else 'fixed sequence step k = ceil(accepted/400); take every '
                     'k-th accepted frame per family in sequence order',
        'fallback_rule_if_gt_400': 'per family, sort accepted frames by '
                                   'sequence, k = ceil(total_accepted/400), '
                                   'take every k-th starting from the first '
                                   'accepted frame; sequence order only, no '
                                   'model score and no random choice',
        'no_score_selection': True,
        'lead_expectation_note': 'the hand-off expected the raw accepted pool '
                                 'to exceed 200-400 and require sampling; the '
                                 'independent recount is 279 accepted (297 RGB '
                                 'frames including 18 WARMUP), so the fixed '
                                 'rule N=1 keeps every accepted frame and no '
                                 'sampling is triggered',
        'recount_note': 'accepted is recounted from observations.jsonl as '
                        'gate.accepted AND validity.valid AND phase==RUN; the '
                        'RGB frame total includes 3 WARMUP frames per episode',
    }


def _overlap_against_freezes(repo_root, frames, family_ids, group_ids,
                             freeze_paths):
    root = Path(repo_root)
    seal_shas = {item['sha256'] for item in frames}
    result = {
        'freeze_paths': list(freeze_paths),
        'freezes': [],
        'frame_sha_overlap': [],
        'frame_sha_overlap_count': 0,
        'family_overlap': [],
        'group_overlap': [],
        'dataset_root_overlap': [],
    }
    for relative in freeze_paths:
        path = root / relative
        if not path.is_file():
            continue
        document = load_json(path)
        shas = set()
        families = set()
        groups = set()
        for group in document.get('groups') or []:
            groups.add(group.get('group_id'))
            families.add(group.get('family_id'))
            for frame in group.get('frames') or []:
                if frame.get('sha256'):
                    shas.add(frame['sha256'])
        result['freezes'].append({
            'path': relative,
            'canonical_sha256': freeze_sha256(document),
            'frames': len(shas),
            'families': len(families),
            'groups': len(groups),
        })
        overlap = sorted(seal_shas & shas)
        result['frame_sha_overlap'].extend(overlap)
        result['family_overlap'].extend(sorted(set(family_ids) & families))
        result['group_overlap'].extend(sorted(set(group_ids) & groups))
        result['dataset_root_overlap'].extend(
            sorted({FINAL_POOL_SENSOR} & set((document.get('datasets') or {}).keys())))
    result['frame_sha_overlap_count'] = len(result['frame_sha_overlap'])
    result['family_overlap'] = sorted(set(result['family_overlap']))
    result['group_overlap'] = sorted(set(result['group_overlap']))
    result['dataset_root_overlap'] = sorted(set(result['dataset_root_overlap']))
    return result


def build_final_pool(repo_root):
    root = Path(repo_root)
    dataset_root = 'outputs/sensor_shadow/' + FINAL_POOL_SENSOR
    observations = dataset_root + '/observations.jsonl'
    try:
        loaded = load_dataset_frames(root, FINAL_POOL_SENSOR, dataset_root,
                                     observations, verify_images=True)
    except DatasetInputError as error:
        raise SystemExit('final pool input error: ' + str(error))
    manifest = read_manifest(root, FINAL_POOL_RUN) or {}
    sensor = manifest.get('sensor_shadow') or {}
    render_version = 'sensor_config_' + str(
        sensor.get('config_sha256') or 'unknown')[:12]
    frames_by_episode = {}
    for frame in loaded.frames:
        frames_by_episode.setdefault(frame.episode_id, []).append(frame)
    groups = []
    families = []
    for spec in FINAL_POOL_FAMILIES:
        frames = sorted(frames_by_episode.get(spec['episode_id'], []),
                        key=lambda item: (item.generation, item.sequence))
        if not frames:
            raise SystemExit('no frames for episode ' + spec['episode_id'])
        accepted = sum(1 for frame in frames if frame.accepted)
        groups.append({
            'group_id': spec['group_id'],
            'family_id': spec['family_id'],
            'dataset': FINAL_POOL_SENSOR,
            'session': FINAL_POOL_RUN,
            'case_id': spec['case_id'],
            'render_version': render_version,
            'episodes': [spec['episode_id']],
            'split': 'test',
            'sealed': True,
            'view_cluster': None,
            'route': spec['route'],
            'notes': spec['description'],
            'frame_count': len(frames),
            'accepted_frame_count': accepted,
            'frames': [{'frame_id': frame.frame_id, 'sha256': frame.sha256,
                        'accepted': frame.accepted} for frame in frames],
        })
        families.append({
            'family_id': spec['family_id'],
            'case_id': spec['case_id'],
            'description': spec['description'],
            'groups': [spec['group_id']],
        })
    splits = {'train': [], 'val': [], 'test': [group['group_id'] for group in groups],
              'excluded': []}
    datasets = {
        FINAL_POOL_SENSOR: {
            'root': dataset_root,
            'observations': observations,
            'observations_sha256': loaded.observations_sha256,
            'summary': dataset_root + '/summary.json',
            'summary_sha256': sha256_file(root / (dataset_root + '/summary.json'))
            if (root / (dataset_root + '/summary.json')).is_file() else None,
            'in_inventory': False,
            'role': 'final_pool_sealed',
            'empty_capture': False,
            'description': 'T1 final candidate pool shadow sensor run',
            'rgb_frames': len(loaded.frames),
            'accepted_rgb_frames': sum(1 for frame in loaded.frames
                                       if frame.accepted),
            'images_present': loaded.images_present,
            'images_missing': loaded.images_missing,
        },
    }
    provenance_files = [_provenance_entry(root, relative)
                        for relative in FINAL_POOL_PROVENANCE_FILES]
    t1_entry = _provenance_entry(root, FINAL_POOL_T1_REPORT)
    condition = _condition_coverage(root, loaded, FINAL_POOL_FAMILIES)
    sampling = _sampling_block(loaded)
    run_manifest_entry = _provenance_entry(
        root, 'outputs/sensor_shadow/' + FINAL_POOL_RUN + '/manifest.json')
    provenance = {
        'pool_run': FINAL_POOL_RUN,
        'sensor_run': FINAL_POOL_SENSOR,
        'case_manifest': FINAL_POOL_CASES,
        'case_manifest_sha256': sha256_file(root / FINAL_POOL_CASES),
        'code_commit': manifest.get('code_commit'),
        'code_commit_source': 'run manifest',
        'expected_head': '43fee3e02de57840e54297e8595924e2f213d722',
        'branch': 'feat/v2.2-simulation-perception',
        'gui_mode': manifest.get('gui_mode'),
        'renderer': manifest.get('renderer'),
        'gpu_driver': manifest.get('gpu_driver'),
        'map_asset_id': manifest.get('map_asset_id'),
        'started_at': manifest.get('started_at'),
        'run_manifest_sha256': run_manifest_entry['sha256'],
        'completion': manifest.get('completion'),
        'sensor_config': sensor.get('config'),
        'sensor_config_sha256_recorded': sensor.get('config_sha256'),
        'gui_evidence': [
            'outputs/sensor_shadow/lm_final_candidate_20261104/_evidence/desktop_full_run.png',
            'outputs/sensor_shadow/lm_final_candidate_20261104/_evidence/desktop_smoke_run_1815.png',
            'outputs/sensor_shadow/lm_final_candidate_20261104/_evidence/window_check/desktop_full_run_view.png',
            'outputs/sensor_shadow/lm_final_candidate_20261104/_evidence/window_check/desktop_smoke_run_1815_view.png',
        ],
        't1_report': {
            'path': FINAL_POOL_T1_REPORT,
            'sha256': t1_entry['sha256'],
            'status': 'PRESENT' if t1_entry['exists'] else 'PENDING',
            'note': 'the Lead hand-off said the T1 report was not yet on disk; '
                    'it is present at seal time and its hash is recorded here',
        },
        'files': provenance_files,
        'hash_source': 'sha256 of file bytes; raw files stay in ignored '
                       'outputs/ except the capture report copies',
    }
    dev_path = root / FINAL_POOL_DEV_FREEZE
    dev_reference = None
    if dev_path.is_file():
        dev_document = load_json(dev_path)
        dev_reference = {
            'path': FINAL_POOL_DEV_FREEZE,
            'canonical_sha256': freeze_sha256(dev_document),
            'role': 'dev train/val split v2; family and frame-sha disjointness '
                    'is checked against this freeze',
        }
    cross_checks = _overlap_against_freezes(
        root,
        [{'sha256': frame.sha256} for frame in loaded.frames],
        [family['family_id'] for family in families],
        [group['group_id'] for group in groups],
        [FINAL_POOL_DEV_FREEZE])
    overlap_path = (root / 'outputs/sensor_shadow' / FINAL_POOL_RUN /
                    '_evidence' / 'overlap_check.json')
    start_pose_proximity = []
    identical_waypoint_families = 0
    if overlap_path.is_file():
        overlap_doc = load_json(overlap_path)
        by_case = {item.get('case_id'): item
                   for item in overlap_doc.get('new_cases') or []}
        for spec in FINAL_POOL_FAMILIES:
            item = by_case.get(spec['case_id']) or {}
            nearest = item.get('nearest_existing_case') or {}
            identical = item.get('identical_waypoint_sequence_with_existing') or []
            if identical:
                identical_waypoint_families += 1
            start_pose_proximity.append({
                'family_id': spec['family_id'],
                'case_id': spec['case_id'],
                'nearest_existing_case': nearest.get('case_id'),
                'nearest_existing_run': nearest.get('run'),
                'start_position_distance_m': nearest.get('distance_m'),
                'yaw_difference_rad': nearest.get('yaw_difference_rad'),
                'identical_waypoint_sequence_with_existing': identical,
            })
    family_independence = {
        'new_trajectory_families': len(groups),
        'minimum_required_new_families': 3,
        'family_requirement_met': len(groups) >= 3,
        'rgb_frames': len(loaded.frames),
        'accepted_frames': sum(1 for frame in loaded.frames if frame.accepted),
        'frame_budget_200_400_met': 200 <= sum(
            1 for frame in loaded.frames if frame.accepted) <= 400,
        'identical_waypoint_sequences_with_existing_cases':
            identical_waypoint_families,
        'start_pose_proximity': start_pose_proximity,
        'frame_sha_overlap_with_dev_freeze': cross_checks['frame_sha_overlap_count'],
        'note': 'start-pose proximity is NOT trajectory identity; all families '
                'use new E-area / MID-field waypoint sequences, not the south '
                'or north corridors. The closest pairs are lmf_edge vs '
                'pilot_east_center (0.30 m, yaw differs 0.60 rad) and '
                'lmf_similar_negative vs pilot_east_away (0.54 m, same yaw). '
                'T6/T5 must report this adjacency; byte sha differs and the '
                'closest image pair still differs by >=7.7/255 mean abs.',
    }
    pool_adequacy = {
        'new_families': len(groups),
        'families_ge_3': len(groups) >= 3,
        'accepted_frames': sum(1 for frame in loaded.frames if frame.accepted),
        'accepted_in_200_400': 200 <= sum(
            1 for frame in loaded.frames if frame.accepted) <= 400,
        'condition_matrix_source': FINAL_POOL_CONDITION_SOURCE,
        'missing_conditions': [
            'HN1 verified similar-structure hard negative',
            'scene-structure occlusion',
        ],
        'note': 'six new families and 279 accepted frames satisfy the T5 '
                'fresh-family and 200-400 budget; condition coverage is '
                'partial (no HN1, no constructed occlusion).',
    }
    seal = {
        'schema_version': FREEZE_SCHEMA,
        'grouping_protocol': GROUPING_PROTOCOL,
        'freeze_id': 'landmark_final_pool_seal_v1',
        'pool_kind': 'FINAL_SEALED_TEST',
        'status': 'SEALED_TEST_POOL_FROZEN_LABELS_PENDING',
        'generated_at': datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        'generated_by': 'scripts/verify_landmark_dataset.py '
                        '--build-final-pool',
        'scope': 'T1 final candidate pool sealed as test only; no training, no '
                 'Isaac run, no model evaluation in this step',
        'hash_algorithm': {
            'name': 'sha256',
            'canonicalisation': 'json_sort_keys_utf8_compact_v1',
            'excluded_fields': ['generated_at', 'freeze_sha256'],
        },
        'sampling': sampling,
        'condition_coverage': condition,
        'family_independence': family_independence,
        'pool_adequacy': pool_adequacy,
        'provenance': provenance,
        'dev_freeze_reference': dev_reference,
        'cross_checks': cross_checks,
        'annotation_status': {
            'status': 'PENDING',
            'full_semantic_labels': 'NOT_PRODUCED',
            'planned_pilot_annotation': {
                'path': FINAL_POOL_ANNOTATION_PLAN,
                'sha256': None,
                'directory_gitignored': True,
                'produced_by': 'T6 pilot annotation, not this freeze',
            },
            'annotation_spec': 'configs/perception/landmark_annotation_spec_v1.json',
            'boundary': 'when the same executor annotates and develops, only '
                        'process isolation + hash commitment can be claimed; '
                        'blindness or statistical independence cannot be '
                        'proven by a hash',
            'labels_git_status': 'not in git; raw labels stay in ignored '
                                 'outputs/ and only path + hash are recorded',
        },
        'datasets': datasets,
        'families': families,
        'groups': groups,
        'splits': splits,
        'sealed': {
            'present': True,
            'groups': [group['group_id'] for group in groups],
            'note': 'all six new trajectory families are sealed test-only; a '
                    'hash plus process record is not third-party independent '
                    'sealing',
        },
        'labels': {},
        'access_boundary': {
            'all_current_data_exposed': False,
            'sealed_test_only': True,
            'test_content_must_not_drive_model_or_threshold_decisions': True,
            'hash_does_not_imply_sealed': True,
            'same_person_annotation_and_development': 'only process isolation '
                '+ hash commitment; blindness is not proven',
            'final_test_reported_once': True,
        },
        'raw_data_boundary': {
            'gitignored': 'outputs/ is ignored by .gitignore; the 297 raw PNGs '
                          'and observations stay outside git',
            'seal_role': 'the seal lists every frame id + payload sha256 so the '
                         'raw directory can be identified or re-verified',
            'images_verified': 'the builder and verifier recompute PNG bytes '
                               'against payload sha256',
            'labels': 'not in git; only the planned ignored path is recorded '
                      'until T6 produces them',
        },
        'notes': [
            'This is a sealed TEST pool of existing captured simulation data; '
            'PASS here is manifest/hash/grouping QA only.',
            'No model, board or navigation result exists yet.',
            'Only 41 accepted target-absent frames and no verified '
            'similar-structure (HN1) frame; A8 sample adequacy is INCOMPLETE.',
            'No scene-structure occlusion was constructed; only edge '
            'truncation and near out-of-frame views exist.',
        ],
    }
    seal['freeze_sha256'] = freeze_sha256(seal)
    return seal


def verify_final_pool(seal, repo_root, cross_run_freezes, *,
                      require_images=False, verify_images=True):
    report = validate_freeze(seal, repo_root, verify_input_hashes=True,
                             require_images=require_images,
                             verify_images=verify_images)
    root = Path(repo_root)
    groups = {group.get('group_id'): group
              for group in seal.get('groups') or []}
    splits = seal.get('splits') or {}
    test_groups = set(splits.get('test') or [])
    sealed_ids = {group_id for group_id, group in groups.items()
                  if group.get('sealed')}
    if seal.get('pool_kind') != 'FINAL_SEALED_TEST':
        report.add_error('SEAL_KIND',
                         'pool_kind must be FINAL_SEALED_TEST, found %r'
                         % seal.get('pool_kind'))
    if not (seal.get('sealed') or {}).get('present'):
        report.add_error('SEAL_NOT_PRESENT',
                         'sealed.present is not true for the final pool')
    if not test_groups:
        report.add_error('SEALED_TEST_EMPTY',
                         'no group is assigned to the test split')
    for group_id in sealed_ids:
        if group_id not in test_groups:
            report.add_error('SEALED_GROUP_NOT_IN_TEST',
                             'sealed group %s is not in splits.test'
                             % group_id)
    for split in ('train', 'val', 'excluded'):
        for group_id in splits.get(split) or []:
            if group_id in sealed_ids:
                report.add_error(
                    'SEALED_GROUP_IN_DEV' if split in ('train', 'val')
                    else 'SEALED_GROUP_NOT_IN_TEST',
                    'sealed group %s appears in split %s' % (group_id, split))
    for group_id in test_groups:
        if group_id not in sealed_ids:
            report.add_warning('TEST_GROUP_NOT_SEALED',
                               'test group %s is not marked sealed' % group_id)
    total = sum(len(group.get('frames') or []) for group in groups.values())
    accepted = sum(1 for group in groups.values()
                   for frame in group.get('frames') or []
                   if frame.get('accepted'))
    report.stats['final_pool'] = {
        'total_frames': total,
        'accepted_frames': accepted,
        'families': len(seal.get('families') or []),
        'groups': len(groups),
        'test_groups': len(test_groups),
        'sealed_groups': len(sealed_ids),
    }
    sampling = seal.get('sampling') or {}
    if not (200 <= accepted <= 400):
        report.add_error('POOL_FRAME_BUDGET',
                         'accepted final pool size %d is outside 200-400'
                         % accepted)
    if sampling.get('selected_accepted_frames') != accepted:
        report.add_error('SAMPLING_MISMATCH',
                         'sampling.selected_accepted_frames=%r does not match '
                         'recounted accepted=%d'
                         % (sampling.get('selected_accepted_frames'), accepted))
    if sampling.get('required') is False and sampling.get('k') is not None:
        report.add_error('SAMPLING_RULE_INCONSISTENT',
                         'sampling says no sampling but k is set')
    if sampling.get('required') is True and not sampling.get('k'):
        report.add_error('SAMPLING_RULE_INCONSISTENT',
                         'sampling says required sampling but k is missing')
    if report.stats.get('frame_total') != total:
        report.add_error('POOL_FRAME_COUNT_MISMATCH',
                         'validator reconciled %d frames, seal groups list %d'
                         % (report.stats.get('frame_total'), total))
    if report.stats.get('accepted_frame_total') != accepted:
        report.add_error('POOL_ACCEPTED_COUNT_MISMATCH',
                         'validator reconciled %d accepted frames, seal groups '
                         'list %d'
                         % (report.stats.get('accepted_frame_total'), accepted))
    provenance = seal.get('provenance') or {}
    for key in ('pool_run', 'sensor_run', 'code_commit', 'gpu_driver',
                'case_manifest_sha256', 't1_report', 'files'):
        if key not in provenance:
            report.add_error('PROVENANCE_FIELD_MISSING',
                             'provenance.%s is missing' % key)
    checked_files = 0
    for entry in provenance.get('files') or []:
        relative = entry.get('path')
        expected = entry.get('sha256')
        if not relative:
            report.add_error('PROVENANCE_ENTRY_MALFORMED',
                             'provenance file entry without path')
            continue
        path = root / relative
        checked_files += 1
        if not path.is_file():
            report.add_error('PROVENANCE_FILE_MISSING',
                             'provenance file missing: %s' % relative)
        elif expected is None:
            report.add_error('PROVENANCE_SHA_MISSING',
                             'provenance file has no sha256: %s' % relative)
        elif sha256_file(path) != expected:
            report.add_error('PROVENANCE_SHA_MISMATCH',
                             'provenance file hash changed: %s' % relative)
    report.stats['provenance_files_checked'] = checked_files
    t1_report = provenance.get('t1_report') or {}
    if t1_report.get('status') != 'PRESENT':
        report.add_warning('T1_REPORT_PENDING',
                           'T1 capture report is not recorded as PRESENT')
    elif t1_report.get('sha256'):
        path = root / (t1_report.get('path') or '')
        if path.is_file() and sha256_file(path) != t1_report['sha256']:
            report.add_error('T1_REPORT_SHA_MISMATCH',
                             'T1 capture report hash changed')
    annotation = seal.get('annotation_status') or {}
    if annotation.get('status') != 'PENDING':
        report.add_warning('ANNOTATION_STATUS',
                           'expected full labels PENDING, found %r'
                           % annotation.get('status'))
    if annotation.get('full_semantic_labels') != 'NOT_PRODUCED':
        report.add_warning('ANNOTATION_STATUS',
                           'expected full_semantic_labels=NOT_PRODUCED')
    if not annotation.get('boundary'):
        report.add_error('ANNOTATION_BOUNDARY_MISSING',
                         'annotation boundary statement is missing')
    overlap = _overlap_against_freezes(
        root,
        [{'sha256': frame.get('sha256')}
         for group in groups.values()
         for frame in group.get('frames') or []],
        [family.get('family_id') for family in seal.get('families') or []],
        list(groups),
        cross_run_freezes)
    report.stats['cross_run'] = overlap
    if overlap['frame_sha_overlap_count']:
        report.add_error('CROSS_RUN_SHA_OVERLAP',
                         '%d final-pool frame sha256 already appear in the dev '
                         'freeze' % overlap['frame_sha_overlap_count'])
    if overlap['family_overlap']:
        report.add_error('FAMILY_OVERLAP',
                         'final pool family ids overlap dev freeze: %s'
                         % overlap['family_overlap'])
    if overlap['group_overlap']:
        report.add_error('GROUP_OVERLAP',
                         'final pool group ids overlap dev freeze: %s'
                         % overlap['group_overlap'])
    if overlap['dataset_root_overlap']:
        report.add_error('DATASET_ROOT_OVERLAP',
                         'final pool reuses a dev dataset root: %s'
                         % overlap['dataset_root_overlap'])
    return report


def admission_block(seal, report):
    condition = seal.get('condition_coverage') or {}
    aggregate = condition.get('aggregate') or {}
    reasons = []
    if (seal.get('annotation_status') or {}).get('status') != 'PRODUCED':
        reasons.append('full semantic labels are PENDING (T6)')
    if not aggregate.get('similar_structure_verified_frames'):
        reasons.append('HN1 verified similar-structure negative is missing')
    if not aggregate.get('occlusion_frames'):
        reasons.append('scene-structure occlusion was not constructed')
    if aggregate.get('target_absent_frames', 0) < 60:
        reasons.append('only %s accepted target-absent frames'
                       % aggregate.get('target_absent_frames'))
    return {
        'A3_sealed_final_pool': 'PASS' if not reasons else 'INCOMPLETE',
        'A8_sample_adequacy': 'INCOMPLETE',
        'reasons': reasons,
        'note': 'A3/A8 are admission-gate judgments; the seal integrity status '
                'is reported separately as PASS/INCOMPLETE in this evidence',
    }


def write_json(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + '\n',
                    encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument('--freeze', default=None,
                        help='freeze/seal path (default depends on the mode)')
    parser.add_argument('--output', default=None,
                        help='evidence JSON path (default depends on the mode)')
    parser.add_argument('--build', action='store_true',
                        help='scan raw observations and rewrite the dev freeze')
    parser.add_argument('--profile', choices=sorted(PROFILE_OVERRIDES),
                        default='v1',
                        help='named dev split profile used by --build')
    parser.add_argument('--build-final-pool', action='store_true',
                        help='build the T5 final sealed pool manifest')
    parser.add_argument('--final-pool', action='store_true',
                        help='verify a final sealed pool manifest')
    parser.add_argument('--cross-run-freezes', default=FINAL_POOL_DEV_FREEZE,
                        help='comma separated freeze paths checked for frame '
                             'sha / family / group overlap')
    parser.add_argument('--require-images', action='store_true',
                        help='fail when a raw PNG referenced by a frame is missing')
    parser.add_argument('--skip-image-bytes', action='store_true',
                        help='skip hashing raw PNG bytes')
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    final_pool_mode = args.final_pool or args.build_final_pool
    freeze_relative = args.freeze or (
        DEFAULT_FINAL_POOL_FREEZE if final_pool_mode else DEFAULT_FREEZE)
    output_relative = args.output or (
        DEFAULT_FINAL_POOL_OUTPUT if final_pool_mode else DEFAULT_OUTPUT)
    freeze_path = (repo_root / freeze_relative) if not Path(
        freeze_relative).is_absolute() else Path(freeze_relative)
    output_path = (repo_root / output_relative) if not Path(
        output_relative).is_absolute() else Path(output_relative)

    if args.build_final_pool:
        freeze = build_final_pool(repo_root)
        write_json(freeze_path, freeze)
    elif args.build:
        freeze = build_freeze(repo_root, args.profile)
        write_json(freeze_path, freeze)
    else:
        if not freeze_path.is_file():
            raise SystemExit('freeze file missing: %s' % freeze_path)
        freeze = load_json(freeze_path)

    cross_run_freezes = [item.strip() for item in
                         (args.cross_run_freezes or '').split(',')
                         if item.strip()]
    if final_pool_mode:
        report = verify_final_pool(
            freeze, repo_root, cross_run_freezes,
            require_images=args.require_images,
            verify_images=not args.skip_image_bytes)
    else:
        report = validate_freeze(
            freeze, repo_root,
            verify_input_hashes=True,
            require_images=args.require_images,
            verify_images=not args.skip_image_bytes)
    evidence = {
        'schema_version': 'dsh.landmark_dataset_evidence.v1',
        'status': 'PASS' if report.ok else (
            'FAIL' if not final_pool_mode else 'INCOMPLETE'),
        'generated_at': datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        'mode': ('build+verify-final-pool' if args.build_final_pool else
                 'verify-final-pool' if args.final_pool else
                 'build+verify' if args.build else 'verify'),
        'split_profile': args.profile,
        'freeze': {
            'path': str(freeze_path.relative_to(repo_root)).replace('\\', '/')
            if freeze_path.is_relative_to(repo_root) else str(freeze_path),
            'file_sha256': sha256_file(freeze_path),
            'canonical_sha256': freeze_sha256(freeze),
            'schema_version': freeze.get('schema_version'),
            'grouping_protocol': freeze.get('grouping_protocol'),
            'generated_at': freeze.get('generated_at'),
            'status': freeze.get('status'),
            'pool_kind': freeze.get('pool_kind'),
            'freeze_id': freeze.get('freeze_id'),
        },
        'checks': {
            'errors': [issue.__dict__ for issue in report.errors],
            'warnings': [issue.__dict__ for issue in report.warnings],
        },
        'stats': report.stats,
        'limits': [
            'grouping/hash QA only; not a model, board or navigation result',
            'raw outputs are gitignored; the freeze records their hashes',
        ],
    }
    if final_pool_mode:
        condition = freeze.get('condition_coverage') or {}
        evidence['final_pool'] = {
            'sampling': freeze.get('sampling'),
            'condition_coverage_aggregate': condition.get('aggregate'),
            'annotation_status': (freeze.get('annotation_status') or {}).get('status'),
            'cross_checks': report.stats.get('cross_run'),
            'admission': admission_block(freeze, report),
        }
        evidence['limits'].append(
            'sealed test pool manifest/hash QA only; no full semantic labels '
            'yet (PENDING, T6) and no model evaluation')
    write_json(output_path, evidence)
    summary = {
        'status': evidence['status'],
        'freeze': evidence['freeze'],
        'frame_total': report.stats['frame_total'],
        'split_frame_counts': report.stats['split_frame_counts'],
        'errors': len(report.errors),
        'warnings': len(report.warnings),
        'evidence': str(output_path),
    }
    if final_pool_mode:
        summary['final_pool'] = evidence['final_pool']
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if report.ok else 1


if __name__ == '__main__':
    sys.exit(main())
