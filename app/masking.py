"""Applies column masking based on a source's and a query's sensitive-column metadata."""
from typing import Set

import pandas as pd

from app.registry.models import QueryDefinition, SourceDefinition

_MASK_VISIBLE_SUFFIX_LENGTH = 4
_MASK_CHAR = "*"


def effective_sensitive_columns(query: QueryDefinition, source: SourceDefinition) -> Set[str]:
    sensitive = set(source.sensitive_columns) | set(query.additional_sensitive_columns)
    return sensitive - set(query.unmasked_columns)


def _mask_value(value):
    if value is None:
        return value
    text = str(value)
    if len(text) <= _MASK_VISIBLE_SUFFIX_LENGTH:
        return _MASK_CHAR * len(text)
    return _MASK_CHAR * (len(text) - _MASK_VISIBLE_SUFFIX_LENGTH) + text[-_MASK_VISIBLE_SUFFIX_LENGTH:]


def mask_dataframe(
    dataframe: pd.DataFrame, query: QueryDefinition, source: SourceDefinition
) -> pd.DataFrame:
    columns_to_mask = effective_sensitive_columns(query, source) & set(dataframe.columns)
    if not columns_to_mask:
        return dataframe
    masked = dataframe.copy()
    for column in columns_to_mask:
        masked[column] = masked[column].map(_mask_value)
    return masked
