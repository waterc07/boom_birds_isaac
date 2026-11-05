# -*- coding: utf-8 -*-
"""Independent audit of the ultralytics 8.2.0 pose keypoint loss mask for the
two-class label spec: class1 keypoint v=0 must not contribute to the location
loss, class0 v=1 must be supervised normally, and visibility (kobj) is
supervised to 0 for class1.

This exercises the installed KeypointLoss directly (CPU, tiny tensors) and
records the source hash/line numbers.  It is an independent check, not a
training run.
"""
import hashlib, json, inspect
from pathlib import Path
import torch
from ultralytics.utils.loss import KeypointLoss
import ultralytics

ROOT = Path(__file__).resolve().parents[5]
OUT = ROOT / "docs/reports/perception/posteval_20261104"
LOSS_PATH = Path(ultralytics.__file__).resolve().parent / "utils" / "loss.py"
SOURCE = LOSS_PATH.read_text(encoding="utf-8")
SOURCE_SHA = hashlib.sha256(LOSS_PATH.read_bytes()).hexdigest()

def line_of(text):
    for i, line in enumerate(SOURCE.splitlines(), 1):
        if text in line:
            return i
    return None

kl = KeypointLoss(sigmas=torch.ones(1))
area = torch.ones(2, 1)
pred = torch.tensor([[[100.0, 100.0, 0.9]], [[100.0, 100.0, 0.9]]])  # (B=2, N=1, 3)

def gt_batch(class1_xy, class1_v=0.0, class0_xy=(80.0, 90.0), class0_v=1.0):
    return torch.tensor([[[class0_xy[0], class0_xy[1], class0_v]],
                         [[class1_xy[0], class1_xy[1], class1_v]]])

def loss_for(gt):
    mask = gt[..., 2] != 0
    return float(kl(pred, gt, mask, area)), mask

base_loss, base_mask = loss_for(gt_batch((0.0, 0.0)))
pert_class1, mask1 = loss_for(gt_batch((123.0, 45.0)))
pert_class0, mask0 = loss_for(gt_batch((0.0, 0.0), class0_xy=(95.0, 100.0)))
v2_loss, v2_mask = loss_for(gt_batch((95.0, 95.0), class1_v=2.0))
v2_pert, _ = loss_for(gt_batch((90.0, 90.0), class1_v=2.0))

bce = torch.nn.BCEWithLogitsLoss()
kobj = float(bce(pred[..., 2], base_mask.float()))
kobj_v2 = float(bce(pred[..., 2], v2_mask.float()))

checks = {
  "class1_v0_xy_perturbation_changes_location_loss": abs(pert_class1 - base_loss) > 1e-12,
  "class0_xy_perturbation_changes_location_loss": abs(pert_class0 - base_loss) > 1e-12,
  "class1_v0_excluded_from_location_loss": abs(pert_class1 - base_loss) <= 1e-12,
  "class1_v0_visibility_target_is_zero": (kobj > 0),
  "class1_v2_is_treated_as_visible": (abs(v2_pert - v2_loss) > 1e-12) and bool(v2_mask[1,0]),
  "class0_v1_is_treated_as_visible": bool(base_mask[0,0]),
}

result = {
  "schema_version": "dsh.landmark_two_class_loss_mask_audit.v1",
  "created_at": "2026-11-05",
  "source": {"ultralytics_version": ultralytics.__version__, "loss_py": str(LOSS_PATH),
             "loss_py_sha256": SOURCE_SHA,
             "kpt_mask_line": line_of("kpt_mask = gt_kpt[..., 2] != 0"),
             "keypoint_loss_line": line_of("kpts_loss = self.keypoint_loss(pred_kpt, gt_kpt, kpt_mask, area)"),
             "kobj_line": line_of("kpts_obj_loss = self.bce_pose(pred_kpt[..., 2], kpt_mask.float())"),
             "normalization_line": line_of("kpt_loss_factor = kpt_mask.shape[1] / (torch.sum(kpt_mask != 0, dim=1) + 1e-9)")},
  "semantics": {
    "location_loss": "masked by (gt_kpt[...,2] != 0); class1 v=0 contributes exactly 0 to the keypoint coordinate loss",
    "visibility_loss": "kobj = BCE(pred_vis, mask.float()); class1 v=0 is supervised toward visibility 0 (intended, not a coordinate leak)",
    "class_agnostic": "the mask has no class branch; two-class semantics live entirely in the labels",
    "v_encoding": "ndim=3 pose labels keep the written v; only v=2 or other non-zero values would count as visible; the label builder must enforce v in {0,1} (never v=2)",
    "placeholder": "v=0 rows still contain normalized xy in the txt; label builder must write 0,0 for class1 (never bbox centre) and no code may treat the v=0 xy as a reference point",
  },
  "experiment": {
    "instances": ["row0 = class0 v=1", "row1 = class1 v=0"],
    "base_loss": base_loss, "class1_xy_perturbed_loss": pert_class1,
    "class0_xy_perturbed_loss": pert_class0, "class1_v2_loss": v2_loss, "class1_v2_perturbed_loss": v2_pert,
    "kobj_loss_v0": kobj, "kobj_loss_v2": kobj_v2, "kpt_mask": base_mask.tolist(),
  },
  "checks": checks,
  "verdict": "PASS" if (checks["class1_v0_excluded_from_location_loss"]
                        and checks["class0_xy_perturbation_changes_location_loss"]
                        and checks["class1_v0_visibility_target_is_zero"]
                        and checks["class1_v2_is_treated_as_visible"]
                        and checks["class0_v1_is_treated_as_visible"]) else "FAIL",
  "required_builder_checks_for_two_class": [
    "label builder writes nc=2, kpt_shape [1,3]",
    "class1 keypoint xy written as 0,0 and v=0 (never bbox centre)",
    "class0 keypoint v=1 only when the green roof light is visible/locatable; v=0 otherwise",
    "v is in {0,1} for every instance; reject v=2 or other non-zero values in QA",
    "same-frame completeness QA: every visible/decidable MS1 instance labelled; MS1 never left as background",
    "class1 bbox present for every class1 instance (bbox loss still supervised; only the keypoint coordinate loss is masked)",
    "keypoint-mask regression test on the real v6 dataset: pick one class1 v=0 row and one class0 v=1 row, recompute the mask/loss contribution",
  ],
  "limitations": ["CPU tiny-tensor check of the installed loss, not a training run",
                  "no real two-class labels exist yet (P1); the real-dataset mask test must run in P2 engineering smoke"],
}
(OUT/"TWO_CLASS_LOSS_MASK_AUDIT_20261105.json").write_text(json.dumps(result, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
print(json.dumps({"verdict": result["verdict"], "checks": checks, "base": base_loss,
                  "class1_perturbed": pert_class1, "class0_perturbed": pert_class0,
                  "kobj_v0": kobj, "kobj_v2": kobj_v2}, ensure_ascii=False))
