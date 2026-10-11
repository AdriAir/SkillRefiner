"""Validate trusted packaged contracts without remote schema retrieval."""
from pathlib import Path
import json

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .common import RefinerError


def validate_contract(name, value):
    directory = Path(__file__).resolve().parents[2] / "schemas"
    registry = Registry()
    schemas = {}
    for path in directory.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        schemas[path.stem.removesuffix(".schema")] = schema
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    if name not in schemas:
        raise RefinerError("Unknown packaged contract")
    validator = Draft202012Validator(schemas[name], registry=registry)
    if next(validator.iter_errors(value), None) is not None:
        # Validation diagnostics must never include private instance values.
        raise RefinerError(f"Invalid {name} contract")
    return value
