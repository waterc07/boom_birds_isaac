"""Shadow sensor adapter: rendered RGB + ideal PhysX ray range.

Standard-library contracts live in ``boom_birds.evaluation.sensor_observation``;
Isaac/Torch/PIL are imported only in this adapter.  The recorded ORACLE route
control does not consume this data.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np

from boom_birds.contracts import reasons
from boom_birds.contracts.context import ContractContext, MessageHeader
from boom_birds.evaluation import sensor_observation as obs_mod


class ShadowSensorChain:
    """Per-episode camera/range chain; reset creates a fresh camera and generation."""

    def __init__(self, env: Any, robot_root: str, output_dir: Path,
                 config: dict, *, dt_s: float, physics_dt_s: float):
        self.env = env
        self.robot_root = robot_root
        self.output_dir = Path(output_dir)
        self.config = config
        self.dt_s = float(dt_s)
        self.physics_dt_s = float(physics_dt_s)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir = self.output_dir / 'images'
        self.images_dir.mkdir(exist_ok=True)
        self._camera = None
        self._generation = None
        self._episode_id = None
        self._active = False
        self._warmup_remaining = 0
        self._step_counter = 0
        self._sequence = {'front_rgb': 0, 'front_depth': 0}
        self._gate = obs_mod.ObservationGate(
            int(config['observation']['max_age_ns']))
        self._samples = []
        self._images = []
        self._records_path = self.output_dir / 'observations.jsonl'
        self._records_stream = self._records_path.open('w', encoding='utf-8')
        self._summary = {
            'schema_version': 'dsh.sensor_shadow.v1',
            'mode': 'SHADOW_ONLY_NOT_IN_CONTROL',
            'camera': config['camera'],
            'range': config['range'],
            'sample_period_steps': int(config['observation']['sample_period_steps']),
            'max_age_ns': int(config['observation']['max_age_ns']),
            'warmup_frames': int(config['observation']['warmup_frames']),
            'episodes': [],
        }

    # -- camera lifecycle -------------------------------------------------
    def _camera_cfg(self, generation):
        from isaaclab.sensors import CameraCfg
        from isaaclab.sim import PinholeCameraCfg
        cam = self.config['camera']
        width = int(cam['width'])
        height = int(cam['height'])
        horizontal_fov_deg = float(cam['horizontal_fov_deg'])
        # PinholeCameraCfg uses a 20.955 mm baseline horizontal aperture.
        focal = 20.955 / (2.0 * math.tan(math.radians(horizontal_fov_deg) / 2.0))
        prim_path = (self.robot_root + '/body/shadow_camera_' + str(generation))
        return CameraCfg(
            prim_path=prim_path,
            update_period=0.0,
            height=height,
            width=width,
            data_types=['rgb', 'depth'],
            update_latest_camera_pose=True,
            spawn=PinholeCameraCfg(
                focal_length=focal, focus_distance=2.0,
                horizontal_aperture=20.955,
                clipping_range=(0.05, 60.0)),
            offset=CameraCfg.OffsetCfg(
                pos=(float(cam['mount'][0]), float(cam['mount'][1]),
                     float(cam['mount'][2])),
                rot=(1.0, 0.0, 0.0, 0.0),
                convention='world'))

    def begin_episode(self, *, episode_id, generation, dt_s, physics_dt_s):
        self._close_camera()
        self._episode_id = episode_id
        self._generation = int(generation)
        self.dt_s = float(dt_s)
        self.physics_dt_s = float(physics_dt_s)
        self._sequence = {'front_rgb': 0, 'front_depth': 0}
        self._step_counter = 0
        self._active = False
        from isaaclab.sensors import Camera
        self._camera = Camera(self._camera_cfg(self._generation))
        self._camera._initialize_callback(None)
        self._gate.reset(
            context=self._context(),
            generation=self._generation)
        self._warmup_remaining = int(self.config['observation']['warmup_frames'])
        self._episode_samples = []
        self._episode_images = []
        self._summary['episodes'].append({
            'episode_id': episode_id,
            'physics_generation': self._generation,
            'warmup_frames': self._warmup_remaining,
            'sample_count': 0,
            'valid_count': 0,
            'invalid_reasons': {},
        })

    def _close_camera(self):
        if self._camera is not None:
            try:
                self._camera.close()
            except Exception:
                pass
            self._camera = None

    def start_measurement(self):
        """Warm render products after the reset/handshake, outside task steps."""
        if self._camera is None:
            raise RuntimeError('sensor chain has no camera; begin_episode first')
        for _ in range(max(1, int(self.config['observation']['warmup_frames']))):
            self._camera.update(self.dt_s)
            self._record(warmup=True)
        self._warmup_remaining = 0
        self._active = True

    # -- contract/timestamp helpers --------------------------------------
    def _context(self):
        return ContractContext(
            system_boot_id=int(self.config['identity']['system_boot_id']),
            mission_epoch=0, localization_epoch=0, control_epoch=0,
            clock_id='sim_physics', px4_boot_id=0,
            sync_generation=self._generation)

    def _header(self, sensor_id, source_id, sequence, capture_sim_ns,
                ready_sim_ns, consume_sim_ns):
        return MessageHeader(
            system_boot_id=int(self.config['identity']['system_boot_id']),
            mission_epoch=0, localization_epoch=0, control_epoch=0,
            clock_id='sim_physics', px4_boot_id=None,
            sync_generation=self._generation, sync_valid=True,
            sequence_id=sequence, capture_timestamp_ns=capture_sim_ns,
            receive_timestamp_ns=ready_sim_ns,
            publish_timestamp_ns=consume_sim_ns,
            source_id=int(source_id),
            timestamp_uncertainty_ns=int(round(self.physics_dt_s * 1e9)),
            quarantine=False, valid=True)

    # -- capture ----------------------------------------------------------
    def on_policy_step(self):
        if not self._active or self._camera is None:
            return
        period = max(1, int(self.config['observation']['sample_period_steps']))
        self._step_counter += 1
        if self._step_counter % period != 0:
            return
        self._camera.update(self.dt_s)
        self._record(warmup=False)

    def _record(self, *, warmup):
        camera = self._camera
        if camera is None:
            return
        capture_host_ns = time.monotonic_ns()
        capture_sim_ns = int(round(float(self.env.sim.current_time) * 1e9))
        data = camera.data
        rgb = data.output.get('rgb')
        depth = data.output.get('depth')
        if rgb is None:
            raise RuntimeError('camera produced no RGB payload')
        ready_host_ns = time.monotonic_ns()
        rgb_np = rgb[0].detach().cpu().numpy()
        if rgb_np.dtype != np.uint8:
            rgb_np = np.clip(rgb_np, 0, 255).astype(np.uint8)
        if rgb_np.ndim == 2:
            rgb_np = np.repeat(rgb_np[:, :, None], 3, axis=2)
        if rgb_np.shape[2] == 4:
            rgb_np = rgb_np[:, :, :3]
        valid_image = bool(rgb_np.size and rgb_np.shape[2] == 3)
        reason = reasons.ACCEPT if valid_image else 'EMPTY_IMAGE'
        if warmup:
            valid_image = False
            reason = 'WARMUP'
        image_name = (self._episode_id + '_g' + str(self._generation) + '_'
                      + str(self._sequence['front_rgb']) + '.png')
        image_path = self.images_dir / image_name
        from PIL import Image
        Image.fromarray(rgb_np, mode='RGB').save(image_path, format='PNG')
        image_bytes = image_path.read_bytes()
        image_sha = obs_mod.payload_sha256(image_bytes)
        intrinsics = (data.intrinsic_matrices[0].detach().cpu().numpy()
                      .astype(float).tolist())
        cam_pos = data.pos_w[0].detach().cpu().numpy().astype(float).tolist()
        cam_quat = data.quat_w_world[0].detach().cpu().numpy().astype(float).tolist()
        depth_center = None
        if depth is not None:
            d = depth[0].detach().cpu().numpy()
            if d.ndim == 3:
                d = d[:, :, 0]
            depth_center = float(d[d.shape[0] // 2, d.shape[1] // 2])
        seq_rgb = self._sequence['front_rgb']
        self._sequence['front_rgb'] += 1
        timestamps = {
            'capture_sim_ns': capture_sim_ns,
            'ready_sim_ns': capture_sim_ns,
            'consume_sim_ns': capture_sim_ns,
            'capture_host_ns': capture_host_ns,
            'ready_host_ns': ready_host_ns,
            'consume_host_ns': time.monotonic_ns(),
            'capture_clock_id': 'sim_physics',
            'ready_clock_id': 'host_monotonic',
            'consume_clock_id': 'host_monotonic',
            'exposure_uncertainty_ns': int(round(self.physics_dt_s * 1e9)),
        }
        header = self._header('front_rgb', 10, seq_rgb, capture_sim_ns,
                              capture_sim_ns, capture_sim_ns)
        record = obs_mod.make_observation(
            header=header, context=self._context(),
            sensor={
                'sensor_id': 'front_rgb', 'modality': 'RGB_IMAGE',
                'frame_id': 'body_flu', 'source': 'SIM_RENDER_RGB',
                'units': 'px', 'intrinsics': intrinsics,
                'extrinsics': {'position_world_m': cam_pos,
                               'quat_w_world': cam_quat,
                               'camera_convention': 'world'},
                'shape': list(rgb_np.shape), 'dtype': 'uint8'},
            timestamps=timestamps,
            payload={'ref': image_path.as_posix(), 'sha256': image_sha,
                     'shape': list(rgb_np.shape), 'dtype': 'uint8',
                     'size_bytes': len(image_bytes)},
            validity={'valid': valid_image, 'reason': reason})
        self._append(record, 'front_rgb', warmup=warmup)

        # Distance channel: rendered center-pixel depth along camera optical +X.
        # A PhysX raycast is attempted only as an auxiliary independent reference;
        # no-hit/out-of-range is explicit and never replaced by zero.
        import omni.physx
        direction = self._quat_rotate(cam_quat, [1.0, 0.0, 0.0])
        origin = [cam_pos[i] + direction[i] * 0.01 for i in range(3)]
        max_range = float(self.config['range']['max_range_m'])
        try:
            hit = omni.physx.get_physx_scene_query_interface().raycast_closest(
                tuple(origin), tuple(direction), max_range)
        except Exception as error:  # noqa: BLE001
            hit = {'hit': False, 'error': repr(error)}
        raycast = {'hit': bool(hit.get('hit')),
                   'distance_m': (float(hit.get('distance'))
                                  if hit.get('hit') else None),
                   'collision': (str(hit.get('collision', ''))
                                 if hit.get('hit') else ''),
                   'max_range_m': max_range}
        range_value = depth_center
        if warmup:
            range_valid, range_reason = False, 'WARMUP'
        elif range_value is None:
            range_valid, range_reason = False, 'NO_RETURN'
        elif not math.isfinite(float(range_value)):
            range_valid, range_reason = False, 'NON_FINITE'
        elif float(range_value) <= 0.0 or float(range_value) > max_range:
            range_valid, range_reason = False, 'OUT_OF_RANGE'
        else:
            range_valid, range_reason = True, reasons.ACCEPT
        seq_range = self._sequence['front_depth']
        self._sequence['front_depth'] += 1
        range_payload_bytes = json.dumps(
            {'depth_m': range_value, 'raycast_reference': raycast,
             'origin_world_m': origin, 'direction_world': direction,
             'max_range_m': max_range, 'definition':
             'SIM_RENDER_DEPTH_CENTER_PIXEL_DISTANCE_TO_IMAGE_PLANE'},
            sort_keys=True).encode('utf-8')
        range_sha = obs_mod.payload_sha256(range_payload_bytes)
        range_record = obs_mod.make_observation(
            header=self._header('front_depth', 11, seq_range, capture_sim_ns,
                                capture_sim_ns, capture_sim_ns),
            context=self._context(),
            sensor={
                'sensor_id': 'front_depth', 'modality': 'SIM_RENDER_DEPTH',
                'frame_id': 'body_flu', 'source': 'SIM_RENDER_DEPTH',
                'units': 'm', 'intrinsics': {}, 'extrinsics': {
                    'position_world_m': origin,
                    'quat_w_world': cam_quat,
                    'direction_world': direction,
                    'definition': 'center_pixel_distance_to_image_plane; not_tof'},
                'shape': [1], 'dtype': 'float64'},
            timestamps=dict(timestamps),
            payload={'ref': '', 'sha256': range_sha, 'shape': [1],
                     'dtype': 'float64', 'size_bytes': len(range_payload_bytes)},
            validity={'valid': range_valid, 'reason': range_reason})
        self._append(range_record, 'front_depth', warmup=warmup,
                     extra={'range_m': range_value, 'depth_center_m': depth_center,
                            'raycast_reference': raycast})

    def _append(self, record, sensor_id, *, warmup, extra=None):
        decision = {'accepted': False, 'reason': 'WARMUP', 'age_ns': None}
        if not warmup:
            decision = self._gate.accept(
                record, record.timestamps['consume_sim_ns'])
        data = record.to_dict()
        data['phase'] = 'WARMUP' if warmup else 'RUN'
        data['gate'] = decision
        data['sensor_key'] = sensor_id
        if extra:
            data['range_reference'] = extra
        self._records_stream.write(json.dumps(data, ensure_ascii=False) + '\n')
        self._records_stream.flush()
        self._samples.append(data)
        ep = self._summary['episodes'][-1]
        ep['sample_count'] += 1
        if decision['accepted']:
            ep['valid_count'] += 1
        else:
            ep['invalid_reasons'][decision['reason']] = (
                ep['invalid_reasons'].get(decision['reason'], 0) + 1)
        if sensor_id == 'front_rgb':
            self._episode_images.append(data['payload']['ref'])
            self._images.append(data['payload']['ref'])

    @staticmethod
    def _quat_rotate(quat_wxyz, vector):
        w, x, y, z = [float(v) for v in quat_wxyz]
        vx, vy, vz = [float(v) for v in vector]
        # Quaternion rotation without importing a math runtime.
        tx = 2.0 * (y * vz - z * vy)
        ty = 2.0 * (z * vx - x * vz)
        tz = 2.0 * (x * vy - y * vx)
        return [vx + w * tx + (y * tz - z * ty),
                vy + w * ty + (z * tx - x * tz),
                vz + w * tz + (x * ty - y * tx)]

    def end_episode(self):
        self._active = False

    def close(self):
        self.end_episode()
        self._close_camera()
        try:
            self._records_stream.close()
        except Exception:
            pass
        self._summary['sample_count'] = len(self._samples)
        self._summary['accepted_count'] = sum(
            1 for sample in self._samples if sample['gate']['accepted'])
        self._summary['invalid_count'] = len(self._samples) - self._summary[
            'accepted_count']
        self._summary['images'] = self._images
        (self.output_dir / 'summary.json').write_text(
            json.dumps(self._summary, indent=2, ensure_ascii=False) + '\n',
            encoding='utf-8')
        return self._summary
