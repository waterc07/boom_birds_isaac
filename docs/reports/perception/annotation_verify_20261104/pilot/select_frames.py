"""Deterministic stratified pilot selection from the T5 final-pool seal.

Rule (frozen before looking at any image; no model/detector score is used):
 R1 roster: seal groups' accepted frames only (accepted=true), sorted by integer sequence.
 R2 base: midpoint systematic sampling: idx_i = floor((i+0.5)*n/k), i=0..k-1, deduped.
 R3 lmf_backoff override: force-include the max-distance and min-distance frames.
 R4 lmf_edge override: force-include one truncated=false frame if any exists.
 R5 lmf_side_negative: all accepted frames (3).
"""
import json
import math
from pathlib import Path

REPO = Path(r"E:\isaac\proj_boom_birds")
BASE = REPO / "docs/reports/perception/annotation_verify_20261104"
seal = json.loads((REPO / "configs/perception/landmark_final_pool_seal_v1.json").read_text(encoding="utf-8"))
cond = json.loads((REPO / "docs/reports/perception/capture_20261104/frame_conditions.json").read_text(encoding="utf-8"))
cond_by_id = {row["frame_id"]: row for row in cond}

K = {
    "lmf_sweep": 8,
    "lmf_backoff": 6,
    "lmf_near": 5,
    "lmf_edge": 6,
    "lmf_similar_negative": 6,
    "lmf_side_negative": 3,
}

def seq_of(frame_id):
    return int(frame_id.rsplit("_", 1)[1].split(".")[0])

def selects(sequence, k):
    n = len(sequence)
    idx = []
    for i in range(k):
        j = int(math.floor((i + 0.5) * n / k))
        j = min(j, n - 1)
        if j not in idx:
            idx.append(j)
    return [sequence[j] for j in idx]

def replace_nearest(selected, candidate, sequence):
    if candidate in selected:
        return selected
    pos = sequence.index(candidate)
    best = None
    for old in selected:
        d = abs(sequence.index(old) - pos)
        if best is None or d < best[0]:
            best = (d, old)
    out = [candidate if s == best[1] else s for s in selected]
    return out

by_family = {}
for group in seal["groups"]:
    fam = group["family_id"]
    frames = [f["frame_id"] for f in group["frames"] if f.get("accepted")]
    frames.sort(key=seq_of)
    by_family[fam] = frames

selected = {}
notes = {}
for fam, frames in by_family.items():
    k = K[fam]
    picks = selects(frames, k)
    if fam == "lmf_backoff":
        by_dist = sorted(frames, key=lambda f: cond_by_id[f]["distance_to_tower_m"])
        picks = replace_nearest(picks, by_dist[-1], frames)
        picks = replace_nearest(picks, by_dist[0], frames)
        notes[fam] = "forced max-distance and min-distance frames"
    if fam == "lmf_edge":
        untrunc = [f for f in frames
                   if not cond_by_id[f]["truncated_right"] and not cond_by_id[f]["truncated_left"]]
        if untrunc:
            picks = replace_nearest(picks, untrunc[0], frames)
            notes[fam] = "forced one truncated=false frame to cover the boundary"
        else:
            notes[fam] = "no truncated=false frame exists"
    if fam == "lmf_side_negative":
        picks = list(frames)
        notes[fam] = "all accepted frames (3)"
    picks = sorted(set(picks), key=seq_of)
    selected[fam] = picks

rows = []
for fam in by_family:
    for fid in selected[fam]:
        c = cond_by_id[fid]
        rows.append({
            "frame_id": fid,
            "family_id": fam,
            "group_id": "g_" + fam,
            "sequence": c["sequence"],
            "distance_to_tower_m": c["distance_to_tower_m"],
            "bearing_relative_deg": c["bearing_relative_deg"],
            "truncated_right": c["truncated_right"],
            "truncated_left": c["truncated_left"],
            "green_pixels": c["green_pixels"],
            "green_centroid_uv": c["green_centroid_uv"],
            "image_sha256": c["image_sha256"],
        })
rows.sort(key=lambda r: (list(by_family).index(r["family_id"]), r["sequence"]))

doc = {
    "schema_version": "dsh.landmark_final_pilot_selection.v1",
    "seal": {
        "path": "configs/perception/landmark_final_pool_seal_v1.json",
        "freeze_sha256": seal["freeze_sha256"],
        "freeze_id": seal["freeze_id"],
        "status": seal["status"],
    },
    "condition_source": "docs/reports/perception/capture_20261104/frame_conditions.json",
    "spec_v2": "configs/perception/landmark_annotation_spec_v2.json",
    "rule": {
        "rule_id": "pilot_midpoint_systematic_v1",
        "text": "R1 accepted frames from seal, sorted by integer sequence; R2 midpoint systematic sampling idx=floor((i+0.5)*n/k); R3 backoff force-include max/min distance frames; R4 edge force-include one truncated=false frame; R5 side_negative=all 3. No model/detector score used; capture-derived pose/distance/truncation metadata only.",
        "k_per_family": K,
        "frozen_before_image_inspection": True,
    },
    "counts": {fam: len(selected[fam]) for fam in selected},
    "total_frames": len(rows),
    "family_notes": notes,
    "frames": rows,
}
out = BASE / "pilot/selection.json"
out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("frames:", len(rows), "per family:", doc["counts"])
for fam, picks in selected.items():
    print(fam, len(picks), picks)
print("wrote", out)
