"""C follows the shared system principal and trusted internal source parameter."""
from dataclasses import replace

import pytest
from sqlalchemy import select, func

from app.contracts.context import Actor, SYSTEM_ACTOR, SYSTEM_USER_ID
from app.core.errors import AppError
from app.models.agent import AgentAction
from app.models.health import Checkin
from app.schemas.agent import ActionDecision, AgentTurnWrite
from app.schemas.common import SourceRef
from app.schemas.enums import Role


def pending(h):
    turn = h.turn(AgentTurnWrite(elder_id=h.elder_id, client_turn_id='trusted-source',
                                text='我散步了20分钟', mock_fixture_id='exercise_walk'))
    return turn.actions[0].action_id


def test_old_checkin_signature_is_501_without_execution_or_confirmation(h):
    action = pending(h)
    calls = []
    class Old:
        def create_or_update(self, tx, actor, elder_id, payload, checkin_id=None):
            calls.append(payload)
            raise AssertionError('An incompatible B port must never be executed')
    h.agent.services = replace(h.agent.services, checkins=Old())
    with pytest.raises(AppError) as exc:
        with h.tx() as tx:
            h.agent.decide(tx, h.actor(), action, ActionDecision(decision='confirm'))
    assert exc.value.status == 501 and exc.value.code == 'MODULE_NOT_IMPLEMENTED'
    assert calls == []
    with h.tx(write=False) as tx:
        row = tx.get(AgentAction, action)
        assert row.status == 'pending' and row.result_json is None
        assert tx.scalar(select(func.count()).select_from(Checkin)) == 0


def test_port_ignoring_provenance_rolls_back_its_write(h):
    action = pending(h)
    real = h.tools
    class Wrong:
        def create_or_update(self, tx, actor, elder_id, payload, checkin_id=None, *, source='user'):
            assert source == 'agent_confirmed'
            return real.create_or_update(tx, actor, elder_id, payload, source='user')
    h.agent.services = replace(h.agent.services, checkins=Wrong())
    with pytest.raises(AppError) as exc:
        with h.tx() as tx:
            h.agent.decide(tx, h.actor(), action, ActionDecision(decision='confirm'))
    assert exc.value.status == 502
    with h.tx(write=False) as tx:
        assert tx.scalar(select(func.count()).select_from(Checkin)) == 0
        assert tx.get(AgentAction, action).status == 'pending'


def test_business_typeerror_is_not_retried_without_source_or_masked(h):
    action = pending(h)
    class Broken:
        def create_or_update(self, *args, source='user'):
            assert source == 'agent_confirmed'
            raise TypeError('real B implementation bug')
    h.agent.services = replace(h.agent.services, checkins=Broken())
    with pytest.raises(TypeError, match='real B implementation bug'):
        with h.tx() as tx:
            h.agent.decide(tx, h.actor(), action, ActionDecision(decision='confirm'))


def test_system_source_invalidation_delegates_to_the_same_access_port(h):
    access = h.memory.access
    calls = []
    class RecordingAccess:
        def require_elder_access(self, tx, actor, elder_id, write_scope='read'):
            calls.append((actor, elder_id, write_scope))
            return access.require_elder_access(tx, actor, elder_id, write_scope)
    h.memory.access = RecordingAccess()
    with h.tx() as tx:
        h.memory.on_source_changed(tx, SYSTEM_ACTOR, h.elder_id, SourceRef(type='profile', id=h.elder_id, version=2))
        h.memory.context(tx, SYSTEM_ACTOR, h.elder_id)
    assert calls == [(SYSTEM_ACTOR, h.elder_id, 'read')] * 2
    for actor, elder in [(SYSTEM_ACTOR, 'missing-elder'), (h.actor('stranger_elder'), h.elder_id)]:
        with pytest.raises(AppError) as exc:
            with h.tx() as tx:
                h.memory.on_source_changed(tx, actor, elder, SourceRef(type='profile', id=elder))
        assert exc.value.status == 403


@pytest.mark.parametrize('actor', [SYSTEM_ACTOR, Actor(SYSTEM_USER_ID, Role.child)])
def test_system_principal_cannot_pose_as_a_user_for_agent_or_memory_edits(h, actor):
    action = pending(h)
    with pytest.raises(AppError) as exc:
        with h.tx() as tx:
            h.agent.decide(tx, actor, action, ActionDecision(decision='confirm'))
    assert exc.value.status in {403, 404}
    for operation in ['update_entry', 'delete_entry']:
        with pytest.raises(AppError) as exc:
            with h.tx() as tx:
                args = [tx, actor, h.elder_id, 'missing-entry', 1]
                if operation == 'update_entry':
                    args.append('系统不能代替本人修正')
                getattr(h.memory, operation)(*args)
        assert exc.value.status == 403
