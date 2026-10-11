"""Planning sensitivity calculations, stdlib only. Not a flight/vision implementation."""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "planning" / "budget_results.json"


def calculate():
    pixel = []
    for fov in (50, 70, 90):
        for width in (160, 320, 640, 1280):
            fx = width / (2 * math.tan(math.radians(fov / 2)))
            for size in (0.135, 0.150):
                for distance in (1, 3, 5, 10, 14):
                    for angle in (0, 45, 60):
                        pixel.append(dict(hfov_deg=fov, width_px=width,
                                          target_width_m=size, distance_m=distance,
                                          obliquity_deg=angle,
                                          projected_width_px=fx * size * math.cos(math.radians(angle)) / distance))
    fx = 1280 / (2 * math.tan(math.radians(35)))
    stereo = [dict(distance_m=z, disparity_px=fx * 0.0676718 / z,
                   first_order_depth_sigma_m=z*z*0.5/(fx*0.0676718)) for z in (1, 3, 5, 10, 14)]
    return {
        "status": "ASSUMED sensitivity calculations; no hardware or recognition PASS",
        "input_provenance": {
            "target_150mm": "USER_PROVIDED approximate; enemy-base small armor confirmed 2026-10-10; exact mounting/geometry unverified",
            "target_135mm": "2026 robot specification V1.3 p71, ordinary small armor only",
            "route_14m": "28m historical field divided by two, not actual trajectory",
            "mass_formula": "inherited 2027 preview snapshot, original PDF not obtained",
            "stereo_baseline_m": "0.0676718 candidate calibration, not verified",
            "hfov_disparity_error_velocity_acceleration_power": "ASSUMED examples, not measurements"
        },
        "pixel_sweep": pixel,
        "stereo": stereo,
        "mass": [dict(max_edge_mm=d, max_mass_g=min(249, 322.5-1.225*d), min_mass_g=150) for d in (118, 120)],
        "geometry": {"prop_diameter_mm": 2.2*25.4,
                     "square_coplanar_no_overlap_min_side_mm": 2*2.2*25.4,
                     "total_guard_and_gap_room_at_120mm": 120-2*2.2*25.4,
                     "limitation": "axis-aligned square layout; excludes deformation and motor/guard clearance"},
        "navigation": {"cross_track_14m": [dict(yaw_error_deg=a, error_m=14*math.sin(math.radians(a))) for a in (1, 3, 5)],
                       "velocity_bias_0_05mps_for_10s_m": 0.05*10},
        "flight_time": [dict(speed_mps=v, one_way_s=14/v+13, round_trip_s=28/v+13,
                             reconnaissance_round_trip_with_10s_dwell_s=28/v+23)
                        for v in (0.5, 1, 1.5, 2)],
        "time_assumptions": "13s = takeoff3 + alignment4 + landing3 + reserve3; hypothetical, accelerations/detours omitted",
        "energy": {"nominal_3s_300mah_Wh": 11.1*0.3,
                   "consumption_30s": [dict(average_power_W=p, energy_Wh=p*30/3600) for p in (60, 100, 150)],
                   "limitation": "nominal voltage/label capacity; no discharge, peak current or return proof"},
        "stopping": [dict(speed_mps=v, distance_m=v*0.15+v*v/(2*2)+0.2+0.06+0.1) for v in (0.5, 1, 2)],
        "stopping_assumptions": "latency0.15s, deceleration2m/s2, position bound0.2m, radius0.06m, margin0.1m; all proposed",
        "velocity_yaw_rate_type_mask": 1+2+4+64+128+256+1024,
    }


if __name__ == "__main__":
    result = calculate()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    fx = 1280 / (2 * math.tan(math.radians(35)))
    interception = {
        "status": "ASSUMED sensitivity, no interception performance PASS",
        "source": "2026 V1.3 historical nominal 42.5mm projectile; speed scenarios not 2027 final rule",
        "hfov_deg": 70, "image_width_px": 1280, "projectile_diameter_m": 0.0425,
        "camera_fps_requested": 60, "policy_hz_candidate": 20,
        "scenarios": [dict(speed_mps_assumed=v, distance_m=d, pixel_diameter_px=fx*0.0425/d,
                           constant_speed_remaining_s=d/v, travel_one_frame_m=v/60,
                           travel_one_policy_tick_m=v/20) for v in (12, 16.5, 25) for d in (3, 5, 10)],
        "translation_example": {"distance_m": 0.5, "acceleration_mps2_assumed": 2,
                                "from_rest_min_motion_s": math.sqrt(2*0.5/2),
                                "limits": "optimistic kinematic example; excludes latency, speed limit, settling; not measured"},
    }
    (OUT.parent / "interception_budget.json").write_text(json.dumps(interception, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"Wrote {OUT}: {len(result['pixel_sweep'])} pixel scenarios")
    print(json.dumps({k: v for k, v in result.items() if k != "pixel_sweep"}, ensure_ascii=False, indent=2))
