from boom_birds.evaluation.action_transport import DelayedActionQueue

def test_delayed_action_order_and_clear():
    q=DelayedActionQueue()
    q.schedule(0.2,'late',(0.2,)); q.schedule(0.1,'early',(0.1,))
    assert [a for a,_ in q.take_due(0.05)] == []
    due=q.take_due(0.15)
    assert len(due)==1 and due[0][0]=='early'
    assert q.pending()==1
    assert q.clear()==1 and q.pending()==0
