import secrets
from datetime import timedelta
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.models.identity import User, AuthChallenge, AuthSession, ElderProfile, FamilyBinding
from app.core.clock import Clock, local_date
from app.core.auth import token_hash
from app.core.errors import AppError
from app.contracts.context import Actor
from app.schemas.identity import CodeRequest, CodeResponse, LoginRequest, LoginResponse, Me, User as UserDTO, ElderSummary

class IdentityService:
    def __init__(self, clock: Clock):
        self.clock = clock
    def issue_challenge(self, tx: Session, payload: CodeRequest) -> CodeResponse:
        user = tx.scalar(select(User).where(User.phone == payload.phone, User.role == payload.role.value))
        if not user:
            raise AppError(401, "LOGIN_CODE_INVALID", "Only allocated demo accounts may log in")
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
        summaries = []
        for elder, binding in bound:
            from datetime import date
            birthday = date.fromisoformat(elder.profile_json['birth_date']) if elder.profile_json.get('birth_date') else None
            age = today.year - birthday.year - ((today.month, today.day) < (birthday.month, birthday.day)) if birthday else None
            summaries.append(ElderSummary(elder_id=elder.id, display_name=elder.profile_json['display_name'], age=age, conditions=elder.profile_json.get('conditions', []), binding_id=binding.id, relationship=binding.relationship))
        return Me(user=UserDTO(user_id=user.id, phone=user.phone, role=user.role, demo_id=user.demo_id), elder_id=owned.id if owned else None, bound_elders=summaries)
