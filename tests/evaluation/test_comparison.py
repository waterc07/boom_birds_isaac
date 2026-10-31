"""Unified comparison statistics: Wilson intervals, strata and paired deltas."""
import math

import pytest

from boom_birds.evaluation.comparison import (
    method_summary,
    paired_comparison,
    stratified_summary,
    wilson_interval,
)
from boom_birds.evaluation.episodes import EpisodeResult


def result(scenario_id, method, outcome, *, time_to_goal_s=None, final_distance=0.1,
           distance_bin='short', bearing_bin='front', seed=0):
    return EpisodeResult(
        episode_id=method + '-' + scenario_id, seed=seed, outcome=outcome,
        steps=100, duration_s=time_to_goal_s if time_to_goal_s is not None else 5.0,
        final_distance_m=final_distance, peak_speed_mps=0.5, reason='',
        method=method, scenario_id=scenario_id, distance_bin=distance_bin,
        bearing_bin=bearing_bin, time_to_goal_s=time_to_goal_s)


def test_wilson_interval_known_values_and_edge_cases():
    low, high = wilson_interval(8, 10)
    assert 0.48 < low < 0.50
    assert 0.94 < high < 0.95
    assert wilson_interval(0, 0) is None
    zero_low, zero_high = wilson_interval(0, 10)
    assert zero_low == pytest.approx(0.0)
    assert zero_high < 0.35
    full_low, full_high = wilson_interval(10, 10)
    assert full_low > 0.7 and full_high == pytest.approx(1.0)
    with pytest.raises(ValueError):
        wilson_interval(11, 10)


def test_method_summary_reports_denominators_and_interval():
    results = [result('a', 'braking', 'SUCCESS', time_to_goal_s=3.0),
               result('b', 'braking', 'SUCCESS', time_to_goal_s=5.0),
               result('c', 'braking', 'COLLISION', time_to_goal_s=None),
               result('d', 'braking', 'INVALID', time_to_goal_s=None)]
    summary = method_summary(results)
    assert summary['method'] == 'braking'
    assert summary['total_episodes'] == 4
    assert summary['valid_episodes'] == 3
    assert summary['success'] == 2
    assert summary['success_rate_of_valid'] == pytest.approx(2 / 3)
    assert summary['success_ci95'][0] < 2 / 3 < summary['success_ci95'][1]
    assert summary['mean_time_to_goal_s'] == pytest.approx(4.0)


def test_stratified_summary_groups_by_bin():
    results = [result('a', 'braking', 'SUCCESS', distance_bin='short'),
               result('b', 'braking', 'COLLISION', distance_bin='short'),
               result('c', 'braking', 'SUCCESS', distance_bin='long')]
    strata = stratified_summary(results, 'distance_bin')
    assert strata['short']['total_episodes'] == 2
    assert strata['short']['success'] == 1
    assert strata['long']['total_episodes'] == 1
    with pytest.raises(ValueError):
        stratified_summary(results, 'unknown_bin')


def test_paired_comparison_uses_same_scenario_ids():
    a = [result('s1', 'proportional', 'SUCCESS', time_to_goal_s=4.0),
         result('s2', 'proportional', 'SUCCESS', time_to_goal_s=5.0),
         result('s3', 'proportional', 'TIMEOUT', time_to_goal_s=None)]
    b = [result('s1', 'braking', 'SUCCESS', time_to_goal_s=3.5),
         result('s2', 'braking', 'COLLISION', time_to_goal_s=None),
         result('s3', 'braking', 'SUCCESS', time_to_goal_s=6.0)]
    paired = paired_comparison(a, b)
    assert paired['pairs_total'] == 3
    assert paired['pairs_both_success'] == 1
    assert paired['a_only_success'] == 1
    assert paired['b_only_success'] == 1
    assert paired['neither_success'] == 0
    assert paired['time_wins_b'] == 1
    assert paired['time_wins_a'] == 0
    assert paired['mean_time_delta_b_minus_a_s'] == pytest.approx(-0.5)
    with pytest.raises(ValueError):
        paired_comparison(a, b[:2])
