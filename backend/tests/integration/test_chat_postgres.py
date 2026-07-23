import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import select, update

from app.core.config import Settings
from app.db.models.conversation import Conversation, MessageRole, ToolExecutionStatus
from app.db.models.ticket import FeedbackRating
from app.db.models.user import User
from app.db.session import Database
from app.repositories.conversations import (
    ConversationRepository,
    MessageCreateRecord,
    ToolExecutionCreateRecord,
)

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL is required",
)
async def test_conversation_repository_enforces_owner_and_feedback_scope() -> None:
    settings = Settings(database_url=SecretStr(os.environ["TEST_DATABASE_URL"]))
    database = Database(settings)
    repository = ConversationRepository(database.sessions)
    conversation_id = None
    owner_id = None

    try:
        async with database.sessions() as session:
            users = (
                await session.scalars(
                    select(User)
                    .where(
                        User.email.in_(
                            [
                                "customer0006@example.test",
                                "customer0007@example.test",
                            ]
                        )
                    )
                    .order_by(User.email)
                )
            ).all()
        assert len(users) == 2
        owner, stranger = users
        owner_id = owner.id
        conversation = await repository.create_conversation(
            user_id=owner.id,
            title="Kiểm tra đơn hàng",
        )
        conversation_id = conversation.id
        user_message = await repository.add_message(
            MessageCreateRecord(
                id=uuid4(),
                conversation_id=conversation.id,
                role=MessageRole.USER,
                content="Đơn DH2026000001 tới đâu?",
            )
        )
        assistant_message = await repository.add_message(
            MessageCreateRecord(
                id=uuid4(),
                conversation_id=conversation.id,
                role=MessageRole.ASSISTANT,
                content="Đơn hàng đang được vận chuyển.",
                intent="order_status",
                citations=[],
            )
        )
        await repository.add_tool_executions(
            [
                ToolExecutionCreateRecord(
                    conversation_id=conversation.id,
                    message_id=assistant_message.id,
                    tool_name="get_order_status",
                    status=ToolExecutionStatus.SUCCESS,
                    duration_ms=9,
                )
            ]
        )

        assert (
            await repository.get_conversation(
                conversation.id,
                user_id=stranger.id,
            )
            is None
        )
        assert (
            await repository.list_messages(
                conversation.id,
                user_id=stranger.id,
            )
            is None
        )
        assert (
            await repository.upsert_feedback(
                message_id=assistant_message.id,
                user_id=stranger.id,
                rating=FeedbackRating.POSITIVE,
                comment=None,
            )
            is None
        )
        assert (
            await repository.upsert_feedback(
                message_id=user_message.id,
                user_id=owner.id,
                rating=FeedbackRating.POSITIVE,
                comment=None,
            )
            is None
        )
        feedback = await repository.upsert_feedback(
            message_id=assistant_message.id,
            user_id=owner.id,
            rating=FeedbackRating.POSITIVE,
            comment="Đã rõ",
        )
        assert feedback is not None
        assert feedback.rating == FeedbackRating.POSITIVE

        assert not await repository.delete_conversation(
            conversation.id,
            user_id=stranger.id,
        )
        assert await repository.delete_conversation(
            conversation.id,
            user_id=owner.id,
        )
        conversation_id = None
    finally:
        if conversation_id is not None and owner_id is not None:
            await repository.delete_conversation(
                conversation_id,
                user_id=owner_id,
            )
        await database.dispose()


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL is required",
)
async def test_retention_repository_deletes_only_expired_conversations() -> None:
    settings = Settings(database_url=SecretStr(os.environ["TEST_DATABASE_URL"]))
    database = Database(settings)
    repository = ConversationRepository(database.sessions)
    active_id = None
    owner_id = None

    try:
        async with database.sessions() as session:
            owner = await session.scalar(
                select(User).where(User.email == "customer0006@example.test")
            )
        assert owner is not None
        owner_id = owner.id
        expired = await repository.create_conversation(
            user_id=owner.id,
            title="Expired retention test",
        )
        active = await repository.create_conversation(
            user_id=owner.id,
            title="Active retention test",
        )
        active_id = active.id
        now = datetime.now(UTC)
        async with database.sessions() as session:
            await session.execute(
                update(Conversation)
                .where(Conversation.id == expired.id)
                .values(updated_at=now - timedelta(days=31))
            )
            await session.commit()

        deleted = await repository.delete_expired_conversations(
            before=now - timedelta(days=30),
        )

        assert deleted == 1
        assert (
            await repository.get_conversation(
                expired.id,
                user_id=owner.id,
            )
            is None
        )
        assert (
            await repository.get_conversation(
                active.id,
                user_id=owner.id,
            )
            is not None
        )
    finally:
        if active_id is not None and owner_id is not None:
            await repository.delete_conversation(active_id, user_id=owner_id)
        await database.dispose()
