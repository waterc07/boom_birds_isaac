"""Evaluation v2: layered scene classes, contact evidence and denominators."""
import math

import pytest

from boom_birds.evaluation.comparison import layered_summary
from boom_birds.evaluation.episodes import (
    EVALUATION_SCHEMA_ID,
    EVALUATION_SCHEMA_ID_V2,
    EpisodeResult,
    summarize,
)


def result(scenario_id, scene_class, outcome, *, contact=False, force=0.0,
           method='proportional', seed=0, final_distance=0.1, time_to_goal=3.0):
    return EpisodeResult(
        episode_id=method + '-' + scenario_id, seed=seed, outcome=outcome,
        steps=60, duration_s=time_to_goal if time_to_goal is not None else 5.0,
        final_distance_m=final_distance, peak_speed_mps=0.5, reason='',
        schema_version=EVALUATION_SCHEMA_ID_V2, method=method,
        scenario_id=scenario_id, scene_class=scene_class, contact_evidence=contact,
        contact_force_n=force, time_to_goal_s=time_to_goal)


def test_v2_schema_and_fields_are_supported():
    item = result('s1', 'B_static', 'COLLISION', contact=True, force=0.04)
    assert item.schema_version == EVALUATION_SCHEMA_ID_V2
    assert item.scene_class == 'B_static'
    assert item.contact_evidence is True
    assert item.contact_force_n == pytest.approx(0.04)
    with pytest.raises(ValueError):
        EpisodeResult('x', 0, 'SUCCESS', 1, 0.0, 0.0, 0.0,
                      schema_version=EVALUATION_SCHEMA_ID_V2, contact_force_n=math.nan)


def test_layered_summary_groups_by_scene_class_and_keeps_denominators():
    results = [
        result('a1', 'A_clear', 'SUCCESS'),
        result('a2', 'A_clear', 'SUCCESS'),
        result('b1', 'B_static', 'SUCCESS'),
        result('b2', 'B_static', 'COLLISION', contact=True, force=0.05),
        result('b3', 'B_static', 'COLLISION', contact=False, force=0.0),
        result('d1', 'D_observation', 'INVALID'),
        result('d2', 'D_observation', 'SUCCESS'),
    ]
    summary = layered_summary(results, expected_classes=(
        'A_clear', 'B_static', 'C_dynamic', 'D_observation', 'E_disturbance'))
    assert summary['overall']['total_episodes'] == 7
    assert summary['overall']['valid_denominator'] == 6
    assert summary['overall']['invalid_episodes'] == 1
    assert summary['classes']['A_clear']['valid_episodes'] == 2
    assert summary['classes']['A_clear']['success_rate_of_valid'] == pytest.approx(1.0)
    assert summary['classes']['B_static']['valid_episodes'] == 3
    assert summary['classes']['B_static']['success_rate_of_valid'] == pytest.approx(1 / 3)
    assert summary['classes']['B_static']['collision_with_contact'] == 1
    assert summary['classes']['B_static']['collision_without_contact'] == 1
    assert summary['classes']['D_observation']['invalid_episodes'] == 1
    assert summary['classes']['D_observation']['valid_denominator'] == 1
    assert 'C_dynamic' in summary['missing_classes']
    assert 'E_disturbance' in summary['missing_classes']
    coverage = summary['coverage']
    assert coverage['min_required_valid_per_class'] == 20
    assert coverage['classes_meeting_minimum'] == []
    assert coverage['classes_below_minimum'] == ['A_clear', 'B_static', 'D_observation']


def test_layered_summary_requires_known_scene_classes():
    with pytest.raises(ValueError):
        layered_summary([result('x', 'unknown', 'SUCCESS')])
    with pytest.raises(ValueError):
        layered_summary([])


def test_summarize_accepts_v2_results():
    summary = summarize([result('a1', 'A_clear', 'SUCCESS'),
                         result('a2', 'A_clear', 'TIMEOUT', time_to_goal=None)])
    assert summary['schema_version'] == EVALUATION_SCHEMA_ID_V2
    assert summary['valid_denominator'] == 2
    assert summary['success_rate_of_valid'] == pytest.approx(0.5)
    assert EVALUATION_SCHEMA_ID != EVALUATION_SCHEMA_ID_V2
