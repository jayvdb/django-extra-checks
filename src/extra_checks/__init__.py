import enum
from typing import Any, Callable


class CheckID(str, enum.Enum):
    X001 = "X001"
    X002 = "X002"
    X003 = "X003"
    X004 = "X004"
    X005 = "X005"
    X006 = "X006"
    X007 = "X007"
    X008 = "X008"
    X009 = "X009"
    X010 = "X010"
    X011 = "X011"


_IGNORED = {}

EXTRA_CHECKS_ALL_RULES = list(CheckID.__members__.keys())


def ignore_checks(*args: CheckID) -> Callable[[Any], Any]:
    def f(entity: Any) -> Any:
        _IGNORED[entity] = set(args)
        return entity

    return f


default_app_config = "extra_checks.apps.ExtraChecksConfig"

__all__ = [
    "ignore_checks",
    "CheckID",
]
