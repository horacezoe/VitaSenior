import secrets
from datetime import timedelta
from sqlalchemy import select, func
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session
from app.models.identity import User, AuthChallenge, AuthSession, ElderProfile, FamilyBinding, CommunityRecord, DemoIdentity
from app.core.clock import Clock, local_date
from app.core.auth import token_hash, require_elder_access
from app.core.errors import AppError
from app.core.ids import new_id
from app.contracts.context import Actor
from app.fixtures.identity import EMPTY_DRAFT, DEFAULT_PERSONA, UNMATCHED_PERSONA
from app.fixtures.history import HISTORY_DAYS
from app.schemas.health import MedicationPlanWrite
from app.schemas.identity import (
    Account, CodeRequest, CodeResponse, ConfirmWrite, DemoExperience, DemoWrite, LoginRequest,
    LoginResponse, MatchResult, MatchWrite, Me, Profile, ProfileFields, User as UserDTO, ElderSummary,
    DemoPersona, DemoPersonas,
)
from app.services.identity_views import default_reminder_settings, elder_summary, profile_from_row, version_conflict

DEMO_PHONE_PREFIX = "170"

class IdentityService:
    def __init__(self, clock: Clock):
        self.clock = clock

    def issue_challenge(self, tx: Session, payload: CodeRequest) -> CodeResponse:
        user = tx.scalar(select(User).where(User.phone == payload.phone))
        if not user:
            # Challenge rows need an account, but no profile or session is created
            # until verification succeeds. Repeated requests share the same account.
            tx.execute(insert(User).values(phone=payload.phone, role=payload.role.value,
                                           demo_id=new_id("signup"))
                       .on_conflict_do_nothing(index_elements=[User.phone]))
            user = tx.scalar(select(User).where(User.phone == payload.phone))
        if user.role != payload.role.value:
            raise AppError(401, "LOGIN_CODE_INVALID", "Phone is registered with another role")
        count = tx.scalar(select(func.count()).select_from(AuthChallenge).where(AuthChallenge.user_id == user.id, AuthChallenge.created_at > self.clock.now() - timedelta(minutes=5)))
        if count >= 5:
            raise AppError(429, "RATE_LIMITED", "Too many challenges", retryable=True)
        challenge = AuthChallenge(user_id=user.id, created_at=self.clock.now(), expires_at=self.clock.now() + timedelta(seconds=300))
        tx.add(challenge)
        tx.flush()
        return CodeResponse(challenge_id=challenge.id)

    def login(self, tx: Session, payload: LoginRequest) -> LoginResponse:
        challenge = tx.get(AuthChallenge, payload.challenge_id)
        user = tx.get(User, challenge.user_id) if challenge else None
        if not challenge or not user or user.phone != payload.phone or user.role != payload.role.value or challenge.purpose != "login":
            raise AppError(401, "LOGIN_CODE_INVALID", "Challenge does not match the account")
        if challenge.consumed_at is not None or challenge.expires_at <= self.clock.now():
            raise AppError(401, "CHALLENGE_EXPIRED", "Challenge expired or consumed")
        if payload.code != "123456":
            raise AppError(401, "LOGIN_CODE_INVALID", "Invalid demo code")
        if user.role == "elder" and user.demo_id.startswith("signup_"):
            # An unrecognized account starts with no community identity or health
            # facts. Existing confirmed profiles survive every subsequent login.
            tx.execute(insert(ElderProfile).values(
                owner_user_id=user.id,
                profile_json={**EMPTY_DRAFT, "source": "community_mock"},
                reminder_settings_json=default_reminder_settings(),
                onboarding_status="draft", version=1, updated_at=self.clock.now(),
            ).on_conflict_do_nothing(index_elements=[ElderProfile.owner_user_id]))
            tx.execute(insert(DemoIdentity).values(
                user_id=user.id, demo_id=user.demo_id, phone=user.phone,
                community_record_id=None,
            ).on_conflict_do_nothing(index_elements=[DemoIdentity.user_id]))
        token = secrets.token_urlsafe(32)
        expires_at = self.clock.now() + timedelta(hours=48)
        challenge.consumed_at = self.clock.now()
        tx.add(AuthSession(user_id=user.id, token_hash=token_hash(token), expires_at=expires_at))
        tx.flush()
        me = self.me(tx, Actor(user.id, payload.role))
        return LoginResponse(**me.model_dump(), access_token=token, expires_at=expires_at)

    def me(self, tx: Session, actor: Actor) -> Me:
        user = tx.get(User, actor.user_id)
        owned = tx.scalar(select(ElderProfile).where(ElderProfile.owner_user_id == user.id))
        bound = tx.execute(select(ElderProfile, FamilyBinding).join(FamilyBinding, FamilyBinding.elder_id == ElderProfile.id).where(FamilyBinding.child_user_id == user.id, FamilyBinding.status == "active")).all()
        today = local_date(self.clock.now())
        return Me(user=UserDTO(user_id=user.id, phone=user.phone, role=user.role, demo_id=user.demo_id),
                  elder_id=owned.id if owned else None,
                  bound_elders=[elder_summary(elder, binding, today) for elder, binding in bound])

    # ---- DEMO01: independent pair of accounts + an unconfirmed elder draft ----

    def demo_personas(self, tx: Session) -> DemoPersonas:
        items = [DemoPersona(persona_id=r.id, display_name=r.sample_json["profile"]["display_name"],
                             conditions=r.sample_json["profile"]["conditions"], has_community_record=True)
                 for r in tx.scalars(select(CommunityRecord).order_by(CommunityRecord.id))]
        items.append(DemoPersona(persona_id=UNMATCHED_PERSONA, display_name="新住户（未建档）",
                                 conditions=[], has_community_record=False))
        return DemoPersonas(items=items)

    def create_demo_experience(self, tx: Session, payload: DemoWrite, *, entry_base: str) -> DemoExperience:
        record = tx.get(CommunityRecord, payload.persona_id)
        if record is None and payload.persona_id != UNMATCHED_PERSONA:
            raise AppError(422, "VALIDATION_ERROR", "Unknown demo persona")
        demo_id = new_id("demo")
        elder_phone = self._allocate_phone(tx)
        child_phone = self._allocate_phone(tx, taken={elder_phone})
        elder_user = User(phone=elder_phone, role="elder", demo_id=demo_id)
        child_user = User(phone=child_phone, role="child", demo_id=demo_id)
        tx.add_all([elder_user, child_user])
        tx.flush()
        elder = ElderProfile(
            owner_user_id=elder_user.id,
            profile_json={"display_name": "演示老人", "birth_date": None, "sex": "unknown",
                          "conditions": [], "allergies": [], "medical_notes": "", "source": "community_mock"},
            reminder_settings_json=default_reminder_settings(),
            onboarding_status="draft", version=1, updated_at=self.clock.now(),
        )
        tx.add(elder)
        tx.flush()
        tx.add(DemoIdentity(user_id=elder_user.id, demo_id=demo_id, phone=elder_phone,
                            community_record_id=record.id if record else None))
        tx.flush()
        # No family binding: the demo pair must still authenticate and bind explicitly.
        return DemoExperience(
            demo_id=demo_id, scenario=payload.scenario, is_mock=True,
            elder_account=Account(phone=elder_phone, role="elder"),
            child_account=Account(phone=child_phone, role="child"),
            elder_id=elder.id,
            entry_url=f"{entry_base}/demo/{demo_id}/elder",
            pair_entry_url=f"{entry_base}/demo/{demo_id}/pair",
            history_days=14,
            persona_id=payload.persona_id,
            persona_name=record.sample_json["profile"]["display_name"] if record else "新住户（未建档）",
        )

    def _allocate_phone(self, tx: Session, taken: set[str] | None = None) -> str:
        taken = taken or set()
        for _ in range(200):
            candidate = DEMO_PHONE_PREFIX + f"{secrets.randbelow(10 ** 8):08d}"
            if candidate in taken:
                continue
            if tx.scalar(select(User.id).where(User.phone == candidate)) is None:
                return candidate
        raise AppError(429, "RATE_LIMITED", "No demo phone number available, retry shortly", retryable=True)

    # ---- ONB01/ONB02: draft never touches the confirmed profile ---------------

    def match_onboarding(self, tx: Session, actor: Actor, elder_id: str, body: MatchWrite) -> MatchResult:
        require_elder_access(tx, actor, elder_id, "self")
        elder = tx.get(ElderProfile, elder_id)
        if elder.onboarding_status == "confirmed":
            raise AppError(409, "ONBOARDING_ALREADY_CONFIRMED", "Profile is already confirmed")
        owner = tx.get(User, elder.owner_user_id)
        identity = tx.get(DemoIdentity, owner.id)
        if identity and (identity.demo_id != owner.demo_id or identity.phone != owner.phone):
            raise AppError(409, "DEMO_IDENTITY_INVALID", "Demo account identity changed")
        record = None
        basis = "manual" if body.mode == "manual" else "demo_account"
        if body.mode != "manual":
            if body.sample_identity_key is not None:
                basis = "legacy_sample"
                candidate = tx.get(CommunityRecord, body.sample_identity_key)
                # Legacy framework/old demo accounts may still use the original sample.
                # Mapped accounts cannot choose another person's community identity.
                allowed = identity.community_record_id if identity else DEFAULT_PERSONA
                if candidate and candidate.id != allowed:
                    raise AppError(403, "ELDER_ACCESS_DENIED", "Sample does not match this demo identity")
                record = candidate
            elif identity and identity.community_record_id:
                record = tx.get(CommunityRecord, identity.community_record_id)
        existing = elder.onboarding_draft or {}
        # Returning to auto mode restores an intentional manual draft too. Only an
        # explicit switch to manual may replace a matched draft. Versions never mix.
        if (body.sample_identity_key is None and existing.get("result")
                and existing.get("profile_version") == elder.version
                and (body.mode == "auto" or existing.get("result", {}).get("match_basis") == "manual")):
            return MatchResult.model_validate(existing["result"])
        sample = record.sample_json if record else None
        matched = sample is not None
        profile_draft = {k: v for k, v in (sample["profile"] if matched else EMPTY_DRAFT).items() if k != "source"}
        plans = []
        templates = sample["medication_templates"] if matched else []
        for item in templates:
            data = dict(item["plan"])
            data["start_date"] = data.get("start_date") or (local_date(self.clock.now()) - timedelta(days=HISTORY_DAYS)).isoformat()
            plans.append(MedicationPlanWrite.model_validate(data))
        draft_id = new_id("draft")
        result = MatchResult(match_status="matched" if matched else "not_found", draft_id=draft_id,
                             profile_draft=ProfileFields.model_validate(profile_draft),
                             medication_plan_drafts=plans, is_mock=True, match_basis=basis,
                             community_name=record.community_name if record else None,
                             record_number=record.record_number if record else None)
        elder.onboarding_draft = {
            "draft_id": draft_id,
            "match_status": "matched" if matched else "not_found",
            "sample_identity_key": body.sample_identity_key,
            "face_asset_id": body.face_asset_id,
            "profile_draft": profile_draft,
            "medication_plan_drafts": [p.model_dump(mode="json") for p in plans],
            "medication_template_keys": [p["template_key"] for p in templates],
            "history_key": sample["history_key"] if matched else None,
            "profile_version": elder.version,
            "result": result.model_dump(mode="json"),
            # Only a real DEMO01 experience (demo_*) may import 14-day history.
            "demo_id": owner.demo_id if owner.demo_id.startswith("demo_") else None,
        }
        tx.flush()
        return result

    def confirm_onboarding(self, tx: Session, actor: Actor, elder_id: str, body: ConfirmWrite) -> tuple[Profile, dict]:
        """Promote the draft to the confirmed profile. Returns the profile plus the
        draft facts the callers need for cross-domain imports (plans / history)."""
        require_elder_access(tx, actor, elder_id, "self")
        elder = tx.get(ElderProfile, elder_id)
        if elder.onboarding_status == "confirmed":
            raise AppError(409, "ONBOARDING_ALREADY_CONFIRMED", "Profile is already confirmed")
        draft = dict(elder.onboarding_draft or {})
        if draft.get("draft_id") != body.draft_id:
            raise AppError(404, "NOT_FOUND", "Draft unavailable")
        if elder.version != body.expected_version:
            raise version_conflict(elder.version)
        raw = body.profile.model_dump(mode="json")
        raw["source"] = "user_confirmed"
        elder.profile_json = raw
        elder.onboarding_status = "confirmed"
        elder.version += 1
        elder.updated_at = self.clock.now()
        elder.onboarding_draft = None
        tx.flush()
        return profile_from_row(elder), draft
