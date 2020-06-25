from abc import abstractmethod
from typing import Iterator

import django.core.checks
from rest_framework.serializers import ModelSerializer, Serializer

from .. import CheckId
from ..controller import register
from .base_checks import BaseCheck


class CheckDRFSerializer(BaseCheck):
    @abstractmethod
    def apply(
        self, serializer: Serializer
    ) -> Iterator[django.core.checks.CheckMessage]:
        raise NotImplementedError()


class CheckDRFModelSerializer(BaseCheck):
    @abstractmethod
    def apply(
        self, serializer: ModelSerializer
    ) -> Iterator[django.core.checks.CheckMessage]:
        raise NotImplementedError()


@register("extra_checks_drf_serializer")
class CheckDRFSerializerExtraKwargs(CheckDRFModelSerializer):
    Id = CheckId.X301
    level = django.core.checks.ERROR

    def apply(
        self, serializer: ModelSerializer
    ) -> Iterator[django.core.checks.CheckMessage]:
        if not hasattr(serializer, "Meta") or not hasattr(
            serializer.Meta, "extra_kwargs"
        ):
            return
        invalid = serializer.Meta.extra_kwargs.keys() & serializer._declared_fields
        if invalid:
            yield self.message(
                "extra_kwargs mustn't include fields that declared on serializer.",
                hint=f"Remove extra_kwargs for fields: {', '.join(invalid)}",
                obj=serializer,
            )
