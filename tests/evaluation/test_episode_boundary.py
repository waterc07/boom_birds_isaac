"""Regression tests for the evaluation episode-boundary contract."""
import torch

from boom_birds.evaluation.episode_boundary import EpisodeBoundary


class _RobotData:
    def __init__(self):
        self.root_pos_w = torch.tensor([[0.0, 0.0, 0.5]])
        self.root_quat_w = torch.tensor([[1.0, 0.0, 0.0, 0.0]])
        self.root_lin_vel_w = torch.tensor([[0.0, 0.0, 0.0]])


class _Robot:
    def __init__(self):
        self.data = _RobotData()


class _FakeEnv:
    """Mimics the Quadcopter task: reset leaves a randomised episode counter."""

    def __init__(self, random_counter=1168):
        self.random_counter = random_counter
        self.episode_length_buf = torch.tensor([1168], dtype=torch.long)
        self.reset_terminated = torch.tensor([True])
        self.reset_time_outs = torch.tensor([False])
        self._robot = _Robot()
        self.reset_calls = []

    def reset(self, seed=None):
        self.reset_calls.append(seed)
        self.episode_length_buf[0] = self.random_counter
        return None

    def _reset_idx(self, env_ids):
        return None


def test_start_clears_randomised_counter_and_flags():
    env = _FakeEnv()
    boundary = EpisodeBoundary(env).start(7)
    assert env.reset_calls == [7]
    assert env.episode_length_buf.tolist() == [0]
    assert env.reset_terminated.tolist() == [False]
    assert env.reset_time_outs.tolist() == [False]
    assert boundary.expected_steps == 0


def test_after_step_accepts_monotonic_counter():
    env = _FakeEnv()
    boundary = EpisodeBoundary(env).start(1)
    env.episode_length_buf[0] = 1
    state = boundary.after_step(False, False)
    assert state['count_ok'] is True
    assert state['unexpected_reset'] is False
    assert state['reset_snapshot'] is None


def test_after_step_detects_counter_mismatch_without_flags():
    env = _FakeEnv()
    boundary = EpisodeBoundary(env).start(1)
    env.episode_length_buf[0] = 532
    state = boundary.after_step(False, False)
    assert state['count_ok'] is False
    assert state['unexpected_reset'] is True


def test_terminal_flags_end_the_episode_and_are_primary():
    env = _FakeEnv()
    boundary = EpisodeBoundary(env).start(1)
    env.episode_length_buf[0] = 2
    state = boundary.after_step(False, True)
    assert state['truncated'] is True
    assert state['unexpected_reset'] is False
