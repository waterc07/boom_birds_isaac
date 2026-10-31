"""Comparison statistics: Wilson intervals, strata and paired deltas.

All rates keep their denominator; invalid episodes stay visible and are never
silently dropped or promoted to success.
"""
import math
import statistics

from .episodes import summarize

VALID_STRATA = ('distance_bin', 'bearing_bin')


def _counter(value, name):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(name + ' must be a nonnegative integer')


def wilson_interval(successes, trials, z=1.96):
    """Wilson score interval for a binomial proportion; None with no trials."""
    _counter(successes, 'successes')
    _counter(trials, 'trials')
    if successes > trials:
        raise ValueError('successes cannot exceed trials')
    if (not isinstance(z, (int, float)) or isinstance(z, bool)
            or not math.isfinite(z) or z <= 0):
        raise ValueError('z must be a positive finite number')
    if trials == 0:
        return None
    proportion = successes / trials
    denominator = 1.0 + z * z / trials
    center = (proportion + z * z / (2.0 * trials)) / denominator
    margin = z * math.sqrt(
        proportion * (1.0 - proportion) / trials
        + z * z / (4.0 * trials * trials)) / denominator
    return (max(0.0, center - margin), min(1.0, center + margin))


def _mean(values):
    return statistics.fmean(values) if values else None


def method_summary(results):
    results = list(results)
    summary = summarize(results)
    successful = [item for item in results
                  if item.outcome == 'SUCCESS' and item.time_to_goal_s is not None]
    times = [item.time_to_goal_s for item in successful]
    summary['method'] = results[0].method if results else 'unknown'
    summary['success_ci95'] = wilson_interval(summary['success'],
                                              summary['valid_denominator'])
    summary['mean_time_to_goal_s'] = _mean(times)
    summary['median_time_to_goal_s'] = statistics.median(times) if times else None
    return summary


def stratified_summary(results, stratum='distance_bin'):
    if stratum not in VALID_STRATA:
        raise ValueError('unsupported stratum: ' + str(stratum))
    groups = {}
    for item in results:
        key = getattr(item, stratum) or 'unspecified'
        groups.setdefault(key, []).append(item)
    return {key: method_summary(group) for key, group in sorted(groups.items())}


def paired_comparison(results_a, results_b):
    a = list(results_a)
    b = list(results_b)
    if not a or not b:
        raise ValueError('paired comparison needs two nonempty result sets')
    index_a = {}
    for item in a:
        if item.scenario_id in index_a:
            raise ValueError('duplicate scenario_id in first set: ' + item.scenario_id)
        index_a[item.scenario_id] = item
    index_b = {}
    for item in b:
        if item.scenario_id in index_b:
            raise ValueError('duplicate scenario_id in second set: ' + item.scenario_id)
        index_b[item.scenario_id] = item
    shared = sorted(set(index_a) & set(index_b))
    if set(index_a) != set(index_b):
        raise ValueError('paired comparison requires identical scenario sets')
    if not shared:
        raise ValueError('the two result sets share no scenario_id')
    both_success = a_only = b_only = neither = 0
    time_deltas = []
    distance_deltas = []
    wins_b = wins_a = ties = 0
    for scenario_id in shared:
        left = index_a[scenario_id]
        right = index_b[scenario_id]
        left_success = left.outcome == 'SUCCESS'
        right_success = right.outcome == 'SUCCESS'
        if left_success and right_success:
            both_success += 1
        elif left_success:
            a_only += 1
        elif right_success:
            b_only += 1
        else:
            neither += 1
        if left_success and right_success and left.time_to_goal_s is not None \
                and right.time_to_goal_s is not None:
            delta = right.time_to_goal_s - left.time_to_goal_s
            time_deltas.append(delta)
            if abs(delta) < 1e-9:
                ties += 1
            elif delta < 0:
                wins_b += 1
            else:
                wins_a += 1
        if left.outcome != 'INVALID' and right.outcome != 'INVALID':
            distance_deltas.append(right.final_distance_m - left.final_distance_m)
    return {
        'method_a': a[0].method,
        'method_b': b[0].method,
        'pairs_total': len(shared),
        'unpaired_a': len(index_a) - len(shared),
        'unpaired_b': len(index_b) - len(shared),
        'pairs_both_success': both_success,
        'a_only_success': a_only,
        'b_only_success': b_only,
        'neither_success': neither,
        'time_pairs': len(time_deltas),
        'time_wins_a': wins_a,
        'time_wins_b': wins_b,
        'time_ties': ties,
        'mean_time_delta_b_minus_a_s': _mean(time_deltas),
        'median_time_delta_b_minus_a_s': (statistics.median(time_deltas)
                                          if time_deltas else None),
        'distance_pairs': len(distance_deltas),
        'mean_final_distance_delta_b_minus_a_m': _mean(distance_deltas),
    }
