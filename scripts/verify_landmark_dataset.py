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
    FREEZE_SCHEMA, GROUPING_PROTOCOL, SPLITS, DatasetInputError, freeze_sha256,
    load_dataset_frames, parse_frame_id, sha256_bytes, validate_freeze)


DEFAULT_FREEZE = 'configs/perception/landmark_split_freeze_v1.json'
DEFAULT_FREEZE_V2 = 'configs/perception/landmark_split_freeze_v2.json'
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
    {'dataset': 'lm_dev_capture_20261104_sensor',
     'run': 'lm_dev_capture_20261104', 'role': 'dev_new_family',
     'in_inventory': False, 'empty_capture': False, 'introduced_in': 'v3',
     'description': 'T9 dev batch1: inner-north/inner-south corridors, '
                    'static high/low, target-out-of-view negative'},
    {'dataset': 'lm_dev_hn_capture_20261104_sensor',
     'run': 'lm_dev_hn_capture_20261104', 'role': 'dev_hard_negative',
     'in_inventory': False, 'empty_capture': False, 'introduced_in': 'v3',
     'description': 'T9 dev batch2: HN1 synthetic green-light confuser and '
                    'HN2 synthetic visual-only wall full occlusion'},
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
    'lm_dev_capture_20261104_sensor': {
        'lmf_dev_inner_north_0': 'g_lmf_dev_inner_north',
        'lmf_dev_inner_south_0': 'g_lmf_dev_inner_south',
        'lmf_dev_static_high_0': 'g_lmf_dev_static_high',
        'lmf_dev_static_low_0': 'g_lmf_dev_static_low',
        'lmf_dev_static_negative_0': 'g_lmf_dev_static_negative',
    },
    'lm_dev_hn_capture_20261104_sensor': {
        'lmf_dev_hn1_confuser_0': 'g_lmf_dev_hn1_confuser',
        'lmf_dev_hn2_occluder_0': 'g_lmf_dev_hn2_occluder',
    },
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
    # --- T9 dev new families (introduced in v3) ---
    {'group_id': 'g_lmf_dev_inner_south', 'family_id': 'fam_inner_south',
     'dataset': 'lm_dev_capture_20261104_sensor', 'split': 'train',
     'view_cluster': None, 'introduced_in': 'v3',
     'route': 'E -> inner-south out-and-back [9.4,-1.2,1] -> [8,-3,1.1] -> '
              '[3,-3,1.1] -> [7,-2.2,1] -> [9.2,-0.4,1]',
     'notes': 'new inner-south approach (y about -3.0), not the south '
              'perimeter corridor; target seen from the south side/far range'},
    {'group_id': 'g_lmf_dev_static_high', 'family_id': 'fam_static_high_far',
     'dataset': 'lm_dev_capture_20261104_sensor', 'split': 'train',
     'view_cluster': 'static_E_new_views', 'introduced_in': 'v3',
     'route': 'static-ish high/far E view z=1.65-1.75 at 3.7-4.3 m',
     'notes': 'new high/far static viewpoint, target slightly above optical '
              'axis'},
    {'group_id': 'g_lmf_dev_static_negative',
     'family_id': 'fam_static_negative_E',
     'dataset': 'lm_dev_capture_20261104_sensor', 'split': 'train',
     'view_cluster': 'static_E_new_views', 'introduced_in': 'v3',
     'route': 'static-ish E pose yaw=+2.2 rad, tower outside FOV',
     'notes': 'target-out-of-view negative pose; presence to be confirmed on '
              'images and labels'},
    {'group_id': 'g_lmf_dev_inner_north', 'family_id': 'fam_inner_north',
     'dataset': 'lm_dev_capture_20261104_sensor', 'split': 'val',
     'view_cluster': None, 'introduced_in': 'v3',
     'route': 'inner-north corridor W -> E at y about +3.0 (not the y=5.8 '
              'north perimeter corridor)',
     'notes': 'new north-side approach; val includes north-like route but a '
              'different corridor geometry'},
    {'group_id': 'g_lmf_dev_static_low', 'family_id': 'fam_static_low_oblique',
     'dataset': 'lm_dev_capture_20261104_sensor', 'split': 'val',
     'view_cluster': 'static_E_new_views', 'introduced_in': 'v3',
     'route': 'static-ish low oblique close E view (1.9-2.1 m) yaw +0.2 rad',
     'notes': 'new near/low oblique viewpoint; partial truncation expected'},
    {'group_id': 'g_lmf_dev_hn1_confuser', 'family_id': 'fam_HN1_confuser',
     'dataset': 'lm_dev_hn_capture_20261104_sensor', 'split': 'val',
     'view_cluster': None, 'introduced_in': 'v3',
     'route': 'yaw +pi/2 facing +Y; synthetic green-light confuser at '
              '(8.5,4.2) in view, central tower behind camera',
     'notes': 'HN1 hard negative via synthetic visual-only confuser injection '
              'hn1_confuser_v1; synthetic, not arena asset, no collision'},
    {'group_id': 'g_lmf_dev_hn2_occluder', 'family_id': 'fam_HN2_occluder',
     'dataset': 'lm_dev_hn_capture_20261104_sensor', 'split': 'val',
     'view_cluster': None, 'introduced_in': 'v3',
     'route': 'facing +X with synthetic visual-only wall between camera and '
              'central tower',
     'notes': 'HN2 full occlusion via synthetic visual-only wall injection '
              'hn2_occluder_v1; geometric metadata recorded in the case '
              'manifest'},
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
    # v3 = conservative dev split + T9 new dev families.  New groups carry
    # their own train/val assignment in GROUP_DEFS; legacy groups keep the
    # conservative assignment.
    'v3': {
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
    'v3': 'v2 conservative split plus T9 dev new families; val covers the '
          'north corridor, inner-north corridor, a new low static view and '
          'the HN1 confuser / HN2 occluder hard negatives',
}
PROFILE_FREEZE_IDS = {
    'v1': 'landmark_split_freeze_v1',
    'conservative': 'landmark_split_freeze_v2',
    'v3': 'landmark_split_freeze_v3',
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
    {'family_id': 'fam_inner_south', 'introduced_in': 'v3',
     'description': 'T9 inner-south out-and-back approach (y about -3.0)'},
    {'family_id': 'fam_static_high_far', 'introduced_in': 'v3',
     'description': 'T9 high/far static E viewpoint'},
    {'family_id': 'fam_static_negative_E', 'introduced_in': 'v3',
     'description': 'T9 target-out-of-view negative pose at E'},
    {'family_id': 'fam_inner_north', 'introduced_in': 'v3',
     'description': 'T9 inner-north corridor W -> E at y about +3.0'},
    {'family_id': 'fam_static_low_oblique', 'introduced_in': 'v3',
     'description': 'T9 low oblique close E viewpoint'},
    {'family_id': 'fam_HN1_confuser', 'introduced_in': 'v3',
     'description': 'T9 HN1 synthetic green-light confuser hard negative'},
    {'family_id': 'fam_HN2_occluder', 'introduced_in': 'v3',
     'description': 'T9 HN2 synthetic visual-only wall full occlusion'},
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


def build_datasets(repo_root, profile='v1'):
    root = Path(repo_root)
    datasets_doc = {}
    loaded_frames = {}
    for spec in DATASETS:
        if spec.get('introduced_in') and spec['introduced_in'] != profile:
            continue
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
        if (definition.get('introduced_in')
                and definition['introduced_in'] != profile):
            continue
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
        if (definition.get('introduced_in')
                and definition['introduced_in'] != profile):
            continue
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
    datasets_doc, loaded_frames = build_datasets(repo_root, profile)
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
        if (definition.get('introduced_in')
                and definition['introduced_in'] != profile):
            continue
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
        freeze['split_profile'] = {
            'name': profile,
            'description': PROFILE_DESCRIPTIONS[profile],
        }
        if profile in PROFILE_EVIDENCE:
            freeze['split_profile']['evidence'] = PROFILE_EVIDENCE[profile]
        if profile == 'v3':
            v2_path = root / DEFAULT_FREEZE_V2
            supersedes = None
            delta = {
                'base_path': DEFAULT_FREEZE_V2,
                'base_canonical_sha256': None,
                'new_groups': sorted(
                    {group['group_id'] for group in groups}
                    - {group['group_id']
                       for group in (load_json(v2_path).get('groups') or [])
                       if v2_path.is_file()}),
                'new_frames': None,
                'frame_total': sum(len(group.get('frames') or [])
                                   for group in groups),
                'split_frame_counts': {
                    split: sum(len(group.get('frames') or [])
                               for group in groups
                               if group.get('split') == split)
                    for split in SPLITS},
                'split_group_counts': {
                    split: sum(1 for group in groups
                               if group.get('split') == split)
                    for split in SPLITS},
                'note': 'v3 = conservative v2 split + T9 dev new families; '
                        'legacy v2 groups keep their frames and splits',
            }
            if v2_path.is_file():
                v2_document = load_json(v2_path)
                supersedes = {
                    'path': DEFAULT_FREEZE_V2,
                    'canonical_sha256': freeze_sha256(v2_document),
                    'reason': 'v3 adds the T9 dev new families on top of the '
                              'conservative v2 split; v2 remains the frozen '
                              'base, v1 stays history',
                }
                delta['base_canonical_sha256'] = freeze_sha256(v2_document)
                v2_frame_total = sum(len(group.get('frames') or [])
                                     for group in v2_document.get('groups') or [])
                delta['new_frames'] = delta['frame_total'] - v2_frame_total
            freeze['supersedes'] = supersedes
            freeze['delta_from_v2'] = delta
            annotation_lists = _annot2_alignment(root, groups)
            freeze['annotation_frame_lists'] = annotation_lists
            if annotation_lists['status'] != 'PASS':
                raise SystemExit(
                    'annot2 train/val frame lists are not consistent with the '
                    'v3 split: %d mismatches, %d unresolved'
                    % (len(annotation_lists['mismatches']),
                       len(annotation_lists['unresolved_frames'])))
            freeze['exposure_registry'] = {
                'path': 'configs/perception/landmark_exposure_registry_v1.json',
                'status': 'PRODUCED_SEPARATELY_WITH_ITS_OWN_VERIFY_EVIDENCE',
                'note': 'the registry records exposure state; it is built after '
                        'this freeze and therefore referenced without a hash '
                        'here to avoid a circular hash dependency',
            }
            freeze['notes'].append(
                'v3 adds T9 dev new families: val covers the north corridor, '
                'inner-north corridor, a new low static view and the HN1 '
                'confuser / HN2 occluder hard negatives.')
        else:
            v1_path = root / DEFAULT_FREEZE
            supersedes = None
            if v1_path.is_file():
                supersedes = {
                    'path': DEFAULT_FREEZE,
                    'canonical_sha256': freeze_sha256(load_json(v1_path)),
                    'reason': 'conservative variant: the E static viewpoint '
                              'cluster is moved into train so val keeps only '
                              'the held-out north corridor family; v1 is '
                              'retained as history and must not be used for '
                              'new training',
                }
            freeze['supersedes'] = supersedes
            freeze['access_boundary']['final_pool'] = {
                'freeze_registers_exposed_data_only': True,
                'final_pool_labels_location': 'ignored external directory; '
                    'the repository stores only the frame manifest and sha256 '
                    'values',
                'same_executor_claim': 'process isolation + hash commitment '
                    'only',
                'blindness_not_proven_by_hash': True,
            }
            freeze['notes'].append(
                'conservative v2: val keeps only the north corridor family; '
                'the E static viewpoint cluster is train data.')
    freeze['freeze_sha256'] = freeze_sha256(freeze)
    return freeze


def _annot2_alignment(repo_root, groups):
    """Check the annot2 dev train/val label lists against the v3 groups.

    The authoritative source is configs/perception/landmark_dev_label_lists_v1
    .json (explicit train/val frame lists + label hashes).  Fallback: the
    selection JSONs.  Frame ids must be resolved through the group, because
    ids like sensor_reset_0-... also exist in the excluded debug_all6 dataset.
    """
    root = Path(repo_root)
    group_info = {}
    for group in groups:
        group_info[group.get('group_id')] = {
            'split': group.get('split'),
            'family_id': group.get('family_id'),
            'episodes': set(group.get('episodes') or []),
            'frames': {frame.get('frame_id')
                       for frame in group.get('frames') or []},
        }

    def _resolve_group(group_id, frame_id):
        entry = group_info.get(group_id)
        if entry is not None and frame_id in entry['frames']:
            return group_id, entry
        parsed = parse_frame_id(frame_id)
        episode = parsed['episode_id'] if parsed else None
        if episode:
            candidates = [
                candidate for candidate, info in group_info.items()
                if episode in info['episodes']
                and frame_id in info['frames']]
            if len(candidates) == 1:
                return candidates[0], group_info[candidates[0]]
        return None, None
    result = {
        'config': None,
        'annotation_spec': None,
        'labels': {},
        'source_lists': [],
        'checked_frames': 0,
        'unresolved_frames': [],
        'mismatches': [],
        'hn_val_pending': True,
        'status': 'PASS',
    }
    config_relative = ('configs/perception/'
                       'landmark_dev_label_lists_v1.json')
    if (root / config_relative).is_file():
        document = load_json(root / config_relative)
        result['config'] = {
            'path': config_relative,
            'sha256': sha256_file(root / config_relative),
            'status': document.get('status'),
            'generated_at_local': document.get('generated_at_local'),
        }
        result['annotation_spec'] = document.get('annotation_spec')
        result['labels'] = document.get('labels') or {}
        val_labels = ((document.get('labels') or {}).get('val') or {})
        val_groups = (((val_labels.get('counts') or {}).get('by_group')) or {})
        result['hn_val_pending'] = not any(
            'hn' in str(group_id).lower() for group_id in val_groups)
        for split in ('train', 'val'):
            split_doc = (document.get('splits') or {}).get(split) or {}
            # some doc versions keep groups under splits.train.groups
            groups_doc = split_doc.get('groups') or []
            result['source_lists'].append({
                'split': split,
                'frames': split_doc.get('total_frames'),
                'groups': len(groups_doc),
                'label_sha256': ((document.get('labels') or {})
                                 .get(split) or {}).get('sha256'),
            })
            for group in groups_doc:
                declared_group_id = group.get('group_id')
                for frame_id in group.get('frames') or []:
                    group_id, entry = _resolve_group(declared_group_id,
                                                     frame_id)
                    if entry is None:
                        result['unresolved_frames'].append({
                            'frame_id': frame_id,
                            'group_id': declared_group_id,
                            'reason': 'FRAME_OR_GROUP_NOT_IN_V3',
                        })
                        continue
                    result['checked_frames'] += 1
                    if entry['split'] != split:
                        result['mismatches'].append({
                            'frame_id': frame_id,
                            'group_id': group_id,
                            'reason': 'SPLIT_MISMATCH',
                            'selection_split': split,
                            'v3_split': entry['split'],
                        })
        if (result['mismatches'] or result['unresolved_frames']):
            result['status'] = 'FAIL'
        result['note'] = ('the annot2 label-list config is the authoritative '
                          'train/val frame list; v3 must keep every listed '
                          'frame in the same split. When hn_val_pending is '
                          'true the second-batch HN val frames are not yet in '
                          'the lists, so v3 must not claim complete HN '
                          'annotation coverage.')
        return result
    # fallback: selection JSONs without label-list config
    sources = [
        ('train', 'outputs/perception/dev_annotations_20261104/'
                  'selection_train.json'),
        ('val', 'outputs/perception/dev_annotations_20261104/'
                'selection_val.json'),
    ]
    for split, relative in sources:
        path = root / relative
        if not path.is_file():
            continue
        document = load_json(path)
        frames = document.get('frames') or []
        result['source_lists'].append({
            'path': relative,
            'sha256': sha256_file(path),
            'split': split,
            'frames': len(frames),
            'rule_id': document.get('rule_id'),
        })
        for item in frames:
            frame_id = item.get('frame_id')
            cluster = str(item.get('cluster_id') or '')
            group_id = cluster.split('_c')[0] if '_c' in cluster else None
            resolved_group_id, entry = _resolve_group(group_id, frame_id)
            if entry is None:
                candidates = [candidate for candidate, info
                              in group_info.items()
                              if frame_id in info['frames']]
                result['unresolved_frames'].append({
                    'frame_id': frame_id,
                    'cluster_id': cluster,
                    'candidate_groups': candidates,
                })
                continue
            group_id = resolved_group_id
            result['checked_frames'] += 1
            if entry['split'] != split:
                result['mismatches'].append({
                    'frame_id': frame_id,
                    'group_id': group_id,
                    'reason': 'SPLIT_MISMATCH',
                    'selection_split': split,
                    'v3_split': entry['split'],
                })
    if result['mismatches'] or result['unresolved_frames']:
        result['status'] = 'FAIL'
    result['note'] = 'fallback selection lists used; label-list config missing'
    return result


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


# ---------------------------------------------------------------------------
# T12: near-duplicate / leakage audit and external product index
# ---------------------------------------------------------------------------
T12_AUDIT_OUTPUT = ('docs/reports/perception/dataset_freeze_20261104/'
                    'landmark_leakage_audit_20261104.json')
T12_INDEX_OUTPUT = ('docs/reports/perception/dataset_freeze_20261104/'
                    'landmark_external_index_20261104.json')
NEAR_DUP_DOWNSAMPLE = (16, 12)
NEAR_DUP_DOWNSAMPLE_THRESHOLD = 2.0   # mean abs diff on 0-255 grayscale
NEAR_DUP_FULL_MEAN_THRESHOLD = 3.0
NEAR_DUP_FULL_MAX_THRESHOLD = 40


def _frame_records(repo_root, freeze, set_name):
    records = []
    datasets = freeze.get('datasets') or {}
    for group in freeze.get('groups') or []:
        dataset_name = group.get('dataset')
        dataset_root = (datasets.get(dataset_name) or {}).get('root') or (
            'outputs/sensor_shadow/' + str(dataset_name))
        for frame in group.get('frames') or []:
            parsed = parse_frame_id(frame.get('frame_id')) or {}
            records.append({
                'set': set_name,
                'split': group.get('split'),
                'group_id': group.get('group_id'),
                'family_id': group.get('family_id'),
                'dataset': dataset_name,
                'frame_id': frame.get('frame_id'),
                'sha256': frame.get('sha256'),
                'accepted': frame.get('accepted'),
                'episode_id': parsed.get('episode_id'),
                'sequence': parsed.get('sequence'),
                'ref': dataset_root + '/images/' + str(frame.get('frame_id')),
            })
    return records


def _image_signatures(repo_root, records):
    try:
        from PIL import Image
        import numpy as np
    except Exception:  # pragma: no cover - optional dependency
        return None, records, {'available': False}
    root = Path(repo_root)
    signatures = []
    kept = []
    missing = 0
    unreadable = 0
    for record in records:
        path = root / record['ref']
        if not path.is_file():
            missing += 1
            continue
        try:
            with Image.open(path) as image:
                signature = np.asarray(
                    image.convert('L').resize(NEAR_DUP_DOWNSAMPLE),
                    dtype=np.float32).reshape(-1)
        except Exception:
            unreadable += 1
            continue
        signatures.append(signature)
        kept.append(record)
    array = np.asarray(signatures) if signatures else None
    return array, kept, {'available': True, 'missing': missing,
                         'unreadable': unreadable}


def _scan_cross_signatures(left, right, threshold):
    candidates = []
    if left is None or right is None or not len(left) or not len(right):
        return candidates
    import numpy as np
    for start in range(0, len(left), 128):
        block = left[start:start + 128]
        distances = np.abs(block[:, None, :] - right[None, :, :]).mean(axis=2)
        for row, column in np.argwhere(distances <= threshold):
            candidates.append((start + int(row), int(column),
                               float(distances[row, column])))
    return candidates


def _full_resolution_diff(repo_root, first_ref, second_ref):
    try:
        from PIL import Image
        import numpy as np
    except Exception:  # pragma: no cover
        return None
    first = Path(repo_root) / first_ref
    second = Path(repo_root) / second_ref
    with Image.open(first) as image_a, Image.open(second) as image_b:
        if image_a.size != image_b.size:
            return None
        array_a = np.asarray(image_a.convert('RGB'), dtype=np.int16)
        array_b = np.asarray(image_b.convert('RGB'), dtype=np.int16)
    difference = np.abs(array_a - array_b)
    return {
        'mean_abs': float(difference.mean()),
        'max': int(difference.max()),
        'p99': float(np.percentile(difference, 99)),
    }


def _structural_audit(freeze_path_docs):
    try:
        from boom_birds.evaluation.landmark_dataset import audit_split_leakage
    except Exception:  # pragma: no cover
        return {}
    return {path: audit_split_leakage(document)
            for path, document in freeze_path_docs.items()}


def run_near_duplicate_audit(repo_root, freeze_paths, seal_path):
    root = Path(repo_root)
    freeze_docs = {}
    records = []
    for relative in freeze_paths:
        path = root / relative
        if not path.is_file():
            raise SystemExit('audit freeze missing: %s' % relative)
        document = load_json(path)
        freeze_docs[relative] = document
        records.extend(_frame_records(root, document, 'dev'))
    if seal_path:
        seal_file = root / seal_path
        if not seal_file.is_file():
            raise SystemExit('audit seal missing: %s' % seal_path)
        seal_document = load_json(seal_file)
        records.extend(_frame_records(root, seal_document, 'exploratory'))
    sets = {}
    for record in records:
        key = (record['set'], record['split'])
        sets.setdefault(key, []).append(record)
    train_val_records = [record for record in records
                         if record['set'] == 'dev']
    exploratory_records = [record for record in records
                           if record['set'] == 'exploratory']
    # sha-level cross-set overlap
    sha_train = {record['sha256'] for record in train_val_records
                 if record['split'] == 'train'}
    sha_val = {record['sha256'] for record in train_val_records
               if record['split'] == 'val'}
    sha_exploratory = {record['sha256'] for record in exploratory_records}
    sha_cross = {
        'train_val': len(sha_train & sha_val),
        'exploratory_dev': len(sha_exploratory & (sha_train | sha_val)),
    }
    # pixel-level near duplicates between sets
    near_duplicate_pairs = []
    scan_meta = {}
    left_array, left_records, left_meta = _image_signatures(
        root, [record for record in train_val_records
               if record['split'] == 'train'])
    right_array, right_records, right_meta = _image_signatures(
        root, [record for record in train_val_records
               if record['split'] == 'val'])
    scan_meta['train'] = left_meta
    scan_meta['val'] = right_meta
    for index_left, index_right, distance in _scan_cross_signatures(
            left_array, right_array, NEAR_DUP_DOWNSAMPLE_THRESHOLD):
        record_left = left_records[index_left]
        record_right = right_records[index_right]
        full = _full_resolution_diff(root, record_left['ref'],
                                     record_right['ref'])
        pair = {
            'set_pair': 'train_vs_val',
            'left': {'frame_id': record_left['frame_id'],
                     'group_id': record_left['group_id']},
            'right': {'frame_id': record_right['frame_id'],
                      'group_id': record_right['group_id']},
            'downsample_mean_abs': round(distance, 4),
            'full_resolution': full,
        }
        if full and full['mean_abs'] <= NEAR_DUP_FULL_MEAN_THRESHOLD \
                and full['max'] <= NEAR_DUP_FULL_MAX_THRESHOLD:
            pair['near_duplicate'] = True
            near_duplicate_pairs.append(pair)
    dev_records = left_records + right_records
    if left_array is not None and right_array is not None:
        import numpy as np
        dev_array = np.concatenate([left_array, right_array], axis=0)
    else:
        dev_array = None
    if exploratory_records:
        exp_array, exp_records, exp_meta = _image_signatures(
            root, exploratory_records)
        scan_meta['exploratory'] = exp_meta
        for index_dev, index_exp, distance in _scan_cross_signatures(
                dev_array, exp_array, NEAR_DUP_DOWNSAMPLE_THRESHOLD):
            record_dev = dev_records[index_dev]
            record_exp = exp_records[index_exp]
            full = _full_resolution_diff(root, record_dev['ref'],
                                         record_exp['ref'])
            pair = {
                'set_pair': 'dev_vs_exploratory',
                'left': {'frame_id': record_dev['frame_id'],
                         'group_id': record_dev['group_id'],
                         'split': record_dev['split']},
                'right': {'frame_id': record_exp['frame_id'],
                          'group_id': record_exp['group_id']},
                'downsample_mean_abs': round(distance, 4),
                'full_resolution': full,
            }
            if full and full['mean_abs'] <= NEAR_DUP_FULL_MEAN_THRESHOLD \
                    and full['max'] <= NEAR_DUP_FULL_MAX_THRESHOLD:
                pair['near_duplicate'] = True
                near_duplicate_pairs.append(pair)
    # same-trajectory adjacent frames: expected similarity, neighbour check
    episodes = {}
    for record in records:
        episodes.setdefault((record['dataset'], record['episode_id']),
                            []).append(record)
    same_trajectory_neighbours = 0
    same_trajectory_cross_split = 0
    for key, items in episodes.items():
        items.sort(key=lambda item: item['sequence'])
        for previous, current in zip(items, items[1:]):
            if current['sequence'] != previous['sequence'] + 1:
                continue
            same_trajectory_neighbours += 1
            if previous['split'] != current['split']:
                same_trajectory_cross_split += 1
    structural = _structural_audit(freeze_docs)
    leakage_pairs = [pair for pair in near_duplicate_pairs
                     if pair['set_pair'] == 'train_vs_val']
    contamination_pairs = [pair for pair in near_duplicate_pairs
                           if pair['set_pair'] == 'dev_vs_exploratory']
    status = 'PASS' if (not leakage_pairs and not contamination_pairs
                        and sha_cross['train_val'] == 0
                        and sha_cross['exploratory_dev'] == 0
                        and same_trajectory_cross_split == 0) else 'FAIL'
    result = {
        'schema_version': 'dsh.landmark_near_duplicate_audit.v1',
        'generated_at': datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        'status': status,
        'freeze_paths': list(freeze_paths),
        'seal_path': seal_path,
        'set_sizes': {
            'train': len([record for record in train_val_records
                          if record['split'] == 'train']),
            'val': len([record for record in train_val_records
                        if record['split'] == 'val']),
            'exploratory': len(exploratory_records),
        },
        'thresholds': {
            'downsample': list(NEAR_DUP_DOWNSAMPLE),
            'downsample_mean_abs_le': NEAR_DUP_DOWNSAMPLE_THRESHOLD,
            'full_resolution_mean_abs_le': NEAR_DUP_FULL_MEAN_THRESHOLD,
            'full_resolution_max_le': NEAR_DUP_FULL_MAX_THRESHOLD,
            'units': '0-255 grayscale/RGB mean absolute difference',
            'method': '16x12 grayscale signature prefilters pairs; full-'
                      'resolution mean/max confirms near duplicates; sha256 '
                      'equality is checked separately',
        },
        'sha_cross_set': sha_cross,
        'near_duplicate_pairs': near_duplicate_pairs,
        'counts': {
            'near_duplicate_pairs': len(near_duplicate_pairs),
            'train_val_leakage_pairs': len(leakage_pairs),
            'dev_exploratory_contamination_pairs': len(contamination_pairs),
            'same_trajectory_adjacent_pairs': same_trajectory_neighbours,
            'same_trajectory_cross_split': same_trajectory_cross_split,
        },
        'scan_meta': scan_meta,
        'structural': structural,
        'limits': [
            'pixel near-duplicate audit is a heuristic; it does not replace '
            'a human visual review',
            'the exploratory pool is already downgraded; contamination pairs '
            'are reported as evidence, not as a failure of the dev split',
        ],
    }
    return result


def run_external_index(repo_root, freeze_paths, seal_path):
    try:
        from PIL import Image
    except Exception:  # pragma: no cover
        Image = None
    root = Path(repo_root)
    datasets = []
    totals = {'frames': 0, 'png_readable': 0, 'png_missing': 0,
              'png_sha_mismatch': 0, 'observations_sha_mismatch': 0}
    for relative in freeze_paths + ([seal_path] if seal_path else []):
        path = root / relative
        if not path.is_file():
            raise SystemExit('external index freeze missing: %s' % relative)
        document = load_json(path)
        for dataset_name, dataset in (document.get('datasets') or {}).items():
            dataset_root = dataset.get('root') or (
                'outputs/sensor_shadow/' + dataset_name)
            observations = dataset.get('observations') or (
                dataset_root + '/observations.jsonl')
            entry = {'freeze': relative, 'dataset': dataset_name,
                     'root': dataset_root, 'observations': observations}
            try:
                loaded = load_dataset_frames(
                    root, dataset_name, dataset_root, observations,
                    allow_empty=bool(dataset.get('empty_capture')),
                    verify_images=False)
            except DatasetInputError as error:
                entry['status'] = 'OBSERVATIONS_ERROR'
                entry['error'] = str(error)
                datasets.append(entry)
                continue
            entry['observations_sha256'] = loaded.observations_sha256
            expected = dataset.get('observations_sha256')
            entry['observations_sha256_match'] = (
                bool(expected) and expected == loaded.observations_sha256)
            if expected and expected != loaded.observations_sha256:
                totals['observations_sha_mismatch'] += 1
            frames = 0
            readable = 0
            missing = 0
            mismatch = 0
            unreadable = 0
            for frame in loaded.frames:
                frames += 1
                image_path = root / frame.ref
                if not image_path.is_file():
                    missing += 1
                    continue
                if sha256_file(image_path) != frame.sha256:
                    mismatch += 1
                    continue
                if Image is not None:
                    try:
                        with Image.open(image_path) as image:
                            image.verify()
                        with Image.open(image_path) as image:
                            width, height = image.size
                        if [width, height] != [320, 240]:
                            unreadable += 1
                            continue
                    except Exception:
                        unreadable += 1
                        continue
                readable += 1
            entry.update({
                'frames': frames,
                'png_readable_sha_match': readable,
                'png_missing': missing,
                'png_sha_mismatch': mismatch,
                'png_unreadable_or_wrong_size': unreadable,
                'empty_capture': not loaded.frames,
                'status': ('PASS' if not missing and not mismatch
                           and not unreadable else 'FAIL'),
            })
            totals['frames'] += frames
            totals['png_readable'] += readable
            totals['png_missing'] += missing
            totals['png_sha_mismatch'] += mismatch
            datasets.append(entry)
    status = 'PASS' if (totals['png_missing'] == 0
                        and totals['png_sha_mismatch'] == 0
                        and totals['observations_sha_mismatch'] == 0) else 'FAIL'
    return {
        'schema_version': 'dsh.landmark_external_product_index.v1',
        'generated_at': datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        'status': status,
        'freeze_paths': list(freeze_paths),
        'seal_path': seal_path,
        'datasets': datasets,
        'totals': totals,
        'backup_recommendation': [
            'keep the ignored outputs/ raw directories on at least one '
            'external disk or NAS; do not upload without user approval',
            'store the freeze/seal JSON plus this index with the raw package '
            'so a future re-verification can compare sha256 without git',
            'the repository only stores manifests/hashes/reports; raw PNG and '
            'observations stay outside git',
            'external backup is a recommendation, not a blocker for this '
            'data-format QA',
        ],
        'limits': [
            'readability check decodes PNG and checks 320x240 size; it does '
            'not validate image content',
            'observations hash is checked against the freeze record, and PNG '
            'bytes against the per-frame payload sha256',
        ],
    }


REGISTRY_PATH = 'configs/perception/landmark_exposure_registry_v1.json'
REGISTRY_OUTPUT = ('docs/reports/perception/dataset_freeze_20261104/'
                   'landmark_exposure_registry_verify_20261104.json')
REGISTRY_SOURCES = {
    'dev_v3': 'configs/perception/landmark_split_freeze_v3.json',
    'final_seal': 'configs/perception/landmark_final_pool_seal_v1.json',
}


EXPOSURE_SCHEMA = 'dsh.landmark_exposure_registry.v1'
EXPOSURE_PROTOCOL = 'landmark_exposure_group_level_v1'
EXPOSURE_STATUSES = ('exposed_development', 'annotation_calibration',
                     'exploratory_eval_candidate', 'untouched',
                     'excluded_debug', 'empty_capture')
PILOT_SELECTION = ('docs/reports/perception/annotation_verify_20261104/'
                   'pilot/selection.json')
PILOT_LABELS_MANIFEST = ('docs/reports/perception/annotation_verify_20261104/'
                         'pilot/labels_manifest.json')
EXPLORATORY_LABELS_MANIFEST = ('outputs/perception/'
                               'final_exploratory_20261104/'
                               'labels_manifest.json')
DEV_SELECTION_TRAIN = ('outputs/perception/dev_annotations_20261104/'
                       'selection_train.json')
DEV_SELECTION_VAL = ('outputs/perception/dev_annotations_20261104/'
                     'selection_val.json')
DEV_DEDUP_REPORT = ('outputs/perception/dev_annotations_20261104/'
                    'dedup_sampling_report.json')
V3_PATH = 'configs/perception/landmark_split_freeze_v3.json'
SEAL_PATH = 'configs/perception/landmark_final_pool_seal_v1.json'


def _json_if_exists(root, relative):
    path = Path(root) / relative
    if not path.is_file():
        return None
    return load_json(path), {
        'path': relative.replace('\\', '/'),
        'sha256': sha256_file(path),
    }


def build_exposure_registry(repo_root):
    root = Path(repo_root)
    v3 = load_json(root / V3_PATH)
    seal = load_json(root / SEAL_PATH)
    dev_groups = {group['group_id']: group for group in v3.get('groups') or []}
    final_groups = {group['group_id']: group
                    for group in seal.get('groups') or []}
    events = []
    # 1) historical development use of the pre-T9 dev data (templates,
    #    geometry diagnostics, independent landmark evaluations)
    history_evidence = []
    for relative in ('configs/perception/landmark_freeze_v4.json',
                     'configs/perception/independent_freeze_v3.json',
                     'configs/perception/geometry_test_freeze_v2.json'):
        entry = _json_if_exists(root, relative)
        if entry:
            history_evidence.append(entry[1])
    def _is_t9(dataset_name):
        return str(dataset_name or '').startswith(('lm_dev_capture',
                                                   'lm_dev_hn_capture'))

    history_groups = sorted(
        group['group_id'] for group in v3.get('groups') or []
        if not _is_t9(group.get('dataset')))
    events.append({
        'event_id': 'ev_dev_detection_history_20261103',
        'type': 'exposed_development',
        'date': '2026-11-03',
        'executor': 'agent (template / geometry / independent landmark dev)',
        'frames_touched': sum(len(dev_groups[group_id].get('frames') or [])
                              for group_id in history_groups),
        'groups': history_groups,
        'evidence_path': history_evidence[0]['path'] if history_evidence
        else None,
        'evidence_sha256': history_evidence[0]['sha256']
        if history_evidence else None,
        'evidence_extra': history_evidence[1:],
        'extent': 'all pre-T9 dev groups were used for development or '
                  'diagnostics; group-level exposure',
    })
    # 2) annot2 dev annotation selection (label-list config preferred)
    selection_entries = []
    annotated_dev_frames = []
    dev_label_lists = _json_if_exists(
        root, 'configs/perception/landmark_dev_label_lists_v1.json')
    if dev_label_lists:
        document, reference = dev_label_lists
        selection_entries.append({
            'path': 'configs/perception/landmark_dev_label_lists_v1.json',
            'sha256': reference['sha256'],
            'status': document.get('status'),
            'annotation_spec': document.get('annotation_spec'),
            'labels': document.get('labels'),
        })
        for split in ('train', 'val'):
            split_doc = (document.get('splits') or {}).get(split) or {}
            for group in split_doc.get('groups') or []:
                for frame_id in group.get('frames') or []:
                    annotated_dev_frames.append({
                        'frame_id': frame_id,
                        'group_id': group.get('group_id'),
                        'split': split,
                    })
    else:
        for relative, split in ((DEV_SELECTION_TRAIN, 'train'),
                                (DEV_SELECTION_VAL, 'val')):
            entry = _json_if_exists(root, relative)
            if not entry:
                continue
            document, reference = entry
            selection_entries.append({
                'path': relative,
                'sha256': reference['sha256'],
                'split': split,
                'frames': document.get('total_frames'),
                'rule_id': document.get('rule_id'),
                'base_freeze': (document.get('freeze') or {}).get('path'),
            })
            annotated_dev_frames.extend(document.get('frames') or [])
    dedup_entry = _json_if_exists(root, DEV_DEDUP_REPORT)
    events.append({
        'event_id': 'ev_dev_dedup_annotation_selection_20261104',
        'type': 'annotation_calibration',
        'date': '2026-11-04',
        'executor': 'annot2 (agent proxy)',
        'frames_touched': len(annotated_dev_frames),
        'groups': sorted({group for group in
                          (frame.get('cluster_id', '').split('_c')[0]
                           for frame in annotated_dev_frames) if group}),
        'evidence_path': (selection_entries[0]['path']
                          if selection_entries else (DEV_DEDUP_REPORT
                                                    if dedup_entry else None)),
        'evidence_sha256': (selection_entries[0]['sha256']
                            if selection_entries else (
                                dedup_entry[1]['sha256']
                                if dedup_entry else None)),
        'evidence_extra': selection_entries,
        'extent': 'dedup representative frames selected from the v2 train/val '
                  'groups for dev annotation; no T9 frames were in the list '
                  'when the registry was built unless the lists were updated',
    })
    # 3) T9 dev capture (batch1 and batch2 are separate runs)
    t9_frames = 0
    t9_groups = sorted(group['group_id'] for group in v3.get('groups') or []
                       if _is_t9(group.get('dataset')))
    t9_datasets = sorted(
        name for name in (v3.get('datasets') or {})
        if _is_t9(name))
    t9_run_manifests = []
    for dataset_name in t9_datasets:
        dataset = v3['datasets'][dataset_name]
        run_dir = (dataset.get('run') or '').rstrip('/')
        manifest_relative = (run_dir + '/manifest.json') if run_dir else None
        if manifest_relative:
            entry = _json_if_exists(root, manifest_relative)
            if entry:
                t9_run_manifests.append({'path': manifest_relative,
                                         'sha256': entry[1]['sha256']})
        for group in v3.get('groups') or []:
            if group.get('dataset') == dataset_name:
                t9_frames += len(group.get('frames') or [])
    if t9_run_manifests:
        events.append({
            'event_id': 'ev_t9_dev_capture_20261104',
            'type': 'exposed_development',
            'date': '2026-11-04',
            'executor': 'capture (visible foreground Isaac GUI)',
            'frames_touched': t9_frames,
            'groups': t9_groups,
            'evidence_path': t9_run_manifests[0]['path'],
            'evidence_sha256': t9_run_manifests[0]['sha256'],
            'evidence_extra': t9_run_manifests[1:],
            'extent': 'T9 dev new families captured, condition metadata '
                      'inspected and used for the v3 split; HN1/HN2 use '
                      'synthetic visual-only injections',
        })
    # 3b) map-native green-lamp pillar MS1 falsifies identity uniqueness U1/U2
    native_entry = _json_if_exists(
        root, 'docs/reports/perception/capture_dev_20261104/'
              'map_native_structures.json')
    ms1_event_id = 'ev_map_native_ms1_identity_conflict_20261104'
    events.append({
        'event_id': ms1_event_id,
        'type': 'identity_conflict_evidence',
        'date': '2026-11-04',
        'executor': 'capture + datafreeze review (map probe + green cue)',
        'frames_touched': 0,
        'groups': ['g_lmf_dev_inner_north', 'g_lmf_dev_static_negative'],
        'evidence_path': ('docs/reports/perception/capture_dev_20261104/'
                          'map_native_structures.json')
        if native_entry else None,
        'evidence_sha256': native_entry[1]['sha256'] if native_entry else None,
        'extent': 'map-native (not injected) green-lamp pillar MS1 at about '
                  '(3.0,4.0, green lamp z~1.71) is visible from inner_north '
                  '(up to 55 green px) and from static_negative without green; '
                  'this falsifies U1/U2 (at most one tower-like instance / '
                  'central tower is the only green-light tower) for identity '
                  'claims. It is a different evidence class from the synthetic '
                  'HN1 confuser and must not be mixed with it.',
        'identity_impact': 'U1/U2 falsified; identity certification '
                           'INCOMPLETE',
    })
    # 4) final pool 34-frame pilot annotation
    pilot_frames = []
    pilot_entry = _json_if_exists(root, PILOT_SELECTION)
    pilot_manifest = _json_if_exists(root, PILOT_LABELS_MANIFEST)
    if pilot_entry:
        pilot_frames = pilot_entry[0].get('frames') or []
    events.append({
        'event_id': 'ev_final_pilot_annotation_34_20261104',
        'type': 'annotation_calibration',
        'date': '2026-11-04',
        'executor': 'annot (agent proxy)',
        'frames_touched': len(pilot_frames),
        'groups': sorted({frame.get('group_id') for frame in pilot_frames
                          if frame.get('group_id')}),
        'evidence_path': PILOT_LABELS_MANIFEST if pilot_manifest else None,
        'evidence_sha256': pilot_manifest[1]['sha256'] if pilot_manifest else None,
        'extent': '34/279 frames annotated across all 6 final families; the '
                  'whole 6-family pool is contaminated for sealed-final use',
    })
    # 5) full exploratory labels for the final pool
    exploratory_entry = _json_if_exists(root, EXPLORATORY_LABELS_MANIFEST)
    exploratory_manifest = exploratory_entry[0] if exploratory_entry else {}
    exploratory_counts = exploratory_manifest.get('counts') or {}
    events.append({
        'event_id': 'ev_final_exploratory_labels_279_20261104',
        'type': 'exploratory_eval_candidate',
        'date': '2026-11-04',
        'executor': 'annot (agent proxy, spec v2.1)',
        'frames_touched': exploratory_counts.get('frames', 0),
        'groups': sorted(final_groups),
        'evidence_path': EXPLORATORY_LABELS_MANIFEST
        if exploratory_entry else None,
        'evidence_sha256': exploratory_entry[1]['sha256']
        if exploratory_entry else None,
        'extent': 'full 279-frame exploratory labels; dataset_role='
                  'DEVELOPMENT_EXPLORATORY; 34 frames are annotation '
                  'calibration, 245 exploratory; no sealed final remains',
        'label_file': (exploratory_manifest.get('label_file') or {}),
        'dataset_role': exploratory_manifest.get('dataset_role'),
    })
    t9_event_ids = ['ev_t9_dev_capture_20261104']
    dev_event_ids = ['ev_dev_detection_history_20261103',
                     'ev_dev_dedup_annotation_selection_20261104']
    groups_doc = []
    for group_id, group in sorted(dev_groups.items()):
        is_t9 = _is_t9(group.get('dataset'))
        group_events = list(dev_event_ids)
        if is_t9 and t9_run_manifests:
            group_events = list(t9_event_ids)
        if group.get('family_id') in ('fam_inner_north',
                                      'fam_static_negative_E'):
            group_events = group_events + [ms1_event_id]
        groups_doc.append({
            'group_id': group_id,
            'source': 'dev_v3',
            'family_id': group.get('family_id'),
            'dataset': group.get('dataset'),
            'split': group.get('split'),
            'status': 'exposed_development',
            'exposure_events': group_events,
            'certification': 'EXPOSED',
            'contamination': {
                'group_level': True,
                'reason': 'development / annotation-selection exposure',
            },
        })
    for group_id, group in sorted(final_groups.items()):
        groups_doc.append({
            'group_id': group_id,
            'source': 'final_seal',
            'family_id': group.get('family_id'),
            'dataset': group.get('dataset'),
            'split': group.get('split'),
            'status': 'exploratory_eval_candidate',
            'exposure_events': ['ev_final_pilot_annotation_34_20261104',
                                'ev_final_exploratory_labels_279_20261104'],
            'certification': 'EXPOSED',
            'contamination': {
                'group_level': True,
                'reason': '34-frame pilot annotation viewed representatives of '
                          'every family and the full 279-frame exploratory '
                          'labels were produced; removing the 34 frames is not '
                          'enough to recover a sealed pool',
                'neighbor_radius': 'same episode / same group / same family',
            },
        })
    frame_overrides = []
    for frame in pilot_frames:
        frame_overrides.append({
            'source': 'final_seal',
            'group_id': frame.get('group_id'),
            'frame_id': frame.get('frame_id'),
            'status': 'annotation_calibration',
            'event_id': 'ev_final_pilot_annotation_34_20261104',
            'dataset_role': 'ANNOTATION_CALIBRATION',
        })
    dev_episode_groups = {}
    for group_id, group in dev_groups.items():
        for episode in group.get('episodes') or []:
            dev_episode_groups[episode] = group_id
    for frame in annotated_dev_frames:
        frame_id = frame.get('frame_id')
        group_id = frame.get('group_id')
        if group_id not in dev_groups:
            parsed = parse_frame_id(frame_id) or {}
            group_id = dev_episode_groups.get(parsed.get('episode_id'))
        if not group_id or group_id not in dev_groups:
            continue
        frame_overrides.append({
            'source': 'dev_v3',
            'group_id': group_id,
            'frame_id': frame_id,
            'status': 'annotation_calibration',
            'event_id': 'ev_dev_dedup_annotation_selection_20261104',
            'dataset_role': 'ANNOTATION_CALIBRATION',
        })
    registry = {
        'schema_version': EXPOSURE_SCHEMA,
        'protocol': EXPOSURE_PROTOCOL,
        'generated_at': datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        'generated_by': 'scripts/verify_landmark_dataset.py '
                        '--build-exposure-registry',
        'status': 'PARTIAL_EXPOSURE_AUDIT',
        'policy': {
            'statuses': list(EXPOSURE_STATUSES),
            'group_level_rule': 'if any frame of a group was viewed, selected '
                                'or annotated, the whole group is exposed; '
                                'removing single frames does not make the '
                                'remaining frames untouched',
            'sealed_rule': 'no group may be called sealed after an exposure '
                           'event; the final pool is development/exploratory',
            'near_neighbor_rule': 'same episode / same group / same family '
                                  'counts as the same contamination unit',
            'project_decision': 'user 2026-11-04 authorised the main candidate '
                                'for bounded internal research only; '
                                'distribution is a separate decision and is '
                                'NOT a solved license question',
        },
        'freezes': {
            'dev_v3': {
                'path': V3_PATH,
                'canonical_sha256': freeze_sha256(v3),
                'groups': len(dev_groups),
                'frames': sum(len(group.get('frames') or [])
                              for group in dev_groups.values()),
            },
            'final_seal': {
                'path': SEAL_PATH,
                'canonical_sha256': freeze_sha256(seal),
                'groups': len(final_groups),
                'frames': sum(len(group.get('frames') or [])
                              for group in final_groups.values()),
                'downgraded_to': 'development_exploratory',
            },
        },
        'events': events,
        'groups': groups_doc,
        'frame_overrides': frame_overrides,
        'summary': {
            'exposed_development_groups': sum(
                1 for entry in groups_doc
                if entry['status'] == 'exposed_development'),
            'exploratory_eval_candidate_groups': sum(
                1 for entry in groups_doc
                if entry['status'] == 'exploratory_eval_candidate'),
            'untouched_groups': sum(1 for entry in groups_doc
                                    if entry['status'] == 'untouched'),
            'annotation_calibration_frames': len(frame_overrides),
            'final_groups_contaminated': len(final_groups),
            't9_groups': len(t9_groups),
        },
        'identity_certification': {
            'U1_at_most_one_tower_like_instance': 'FALSIFIED',
            'U2_central_tower_is_only_green_light_tower': 'FALSIFIED',
            'evidence': 'map-native green-lamp pillar MS1 at about (3.0,4.0, '
                        'green lamp z~1.71) is visible from the inner_north '
                        'dev route (55 green px at g1_90) and is not the '
                        'central tower; it is map-native, not synthetic',
            'final_pool_verified_HN1_frames': 0,
            'final_pool_HN1_status': 'the final pool similar_negative is '
                                    'target-absent with <=3 px green false '
                                    'clues; no verified similar-structure '
                                    'frame exists there',
            'identity_status': 'INCOMPLETE',
            'note': 'tower class detection can still be trained, but landmark '
                    'identity claims require a revised uniqueness statement or '
                    'an explicit multi-landmark candidate design',
        },
        'certification': {
            'can_claim_sealed': False,
            'untouched_final_groups': 0,
            'conclusion': 'INCOMPLETE',
            'reasons': [
                'all 279 final-pool frames were annotated as exploratory '
                'development labels, and a 34-frame pilot was annotated '
                'before that',
                'the 34 pilot frames cannot simply be removed: all 6 families '
                'were represented in the pilot, so group-level contamination '
                'applies',
                'T9 dev data is development/calibration data, not a sealed '
                'holdout',
                'no third-party independent sealing exists; only process '
                'isolation + hash commitment is claimed',
                'identity uniqueness U1/U2 is falsified by the map-native '
                'green-lamp pillar MS1; the final pool has no verified HN1 '
                'frame, so identity certification is INCOMPLETE',
            ],
        },
        'notes': [
            'PASS for this registry means the exposure record is consistent '
            'with the freezes; it does not prove nobody looked at the data.',
            'The final seal file keeps its original bytes and historical '
            'sealed_test label; this registry is the authoritative exposure '
            'state and downgrades it to exploratory.',
        ],
    }
    return registry


def verify_exposure_registry_mode(repo_root, registry_relative,
                                  sources=None, output_relative=REGISTRY_OUTPUT):
    from boom_birds.evaluation.landmark_dataset import (
        validate_exposure_registry)
    root = Path(repo_root)
    registry_path = root / registry_relative
    if not registry_path.is_file():
        raise SystemExit('exposure registry missing: %s' % registry_relative)
    registry = load_json(registry_path)
    source_map = sources or REGISTRY_SOURCES
    freeze_documents = {}
    missing_sources = []
    for source, relative in source_map.items():
        path = root / relative
        if not path.is_file():
            missing_sources.append(relative)
            continue
        freeze_documents[source] = load_json(path)
    if missing_sources:
        raise SystemExit('registry source freeze missing: %s'
                         % ', '.join(missing_sources))
    report = validate_exposure_registry(
        registry, freeze_documents, root, verify_evidence=True)
    evidence = {
        'schema_version': 'dsh.landmark_exposure_registry_evidence.v1',
        'status': 'PASS' if report.ok else 'FAIL',
        'generated_at': datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        'registry': {
            'path': registry_relative,
            'sha256': sha256_file(registry_path),
        },
        'sources': {source: {
            'path': relative,
            'canonical_sha256': freeze_sha256(freeze_documents[source]),
        } for source, relative in source_map.items()},
        'checks': {
            'errors': [issue.__dict__ for issue in report.errors],
            'warnings': [issue.__dict__ for issue in report.warnings],
        },
        'stats': report.stats,
        'limits': [
            'exposure registry PASS means the record is internally consistent '
            'with the freezes; it does not prove nobody looked at the data',
            'no sealed/untouched claim is allowed once an exposure event '
            'exists',
        ],
    }
    output = (root / output_relative
              if not Path(output_relative).is_absolute()
              else Path(output_relative))
    write_json(output, evidence)
    print(json.dumps({'status': evidence['status'],
                      'output': str(output),
                      'errors': len(report.errors),
                      'warnings': len(report.warnings),
                      'stats': report.stats}, ensure_ascii=False))
    return 0 if report.ok else 1


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
    parser.add_argument('--audit-near-duplicates', action='store_true',
                        help='T12: near-duplicate / split leakage audit')
    parser.add_argument('--audit-freezes', default=None,
                        help='comma separated dev freeze paths for the audit')
    parser.add_argument('--audit-seal', default=None,
                        help='optional final seal path for the audit')
    parser.add_argument('--audit-output', default=T12_AUDIT_OUTPUT)
    parser.add_argument('--external-index', action='store_true',
                        help='T12: verify the ignored raw product directory')
    parser.add_argument('--index-freezes', default=None,
                        help='comma separated freeze paths for the index')
    parser.add_argument('--index-seal', default=None)
    parser.add_argument('--index-output', default=T12_INDEX_OUTPUT)
    parser.add_argument('--build-exposure-registry', action='store_true',
                        help='T12: build the exposure registry then verify it')
    parser.add_argument('--verify-exposure-registry', action='store_true',
                        help='T12: verify the exposure registry')
    parser.add_argument('--registry', default=REGISTRY_PATH)
    parser.add_argument('--registry-output', default=REGISTRY_OUTPUT)
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    if args.build_exposure_registry:
        registry = build_exposure_registry(repo_root)
        write_json(repo_root / args.registry, registry)
        return verify_exposure_registry_mode(
            repo_root, args.registry, output_relative=args.registry_output)
    if args.verify_exposure_registry:
        return verify_exposure_registry_mode(
            repo_root, args.registry, output_relative=args.registry_output)
    if args.audit_near_duplicates or args.external_index:
        default_dev = ('configs/perception/landmark_split_freeze_v3.json'
                       if (repo_root / 'configs/perception/'
                           'landmark_split_freeze_v3.json').is_file()
                       else DEFAULT_FREEZE_V2)
        default_seal = ('configs/perception/'
                        'landmark_final_pool_seal_v1.json')
        audit_freezes = [item.strip() for item in
                         (args.audit_freezes or default_dev).split(',')
                         if item.strip()]
        index_freezes = [item.strip() for item in
                         (args.index_freezes or default_dev).split(',')
                         if item.strip()]
        selected_seal = args.audit_seal or (
            default_seal if (repo_root / default_seal).is_file() else None)
        selected_index_seal = args.index_seal or (
            default_seal if (repo_root / default_seal).is_file() else None)
        if args.audit_near_duplicates:
            result = run_near_duplicate_audit(
                repo_root, audit_freezes, selected_seal)
            output = (repo_root / args.audit_output
                      if not Path(args.audit_output).is_absolute()
                      else Path(args.audit_output))
            write_json(output, result)
            print(json.dumps({'status': result['status'],
                              'output': str(output),
                              'counts': result['counts'],
                              'sha_cross_set': result['sha_cross_set']},
                             ensure_ascii=False))
            return 0 if result['status'] == 'PASS' else 1
        result = run_external_index(
            repo_root, index_freezes, selected_index_seal)
        output = (repo_root / args.index_output
                  if not Path(args.index_output).is_absolute()
                  else Path(args.index_output))
        write_json(output, result)
        print(json.dumps({'status': result['status'],
                          'output': str(output),
                          'totals': result['totals']},
                         ensure_ascii=False))
        return 0 if result['status'] == 'PASS' else 1
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
