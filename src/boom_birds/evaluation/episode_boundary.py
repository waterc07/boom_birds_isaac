"""Evaluation episode-boundary contract.

The Quadcopter task randomises its episode counter when all envs are reset
(training trick). Evaluation must start each episode from a cleared counter and
must stop the episode when the environment reports a terminal/truncated flag.
This module wraps those rules once so every evaluation entry uses the same
semantics instead of ad-hoc patches.
"""
from .episodes import clear_episode_buffers


class EpisodeBoundary:
    """Track one evaluation episode from its reset to its end.

    start() resets the environment, clears the task episode counter and reset
    flags, and records the counter expected after each step. after_step()
    reports whether the task counter advanced exactly once (auxiliary
    detection), together with the environment terminated/truncated flags
    (primary signal). A terminal/truncated step ends the episode; its
    post-reset state must never be evaluated as an in-episode state.
    """

    def __init__(self, env):
        self.env = env
        self.expected_steps = 0
        self.active = False
        self.last_reset_snapshot = None
        self._original_reset_idx = env._reset_idx

        def wrapped_reset_idx(env_ids):
            try:
                robot = env._robot
                self.last_reset_snapshot = {
                    'root_pos_w': robot.data.root_pos_w.clone(),
                    'root_quat_w': robot.data.root_quat_w.clone(),
                    'root_lin_vel_w': robot.data.root_lin_vel_w.clone(),
                }
            except Exception:
                self.last_reset_snapshot = None
            return self._original_reset_idx(env_ids)

        env._reset_idx = wrapped_reset_idx

    def start(self, seed=None):
        """Reset the env and begin a deterministic evaluation episode."""
        if seed is None:
            self.env.reset()
        else:
            self.env.reset(seed=seed)
        clear_episode_buffers(self.env)
        self.expected_steps = 0
        self.active = True
        self.last_reset_snapshot = None
        return self

    def after_step(self, terminated, truncated):
        """Report boundary state after one env.step call."""
        self.expected_steps += 1
        actual = int(self.env.episode_length_buf[0].item())
        terminated = bool(terminated)
        truncated = bool(truncated)
        count_ok = actual == self.expected_steps
        unexpected_reset = (not terminated) and (not truncated) and (not count_ok)
        snapshot = self.last_reset_snapshot
        self.last_reset_snapshot = None
        return {
            'expected_steps': self.expected_steps,
            'episode_length_buf': actual,
            'count_ok': count_ok,
            'terminated': terminated,
            'truncated': truncated,
            'unexpected_reset': unexpected_reset,
            'reset_snapshot': snapshot,
        }
