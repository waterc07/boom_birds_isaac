#!/usr/bin/env python
"""Deterministic near-duplicate detection and representative sampling for dev frames.

Rule set (frozen before any image inspection; no model/detector score is used):

R1 roster
    Accepted frames (accepted=true) of the dev groups declared in
    configs/perception/landmark_split_freeze_v2.json with split in {train, val}.
    Frame order inside a group = (episode order as listed in the freeze, sequence).

R2 exact duplicates
    Frames with the same sha256 inside one group collapse to the first frame in
    roster order (SHA_DUPLICATE); duplicates are never cluster representatives and
    are never selected. Cross-group / cross-split exact duplicates are reported as
    an upstream split defect.

R3 near-duplicate clustering
    Two unique accepted frames of one group are joined when BOTH hold:
      * dHash64 (9x8 grayscale horizontal-gradient sign) Hamming distance <= 6
        (64-bit hash; <= 9.4% of bits changed), and
      * mean absolute difference of the 64x48 grayscale thumbnails <= 3.0
        (0..255 scale; <= 1.2% of full scale).
    Transitive closure (union-find) yields clusters. Rationale: consecutive
    captures are 0.25 s apart; identical static reset poses differ by render noise
    only. The joint threshold pair is conservative: it merges near-identical
    frames but keeps frames with a real viewpoint change separate.

R4 cluster representative (medoid)
    Among the unique members, the smallest sum of dHash64 Hamming distances to the
    other members; ties -> smaller roster order. No appearance score beyond the
    dedup hashes is used.

R5 fixed-stride representative sampling
    Clusters of a group are sorted in roster order. Static groups (< 32 accepted
    frames) contribute all cluster representatives. Dynamic groups get a budget
    proportional to their cluster count with a minimum, and picks are endpoints +
    midpoint systematic: idx_i = floor((i + 0.5) * n / k), i = 0..k-1, plus first
    and last cluster index. No randomness.

R6 capture-derived coverage overrides (computed from observations.jsonl camera
    extrinsics + a triangulated tower estimate; acquisition metadata, not a model
    score):
      * cluster holding the minimum and maximum distance-to-tower frame,
      * cluster holding the maximum |relative bearing| frame,
      * one cluster holding a predicted left/right frame-edge truncation,
      * one cluster with 3 <= green_pixels <= 6 (small but usable reference),
        otherwise one with 1 <= green_pixels < 3 (unusable reference).
    Each override replaces the nearest fixed-stride pick (pilot replace_nearest
    rule) so the group budget stays fixed. Static groups already take all clusters.

R7 budgets
    train 160 / val 110 total (task budget ranges 150-200 / 100-120). Static groups
    keep all cluster representatives; dynamic budgets are allocated by largest
    remainder proportional to cluster count, minimum 8 per dynamic group.

R8 exclusions are recorded, never silent
    Every roster frame gets exactly one of: SELECTED, SELECTED_BY_OVERRIDE,
    NOT_ACCEPTED, SHA_DUPLICATE, NEAR_DUPLICATE_OF_CLUSTER_REP,
    CLUSTER_NOT_SELECTED_BY_STRIDE.

Outputs (gitignored, task write scope):
    outputs/perception/dev_annotations_20261104/dedup_sampling_report.json
    outputs/perception/dev_annotations_20261104/selection_train.json
    outputs/perception/dev_annotations_20261104/selection_val.json

Source frames are read only; no file is written outside the task write scope.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

REPO_DEFAULT = Path(r"E:\isaac\proj_boom_birds")

DHASH_HAMMING_MAX = 6
MAD_MAX = 3.0
STATIC_GROUP_THRESHOLD = 32
DEFAULT_TRAIN_BUDGET = 160
DEFAULT_VAL_BUDGET = 110
MIN_PER_DYNAMIC_GROUP = 8
TOWER_WORLD_M = (11.52, -0.01, 1.25)  # triangulated estimate; capture-derived aid, not truth
HALF_BAR_M = 0.85
GREEN_REF_MIN_PX = 3


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dhash64(gray: np.ndarray) -> int:
    image = Image.fromarray(gray).resize((9, 8), Image.BILINEAR)
    arr = np.asarray(image, dtype=np.int16)
    diff = (arr[:, 1:] >= arr[:, :-1]).reshape(-1)
    value = 0
    for bit in diff:
        value = (value << 1) | int(bit)
    return value


def ahash64(gray: np.ndarray) -> int:
    arr = np.asarray(Image.fromarray(gray).resize((8, 8), Image.BILINEAR), dtype=np.float32)
    bits = (arr > arr.mean()).reshape(-1)
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def hamming(a: int, b: int) -> int:
    return int((a ^ b).bit_count())


def green_stats(image_rgb: np.ndarray):
    """Spec v2.1 green cue: g>=90, g-r>=25, g-b>=25; largest 4-connected component."""
    r = image_rgb[..., 0].astype(np.int16)
    g = image_rgb[..., 1].astype(np.int16)
    b = image_rgb[..., 2].astype(np.int16)
    mask = ((g >= 90) & ((g - r) >= 25) & ((g - b) >= 25)).astype(np.uint8)
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=4)
    if count <= 1:
        return 0, None
    areas = stats[1:, cv2.CC_STAT_AREA]
    index = 1 + int(np.argmax(areas))
    area = int(stats[index, cv2.CC_STAT_AREA])
    centroid = (float(centroids[index][0]), float(centroids[index][1])) if area > 0 else None
    return area, centroid


def wrap_deg(value: float) -> float:
    return (value + 180.0) % 360.0 - 180.0


def yaw_from_quat(qw: float, qx: float, qy: float, qz: float) -> float:
    return math.atan2(2.0 * (qw * qz + qx * qy), 1.0 - 2.0 * (qy * qy + qz * qz))


def load_conditions(repo: Path, datasets_meta: dict):
    """Per-frame capture-derived conditions for the datasets used by dev groups."""
    datasets = {}
    for dataset in datasets_meta:
        obs_path = repo / datasets_meta[dataset]["observations"]
        conditions = {}
        if obs_path.is_file():
            for line in obs_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                sensor = record.get("sensor", {})
                if sensor.get("sensor_id") != "front_rgb":
                    continue
                if not record.get("gate", {}).get("accepted"):
                    continue
                ref = record.get("payload", {}).get("ref") or ""
                frame_id = Path(ref).name
                position = np.array(sensor["extrinsics"]["position_world_m"], dtype=float)
                qw, qx, qy, qz = sensor["extrinsics"]["quat_w_world"]
                yaw = yaw_from_quat(qw, qx, qy, qz)
                delta = np.array(TOWER_WORLD_M, dtype=float) - position
                distance = float(np.linalg.norm(delta))
                bearing = wrap_deg(math.degrees(math.atan2(delta[1], delta[0]) - yaw))
                fx = float(sensor["intrinsics"][0][0])
                cx = float(sensor["intrinsics"][0][2])
                u_pred = cx - fx * math.tan(math.radians(bearing))
                half_ang = math.degrees(math.atan(HALF_BAR_M / max(distance, 1e-6)))
                u_left = cx - fx * math.tan(math.radians(bearing + half_ang))
                u_right = cx - fx * math.tan(math.radians(bearing - half_ang))
                conditions[frame_id] = {
                    "camera_position_world_m": [round(float(v), 4) for v in position],
                    "yaw_rad": round(yaw, 5),
                    "distance_to_tower_m": round(distance, 3),
                    "bearing_relative_deg": round(bearing, 2),
                    "predicted_target_u_px": round(u_pred, 1),
                    "predicted_tower_span_u_px": [round(u_left, 1), round(u_right, 1)],
                    "predicted_truncated_left": bool(u_left < 0.0),
                    "predicted_truncated_right": bool(u_right > cx * 2.0),
                    "tower_estimate_source": "triangulated_tower_estimate_capture_aid",
                }
        datasets[dataset] = conditions
    return datasets


def parse_frame(frame_id: str):
    stem = frame_id[:-4] if frame_id.endswith(".png") else frame_id
    episode, rest = stem.rsplit("-follow_only_g", 1)
    generation_s, sequence_s = rest.rsplit("_", 1)
    return episode, int(generation_s), int(sequence_s)


def features_for(repo: Path, image_path: Path, cache: dict):
    key = str(image_path)
    if key in cache:
        return cache[key]
    with Image.open(image_path) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    gray = np.asarray(Image.fromarray(rgb).convert("L"), dtype=np.uint8)
    thumb = np.asarray(Image.fromarray(gray).resize((64, 48), Image.BILINEAR), dtype=np.uint8)
    green_pixels, green_centroid = green_stats(rgb)
    value = {
        "width": int(rgb.shape[1]),
        "height": int(rgb.shape[0]),
        "thumb": thumb,
        "dhash64": dhash64(gray),
        "ahash64": ahash64(gray),
        "green_pixels": green_pixels,
        "green_centroid_uv": None if green_centroid is None else
        [round(green_centroid[0], 1), round(green_centroid[1], 1)],
    }
    cache[key] = value
    return value


class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def cluster_records(records, thumbs):
    """R2/R3. Returns clusters (root -> member indices incl. duplicates), duplicate_of."""
    duplicate_of = {}
    first_by_sha = {}
    for index, record in enumerate(records):
        sha = record["sha256"]
        if sha in first_by_sha:
            duplicate_of[index] = first_by_sha[sha]
        else:
            first_by_sha[sha] = index
    unique = [i for i in range(len(records)) if i not in duplicate_of]
    union = UnionFind(len(records))
    for index in duplicate_of:
        union.union(index, duplicate_of[index])
    hashes = [records[i]["dhash64"] for i in unique]
    pairs = 0
    near = 0
    for a_pos in range(len(unique)):
        for b_pos in range(a_pos + 1, len(unique)):
            pairs += 1
            if hamming(hashes[a_pos], hashes[b_pos]) <= DHASH_HAMMING_MAX:
                near += 1
                ia, ib = unique[a_pos], unique[b_pos]
                mad = float(np.abs(thumbs[ia].astype(np.int16) - thumbs[ib].astype(np.int16)).mean())
                if mad <= MAD_MAX:
                    union.union(ia, ib)
    clusters = defaultdict(list)
    for index in range(len(records)):
        clusters[union.find(index)].append(index)
    return clusters, duplicate_of, {"pairs_compared": pairs, "pairs_passing_dhash": near}


def build_group(repo: Path, group: dict, datasets_meta: dict, conditions: dict, cache: dict):
    dataset = group["dataset"]
    root = repo / datasets_meta[dataset]["root"]
    episodes = {name: index for index, name in enumerate(group.get("episodes") or [])}
    roster = []
    not_accepted = []
    for frame in group["frames"]:
        frame_id = frame["frame_id"]
        episode, generation, sequence = parse_frame(frame_id)
        order = (episodes.get(episode, len(episodes)), generation, sequence)
        if not frame.get("accepted"):
            not_accepted.append({"frame_id": frame_id, "episode": episode,
                                 "generation": generation, "sequence": sequence,
                                 "sha256": frame.get("sha256"), "order": list(order)})
            continue
        roster.append({"frame_id": frame_id, "episode": episode,
                       "generation": generation, "sequence": sequence,
                       "sha256": frame["sha256"], "order": order,
                       "image_path": root / "images" / frame_id})
    roster.sort(key=lambda item: item["order"])
    thumbs = []
    for record in roster:
        features = features_for(repo, record.pop("image_path"), cache)
        record.update({key: value for key, value in features.items() if key != "thumb"})
        thumbs.append(features["thumb"])
        condition = dict(conditions.get(record["frame_id"], {}))
        condition["green_pixels"] = record["green_pixels"]
        condition["green_centroid_uv"] = record["green_centroid_uv"]
        record["conditions"] = condition
    clusters, duplicate_of, cluster_stats = cluster_records(roster, thumbs)
    ordered = sorted(clusters.values(),
                     key=lambda members: min(roster[i]["order"] for i in members))
    cluster_meta = []
    cluster_id_of = {}
    for index, members in enumerate(ordered):
        cluster_id = "%s_c%04d" % (group["group_id"], index)
        members.sort(key=lambda i: roster[i]["order"])
        unique_members = [i for i in members if i not in duplicate_of]
        if not unique_members:
            unique_members = members
        for i in members:
            cluster_id_of[i] = cluster_id
        best = None
        for i in unique_members:
            total = sum(hamming(roster[i]["dhash64"], roster[j]["dhash64"])
                        for j in unique_members if j != i)
            key = (total, roster[i]["order"])
            if best is None or key < best[0]:
                best = (key, i)
        medoid = best[1]
        cluster_meta.append({
            "cluster_id": cluster_id,
            "cluster_index": index,
            "members": [roster[i]["frame_id"] for i in members],
            "representative": roster[medoid]["frame_id"],
            "roster_order": [list(roster[i]["order"]) for i in members],
        })
    return roster, not_accepted, cluster_meta, cluster_id_of, duplicate_of, cluster_stats


def allocate_budgets(groups_meta, budgets):
    plan = {}
    for group_id, meta in groups_meta.items():
        if meta["static"]:
            plan[group_id] = len(meta["cluster_meta"])
        else:
            plan[group_id] = min(len(meta["cluster_meta"]), MIN_PER_DYNAMIC_GROUP)
    for split in sorted(set(meta["split"] for meta in groups_meta.values())):
        total_budget = budgets[split]
        static_ids = [gid for gid, meta in groups_meta.items()
                      if meta["split"] == split and meta["static"]]
        dynamic_ids = [gid for gid, meta in groups_meta.items()
                       if meta["split"] == split and not meta["static"]]
        fixed = sum(plan[gid] for gid in static_ids)
        remaining = max(0, total_budget - fixed - sum(plan[gid] for gid in dynamic_ids))
        if not dynamic_ids or remaining == 0:
            continue
        capacity = [len(groups_meta[gid]["cluster_meta"]) - plan[gid] for gid in dynamic_ids]
        weights = [max(0, cap) for cap in capacity]
        if sum(weights) == 0:
            continue
        raw = [remaining * weight / float(sum(weights)) for weight in weights]
        extra = [min(int(math.floor(value)), capacity[pos])
                 for pos, value in enumerate(raw)]
        remainder = remaining - sum(extra)
        order = sorted(range(len(dynamic_ids)), key=lambda pos: -(raw[pos] - math.floor(raw[pos])))
        position = 0
        while remainder > 0 and position < len(order) * 3:
            index = order[position % len(order)]
            if extra[index] < capacity[index]:
                extra[index] += 1
                remainder -= 1
            position += 1
        for gid, add in zip(dynamic_ids, extra):
            plan[gid] += int(add)
    return plan


def fixed_stride_indices(n: int, k: int):
    if k >= n:
        return list(range(n))
    if k == 1:
        return [n // 2]
    if k == 2:
        return [0, n - 1]
    picks = [0, n - 1]
    inner = k - 2
    for i in range(inner):
        index = int(math.floor((i + 0.5) * n / inner))
        picks.append(min(max(index, 1), n - 2))
    return sorted(set(picks))


def replace_nearest(selected, candidate):
    if candidate in selected:
        return selected, False
    best = None
    for old in selected:
        distance = abs(old - candidate)
        if best is None or distance < best[0]:
            best = (distance, old)
    return sorted(set(candidate if item == best[1] else item for item in selected)), True


def apply_overrides(selected, cluster_meta, roster):
    notes = []
    selected = list(selected)
    if not cluster_meta:
        return selected, notes
    frame_meta = {record["frame_id"]: record for record in roster}
    accepted = list(frame_meta)
    candidates = []
    distances = [(frame_meta[f]["conditions"].get("distance_to_tower_m"), f) for f in accepted]
    distances = [(d, f) for d, f in distances if d is not None]
    if distances:
        candidates.append(("force_min_distance", min(distances)[1]))
        candidates.append(("force_max_distance", max(distances)[1]))
    bearings = [(abs(frame_meta[f]["conditions"].get("bearing_relative_deg") or 0.0), f) for f in accepted]
    if bearings:
        candidates.append(("force_max_abs_bearing", max(bearings)[1]))
    trunc = [f for f in accepted
             if frame_meta[f]["conditions"].get("predicted_truncated_left")
             or frame_meta[f]["conditions"].get("predicted_truncated_right")]
    if trunc:
        candidates.append(("force_predicted_truncation",
                           sorted(trunc, key=lambda f: -abs(frame_meta[f]["conditions"].get("bearing_relative_deg", 0.0)))[0]))
    small = [f for f in accepted if 3 <= (frame_meta[f]["conditions"].get("green_pixels") or 0) <= 6]
    if small:
        candidates.append(("force_small_usable_green", sorted(small)[0]))
    else:
        tiny = [f for f in accepted if 1 <= (frame_meta[f]["conditions"].get("green_pixels") or 0) < 3]
        if tiny:
            candidates.append(("force_unusable_green", sorted(tiny)[0]))
    selected_set = set(selected)
    for note, frame_id in candidates:
        cluster_index = next((meta["cluster_index"] for meta in cluster_meta
                              if frame_id in meta["members"]), None)
        if cluster_index is None or cluster_index in selected_set:
            continue
        selected, replaced = replace_nearest(selected, cluster_index)
        selected_set = set(selected)
        notes.append({"override": note, "frame_id": frame_id,
                      "cluster_index": cluster_index, "replaced_nearest": replaced})
    return selected, notes


def summarise(rows):
    def bucket(value, edges, labels):
        if value is None:
            return "UNKNOWN"
        for index, edge in enumerate(edges):
            if value <= edge:
                return labels[index]
        return labels[-1]
    summary = {"selected_frames": len(rows), "distance_bins": defaultdict(int),
               "bearing_bins": defaultdict(int), "green_bins": defaultdict(int),
               "predicted_truncation": defaultdict(int)}
    for row in rows:
        condition = row["conditions"]
        summary["distance_bins"][bucket(condition.get("distance_to_tower_m"), [2.5, 4.0, 5.5, 7.0],
                                        ["near<=2.5", "2.5-4.0", "4.0-5.5", "5.5-7.0", "far>7.0"])] += 1
        summary["bearing_bins"][bucket(abs(condition.get("bearing_relative_deg") or 0.0), [10.0, 25.0, 45.0],
                                       ["|b|<=10", "10<|b|<=25", "25<|b|<=45", "|b|>45"])] += 1
        summary["green_bins"][bucket(condition.get("green_pixels"), [2, 6, 15],
                                     ["green<3", "3-6", "7-15", "green>15"])] += 1
        for edge in ("predicted_truncated_left", "predicted_truncated_right"):
            if condition.get(edge):
                summary["predicted_truncation"][edge.replace("predicted_truncated_", "")] += 1
    for key in ("distance_bins", "bearing_bins", "green_bins", "predicted_truncation"):
        summary[key] = dict(sorted(summary[key].items()))
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=str(REPO_DEFAULT))
    parser.add_argument("--freeze", default="configs/perception/landmark_split_freeze_v2.json")
    parser.add_argument("--extra-freeze", action="append", default=[],
                        help="auxiliary group descriptor(s); merged with the main split freeze")
    parser.add_argument("--out-dir", default="outputs/perception/dev_annotations_20261104")
    parser.add_argument("--train-budget", type=int, default=DEFAULT_TRAIN_BUDGET)
    parser.add_argument("--val-budget", type=int, default=DEFAULT_VAL_BUDGET)
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    freeze_path = repo / args.freeze
    freeze_bytes = freeze_path.read_bytes()
    freeze = json.loads(freeze_bytes)
    freeze_docs = [freeze]
    extra_freeze_records = []
    for extra_rel in args.extra_freeze:
        extra_path = repo / extra_rel
        extra_bytes = extra_path.read_bytes()
        extra_doc = json.loads(extra_bytes)
        freeze_docs.append(extra_doc)
        extra_freeze_records.append({"path": extra_rel,
                                     "sha256": hashlib.sha256(extra_bytes).hexdigest(),
                                     "freeze_id": extra_doc.get("freeze_id"),
                                     "status": extra_doc.get("status")})
    datasets_meta = {}
    for doc in freeze_docs:
        datasets_meta.update(doc.get("datasets") or {})
    merged_groups = [group for doc in freeze_docs for group in (doc.get("groups") or [])]
    conditions_by_dataset = load_conditions(repo, datasets_meta)
    out_dir = repo / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = {}

    dev_groups = [group for group in merged_groups if group["split"] in ("train", "val")]
    groups_meta = {}
    for group in dev_groups:
        group_id = group["group_id"]
        roster, not_accepted, cluster_meta, cluster_id_of, duplicate_of, cluster_stats = build_group(
            repo, group, datasets_meta, conditions_by_dataset[group["dataset"]], cache)
        groups_meta[group_id] = {
            "group": group, "split": group["split"], "family": group["family_id"],
            "static": len(roster) < STATIC_GROUP_THRESHOLD, "roster": roster,
            "not_accepted": not_accepted, "cluster_meta": cluster_meta,
            "cluster_id_of": cluster_id_of, "duplicate_of": duplicate_of,
            "cluster_stats": cluster_stats,
        }
        print("group %-24s accepted=%4d clusters=%4d static=%s"
              % (group_id, len(roster), len(cluster_meta), groups_meta[group_id]["static"]),
              flush=True)

    cross_duplicates = []
    sha_owner = {}
    for group in dev_groups:
        meta = groups_meta[group["group_id"]]
        for record in meta["roster"]:
            key = record["sha256"]
            if key in sha_owner:
                owner = sha_owner[key]
                if owner["group_id"] != group["group_id"] or owner["split"] != meta["split"]:
                    cross_duplicates.append({"frame_id": record["frame_id"],
                                             "group_id": group["group_id"],
                                             "other": owner})
            else:
                sha_owner[key] = {"frame_id": record["frame_id"],
                                  "group_id": group["group_id"], "split": meta["split"]}

    budgets = {"train": args.train_budget, "val": args.val_budget}
    plan = allocate_budgets(groups_meta, budgets)

    report = {
        "schema_version": "dsh.landmark_dev_dedup_sampling.v1",
        "generated_at_local": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "generated_by": "scripts/landmark_dedup_sampling.py",
        "script_sha256": sha256_file(Path(__file__).resolve()),
        "freeze": {"path": args.freeze, "sha256": hashlib.sha256(freeze_bytes).hexdigest(),
                   "freeze_sha256": freeze.get("freeze_sha256"), "freeze_id": freeze.get("freeze_id")},
        "extra_freezes": extra_freeze_records,
        "rules": {
            "rule_id": "dev_dedup_stride_v1",
            "frozen_before_image_inspection": True,
            "no_model_or_detector_score_used": True,
            "R1_roster": "accepted frames of dev groups (train/val) in freeze v2; order = (episode, sequence)",
            "R2_exact": "same sha256 in group -> first roster frame; duplicates never selected; cross-group duplicates reported",
            "R3_near_duplicate": {"dhash64_hamming_max": DHASH_HAMMING_MAX, "thumb_mad_max": MAD_MAX,
                                  "thumb_scale": "64x48 grayscale, 0..255 mean absolute difference"},
            "R4_representative": "cluster medoid by sum dHash hamming among unique members; tie -> smaller roster order",
            "R5_fixed_stride": "static groups = all reps; dynamic = endpoints + midpoint systematic floor((i+0.5)*n/k)",
            "R6_overrides": ["force_min_distance", "force_max_distance", "force_max_abs_bearing",
                             "force_predicted_truncation", "force_small_usable_green", "force_unusable_green"],
            "R7_budgets": {"train": args.train_budget, "val": args.val_budget,
                           "min_per_dynamic_group": MIN_PER_DYNAMIC_GROUP,
                           "static_group_accepted_threshold": STATIC_GROUP_THRESHOLD},
            "R8_exclusion_recording": "every roster frame has exactly one status; SELECTED only for cluster reps",
            "tower_estimate": {"world_m": list(TOWER_WORLD_M),
                               "provenance": "triangulated capture aid (existing labels + camera poses); not truth; coverage metadata only",
                               "half_bar_m": HALF_BAR_M},
            "green_rule": "g>=90, g-r>=25, g-b>=25, largest 4-connected component (spec v2.1 reference criterion)",
            "R9_extra_dev_batch": "T9 first dev batch consumed via --extra-freeze: group = capture episode, split per Lead instruction 2026-11-04 (inner_north/static_low -> val; inner_south/static_high/static_negative -> train); HN1/HN2 second batch will be appended to val only",
        },
        "splits": {},
        "cross_group_sha_duplicates": cross_duplicates,
    }

    for split in ("train", "val"):
        group_rows = []
        selected_frames = []
        total_selected = 0
        for group in dev_groups:
            if group["split"] != split:
                continue
            meta = groups_meta[group["group_id"]]
            group_id = group["group_id"]
            n_clusters = len(meta["cluster_meta"])
            k = plan[group_id]
            if meta["static"]:
                base = list(range(n_clusters))
            else:
                base = fixed_stride_indices(n_clusters, k)
            selected, override_notes = apply_overrides(base, meta["cluster_meta"], meta["roster"])
            selected = sorted(set(selected))
            if len(selected) != k:
                print("WARNING %s selected %d != plan %d" % (group_id, len(selected), k), flush=True)
            rep_by_cluster = {index: meta["cluster_meta"][index]["representative"]
                              for index in range(n_clusters)}
            selected_reps = {rep_by_cluster[index] for index in selected}
            override_frames = {note["frame_id"] for note in override_notes}
            roster = meta["roster"]
            frame_rows = []
            for position, record in enumerate(roster):
                cluster_id = meta["cluster_id_of"][position]
                cluster_index = int(cluster_id.rsplit("c", 1)[1])
                frame_id = record["frame_id"]
                if position in meta["duplicate_of"]:
                    status = "SHA_DUPLICATE"
                elif frame_id in selected_reps:
                    status = "SELECTED_BY_OVERRIDE" if frame_id in override_frames else "SELECTED"
                elif frame_id == rep_by_cluster[cluster_index]:
                    status = "CLUSTER_NOT_SELECTED_BY_STRIDE"
                else:
                    status = "NEAR_DUPLICATE_OF_CLUSTER_REP"
                frame_rows.append({
                    "frame_id": frame_id, "episode": record["episode"],
                    "generation": record["generation"], "sequence": record["sequence"],
                    "sha256": record["sha256"], "cluster_id": cluster_id,
                    "cluster_representative": rep_by_cluster[cluster_index],
                    "dhash64": record["dhash64"], "ahash64": record["ahash64"],
                    "green_pixels": record["green_pixels"],
                    "green_centroid_uv": record["green_centroid_uv"],
                    "conditions": record["conditions"], "status": status,
                })
            for item in meta["not_accepted"]:
                frame_rows.append({
                    "frame_id": item["frame_id"], "episode": item["episode"],
                    "generation": item["generation"], "sequence": item["sequence"],
                    "sha256": item["sha256"], "status": "NOT_ACCEPTED",
                    "cluster_id": None, "cluster_representative": None,
                    "dhash64": None, "ahash64": None, "green_pixels": None,
                    "green_centroid_uv": None, "conditions": {},
                })
            frame_rows.sort(key=lambda row: (row["episode"], row["generation"], row["sequence"]))
            selected_rows = [row for row in frame_rows if row["status"] in ("SELECTED", "SELECTED_BY_OVERRIDE")]
            total_selected += len(selected_rows)
            selected_frames.extend(selected_rows)
            status_counts = defaultdict(int)
            for row in frame_rows:
                status_counts[row["status"]] += 1
            group_rows.append({
                "group_id": group_id, "family_id": group["family_id"],
                "dataset": group["dataset"], "split": split, "static": meta["static"],
                "accepted_frames": len(roster), "clusters": n_clusters,
                "cluster_stats": meta["cluster_stats"], "planned_frames": k,
                "selected_frames": len(selected_rows),
                "selected": [row["frame_id"] for row in selected_rows],
                "coverage": summarise(selected_rows),
                "overrides": override_notes,
                "status_counts": dict(sorted(status_counts.items())),
                "clusters_meta": meta["cluster_meta"],
                "frames": frame_rows,
            })
        report["splits"][split] = {"budget": budgets[split],
                                   "selected_total": total_selected,
                                   "groups": group_rows}
        selection_doc = {
            "schema_version": "dsh.landmark_dev_selection.v1",
            "generated_at_local": report["generated_at_local"],
            "script_sha256": report["script_sha256"],
            "freeze": report["freeze"],
            "rule_id": "dev_dedup_stride_v1",
            "split": split,
            "total_frames": total_selected,
            "frames": [
                {
                    "frame_id": row["frame_id"], "episode": row["episode"],
                    "generation": row["generation"], "sequence": row["sequence"],
                    "sha256": row["sha256"], "cluster_id": row["cluster_id"],
                    "green_pixels": row["green_pixels"],
                    "green_centroid_uv": row["green_centroid_uv"],
                    "conditions": row["conditions"], "selected_by": row["status"],
                    "group_id": group_row["group_id"],
                    "family_id": group_row["family_id"],
                    "dataset": group_row["dataset"],
                }
                for group_row in group_rows for row in group_row["frames"]
                if row["status"] in ("SELECTED", "SELECTED_BY_OVERRIDE")
            ],
        }
        (out_dir / ("selection_%s.json" % split)).write_text(
            json.dumps(selection_doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("%s selected %d / budget %d" % (split, total_selected, budgets[split]))

    report_path = out_dir / "dedup_sampling_report.json"
    report_path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
