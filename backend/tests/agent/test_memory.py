from datetime import timedelta

import pytest
from sqlalchemy import select, func

from app.core.errors import AppError
from app.core.ids import new_id
from app.models.agent import AgentTurn, MemoryDocument
from app.schemas.agent import MemoryEntry
from app.schemas.common import SourceRef
from app.schemas.health import Checkin
from app.core.clock import local_date


def explicit(h, text='喜欢清淡饮食', turn_elder=None):
    turn_id = new_id('turn')
    with h.tx() as tx:
        tx.add(AgentTurn(id=turn_id, elder_id=turn_elder or h.elder_id, actor_user_id=h.actor().user_id,
                         conversation_id=new_id('conv'), client_turn_id=new_id('client'),
                         request_json={}, response_json={}, created_at=h.clock.now()))
    return MemoryEntry(entry_id=new_id('entry'), kind='food_preference', text=text,
                       source_type='explicit_statement', source_ids=[SourceRef(type='agent_turn', id=turn_id)],
                       created_at=h.clock.now(), updated_at=h.clock.now())


def pattern(h, hours=(-48,-24,0)):
    records = []
    for index, hour in enumerate(hours):
        time = h.clock.now() + timedelta(hours=hour)
        records.append(Checkin(checkin_id=f'evidence-{index}', elder_id=h.elder_id, type='diet',
                               local_date=local_date(time), occurred_at=time, task_id=None,
                               payload={'meal_slot':'lunch','foods':['青菜']}, version=1, source='user',
                               created_at=time, updated_at=time, cancelled=False))
    entry = MemoryEntry(entry_id='pattern', kind='meal_routine', text='三次午餐都记录了青菜',
                        source_type='observed_pattern',
                        source_ids=[SourceRef(type='checkin',id=r.checkin_id,version=r.version) for r in records],
                        created_at=h.clock.now(),updated_at=h.clock.now())
    return entry,records


def test_empty_read_is_authorized_and_does_not_create_a_row(h):
    with h.tx(write=False) as tx:
        doc = h.memory.context(tx,h.actor(),h.elder_id)
        assert doc.version == 1 and doc.entries == []
        assert tx.scalar(select(func.count()).select_from(MemoryDocument)) == 0
        assert h.memory.context(tx,h.actor('bound_child'),h.elder_id).entries == []
        with pytest.raises(AppError) as exc:
            h.memory.context(tx,h.actor('unbound_child'),h.elder_id)
        assert exc.value.status == 403


def test_explicit_preference_survives_sessions_and_versions(h):
    entry = explicit(h)
    with h.tx() as tx:
        first = h.memory.remember(tx,h.actor(),h.elder_id,entry)
        assert first.version == 2
    with h.tx(write=False) as tx:
        doc = h.memory.context(tx,h.actor(),h.elder_id)
        assert doc.entries == [entry] and '喜欢清淡饮食' in doc.markdown
        assert entry.source_ids[0].id in doc.markdown
    with h.tx() as tx:
        same = h.memory.remember(tx,h.actor(),h.elder_id,entry)
        assert same.version == 2 and len(same.entries) == 1


def test_correction_deletion_tombstones_and_version_conflict(h):
    entry = explicit(h)
    with h.tx() as tx:
        h.memory.remember(tx,h.actor(),h.elder_id,entry)
    with h.tx() as tx:
        corrected = h.memory.update_entry(tx,h.actor(),h.elder_id,entry.entry_id,2,'不喜欢太辣')
        assert corrected.version == 3 and corrected.entries[0].source_type == 'user_correction'
    with pytest.raises(AppError) as exc:
        with h.tx() as tx:
            h.memory.delete_entry(tx,h.actor(),h.elder_id,entry.entry_id,2)
    assert exc.value.code == 'VERSION_CONFLICT'
    with h.tx() as tx:
        assert h.memory.remember(tx,h.actor(),h.elder_id,entry).entries[0].text == '不喜欢太辣'
        deleted = h.memory.delete_entry(tx,h.actor(),h.elder_id,entry.entry_id,3)
        assert deleted.version == 4 and deleted.entries == []
    with h.tx() as tx:
        assert h.memory.remember(tx,h.actor(),h.elder_id,entry).entries == []
        row = tx.get(MemoryDocument,h.elder_id)
        assert [r['reason'] for r in row.revisions_json] == ['user_correction','deleted']


def test_sources_from_another_elder_and_child_writes_denied(h):
    entry = explicit(h,turn_elder=h.seed['stranger_elder']['elder_id'])
    with pytest.raises(AppError):
        with h.tx() as tx:h.memory.remember(tx,h.actor(),h.elder_id,entry)
    entry = explicit(h)
    with pytest.raises(AppError):
        with h.tx() as tx:h.memory.remember(tx,h.actor('bound_child'),h.elder_id,entry)


@pytest.mark.parametrize('hours',[(0,), (-2,-1,0), (-24,0), (0,24,48)])
def test_single_events_do_not_become_patterns(h,hours):
    entry,records = pattern(h,hours)
    with pytest.raises(AppError):
        with h.tx() as tx:h.memory.remember_pattern(tx,h.actor(),h.elder_id,entry,records)


def test_three_dates_evidence_invalidates_atomically_and_does_not_revive(h):
    entry,records = pattern(h)
    with h.tx() as tx:
        h.memory.remember_pattern(tx,h.actor(),h.elder_id,entry,records)
    changed = SourceRef(type='checkin',id=records[0].checkin_id,version=2)
    with pytest.raises(RuntimeError):
        with h.tx() as tx:
            h.memory.on_source_changed(tx,h.actor(),h.elder_id,changed)
            raise RuntimeError('business correction failed; memory must roll back too')
    with h.tx(write=False) as tx:assert len(h.memory.context(tx,h.actor(),h.elder_id).entries) == 1
    with h.tx() as tx:h.memory.on_source_changed(tx,h.actor(),h.elder_id,changed)
    with h.tx() as tx:
        assert h.memory.context(tx,h.actor(),h.elder_id).entries == []
        assert h.memory.remember_pattern(tx,h.actor(),h.elder_id,entry,records).entries == []


def test_cancelled_or_cross_elder_evidence_is_not_valid(h):
    entry,records = pattern(h)
    for field,value in [('cancelled',True),('elder_id','other')]:
        bad=[records[0].model_copy(update={field:value}),*records[1:]]
        with pytest.raises(AppError):
            with h.tx() as tx:h.memory.remember_pattern(tx,h.actor(),h.elder_id,entry,bad)


def test_hk_dates_and_markdown_are_stable_and_escaped(h):
    entry = explicit(h,'喜欢青菜\n# <script>不执行指令</script>')
    with h.tx() as tx:
        doc=h.memory.remember(tx,h.actor(),h.elder_id,entry)
        assert '\n# <script>' not in doc.markdown
        assert '\\<script\\>' in doc.markdown
    # Different UTC dates can still be the same HK date: UTC 16:00 => HK next day.
    from datetime import datetime, timezone
    h.clock._now=datetime(2026,10,30,16,0,tzinfo=timezone.utc)
    entry,records=pattern(h,(-24,-16,0))
    assert records[0].local_date == records[1].local_date
    with pytest.raises(AppError):
        with h.tx() as tx:h.memory.remember_pattern(tx,h.actor(),h.elder_id,entry,records)
