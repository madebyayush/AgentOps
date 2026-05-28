"""
AgentOps — SQLAlchemy Declarative Base
All ORM models must inherit from `Base`.
Importing this module is enough for Alembic to discover all models
(the `from . import models` in db/__init__.py handles that).
"""

from sqlalchemy.orm import DeclarativeBase, MappedColumn


class Base(DeclarativeBase):
    """Shared base class for all AgentOps ORM models."""

    pass
