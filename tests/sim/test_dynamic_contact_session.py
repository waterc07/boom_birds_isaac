"""The initialization wait is bounded and cannot hide nonzero/error samples."""
import pytest
from types import SimpleNamespace

from boom_birds.sim.dynamic_contact_session import DynamicContactSession


def session(samples):
    instance = object.__new__(DynamicContactSession)
    instance.generation = 3
    iterator = iter(samples)
    instance.read = lambda: next(iterator)
    return instance


def sample(force, read_ok=True):
    return {'measure': {'read_ok': read_ok, 'measured_force_n': force}}


def test_nonzero_or_failed_samples_do_not_establish_zero():
    current = session([sample(0.1), sample(None, False), sample(0.0)])
    calls = []
    handshake = current.establish_zero(lambda: calls.append(1), max_steps=3)
    assert len(calls) == 3
    assert handshake['physics_generation'] == 3
    assert len(handshake['samples']) == 3


def test_stale_nonzero_cannot_wait_forever_or_be_overwritten():
    current = session([sample(0.03), sample(0.03)])
    calls = []
    with pytest.raises(RuntimeError, match='fresh'):
        current.establish_zero(lambda: calls.append(1), max_steps=2)
    assert len(calls) == 2
    assert current.handshake['ok'] is False
    assert current.handshake['samples'][-1]['measure']['measured_force_n'] == 0.03


def test_live_sensor_read_passes_raw_audit_before_json_serialization():
    class Sensor:
        data = SimpleNamespace(net_forces_w=[[[0.0, 0.0, 0.0]]],
                               force_matrix_w=[[[[0.0, 0.0, 0.0]]]])
        body_names = ['body']
        contact_physx_view = SimpleNamespace(filter_count=1)

        def update(self, dt, force_recompute):
            assert force_recompute is True

    current = object.__new__(DynamicContactSession)
    current.sensor = Sensor()
    current.env = SimpleNamespace(_sim_step_counter=5)
    current.generation = 2
    current.dt_s = 0.05
    current.target_path = '/Obstacle'
    result = current.read()
    assert result['measure']['read_ok'] is True
    assert result['measure']['measured_force_n'] == 0.0
    assert result['physics_step'] == 5
