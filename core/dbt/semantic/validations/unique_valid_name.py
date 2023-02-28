from __future__ import annotations

import enum
import re
from typing import Dict, Tuple, List
from dbt.semantic.references import (
    EntityElementReference,
    EntityReference,
    MetricModelReference,
    ElementReference,
)

from dbt.contracts.graph.nodes import Entity
from dbt.semantic.user_configured_model import UserConfiguredModel
from dbt.semantic.validations.validator_helpers import (
    EntityContext,
    EntityElementContext,
    EntityElementType,
    MetricContext,
    ModelValidationRule,
    ValidationContext,
    ValidationError,
    ValidationIssueType,
)
from dbt.semantic.object_utils import assert_values_exhausted
from dbt.semantic.time import TimeGranularity


@enum.unique
class SemanticReservedKeywords(enum.Enum):
    """Enumeration of reserved keywords with helper for accessing the reason they are reserved"""

    METRIC_TIME = "metric_time"
    DBT_INTERNAL_UUID = "dbt_internal_uuid"

    @staticmethod
    def get_reserved_reason(keyword: SemanticReservedKeywords) -> str:
        """Get the reason a given keyword is reserved. Guarantees an exhaustive switch"""
        if keyword is SemanticReservedKeywords.METRIC_TIME:
            return (
                "Used as the query input for creating time series metrics from measures with "
                "different time dimension names."
            )
        elif keyword is SemanticReservedKeywords.DBT_INTERNAL_UUID:
            return "Used internally to reference a column that has a uuid generated by dbt."
        else:
            assert_values_exhausted(keyword)


class UniqueAndValidNameRule(ModelValidationRule):
    """Check that names are unique and valid.

    * Names of elements in data sources are unique / valid within the data source.
    * Names of data sources, dimension sets, metric sets, and materializations in the model are unique / valid.
    """

    NAME_REGEX = re.compile(r"\A[a-z][a-z0-9_]*[a-z0-9]\Z")

    @staticmethod
    def check_valid_name(name: str) -> List[ValidationIssueType]:
        issues: List[ValidationIssueType] = []

        if not UniqueAndValidNameRule.NAME_REGEX.match(name):
            issues.append(
                ValidationError(
                    message=f"Invalid name `{name}` - names should only consist of lower case letters, numbers, "
                    f"and underscores. In addition, names should start with a lower case letter, and should not end "
                    f"with an underscore, and they must be at least 2 characters long.",
                )
            )
        if name.upper() in TimeGranularity.list_names():
            issues.append(
                ValidationError(
                    message=f"Invalid name `{name}` - names cannot match reserved time granularity keywords "
                    f"({TimeGranularity.list_names()})",
                )
            )
        if name.lower() in {reserved_name.value for reserved_name in SemanticReservedKeywords}:
            reason = SemanticReservedKeywords.get_reserved_reason(
                SemanticReservedKeywords(name.lower())
            )
            issues.append(
                ValidationError(
                    message=f"Invalid name `{name}` - this name is reserved by MetricFlow. Reason: {reason}",
                )
            )
        return issues

    @staticmethod
    def _validate_entity_elements(entity: Entity) -> List[ValidationIssueType]:
        issues: List[ValidationIssueType] = []
        element_info_tuples: List[Tuple[ElementReference, str, ValidationContext]] = []

        if entity.measures:
            for measure in entity.measures:
                element_info_tuples.append(
                    (
                        measure.reference,
                        "measure",
                        EntityElementContext(
                            entity_element=EntityElementReference(
                                entity_name=entity.name, name=measure.name
                            ),
                            element_type=EntityElementType.MEASURE,
                        ),
                    )
                )
        if entity.identifiers:
            for identifier in entity.identifiers:
                element_info_tuples.append(
                    (
                        identifier.reference,
                        "identifier",
                        EntityElementContext(
                            entity_element=EntityElementReference(
                                entity_name=entity.name, name=identifier.name
                            ),
                            element_type=EntityElementType.IDENTIFIER,
                        ),
                    )
                )
        if entity.dimensions:
            for dimension in entity.dimensions:
                element_info_tuples.append(
                    (
                        dimension.reference,
                        "dimension",
                        EntityElementContext(
                            entity_element=EntityElementReference(
                                entity_name=entity.name, name=dimension.name
                            ),
                            element_type=EntityElementType.DIMENSION,
                        ),
                    )
                )
        name_to_type: Dict[ElementReference, str] = {}

        for name, _type, context in element_info_tuples:
            if name in name_to_type:
                issues.append(
                    ValidationError(
                        message=f"In entity `{entity.name}`, can't use name `{name.name}` for a "
                        f"{_type} when it was already used for a {name_to_type[name]}",
                    )
                )
            else:
                name_to_type[name] = _type

        for name, _type, context in element_info_tuples:
            issues += UniqueAndValidNameRule.check_valid_name(name=name.name)

        return issues

    @staticmethod
    def _validate_top_level_objects(model: UserConfiguredModel) -> List[ValidationIssueType]:
        """Checks names of objects that are not nested."""
        object_info_tuples = []
        if model.entities:
            for entity in model.entities:
                object_info_tuples.append(
                    (
                        entity.name,
                        "entity",
                        EntityContext(
                            entity=EntityReference(entity_name=entity.name),
                        ),
                    )
                )

        name_to_type: Dict[str, str] = {}

        issues: List[ValidationIssueType] = []

        for name, type_, context in object_info_tuples:
            if name in name_to_type:
                issues.append(
                    ValidationError(
                        message=f"Can't use name `{name}` for a {type_} when it was already used for a "
                        f"{name_to_type[name]}",
                    )
                )
            else:
                name_to_type[name] = type_

        if model.metrics:
            metric_names = set()
            for metric in model.metrics:
                if metric.name in metric_names:
                    issues.append(
                        ValidationError(
                            context=MetricContext(
                                metric=MetricModelReference(metric_name=metric.name),
                            ),
                            message=f"Can't use name `{metric.name}` for a metric when it was already used for a metric",
                        )
                    )
                else:
                    metric_names.add(metric.name)

        for name, _type, context in object_info_tuples:
            issues += UniqueAndValidNameRule.check_valid_name(name=name)

        return issues

    @staticmethod
    def validate_model(model: UserConfiguredModel) -> List[ValidationIssueType]:  # noqa: D
        issues = []
        issues += UniqueAndValidNameRule._validate_top_level_objects(model=model)

        for entity in model.entities:
            issues += UniqueAndValidNameRule._validate_entity_elements(entity=entity)

        return issues
