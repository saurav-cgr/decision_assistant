from uuid import UUID, uuid4

from sqlalchemy import Integer, Text, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from decision_assistant.models import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(CITEXT, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    recovery_code_id: Mapped[UUID] = mapped_column(
        default=uuid4,
        unique=True,
    )
    recovery_code_hash: Mapped[str] = mapped_column(Text)
    token_version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default=text("1"),
    )
