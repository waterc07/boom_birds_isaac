"""Standard-library-only runtime contracts.

Two schema generations coexist deliberately:

- boom_birds.velocity.v1 (types/frames/timebase): historical ENU velocity
  contract, still covered by its original regression tests.
- boom_birds.message.v2.0 / boom_birds.action.v2.0 (context/action_v2/
  admission/ownership/lifecycle): V2.2 four-level context, clock domains,
  PX4 boot isolation, observation provenance, non-renewable TTL, admission
  and control ownership.

Nothing here grants flight permission and no module in this package may
import Torch, Isaac, camera or MAVLink libraries.
"""
