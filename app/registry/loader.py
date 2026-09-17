"""Auto-discovery for the sources and queries registries.

Adding a new SourceDefinition or QueryDefinition to a domain file under
app/sources/ or app/queries/ is enough for it to be picked up here -- no
central list to edit.
"""
import importlib
import pkgutil
from types import ModuleType
from typing import Dict, Type, TypeVar

from app.registry.models import QueryDefinition, SourceDefinition

T = TypeVar("T")


class RegistryError(ValueError):
    """Raised for duplicate definitions or a query referencing an unknown source."""


def _discover(package: ModuleType, model_cls: Type[T]) -> Dict[str, T]:
    found: Dict[str, T] = {}
    for module_info in pkgutil.iter_modules(package.__path__, prefix=package.__name__ + "."):
        module = importlib.import_module(module_info.name)
        for attr_name in dir(module):
            value = getattr(module, attr_name)
            if isinstance(value, model_cls):
                if value.name in found:
                    raise RegistryError(
                        f"Duplicate {model_cls.__name__} name '{value.name}' "
                        f"found in {module.__name__}"
                    )
                found[value.name] = value
    return found


def load_sources() -> Dict[str, SourceDefinition]:
    from app import sources

    return _discover(sources, SourceDefinition)


def load_queries() -> Dict[str, QueryDefinition]:
    from app import queries

    return _discover(queries, QueryDefinition)


def validate_query_sources(
    queries: Dict[str, QueryDefinition], sources: Dict[str, SourceDefinition]
) -> None:
    for query in queries.values():
        if query.source not in sources:
            raise RegistryError(
                f"Query '{query.name}' references unknown source '{query.source}'"
            )


def load_registries():
    """Load both registries and validate that every query references a real source."""
    sources = load_sources()
    queries = load_queries()
    validate_query_sources(queries, sources)
    return sources, queries
