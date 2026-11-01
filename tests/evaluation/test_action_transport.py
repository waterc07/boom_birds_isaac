from boom_birds.evaluation.action_transport import DelayedActionQueue, DelayedVelocityExecutor

def test_delayed_action_order_and_clear():
    q=DelayedActionQueue()
    q.schedule(0.2,'late',(0.2,)); q.schedule(0.1,'early',(0.1,))
    assert [a for a,_ in q.take_due(0.05)] == []
    due=q.take_due(0.15)
    assert len(due)==1 and due[0][0]=='early'
    assert q.pending()==1
    assert q.clear()==1 and q.pending()==0

def test_delayed_executor_delivers_after_delay_and_rejects_expired():
    import math
    from boom_birds.sim.velocity_control import (VehicleParams, VehicleState,
        VelocityExecutor, VelocitySetpoint)
    params = VehicleParams(mass_kg=0.0282, inertia_kgm2=(1.4e-5,1.4e-5,2.1e-5))
    state = VehicleState((0,0,1.0),(0,0,0),(1,0,0,0),(0,0,0))
    wrapper = DelayedVelocityExecutor(VelocityExecutor(params), 0.10)
    sp = VelocitySetpoint(0.5,0,0,0,0.0,0.20,0)
    first = wrapper.step(sp, state, 0.05)
    assert first.reason == 'REJECT_NO_CACHED_ACTION'
    second = wrapper.step(None, state, 0.16)
    assert second.reason == 'ACCEPT'
    late = VelocitySetpoint(0.5,0,0,0,0.0,0.10,0)
    wrapper.step(late, state, 0.30)
    result = wrapper.step(None, state, 0.45)
    assert result.reason == 'ACTION_EXPIRED' and result.degraded