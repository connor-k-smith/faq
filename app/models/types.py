from enum import Enum as PythonEnum

from sqlalchemy import Enum


def database_enum[EnumT: PythonEnum](enum_class: type[EnumT], name: str) -> Enum:
    return Enum(
        enum_class,
        name=name,
        values_callable=lambda members: [member.value for member in members],
        create_constraint=False,
    )
