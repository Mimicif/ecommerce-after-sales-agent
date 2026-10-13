import hashlib
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent_schemas import ConversationInput, MessageInput
from app.agent_store import ConversationService, run_view
from app.clock import Clock, FixtureClock, SystemClock
from app.config import Settings
from app.db import make_engine, make_session_factory
from app.errors import BusinessError
from app.models import DevSession, User
from app.reads import ReadService
from app.schemas import (
    EligibilityBody,
    EligibilityInput,
    ListOrdersInput,
    PolicyInput,
    PolicyQuery,
    ResourceId,
)
from app.workspace import CasePageQuery, PageQuery, WorkspaceService
from app.write_schemas import (
    ConfirmInput,
    DraftInput,
    EditDraftInput,
    ReviewInput,
    TicketInput,
    VersionInput,
)
from app.writes import WriteService, audit


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str = Field(pattern=r"^[CE]-[AB][1-9][0-9]*$", max_length=64)


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def local_request(request: Request) -> bool:
    try:
        return request.client is not None and ip_address(request.client.host).is_loopback
    except ValueError:
        return False


def create_app(settings: Settings | None = None, *, clock: Clock | None = None) -> FastAPI:
    settings = settings or Settings()
    engine = make_engine(settings)
    sessions = make_session_factory(engine)
    business_clock = clock or (
        FixtureClock() if settings.business_clock_mode == "fixture" else SystemClock()
    )

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(title="Simulated After-sales API", version="0.6.0", lifespan=lifespan)
    app.state.engine = engine

    @app.middleware("http")
    async def trace(request, call_next):
        request.state.trace_id = uuid4().hex
        response = await call_next(request)
        response.headers["X-Trace-Id"] = request.state.trace_id
        response.headers["Cache-Control"] = "no-store"
        return response

    def result(request, data, code="OK", ok=True):
        return {"ok": ok, "code": code, "data": data, "trace_id": request.state.trace_id}

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(
            result(request, {}, exc.detail, False), status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Do not echo inputs, Authorization headers or submitted secrets.
        return JSONResponse(result(request, {}, "INVALID_ARGUMENT", False), status_code=422)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return JSONResponse(result(request, {}, "DATABASE_UNAVAILABLE", False), status_code=503)

    @app.exception_handler(BusinessError)
    async def business_error(request, exc):
        if request.method in {"POST", "PATCH"} and getattr(request.state, "actor_id", None):
            # Roll back business state before recording a denial in its own transaction.
            request.state.db_session.rollback()
            try:
                with sessions() as audit_session, audit_session.begin():
                    audit(
                        audit_session,
                        request.state.actor_id,
                        request.state.tenant_id,
                        "BUSINESS_WRITE_BLOCKED",
                        "REQUEST",
                        request.state.trace_id,
                        {"method": request.method},
                        result=exc.code,
                    )
            except SQLAlchemyError:
                # A failed database cannot reliably accept an audit; do not mask the error.
                pass
        body = result(request, exc.data, exc.code, False)
        body["retryable"] = exc.retryable
        return JSONResponse(body, status_code=exc.status)

    def db(request: Request):
        with sessions() as session:
            request.state.db_session = session
            yield session

    Db = Annotated[Session, Depends(db)]
    bearer = HTTPBearer(auto_error=False)

    def actor(
        request: Request,
        session: Db,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ):
        if not settings.dev_mode or not local_request(request):
            raise HTTPException(401, "UNAUTHORIZED")
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(401, "UNAUTHORIZED", headers={"WWW-Authenticate": "Bearer"})
        stored = session.get(DevSession, digest(credentials.credentials))
        if stored is None or datetime.now(UTC) >= stored.expires_at:
            raise HTTPException(401, "UNAUTHORIZED")
        user = session.get(User, stored.user_id)
        if user is None:
            raise HTTPException(401, "UNAUTHORIZED")
        request.state.actor_id, request.state.tenant_id = user.id, user.tenant_id
        return user

    Actor = Annotated[User, Depends(actor)]
    Idem = Annotated[
        str,
        Header(
            alias="Idempotency-Key", min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"
        ),
    ]

    def service(session, user):
        return ReadService(session, user.id, business_clock)

    def read_result(request, data):
        return result(request, data.model_dump(mode="json"))

    def writer(session, user, request):
        return WriteService(session, user.id, business_clock, request.state.trace_id)

    def workspace(session, user, request):
        return WorkspaceService(session, user.id, business_clock, request.state.trace_id)

    def written(request, session, data):
        session.commit()
        return result(request, data)

    @app.get("/api/v1/health")
    def health(request: Request, session: Db):
        session.execute(text("SELECT 1"))
        return result(request, {"status": "healthy", "database": "reachable", "simulated": True})

    @app.post("/api/v1/dev/sessions", status_code=201)
    def login(body: LoginInput, request: Request, session: Db):
        if not settings.dev_mode or not local_request(request):
            raise HTTPException(404, "RESOURCE_NOT_FOUND")
        user = session.get(User, body.user_id)
        if user is None:
            raise HTTPException(404, "RESOURCE_NOT_FOUND")
        now = datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        expires = now + timedelta(seconds=settings.session_ttl_seconds)
        session.add(
            DevSession(
                token_digest=digest(token), user_id=user.id, created_at=now, expires_at=expires
            )
        )
        session.commit()
        return result(
            request,
            jsonable_encoder(
                {
                    "access_token": token,
                    "token_type": "bearer",
                    "expires_at": expires,
                    "user_id": user.id,
                    "tenant_id": user.tenant_id,
                    "roles": user.roles,
                    "simulated": True,
                }
            ),
        )

    @app.get("/api/v1/orders")
    def orders(
        request: Request,
        session: Db,
        user: Actor,
        cursor: str | None = Query(None, max_length=64, pattern=r"^[A-Z0-9-]+$"),
        limit: int = Query(20, ge=1, le=20),
    ):
        if set(request.query_params) - {"cursor", "limit"}:
            raise HTTPException(422, "INVALID_ARGUMENT")
        return read_result(
            request, service(session, user).list_orders(ListOrdersInput(cursor=cursor, limit=limit))
        )

    @app.get("/api/v1/me")
    def me(request: Request, session: Db, user: Actor):
        return result(
            request,
            {
                "user_id": user.id,
                "tenant_id": user.tenant_id,
                "roles": user.roles,
                "business_now": business_clock.now(session).isoformat(),
                "simulated": True,
            },
        )

    @app.get("/api/v1/cases")
    def cases(
        request: Request, session: Db, user: Actor, params: Annotated[CasePageQuery, Query()]
    ):
        return result(request, workspace(session, user, request).cases(params))

    @app.get("/api/v1/tickets")
    def tickets(request: Request, session: Db, user: Actor, params: Annotated[PageQuery, Query()]):
        return result(request, workspace(session, user, request).tickets(params))

    @app.get("/api/v1/conversations")
    def list_conversations(
        request: Request, session: Db, user: Actor, params: Annotated[PageQuery, Query()]
    ):
        return result(request, workspace(session, user, request).conversations(params))

    @app.get("/api/v1/orders/{order_id}/evidence")
    def evidence(order_id: ResourceId, request: Request, session: Db, user: Actor):
        return result(request, workspace(session, user, request).evidence(order_id))

    @app.get("/api/v1/cases/{case_id}/timeline")
    def timeline(case_id: ResourceId, request: Request, session: Db, user: Actor):
        return result(request, workspace(session, user, request).timeline(case_id))

    @app.get("/api/v1/orders/{order_id}")
    def order(order_id: ResourceId, request: Request, session: Db, user: Actor):
        return read_result(request, service(session, user).get_order(order_id))

    @app.get("/api/v1/orders/{order_id}/logistics")
    def logistics(order_id: ResourceId, request: Request, session: Db, user: Actor):
        if request.query_params:
            raise HTTPException(422, "INVALID_ARGUMENT")
        return read_result(request, service(session, user).get_logistics(order_id))

    @app.get("/api/v1/orders/{order_id}/policy")
    def policy(
        order_id: ResourceId,
        request: Request,
        session: Db,
        user: Actor,
        params: Annotated[PolicyQuery, Query()],
    ):
        args = PolicyInput(order_id=order_id, **params.model_dump())
        return read_result(request, service(session, user).search_policy(args))

    @app.post("/api/v1/orders/{order_id}/eligibility")
    def eligibility(
        order_id: ResourceId, body: EligibilityBody, request: Request, session: Db, user: Actor
    ):
        args = EligibilityInput(order_id=order_id, **body.model_dump())
        return read_result(request, service(session, user).check_eligibility(args))

    @app.post("/api/v1/cases/drafts", status_code=201)
    def draft(body: DraftInput, key: Idem, request: Request, session: Db, user: Actor):
        return written(request, session, writer(session, user, request).draft(body, key))

    @app.get("/api/v1/cases/{case_id}")
    def get_case(case_id: ResourceId, request: Request, session: Db, user: Actor):
        return result(request, writer(session, user, request).get_case(case_id))

    @app.patch("/api/v1/cases/{case_id}/draft")
    def edit_case(
        case_id: ResourceId,
        body: EditDraftInput,
        key: Idem,
        request: Request,
        session: Db,
        user: Actor,
    ):
        return written(request, session, writer(session, user, request).edit(case_id, body, key))

    @app.post("/api/v1/cases/{case_id}/confirmation")
    def confirmation(
        case_id: ResourceId,
        body: VersionInput,
        key: Idem,
        request: Request,
        session: Db,
        user: Actor,
    ):
        return written(
            request, session, writer(session, user, request).confirmation(case_id, body, key)
        )

    @app.post("/api/v1/confirmations/{confirmation_id}/confirm")
    def confirm(
        confirmation_id: ResourceId,
        body: ConfirmInput,
        key: Idem,
        request: Request,
        session: Db,
        user: Actor,
    ):
        return written(
            request, session, writer(session, user, request).confirm(confirmation_id, body, key)
        )

    @app.post("/api/v1/cases/{case_id}/submit")
    def submit(
        case_id: ResourceId,
        body: VersionInput,
        key: Idem,
        request: Request,
        session: Db,
        user: Actor,
    ):
        return written(request, session, writer(session, user, request).submit(case_id, body, key))

    @app.post("/api/v1/cases/{case_id}/cancel")
    def cancel(
        case_id: ResourceId,
        body: VersionInput,
        key: Idem,
        request: Request,
        session: Db,
        user: Actor,
    ):
        return written(request, session, writer(session, user, request).cancel(case_id, body, key))

    @app.post("/api/v1/cases/{case_id}/review")
    def review(
        case_id: ResourceId,
        body: ReviewInput,
        key: Idem,
        request: Request,
        session: Db,
        user: Actor,
    ):
        return written(request, session, writer(session, user, request).review(case_id, body, key))

    @app.post("/api/v1/cases/{case_id}/return-received")
    def receive(
        case_id: ResourceId,
        body: VersionInput,
        key: Idem,
        request: Request,
        session: Db,
        user: Actor,
    ):
        return written(request, session, writer(session, user, request).receive(case_id, body, key))

    @app.post("/api/v1/cases/{case_id}/refund-reconcile")
    def reconcile(
        case_id: ResourceId,
        body: VersionInput,
        key: Idem,
        request: Request,
        session: Db,
        user: Actor,
    ):
        return written(
            request, session, writer(session, user, request).reconcile(case_id, body, key)
        )

    @app.get("/api/v1/cases/{case_id}/refund")
    def refund(case_id: ResourceId, request: Request, session: Db, user: Actor):
        return result(request, writer(session, user, request).refund(case_id))

    @app.post("/api/v1/tickets", status_code=201)
    def ticket(body: TicketInput, key: Idem, request: Request, session: Db, user: Actor):
        return written(request, session, writer(session, user, request).ticket(body, key))

    @app.get("/api/v1/tickets/{ticket_id}")
    def get_ticket(ticket_id: ResourceId, request: Request, session: Db, user: Actor):
        return result(request, writer(session, user, request).get_ticket(ticket_id))

    def conversations(session, user, request):
        return ConversationService(session, user.id, business_clock, request.state.trace_id)

    @app.post("/api/v1/conversations", status_code=201)
    def create_conversation(
        body: ConversationInput, key: Idem, request: Request, session: Db, user: Actor
    ):
        return written(request, session, conversations(session, user, request).create(body, key))

    @app.post("/api/v1/conversations/{conversation_id}/messages", status_code=202)
    def send_message(
        conversation_id: ResourceId, body: MessageInput, request: Request, session: Db, user: Actor
    ):
        return written(
            request, session, conversations(session, user, request).message(conversation_id, body)
        )

    @app.get("/api/v1/conversations/{conversation_id}/messages")
    def get_messages(conversation_id: ResourceId, request: Request, session: Db, user: Actor):
        return result(request, conversations(session, user, request).messages(conversation_id))

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: ResourceId, request: Request, session: Db, user: Actor):
        return result(request, run_view(conversations(session, user, request).run(run_id)))

    @app.get("/api/v1/runs/{run_id}/events")
    def get_events(
        run_id: ResourceId,
        request: Request,
        session: Db,
        user: Actor,
        after_seq: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=100),
    ):
        if set(request.query_params) - {"after_seq", "limit"}:
            raise HTTPException(422, "INVALID_ARGUMENT")
        return result(
            request, conversations(session, user, request).events(run_id, after_seq, limit)
        )

    @app.post("/api/v1/runs/{run_id}/cancel")
    def cancel_run(
        run_id: ResourceId, body: ConversationInput, request: Request, session: Db, user: Actor
    ):
        return written(request, session, conversations(session, user, request).cancel(run_id))

    return app
