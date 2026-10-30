"""Non-destructive, repeatable framework accounts; NOT the DEMO01 experience."""
import argparse, json
from sqlalchemy import select
from app.core.config import Settings
from app.core.clock import SystemClock, Clock
from app.core.db import build_engine, sessions, create_tables
from app.core.uow import UnitOfWork
from app.models.identity import User, ElderProfile, FamilyBinding

ACCOUNTS = {"elder": "19900000001", "bound_child": "19900000002", "unbound_child": "19900000003", "stranger_elder": "19900000004"}
def framework_seed(factory, clock: Clock) -> dict:
    result = {}
    with UnitOfWork(factory) as uow:
        tx = uow.session
        for label, phone in ACCOUNTS.items():
            role = "child" if "child" in label else "elder"
            user = tx.scalar(select(User).where(User.phone == phone))
            if user is not None and (user.demo_id != "framework-v1" or user.role != role):
                raise RuntimeError("Seed phone collision; refusing to modify existing data")
            if user is None:
                user = User(phone=phone, role=role, demo_id="framework-v1")
                tx.add(user)
                tx.flush()
            result[label] = {"phone": phone, "role": role, "user_id": user.id}
            if role == "elder":
                elder = tx.scalar(select(ElderProfile).where(ElderProfile.owner_user_id == user.id))
                if elder is None:
                    settings = {"meals": [{"slot": s, "local_time": t, "enabled": True} for s,t in [("breakfast","08:30"),("lunch","12:30"),("dinner","18:30")]], "exercise": {"enabled": True,"local_time":"17:00"}, "daily_summary": {"enabled":True,"local_time":"20:30"},"voice_enabled":True}
                    elder = ElderProfile(owner_user_id=user.id, profile_json={"display_name": "框架测试老人" if label == "elder" else "陌生老人", "birth_date": "1958-05-12", "sex": "female", "conditions": [], "allergies": [], "medical_notes": "framework seed", "source": "demo_seed"}, reminder_settings_json=settings, updated_at=clock.now())
                    tx.add(elder)
                    tx.flush()
                result[label]['elder_id'] = elder.id
        binding = tx.scalar(select(FamilyBinding).where(FamilyBinding.elder_id == result['elder']['elder_id'], FamilyBinding.child_user_id == result['bound_child']['user_id']))
        if binding is None:
            tx.add(FamilyBinding(elder_id=result['elder']['elder_id'], child_user_id=result['bound_child']['user_id'], relationship="子女"))
        uow.commit()
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['framework'], default='framework')
    parser.parse_args()
    settings = Settings()
    engine = build_engine(settings.data_dir, settings.database_url)
    try:
        create_tables(engine)
        print(json.dumps(framework_seed(sessions(engine), SystemClock()), ensure_ascii=False, indent=2))
    finally:
        engine.dispose()
if __name__ == '__main__':
    main()
