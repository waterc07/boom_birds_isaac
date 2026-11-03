"""Single-env contact measurement after an explicit physics reset handshake."""
from dataclasses import asdict
from typing import Any, Callable

from boom_birds.evaluation.contact_raw_audit import audit_row
from boom_birds.evaluation.contact_readout import read_contact_sensor


class DynamicContactSession:
    """A positive force sample is not a general proof of contact coverage."""

    def __init__(self, env: Any, *, generation: int, body_path: str,
                 target_path: str, dt_s: float):
        from isaaclab.sensors import ContactSensor, ContactSensorCfg

        self.env = env
        self.generation = generation
        self.dt_s = dt_s
        self.target_path = target_path
        self.handshake = None
        self.last = None
        self.sensor = ContactSensor(ContactSensorCfg(
            prim_path=body_path, filter_prim_paths_expr=[target_path],
            update_period=0.0, history_length=0, debug_vis=False))
        self.sensor._initialize_callback(None)
        if self.sensor.contact_physx_view.filter_count != 1:
            raise RuntimeError('contact filter does not resolve to one target')

    def read(self) -> dict:
        read = read_contact_sensor(self.sensor, dt_s=self.dt_s,
                                   target_paths=(self.target_path,))
        raw = {'reads': [asdict(read)]}
        try:
            measured = audit_row({'contact_readout': raw})
            error = None
        except ValueError as exc:
            measured = {'read_ok': False, 'measured_force_n': None,
                        'max_filtered_force_n': None, 'max_net_force_n': None}
            error = str(exc)
        self.last = {
            'schema_version': 'boom_birds.dynamic_contact_sample.v1',
            'physics_generation': self.generation,
            'physics_step': int(self.env._sim_step_counter),
            'contact_readout': raw, 'measure': measured, 'error': error,
            'body_names': list(self.sensor.body_names),
            'filter_count': int(self.sensor.contact_physx_view.filter_count),
            'negative_contact_verdict': 'UNKNOWN',
            'source': 'last_physics_step_contact_force_not_native_event',
        }
        return self.last

    def establish_zero(self, step: Callable[[], None], *, max_steps: int = 20,
                       zero_tolerance_n: float = 1e-6) -> dict:
        rows = []
        for _ in range(max_steps):
            step()
            sample = self.read()
            rows.append(sample)
            measure = sample['measure']
            if measure['read_ok'] and measure['measured_force_n'] <= zero_tolerance_n:
                self.handshake = {'ok': True, 'physics_generation': self.generation,
                                  'max_steps': max_steps, 'zero_tolerance_n': zero_tolerance_n,
                                  'samples': rows}
                return self.handshake
        self.handshake = {'ok': False, 'physics_generation': self.generation,
                          'samples': rows}
        raise RuntimeError('contact initialization has no fresh separated zero baseline')
