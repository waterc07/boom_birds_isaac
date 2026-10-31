"""Regression tests for deterministic evaluation episode boundaries."""
import torch

from boom_birds.evaluation.episodes import clear_episode_buffers


class _FakeEnv:
    def __init__(self):
        self.episode_length_buf = torch.tensor([1168], dtype=torch.long)
        self.reset_terminated = torch.tensor([True])
        self.reset_time_outs = torch.tensor([False])


def test_clear_episode_buffers_resets_episode_boundary():
    env = _FakeEnv()
    clear_episode_buffers(env)
    assert env.episode_length_buf.tolist() == [0]
    assert env.reset_terminated.tolist() == [False]
    assert env.reset_time_outs.tolist() == [False]
