"""Dynamic customer segments (CRM.md section 5, Design.md section 8).

A segment definition is a nested AND/OR tree. Every field and operator is checked
against a whitelist before anything is compiled, so a stored definition can never
become arbitrary SQL. Definitions are evaluated live, which is what makes a segment
dynamic: it changes as shipments, tasks, and consent records change (AC-15).

Marketing eligibility is deliberately *not* a filter field. Design.md section 8 requires
consent eligibility to stay a separate export filter with its own visible count, so a
segment is never silently treated as an outreach list.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

from sqlalchemy import Select, and_, case, exists, func, not_, or_, select
from sqlalchemy.orm import Session

from app.core.enums import (
    OPEN_TASK_STATUSES,
    ConsentChannel,
    CustomerCategory,
    LifecycleStatus,
    PreferredLanguage,
    RouteGroup,
    ServiceIssueStatus,
    ShippingFrequency,
    ShippingPurpose,
    value_label,
)
from app.core.time_utils import utcnow
from app.models import (
    Customer,
    CustomerRouteInterest,
    CustomerTag,
    FollowUpTask,
    ServiceIssue,
    Shipment,
    Tag,
)
from app.services.activity_service import LifecycleThresholds, qualifying_shipment_filter
from app.services.errors import ValidationError

MatchMode = Literal["all", "any"]

TEXT_OPERATORS = ("contains", "not_contains", "equals", "not_equals", "is_empty", "is_not_empty")
ENUM_OPERATORS = ("in", "not_in")
NUMBER_OPERATORS = ("equals", "not_equals", "gte", "lte", "between")
DATE_OPERATORS = (
    "within_days",
    "more_than_days_ago",
    "before",
    "after",
    "is_empty",
    "is_not_empty",
)
BOOLEAN_OPERATORS = ("is",)


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: str
    operators: tuple[str, ...]
    options: tuple[tuple[str, str], ...] = ()
    help_text: str | None = None
    group: str = "Customer"


def _options(values) -> tuple[tuple[str, str], ...]:
    return tuple((value.value, value_label(value.value)) for value in values)


FIELDS: dict[str, FieldSpec] = {
    spec.key: spec
    for spec in [
        FieldSpec("full_name", "Full name", "text", TEXT_OPERATORS),
        FieldSpec("city", "City", "text", TEXT_OPERATORS),
        FieldSpec("province_state", "Province or state", "text", TEXT_OPERATORS),
        FieldSpec("country_code", "Country", "text", TEXT_OPERATORS),
        FieldSpec(
            "preferred_language",
            "Preferred language",
            "enum",
            ENUM_OPERATORS,
            _options(PreferredLanguage),
            help_text=(
                "Recorded preference only. Language is never inferred from a name or a route."
            ),
        ),
        FieldSpec(
            "category", "Customer category", "enum", ENUM_OPERATORS, _options(CustomerCategory)
        ),
        FieldSpec(
            "primary_shipping_purpose",
            "Primary shipping purpose",
            "enum",
            ENUM_OPERATORS,
            _options(ShippingPurpose),
        ),
        FieldSpec(
            "shipping_frequency",
            "Declared shipping frequency",
            "enum",
            ENUM_OPERATORS,
            _options(ShippingFrequency),
            help_text="Declared expectation, not observed behaviour.",
        ),
        FieldSpec(
            "primary_route_group",
            "Primary route (declared)",
            "enum",
            ENUM_OPERATORS,
            _options(RouteGroup),
            group="Route",
        ),
        FieldSpec(
            "route_interest",
            "Route interest (declared)",
            "enum",
            ENUM_OPERATORS,
            _options(RouteGroup),
            group="Route",
        ),
        FieldSpec(
            "observed_route_group",
            "Route shipped (observed)",
            "enum",
            ENUM_OPERATORS,
            _options(RouteGroup),
            help_text="Derived from qualifying shipment history.",
            group="Route",
        ),
        FieldSpec(
            "lifecycle_status",
            "Lifecycle status",
            "enum",
            ENUM_OPERATORS,
            _options(LifecycleStatus),
            help_text="Derived from qualifying shipments using the configured thresholds.",
            group="Activity",
        ),
        FieldSpec(
            "total_qualifying_shipments",
            "Qualifying shipments",
            "number",
            NUMBER_OPERATORS,
            help_text=(
                "Confirmed outbound shipments with a first handoff, excluding drafts, "
                "cancellations and returns."
            ),
            group="Activity",
        ),
        FieldSpec(
            "is_repeat_customer", "Repeat customer", "boolean", BOOLEAN_OPERATORS, group="Activity"
        ),
        FieldSpec("last_shipment_at", "Last shipment", "date", DATE_OPERATORS, group="Activity"),
        FieldSpec("first_shipment_at", "First shipment", "date", DATE_OPERATORS, group="Activity"),
        FieldSpec("date_added", "Date added", "date", DATE_OPERATORS, group="Activity"),
        FieldSpec(
            "has_overdue_task",
            "Has an overdue follow-up",
            "boolean",
            BOOLEAN_OPERATORS,
            group="Follow-up",
        ),
        FieldSpec(
            "has_open_task",
            "Has an open follow-up",
            "boolean",
            BOOLEAN_OPERATORS,
            group="Follow-up",
        ),
        FieldSpec(
            "has_unresolved_service_issue",
            "Has an unresolved service issue",
            "boolean",
            BOOLEAN_OPERATORS,
            group="Service",
        ),
        FieldSpec("tag", "Tag", "tag", ("has_any", "has_all", "has_none"), group="Customer"),
        FieldSpec(
            "owner_user_id",
            "Assigned staff",
            "number",
            ("in", "not_in", "is_empty"),
            group="Customer",
        ),
        FieldSpec(
            "do_not_contact", "Do not contact", "boolean", BOOLEAN_OPERATORS, group="Compliance"
        ),
        FieldSpec("is_archived", "Archived", "boolean", BOOLEAN_OPERATORS, group="Customer"),
    ]
}


def field_catalog() -> list[dict[str, Any]]:
    """Field metadata for the segment builder UI."""
    return [
        {
            "key": spec.key,
            "label": spec.label,
            "kind": spec.kind,
            "group": spec.group,
            "operators": list(spec.operators),
            "options": [{"value": value, "label": label} for value, label in spec.options],
            "help_text": spec.help_text,
        }
        for spec in FIELDS.values()
    ]


# --- Validation ----------------------------------------------------------


def validate_definition(definition: Any, _depth: int = 0) -> dict[str, Any]:
    """Validate and canonicalize a filter tree, raising ValidationError on anything unknown."""
    if _depth > 4:
        raise ValidationError("Segment filters may be nested at most four groups deep.")
    if not isinstance(definition, dict):
        raise ValidationError("A segment definition must be an object.")

    match = definition.get("match", "all")
    if match not in ("all", "any"):
        raise ValidationError("Group match must be 'all' or 'any'.", field="match")

    raw_conditions = definition.get("conditions")
    if not isinstance(raw_conditions, list) or not raw_conditions:
        raise ValidationError("A segment group needs at least one condition.", field="conditions")
    if len(raw_conditions) > 25:
        raise ValidationError("A segment group may hold at most 25 conditions.", field="conditions")

    conditions: list[dict[str, Any]] = []
    for raw in raw_conditions:
        if not isinstance(raw, dict):
            raise ValidationError("Each condition must be an object.", field="conditions")
        if "conditions" in raw:
            conditions.append(validate_definition(raw, _depth + 1))
            continue
        conditions.append(_validate_condition(raw))

    return {"match": match, "conditions": conditions}


def _validate_condition(raw: dict[str, Any]) -> dict[str, Any]:
    key = raw.get("field")
    spec = FIELDS.get(key)
    if spec is None:
        raise ValidationError(f"Unknown segment field '{key}'.", field="field")

    operator = raw.get("operator")
    if operator not in spec.operators:
        raise ValidationError(
            f"Operator '{operator}' is not available for {spec.label}.", field="operator"
        )

    value = raw.get("value")
    if operator in ("is_empty", "is_not_empty"):
        value = None
    elif spec.kind == "enum" or operator in ("in", "not_in"):
        if not isinstance(value, list) or not value:
            raise ValidationError(f"{spec.label} needs at least one selected value.", field="value")
        if spec.options:
            allowed = {option for option, _ in spec.options}
            unknown = [item for item in value if item not in allowed]
            if unknown:
                raise ValidationError(
                    f"{spec.label} does not accept: {', '.join(map(str, unknown))}", field="value"
                )
    elif spec.kind == "tag":
        if not isinstance(value, list) or not value:
            raise ValidationError("Select at least one tag.", field="value")
        if not all(isinstance(item, int) for item in value):
            raise ValidationError("Tag filters use tag identifiers.", field="value")
    elif spec.kind == "boolean":
        if not isinstance(value, bool):
            raise ValidationError(f"{spec.label} expects true or false.", field="value")
    elif spec.kind == "number":
        if operator == "between":
            if not isinstance(value, list) or len(value) != 2:
                raise ValidationError("A between filter needs two numbers.", field="value")
            if any(not isinstance(item, (int, float)) for item in value):
                raise ValidationError("A between filter needs two numbers.", field="value")
        elif not isinstance(value, (int, float)):
            raise ValidationError(f"{spec.label} expects a number.", field="value")
    elif spec.kind == "date":
        if operator in ("within_days", "more_than_days_ago"):
            if not isinstance(value, int) or value < 0:
                raise ValidationError(
                    f"{spec.label} expects a whole number of days.", field="value"
                )
        elif not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValidationError(f"{spec.label} expects a date as YYYY-MM-DD.", field="value")
    elif spec.kind == "text":
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{spec.label} expects text.", field="value")
        value = value.strip()

    return {"field": key, "operator": operator, "value": value}


# --- Compilation ---------------------------------------------------------


class SegmentCompiler:
    """Compiles a validated definition into SQLAlchemy conditions over ``Customer``."""

    def __init__(self, thresholds: LifecycleThresholds):
        self.thresholds = thresholds
        self.now = utcnow()
        self.shipment_agg = (
            select(
                Shipment.customer_id.label("customer_id"),
                func.count(Shipment.id).label("qualifying_count"),
                func.min(Shipment.first_handoff_at).label("first_shipment_at"),
                func.max(Shipment.first_handoff_at).label("last_shipment_at"),
            )
            .where(*qualifying_shipment_filter())
            .group_by(Shipment.customer_id)
            .subquery()
        )

    @property
    def lifecycle_expression(self):
        agg = self.shipment_agg
        return case(
            (Customer.is_archived.is_(True), LifecycleStatus.ARCHIVED.value),
            (
                or_(agg.c.qualifying_count.is_(None), agg.c.qualifying_count == 0),
                LifecycleStatus.PROSPECT.value,
            ),
            (
                and_(
                    agg.c.qualifying_count == 1,
                    agg.c.last_shipment_at >= self.now - timedelta(days=self.thresholds.new_days),
                ),
                LifecycleStatus.NEW.value,
            ),
            (
                agg.c.last_shipment_at >= self.now - timedelta(days=self.thresholds.active_days),
                LifecycleStatus.ACTIVE.value,
            ),
            (
                agg.c.last_shipment_at >= self.now - timedelta(days=self.thresholds.at_risk_days),
                LifecycleStatus.AT_RISK.value,
            ),
            else_=LifecycleStatus.INACTIVE.value,
        )

    def base_query(self) -> Select:
        return (
            select(Customer)
            .outerjoin(self.shipment_agg, self.shipment_agg.c.customer_id == Customer.id)
            .where(Customer.merged_into_customer_id.is_(None))
        )

    def compile(self, definition: dict[str, Any]):
        clauses = []
        for condition in definition["conditions"]:
            if "conditions" in condition:
                clauses.append(self.compile(condition))
            else:
                clauses.append(self._compile_condition(condition))
        combiner = and_ if definition["match"] == "all" else or_
        return combiner(*clauses)

    def _compile_condition(self, condition: dict[str, Any]):
        key = condition["field"]
        operator = condition["operator"]
        value = condition["value"]
        agg = self.shipment_agg

        if key in ("full_name", "city", "province_state", "country_code"):
            column = getattr(Customer, key)
            return self._text_clause(column, operator, value)

        if key in (
            "preferred_language",
            "category",
            "primary_shipping_purpose",
            "shipping_frequency",
            "primary_route_group",
        ):
            column = getattr(Customer, key)
            return column.in_(value) if operator == "in" else not_(column.in_(value))

        if key == "route_interest":
            clause = exists(
                select(CustomerRouteInterest.id).where(
                    CustomerRouteInterest.customer_id == Customer.id,
                    CustomerRouteInterest.route_group.in_(value),
                )
            )
            # The declared primary route counts as an interest too.
            clause = or_(clause, Customer.primary_route_group.in_(value))
            return clause if operator == "in" else not_(clause)

        if key == "observed_route_group":
            clause = exists(
                select(Shipment.id).where(
                    Shipment.customer_id == Customer.id,
                    Shipment.route_group.in_(value),
                    *qualifying_shipment_filter(),
                )
            )
            return clause if operator == "in" else not_(clause)

        if key == "lifecycle_status":
            expression = self.lifecycle_expression
            return expression.in_(value) if operator == "in" else not_(expression.in_(value))

        if key == "total_qualifying_shipments":
            column = func.coalesce(agg.c.qualifying_count, 0)
            return self._number_clause(column, operator, value)

        if key == "is_repeat_customer":
            clause = func.coalesce(agg.c.qualifying_count, 0) >= 2
            return clause if value else not_(clause)

        if key in ("last_shipment_at", "first_shipment_at"):
            column = (
                agg.c.last_shipment_at if key == "last_shipment_at" else agg.c.first_shipment_at
            )
            return self._date_clause(column, operator, value)

        if key == "date_added":
            return self._date_clause(Customer.created_at, operator, value)

        if key == "has_overdue_task":
            clause = exists(
                select(FollowUpTask.id).where(
                    FollowUpTask.customer_id == Customer.id,
                    FollowUpTask.status.in_(list(OPEN_TASK_STATUSES)),
                    FollowUpTask.due_at.is_not(None),
                    FollowUpTask.due_at < self.now,
                )
            )
            return clause if value else not_(clause)

        if key == "has_open_task":
            clause = exists(
                select(FollowUpTask.id).where(
                    FollowUpTask.customer_id == Customer.id,
                    FollowUpTask.status.in_(list(OPEN_TASK_STATUSES)),
                )
            )
            return clause if value else not_(clause)

        if key == "has_unresolved_service_issue":
            clause = exists(
                select(ServiceIssue.id).where(
                    ServiceIssue.customer_id == Customer.id,
                    ServiceIssue.status.in_(
                        [ServiceIssueStatus.OPEN, ServiceIssueStatus.IN_REVIEW]
                    ),
                )
            )
            return clause if value else not_(clause)

        if key == "tag":
            if operator == "has_any":
                return exists(
                    select(CustomerTag.id).where(
                        CustomerTag.customer_id == Customer.id, CustomerTag.tag_id.in_(value)
                    )
                )
            if operator == "has_none":
                return not_(
                    exists(
                        select(CustomerTag.id).where(
                            CustomerTag.customer_id == Customer.id, CustomerTag.tag_id.in_(value)
                        )
                    )
                )
            return and_(
                *[
                    exists(
                        select(CustomerTag.id).where(
                            CustomerTag.customer_id == Customer.id, CustomerTag.tag_id == tag_id
                        )
                    )
                    for tag_id in value
                ]
            )

        if key == "owner_user_id":
            if operator == "is_empty":
                return Customer.owner_user_id.is_(None)
            clause = Customer.owner_user_id.in_(value)
            return clause if operator == "in" else not_(clause)

        if key in ("do_not_contact", "is_archived"):
            column = getattr(Customer, key)
            return column.is_(True) if value else column.is_(False)

        raise ValidationError(f"Unsupported segment field '{key}'.")

    @staticmethod
    def _text_clause(column, operator: str, value):
        if operator == "contains":
            return func.lower(column).like(f"%{value.lower()}%")
        if operator == "not_contains":
            return or_(column.is_(None), not_(func.lower(column).like(f"%{value.lower()}%")))
        if operator == "equals":
            return func.lower(column) == value.lower()
        if operator == "not_equals":
            return or_(column.is_(None), func.lower(column) != value.lower())
        if operator == "is_empty":
            return or_(column.is_(None), column == "")
        return and_(column.is_not(None), column != "")

    @staticmethod
    def _number_clause(column, operator: str, value):
        if operator == "equals":
            return column == value
        if operator == "not_equals":
            return column != value
        if operator == "gte":
            return column >= value
        if operator == "lte":
            return column <= value
        low, high = sorted(value)
        return and_(column >= low, column <= high)

    def _date_clause(self, column, operator: str, value):
        if operator == "within_days":
            return and_(column.is_not(None), column >= self.now - timedelta(days=value))
        if operator == "more_than_days_ago":
            return and_(column.is_not(None), column < self.now - timedelta(days=value))
        if operator == "before":
            return and_(column.is_not(None), column < _parse_date(value))
        if operator == "after":
            return and_(column.is_not(None), column > _parse_date(value))
        if operator == "is_empty":
            return column.is_(None)
        return column.is_not(None)


def _parse_date(value: str):
    from datetime import datetime

    return datetime.strptime(value, "%Y-%m-%d")


def build_query(definition: dict[str, Any], thresholds: LifecycleThresholds) -> Select:
    compiler = SegmentCompiler(thresholds)
    return compiler.base_query().where(compiler.compile(definition))


def count_members(db: Session, definition: dict[str, Any], thresholds: LifecycleThresholds) -> int:
    query = (
        build_query(definition, thresholds)
        .with_only_columns(func.count(Customer.id))
        .order_by(None)
    )
    return int(db.scalar(query) or 0)


def list_members(
    db: Session,
    definition: dict[str, Any],
    thresholds: LifecycleThresholds,
    *,
    limit: int = 25,
    offset: int = 0,
) -> list[Customer]:
    query = (
        build_query(definition, thresholds)
        .order_by(Customer.full_name.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(query).unique().all())


def marketing_eligible_count(
    db: Session,
    definition: dict[str, Any],
    thresholds: LifecycleThresholds,
    channel: str = ConsentChannel.EMAIL,
) -> int:
    """Count segment members who may actually receive marketing on ``channel``.

    Kept separate from the segment count so a segment is never mistaken for an
    outreach list (Design.md section 8).
    """
    from app.services import consent_service

    members = db.scalars(build_query(definition, thresholds)).unique().all()
    return sum(
        1 for customer in members if consent_service.marketing_eligible(db, customer, channel)
    )


# --- Plain-language description -----------------------------------------


def describe(
    definition: dict[str, Any],
    tag_names: dict[int, str] | None = None,
    staff_names: dict[int, str] | None = None,
) -> str:
    """Generate the readable definition shown next to the builder (Design.md section 8)."""
    tag_names = tag_names or {}
    staff_names = staff_names or {}
    joiner = " and " if definition["match"] == "all" else " or "
    parts: list[str] = []
    for condition in definition["conditions"]:
        if "conditions" in condition:
            parts.append(f"({describe(condition, tag_names, staff_names)})")
        else:
            parts.append(_describe_condition(condition, tag_names, staff_names))
    return joiner.join(parts)


def _describe_condition(
    condition: dict[str, Any], tag_names: dict[int, str], staff_names: dict[int, str]
) -> str:
    spec = FIELDS[condition["field"]]
    operator = condition["operator"]
    value = condition["value"]

    if spec.kind == "tag":
        names = [tag_names.get(item, f"tag {item}") for item in value]
        word = {
            "has_any": "has any tag of",
            "has_all": "has every tag of",
            "has_none": "has none of the tags",
        }[operator]
        return f"{spec.label} {word} {', '.join(names)}"
    if condition["field"] == "owner_user_id":
        if operator == "is_empty":
            return "Assigned staff is empty"
        names = [staff_names.get(item, f"user {item}") for item in value]
        word = "is" if operator == "in" else "is not"
        return f"Assigned staff {word} {', '.join(names)}"
    if spec.kind == "boolean":
        return f"{spec.label} is {'yes' if value else 'no'}"
    if spec.kind == "enum" or operator in ("in", "not_in"):
        labels = dict(spec.options)
        rendered = ", ".join(labels.get(item, str(item)) for item in value)
        return f"{spec.label} {'is' if operator == 'in' else 'is not'} {rendered}"
    if spec.kind == "date":
        if operator == "within_days":
            return f"{spec.label} is within the last {value} days"
        if operator == "more_than_days_ago":
            return f"{spec.label} is more than {value} days ago"
        if operator == "is_empty":
            return f"{spec.label} is empty"
        if operator == "is_not_empty":
            return f"{spec.label} is recorded"
        return f"{spec.label} is {operator} {value}"
    if spec.kind == "number":
        words = {
            "equals": "is",
            "not_equals": "is not",
            "gte": "is at least",
            "lte": "is at most",
            "between": "is between",
        }
        if operator == "between":
            return f"{spec.label} is between {value[0]} and {value[1]}"
        return f"{spec.label} {words[operator]} {value}"
    words = {
        "contains": "contains",
        "not_contains": "does not contain",
        "equals": "is",
        "not_equals": "is not",
        "is_empty": "is empty",
        "is_not_empty": "is recorded",
    }
    if operator in ("is_empty", "is_not_empty"):
        return f"{spec.label} {words[operator]}"
    return f'{spec.label} {words[operator]} "{value}"'


def load_definition(raw: str) -> dict[str, Any]:
    try:
        return validate_definition(json.loads(raw))
    except (
        json.JSONDecodeError
    ) as exc:  # pragma: no cover - stored definitions are validated on write
        raise ValidationError("Stored segment definition is not valid JSON.") from exc


def dump_definition(definition: dict[str, Any]) -> str:
    return json.dumps(definition, ensure_ascii=False, separators=(",", ":"))


def resolve_tag_names(db: Session) -> dict[int, str]:
    return {tag.id: tag.name for tag in db.scalars(select(Tag)).all()}
