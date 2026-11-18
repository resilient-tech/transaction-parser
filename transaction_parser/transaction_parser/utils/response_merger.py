from dataclasses import dataclass
from typing import Any

import frappe


@dataclass
class FieldType:
    """Base class for field types in schema."""

    required: bool

    @staticmethod
    def is_empty(value: Any) -> bool:
        return (
            value is None
            or value == ""
            or (isinstance(value, list | set | tuple | dict) and len(value) == 0)
        )


@dataclass
class PrimitiveField(FieldType):
    """Represents a primitive field (string, number, date, etc.)."""

    pass


@dataclass
class ObjectField(FieldType):
    """Represents a nested object field with child fields."""

    children: dict[str, FieldType]


@dataclass
class ListField(FieldType):
    """Represents a list/array field."""

    item_type: FieldType  # Type of items in the list


class SchemaParser:
    """Parses a schema dict into a structured FieldType hierarchy."""

    def parse(self, schema: dict) -> dict[str, FieldType]:
        """Parse schema dict into field name -> FieldType mapping."""
        fields = {}

        for key, value in schema.items():
            fields[key] = self._parse_field(value)

        return fields

    def _parse_field(self, schema_value: Any) -> FieldType:
        """Determine and return the appropriate FieldType for a schema value."""
        if isinstance(schema_value, list):
            if not schema_value:
                return ListField(required=True, item_type=PrimitiveField(required=True))

            item_schema = schema_value[0]

            if isinstance(item_schema, dict):
                item_fields = self.parse(item_schema)
                return ListField(
                    required=True,
                    item_type=ObjectField(required=True, children=item_fields),
                )
            else:
                return ListField(
                    required=True,
                    item_type=PrimitiveField(required=True),
                )

        elif isinstance(schema_value, dict):
            children = self.parse(schema_value)
            return ObjectField(required=True, children=children)

        else:
            return PrimitiveField(required=True)


class ResponseMerger:
    """Schema-driven merger for AI responses from multiple attachments."""

    def __init__(
        self,
        response: dict,
        schema: dict,
        match_keys: dict[str, list[str]] | None = None,
    ):
        self.response = (
            frappe._dict(response) if isinstance(response, dict) else response
        )
        self.schema = schema
        self.match_keys = match_keys or {}

        parser = SchemaParser()
        self.fields = parser.parse(schema)

    def is_complete(self) -> bool:
        """Return True if all required fields are filled."""
        return len(self.get_missing_fields()) == 0

    def get_missing_fields(self) -> list[str]:
        """Return dot-separated paths of missing required fields."""
        missing = []
        self._check_missing_fields(self.fields, self.response, "", missing)
        return missing

    def _check_missing_fields(
        self,
        fields: dict[str, FieldType],
        data: dict,
        path_prefix: str,
        missing: list[str],
    ) -> None:
        for key, field_type in fields.items():
            field_path = f"{path_prefix}.{key}" if path_prefix else key
            value = data.get(key) if isinstance(data, dict) else None

            if isinstance(field_type, PrimitiveField):
                if field_type.required and field_type.is_empty(value):
                    missing.append(field_path)

            elif isinstance(field_type, ObjectField):
                if field_type.required and field_type.is_empty(value):
                    missing.append(field_path)
                elif value:
                    self._check_missing_fields(
                        field_type.children, value, field_path, missing
                    )

            # List fields are checked during merging, not at top level

    def merge(self, new_response: dict) -> None:
        """Merge new_response into the existing response."""
        self._merge_fields(self.fields, self.response, new_response)

    def _merge_fields(
        self,
        fields: dict[str, FieldType],
        target: dict,
        source: dict,
    ) -> None:
        for key, field_type in fields.items():
            source_value = source.get(key)

            if field_type.is_empty(source_value):
                # keep `[]` / `{}` instead of leaving the key missing
                if source_value is not None and target.get(key) is None:
                    target[key] = source_value

                continue

            if isinstance(field_type, PrimitiveField):
                self._merge_primitive(target, key, source_value)

            elif isinstance(field_type, ObjectField):
                self._merge_object(field_type, target, key, source_value)

            elif isinstance(field_type, ListField):
                self._merge_list(field_type, target, key, source_value)

    def _merge_primitive(self, target: dict, key: str, source_value: Any) -> None:
        if FieldType.is_empty(target.get(key)):
            target[key] = source_value

    def _merge_object(
        self,
        field_type: ObjectField,
        target: dict,
        key: str,
        source_value: dict,
    ) -> None:
        if key not in target or target[key] is None:
            target[key] = frappe._dict()

        self._merge_fields(field_type.children, target[key], source_value)

    def _merge_list(
        self,
        field_type: ListField,
        target: dict,
        key: str,
        source_value: list,
    ) -> None:
        target_list = target.get(key, [])

        if not target_list:
            target[key] = source_value
            return

        if not source_value:
            return

        if not isinstance(field_type.item_type, ObjectField):
            return

        key_fields = self.match_keys.get(key, [])
        if not key_fields:
            return

        for target_item in target_list:
            matched_item = self._find_matching_item(
                target_item, source_value, key_fields
            )
            if matched_item:
                self._merge_fields(
                    field_type.item_type.children, target_item, matched_item
                )

    def _find_matching_item(
        self,
        target_item: dict,
        source_items: list[dict],
        key_fields: list[str],
    ) -> dict | None:
        for source_item in source_items:
            if self._items_match(target_item, source_item, key_fields):
                return source_item

        return None

    def _items_match(
        self,
        item1: dict,
        item2: dict,
        key_fields: list[str],
    ) -> bool:
        for field in key_fields:
            value1 = item1.get(field)
            value2 = item2.get(field)

            if value1 and value2 and value1 == value2:
                return True  # Immediate match if any key field matches

        return False
