import importlib
import site
from functools import partial
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Set,
    Type,
    Union,
)

import django.apps
import django.core.checks
from django import forms
from django.conf import settings
from django.db import models

from . import _IGNORED, CheckId
from .ast import FieldAST, ModelAST
from .forms import ConfigForm

try:
    from rest_framework import serializers
except ImportError:
    serializers = None  # type: ignore

if TYPE_CHECKING:
    from .checks import BaseCheck


DEFAULT_CONFIG: dict = {
    "checks": [],
}


class Registry:
    def __init__(self) -> None:
        self.checks: Dict["Type[BaseCheck]", Sequence[str]] = {}

    def _register(
        self, tags: List[str], check_class: "Type[BaseCheck]"
    ) -> "Type[BaseCheck]":
        self.checks[check_class] = tags
        return check_class

    def register(self, *tags: str) -> Callable[["Type[BaseCheck]"], "Type[BaseCheck]"]:
        return partial(self._register, tags)

    def finish(self) -> "ChecksController":
        controller = ChecksController.create(self.checks)

        def f(callback: Callable) -> Callable:
            """
            Django does `check.tags = ...`, callback is a method of the controller
            and setattr will fail on it so we wrap method with a function.
            """

            def inner(*args: Any, **kwargs: Any) -> Any:
                return callback(*args, **kwargs)

            return inner

        django.core.checks.register(
            f(controller.check_extra_checks_health), "extra_checks_selfcheck"
        )
        django.core.checks.register(
            f(controller.check_drf_serializers), django.core.checks.Tags.models
        )
        if serializers:
            django.core.checks.register(
                f(controller.check_extra_checks_health), "extra_checks_drf_serializer"
            )

        return controller


class ChecksController:
    def __init__(
        self,
        checks: Dict["Type[BaseCheck]", Sequence[str]],
        config: Optional[Dict[CheckId, dict]] = None,
        errors: Optional[forms.utils.ErrorDict] = None,
    ) -> None:
        checks = checks or {}
        config = config or {CheckId.X001: {}}
        self.errors = errors
        self.registered_checks: Dict[str, List["BaseCheck"]] = {}
        self.ignored: Dict[Union[CheckId, str], set] = {}
        for obj, ids in _IGNORED.items():
            for id_ in ids:
                self.ignored.setdefault(id_, set()).add(obj)
        for check_class, tags in checks.items():
            if check_class.Id in config:
                check = check_class(
                    ignored_objects=self.ignored.get(check_class.Id, set()),
                    **config[check_class.Id],
                )
                for tag in tags:
                    self.registered_checks.setdefault(tag, []).append(check)

    @classmethod
    def create(
        cls, checks: Dict["Type[BaseCheck]", Sequence[str]]
    ) -> "ChecksController":
        check_form = {r.Id: r.settings_form_class for r in checks}
        if not hasattr(settings, "EXTRA_CHECKS"):
            return cls(checks=checks)
        form = ConfigForm(settings.EXTRA_CHECKS)  # type: ignore
        if form.is_valid(check_form):
            return cls(checks=checks, config=form.cleaned_data["checks"])
        return cls(checks=checks, errors=form.errors)

    @property
    def is_healthy(self) -> bool:
        return not self.errors

    def check_extra_checks_health(
        self, app_configs: Optional[List[Any]] = None, **kwargs: Any
    ) -> Iterator[django.core.checks.CheckMessage]:
        for check in self.registered_checks.get("extra_checks_selfcheck", []):
            yield from check(self)

    def _get_models_to_check(
        self, app_configs: Optional[List[Any]]
    ) -> Iterator[Type[models.Model]]:
        apps = (
            django.apps.apps.get_app_configs() if app_configs is None else app_configs
        )
        site_prefixes = set(site.PREFIXES)
        for app in apps:
            if not any(app.path.startswith(path) for path in site_prefixes):
                yield from app.get_models()

    def check_models(
        self, app_configs: Optional[List[Any]] = None, **kwargs: Any
    ) -> Iterator[Any]:
        from .checks import CheckModelField

        model_checks = []
        field_checks = []
        for check in self.registered_checks.get(django.core.checks.Tags.models, []):
            if isinstance(check, CheckModelField):
                field_checks.append(check)
            else:
                model_checks.append(check)
        if not model_checks and not field_checks:
            return
        for model in self._get_models_to_check(app_configs):
            model_ast = ModelAST(model)
            for check in model_checks:
                yield from check(model, model_ast=model_ast)
            if field_checks:
                for field, node in model_ast.field_nodes:
                    field_ast = FieldAST(node)
                    for check in field_checks:
                        yield from check(field, field_ast=field_ast, model=model)

    def _collect_serializers(
        self,
        ss: Iterable[Type["serializers.Serializer"]],
        visited: Optional[Set[Type["serializers.Serializer"]]] = None,
    ) -> Iterator[Type["serializers.Serializer"]]:
        visited = visited or set()
        for serializer in ss:
            if serializer not in visited:
                visited.add(serializer)
                yield from self._collect_serializers(
                    serializer.__subclasses__(), visited
                )
                yield serializer

    def _filter_app_serializers(
        self, ss: Iterable[Type["serializers.Serializer"]]
    ) -> Iterator[Type["serializers.Serializer"]]:
        site_prefixes = set(site.PREFIXES)
        for s in ss:
            module = importlib.import_module(s.__module__)
            if not any(module.__file__.startswith(path) for path in site_prefixes):
                yield s

    def check_drf_serializers(
        self, app_configs: Optional[List[Any]] = None, **kwargs: Any
    ) -> Iterator[Any]:
        serializer_classes = self._filter_app_serializers(
            self._collect_serializers(
                s
                for s in serializers.Serializer.__subclasses__()
                if s is not serializers.ModelSerializer
            )
        )
        model_serializer_classes = self._filter_app_serializers(
            self._collect_serializers(serializers.ModelSerializer.__subclasses__())
        )
        model_checks = []
        checks = []
        for check in self.registered_checks.get("extra_checks_drf_serializer", []):
            if isinstance(check, serializers.ModelSerializer):
                model_checks.append(check)
            else:
                checks.append(check)
        for s in model_serializer_classes:
            for check in model_checks:
                yield from check(s)
        for s in serializer_classes:
            for check in checks:
                yield from check(s)
        return []


registry = Registry()
register = registry.register
