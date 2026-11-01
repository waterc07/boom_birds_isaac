"""Tests for the stop-wait-resume supervisor state machine."""
from boom_birds.evaluation.supervisor import RouteSupervisor, SupervisorConfig


def _obs(x, vx=0.0, valid=True, age=0.0):
    return {'valid': valid, 'age_s': age, 'position_world_m': (x, 0.0, 1.0),
            'velocity_world_mps': (vx, 0.0, 0.0), 'reason': 'ACCEPT'}


def _config(**overrides):
    values = dict(stop_distance_m=1.0, release_distance_m=1.5,
                  prediction_horizon_s=0.5, prediction_step_s=0.1,
                  observation_max_age_s=0.2, max_stale_s=1.0,
                  max_wait_s=2.0, min_hold_s=0.2, release_hold_s=0.3,
                  resume_hold_s=0.2, stop_speed_mps=0.1)
    values.update(overrides)
    return SupervisorConfig(**values)


def test_stop_wait_resume_on_temporary_obstacle():
    supervisor = RouteSupervisor(_config())
    robot = (0.0, 0.0, 1.0)
    target = (2.0, 0.0, 1.0)
    # Obstacle blocks ahead.
    decision = supervisor.update(robot, target, 0.5, _obs(0.8), 0.0, 0.05)
    assert decision['state'] == 'BRAKE'
    assert decision['action'] == 'STOP'
    for step in range(1, 10):
        decision = supervisor.update(robot, target, 0.0, _obs(0.8), step * 0.05, 0.05)
    assert decision['state'] in ('HOLD', 'WAIT')
    # Obstacle clears and stays clear long enough.
    for step in range(10, 30):
        decision = supervisor.update(robot, target, 0.0, _obs(3.0), step * 0.05, 0.05)
    assert decision['state'] in ('RESUME', 'FOLLOW')


def test_persistent_obstacle_aborts_after_max_wait():
    supervisor = RouteSupervisor(_config(max_wait_s=0.5))
    robot = (0.0, 0.0, 1.0)
    target = (2.0, 0.0, 1.0)
    for step in range(40):
        decision = supervisor.update(robot, target, 0.0, _obs(0.8), step * 0.05, 0.05)
    assert decision['state'] == 'ABORT'
    assert decision['abort_reason'] in ('MAX_WAIT_EXCEEDED', 'OBSERVATION_STALE')


def test_stale_observation_explicit_degradation():
    supervisor = RouteSupervisor(_config(max_stale_s=0.3))
    decision = supervisor.update((0, 0, 1), (2, 0, 1), 0.5, _obs(0.8, valid=False),
                                 0.0, 0.05)
    assert decision['state'] == 'DEGRADED'
    assert decision['action'] == 'STOP'
    for step in range(1, 10):
        decision = supervisor.update((0, 0, 1), (2, 0, 1), 0.0,
                                     _obs(0.8, valid=False), step * 0.05, 0.05)
    assert decision['state'] == 'ABORT'


def test_hysteresis_avoids_chatter_near_threshold():
    supervisor = RouteSupervisor(_config())
    robot = (0.0, 0.0, 1.0)
    target = (2.0, 0.0, 1.0)
    supervisor.update(robot, target, 0.5, _obs(0.9), 0.0, 0.05)
    transitions = supervisor.transitions
    # Oscillate just inside/outside stop distance; release requires sustained clearance.
    for step in range(1, 30):
        x = 0.9 if step % 2 else 1.2
        supervisor.update(robot, target, 0.0, _obs(x), step * 0.05, 0.05)
    assert supervisor.transitions - transitions <= 2
    assert supervisor.state in ('BRAKE', 'HOLD', 'WAIT')


def test_reset_clears_state_and_timers():
    supervisor = RouteSupervisor(_config())
    supervisor.update((0, 0, 1), (2, 0, 1), 0.5, _obs(0.8), 0.0, 0.05)
    supervisor.reset()
    assert supervisor.state == 'FOLLOW'
    assert supervisor.wait_s == 0.0
    assert supervisor.transitions == 0


def test_wait_timer_is_cumulative_and_not_reset_by_resume():
    supervisor = RouteSupervisor(_config(max_wait_s=1.0, release_hold_s=0.1))
    robot = (0.0, 0.0, 1.0)
    target = (2.0, 0.0, 1.0)
    # First blocked interval.
    for step in range(8):
        decision = supervisor.update(robot, target, 0.0, _obs(0.8), step * 0.05, 0.05)
    assert decision['state'] in ('HOLD', 'WAIT')
    first_wait = decision['wait_s']
    assert first_wait > 0.0
    # Clear long enough to enter RESUME/FOLLOW.
    for step in range(8, 20):
        decision = supervisor.update(robot, target, 0.0, _obs(3.0), step * 0.05, 0.05)
    assert decision['state'] in ('RESUME', 'FOLLOW')
    # Block again; cumulative wait must not be reset by the resume.
    for step in range(20, 45):
        decision = supervisor.update(robot, target, 0.0, _obs(0.8), step * 0.05, 0.05)
    assert decision['state'] == 'ABORT'
    assert decision['abort_reason'] == 'MAX_WAIT_EXCEEDED'
    assert decision['wait_s'] > first_wait
