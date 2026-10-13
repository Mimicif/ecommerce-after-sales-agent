"""Single-namespace, JSON-only LangGraph saver fenced by the owning PostgreSQL run lease."""

import json
import time

from langgraph.checkpoint.base import WRITES_IDX_MAP, BaseCheckpointSaver, CheckpointTuple
from sqlalchemy import select

from app.agent_store import fenced
from app.errors import BusinessError
from app.models import GraphCheckpoint, GraphWrite

CHECKPOINT_VERSION = "checkpoint-v2-m6"
PARENT_WAIT_SECONDS = 2.0


def json_value(value):
    if isinstance(value, BaseException):
        return {"error": type(value).__name__}
    # Reject non-JSON graph state instead of loading arbitrary Python objects/pickle.
    return json.loads(json.dumps(value, ensure_ascii=False))


class PostgresRunSaver(BaseCheckpointSaver):
    def __init__(self, sessions, run_id, token):
        super().__init__()
        self.sessions, self.run_id, self.token = sessions, run_id, token

    def config(self, checkpoint_id):
        return {
            "configurable": {
                "thread_id": self.run_id,
                "checkpoint_ns": "",
                "checkpoint_id": checkpoint_id,
            }
        }

    def check(self, config):
        values = config["configurable"]
        if values.get("thread_id") != self.run_id or values.get("checkpoint_ns", "") != "":
            raise ValueError("Only the server-selected run and root graph namespace are supported")

    def get_tuple(self, config):
        self.check(config)
        with self.sessions() as session, session.begin():
            fenced(session, self.run_id, self.token)
            query = select(GraphCheckpoint).where(GraphCheckpoint.run_id == self.run_id)
            checkpoint_id = config["configurable"].get("checkpoint_id")
            if checkpoint_id:
                query = query.where(GraphCheckpoint.checkpoint_id == checkpoint_id)
            row = session.scalar(query.order_by(GraphCheckpoint.checkpoint_id.desc()).limit(1))
            if row is None:
                return None
            writes = session.scalars(
                select(GraphWrite)
                .where(
                    GraphWrite.run_id == self.run_id, GraphWrite.checkpoint_id == row.checkpoint_id
                )
                .order_by(GraphWrite.task_id, GraphWrite.idx)
            ).all()
            return CheckpointTuple(
                self.config(row.checkpoint_id),
                row.checkpoint,
                row.checkpoint_metadata,
                self.config(row.parent_id) if row.parent_id else None,
                [(write.task_id, write.channel, write.value) for write in writes],
            )

    def put(self, config, checkpoint, metadata, new_versions):
        self.check(config)
        with self.sessions() as session, session.begin():
            fenced(session, self.run_id, self.token)
            key = (self.run_id, checkpoint["id"])
            if session.get(GraphCheckpoint, key) is None:
                session.add(
                    GraphCheckpoint(
                        run_id=self.run_id,
                        checkpoint_id=checkpoint["id"],
                        parent_id=config["configurable"].get("checkpoint_id"),
                        checkpoint=json_value(checkpoint),
                        checkpoint_metadata=json_value(metadata),
                    )
                )
        return self.config(checkpoint["id"])

    def put_writes(self, config, writes, task_id, task_path=""):
        self.check(config)
        checkpoint_id = config["configurable"]["checkpoint_id"]
        deadline = time.monotonic() + PARENT_WAIT_SECONDS
        while True:
            with self.sessions() as session, session.begin():
                fenced(session, self.run_id, self.token)
                if session.get(GraphCheckpoint, (self.run_id, checkpoint_id)) is not None:
                    for index, (channel, value) in enumerate(writes):
                        idx = WRITES_IDX_MAP.get(channel, index)
                        key = (self.run_id, checkpoint_id, task_id, idx)
                        row = session.get(GraphWrite, key)
                        if row is None:
                            session.add(
                                GraphWrite(
                                    run_id=key[0],
                                    checkpoint_id=key[1],
                                    task_id=key[2],
                                    idx=idx,
                                    channel=channel,
                                    value=json_value(value),
                                )
                            )
                        elif idx < 0:
                            row.channel, row.value = channel, json_value(value)
                    return
            # LangGraph schedules parent checkpoints and pending writes independently.
            # Release the run lock before waiting so the parent writer can commit.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BusinessError("RUN_CHECKPOINT_NOT_READY", 503, retryable=True)
            time.sleep(min(0.01, remaining))
