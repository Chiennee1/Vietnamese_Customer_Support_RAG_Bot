from enum import StrEnum
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TicketSeverity(StrEnum):
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class TicketStatus(StrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"


class FeedbackRating(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


class SupportTicket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "support_tickets"

    ticket_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[TicketSeverity] = mapped_column(
        Enum(
            TicketSeverity,
            native_enum=False,
            length=20,
            values_callable=lambda members: [member.value for member in members],
            create_constraint=True,
            name="ticket_severity",
        ),
        nullable=False,
    )
    status: Mapped[TicketStatus] = mapped_column(
        Enum(
            TicketStatus,
            native_enum=False,
            length=20,
            values_callable=lambda members: [member.value for member in members],
            create_constraint=True,
            name="ticket_status",
        ),
        nullable=False,
        default=TicketStatus.OPEN,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )


class Feedback(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "feedback"
    __table_args__ = (UniqueConstraint("message_id", "user_id"),)

    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rating: Mapped[FeedbackRating] = mapped_column(
        Enum(
            FeedbackRating,
            native_enum=False,
            length=20,
            values_callable=lambda members: [member.value for member in members],
            create_constraint=True,
            name="feedback_rating",
        ),
        nullable=False,
    )
    comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
