from datetime import datetime
from typing import ClassVar

from sqlalchemy import DateTime, MetaData, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    metadata = MetaData()
    type_annotation_map: ClassVar[dict[object, object]] = {
        datetime: DateTime(timezone=True),
        str: Text(),
    }
