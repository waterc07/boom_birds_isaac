import math
import pytest

from boom_birds.contracts.frames import decode_action, enu_to_ned, yaw_rate_enu_to_ned
from boom_birds.contracts.types import ActionLimits


@pytest.mark.parametrize('yaw,action,expected', [
    (0, [1, 0, 0, 0], (1, 0, 0)),
    (math.pi / 2, [1, 0, 0, 0], (0, 1, 0)),
    (0, [0, 1, 0, 0], (0, 1, 0)),
    (math.pi / 2, [0, 1, 0, 0], (-1, 0, 0)),
    (0, [0, 0, 1, 0], (0, 0, 0.5)),
    (0, [1, 1, 0, 0], (1 / math.sqrt(2), 1 / math.sqrt(2), 0)),
    (0, [5, -2, -3, 2], (1 / math.sqrt(2), -1 / math.sqrt(2), -0.5)),
])
def test_horizontal_heading_and_vector_speed_limit(yaw, action, expected):
    cmd = decode_action(action, yaw, ActionLimits(), 100, 7)
    assert cmd.velocity_enu_mps == pytest.approx(expected)
    assert math.hypot(*cmd.velocity_enu_mps[:2]) <= 1 + 1e-12
    assert cmd.mission_epoch == 7
    assert cmd.created_ns == 100
    assert cmd.valid_until_ns == 150_000_100


def test_ned_conversion_and_yaw_sign():
    assert enu_to_ned((1, 2, 3)) == (2, 1, -3)
    cmd = decode_action([0, 0, 0, 1], 0, ActionLimits(), 0, 0)
    assert yaw_rate_enu_to_ned(cmd.yaw_rate_rad_s) == -0.5


@pytest.mark.parametrize('action', [[], [1, 2, 3], [0] * 5,
                                   [math.nan, 0, 0, 0], [0, math.inf, 0, 0],
                                   [0, 0, -math.inf, 0]])
def test_reject_invalid_actions(action):
    with pytest.raises(ValueError):
        decode_action(action, 0, ActionLimits(), 0, 0)


@pytest.mark.parametrize('yaw', [math.nan, math.inf])
def test_reject_invalid_heading(yaw):
    with pytest.raises(ValueError):
        decode_action([0] * 4, yaw, ActionLimits(), 0, 0)


@pytest.mark.parametrize('kwargs', [{'horizontal_mps': -1}, {'vertical_mps': math.nan},
                                  {'yaw_rate_rad_s': math.inf}, {'ttl_ns': 0}, {'ttl_ns': 1.5}])
def test_invalid_limits_rejected(kwargs):
    with pytest.raises(ValueError):
        ActionLimits(**kwargs)


def test_contract_modules_do_not_import_training_or_sensor_libraries():
    import subprocess
    import sys
    from pathlib import Path
    source = str(Path(__file__).resolve().parents[2] / 'src')
    script = ('import sys; sys.path.insert(0, ' + repr(source) + '); '
              'import boom_birds.contracts.frames, boom_birds.contracts.timebase; '
              'assert not any(m.split(".")[0] in {"torch", "isaaclab", "isaacsim", "numpy", "cv2"} '
              'for m in sys.modules)')
    subprocess.run([sys.executable, '-c', script], check=True)
