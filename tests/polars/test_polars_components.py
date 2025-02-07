"""Unit tests for polars components."""

from typing import List

import polars as pl
import pytest

import pandera.polars as pa
from pandera.backends.base import CoreCheckResult
from pandera.backends.polars.components import ColumnBackend
from pandera.errors import SchemaError, SchemaDefinitionError


DTYPES_AND_DATA = [
    # python types
    (int, [1, 2, 3]),
    (str, ["foo", "bar", "baz"]),
    (float, [1.0, 2.0, 3.0]),
    (bool, [True, False, True]),
    # polars types
    (pl.Int64, [1, 2, 3]),
    (pl.Utf8, ["foo", "bar", "baz"]),
    (pl.Float64, [1.0, 2.0, 3.0]),
    (pl.Boolean, [True, False, True]),
]


@pytest.mark.parametrize("dtype,data", DTYPES_AND_DATA)
def test_column_schema_simple_dtypes(dtype, data):
    schema = pa.Column(dtype, name="column")
    data = pl.LazyFrame({"column": data})
    validated_data = schema.validate(data).collect()
    assert validated_data.equals(data.collect())


def test_column_schema_name_none():
    schema = pa.Column()
    data = pl.LazyFrame({"column": [1, 2, 3]})
    with pytest.raises(
        SchemaDefinitionError,
        match="Column schema must have a name specified",
    ):
        schema.validate(data).collect()


@pytest.mark.parametrize(
    "column_kwargs",
    [
        {"name": r"^col_\d$", "regex": False},
        {"name": r"col_\d", "regex": True},
    ],
)
def test_column_schema_regex(column_kwargs):
    n_cols = 10
    schema = pa.Column(int, **column_kwargs)
    data = pl.LazyFrame({f"col_{i}": [1, 2, 3] for i in range(n_cols)})
    validated_data = data.pipe(schema.validate).collect()
    assert validated_data.equals(data.collect())

    for i in range(n_cols):
        invalid_data = data.cast({f"col_{i}": str})
        with pytest.raises(SchemaError):
            invalid_data.pipe(schema.validate).collect()


def test_get_columnd_backend():
    assert isinstance(pa.Column.get_backend(pl.LazyFrame()), ColumnBackend)
    assert isinstance(
        pa.Column.get_backend(check_type=pl.LazyFrame), ColumnBackend
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": r"^col_\d+$"},
        {"name": r"col_\d+", "regex": True},
    ],
)
def test_get_regex_columns(kwargs):
    column_schema = pa.Column(**kwargs)
    backend = ColumnBackend()
    data = pl.DataFrame({f"col_{i}": [1, 2, 3] for i in range(10)}).lazy()
    matched_columns = backend.get_regex_columns(column_schema, data)
    assert matched_columns == data.columns

    no_match_data = data.rename(
        lambda c: c.replace(
            "col_",
            "foo_",
        )
    )
    matched_columns = backend.get_regex_columns(column_schema, no_match_data)
    assert matched_columns == []


@pytest.mark.parametrize(
    "data,from_dtype,to_dtype,exception_cls",
    [
        ([1, 2, 3], pl.Int64, pl.Utf8, None),
        ([1, 2, 3], pl.Int64, pl.Float64, None),
        ([0, 1, 0], pl.Int64, pl.Boolean, None),
        ([*"123"], pl.Utf8, pl.Int64, None),
        ([*"123"], pl.Utf8, pl.Float64, None),
        ([*"101"], pl.Utf8, pl.Boolean, SchemaError),
        ([*"abc"], pl.Utf8, pl.Int64, SchemaError),
        ([1.0, 2.0, 3.0], pl.Float64, pl.Utf8, None),
        ([1.0, 2.0, 3.0], pl.Float64, pl.Int64, None),
        ([1.0, 0.0, 1.0], pl.Float64, pl.Boolean, None),
        ([True, False], pl.Boolean, pl.Int64, None),
        ([True, False], pl.Boolean, pl.Float64, None),
        ([True, False], pl.Boolean, pl.Utf8, None),
    ],
)
def test_coerce_dtype(data, from_dtype, to_dtype, exception_cls):
    data = pl.LazyFrame({"column": pl.Series(data, dtype=from_dtype)})
    column_schema = pa.Column(to_dtype, name="column", coerce=True)
    backend = ColumnBackend()

    if exception_cls is None:
        coerced_data = backend.coerce_dtype(data, column_schema)
        assert coerced_data.collect().schema["column"] == to_dtype
    else:
        with pytest.raises(exception_cls):
            backend.coerce_dtype(data, column_schema)


NULLABLE_DTYPES_AND_DATA = [
    [pl.Int64, [1, 2, 3, None]],
    [pl.Utf8, ["foo", "bar", "baz", None]],
    [pl.Float64, [1.0, 2.0, 3.0, float("nan")]],
    [pl.Boolean, [True, False, True, None]],
]


@pytest.mark.parametrize("dtype, data", NULLABLE_DTYPES_AND_DATA)
@pytest.mark.parametrize("nullable", [True, False])
def test_check_nullable(dtype, data, nullable):
    data = pl.LazyFrame({"column": pl.Series(data, dtype=dtype)})
    column_schema = pa.Column(pl.Int64, nullable=nullable, name="column")
    backend = ColumnBackend()
    check_results: List[CoreCheckResult] = backend.check_nullable(
        data, column_schema
    )
    for result in check_results:
        assert result.passed if nullable else not result.passed


@pytest.mark.parametrize("dtype, data", NULLABLE_DTYPES_AND_DATA)
@pytest.mark.parametrize("nullable", [True, False])
def test_check_nullable_regex(dtype, data, nullable):
    data = pl.LazyFrame(
        {f"column_{i}": pl.Series(data, dtype=dtype) for i in range(3)}
    )
    column_schema = pa.Column(
        pl.Int64, nullable=nullable, name=r"^column_\d+$"
    )
    backend = ColumnBackend()
    check_results = backend.check_nullable(data, column_schema)
    for result in check_results:
        assert result.passed if nullable else not result.passed


@pytest.mark.parametrize("unique", [True, False])
def test_check_unique(unique):
    data = pl.LazyFrame({"column": [2, 2, 2]})
    column_schema = pa.Column(name="column", unique=unique)
    backend = ColumnBackend()
    check_results = backend.check_unique(data, column_schema)
    for result in check_results:
        assert not result.passed if unique else result.passed


@pytest.mark.parametrize(
    "data,from_dtype",
    [
        ([1, 2, 3], pl.Int64),
        ([*"abc"], pl.Utf8),
        ([1.0, 2.0, 3.0], pl.Float64),
        ([True, False], pl.Boolean),
    ],
)
@pytest.mark.parametrize(
    "check_dtype", [pl.Int64, pl.Utf8, pl.Float64, pl.Boolean]
)
def test_check_dtype(data, from_dtype, check_dtype):
    data = pl.LazyFrame({"column": pl.Series(data, dtype=from_dtype)})
    column_schema = pa.Column(check_dtype, name="column", coerce=True)
    backend = ColumnBackend()

    check_results = backend.check_dtype(data, column_schema)
    for result in check_results:
        assert (
            result.passed if from_dtype == check_dtype else not result.passed
        )


@pytest.mark.parametrize(
    "data,dtype,default",
    [
        ([1, 2, None], pl.Int64, 3),
        (["a", "b", "c", None], pl.Utf8, "d"),
        ([1.0, 2.0, 3.0, float("nan")], pl.Float64, 4.0),
        ([False, False, False, None], pl.Boolean, True),
    ],
)
def test_set_default(data, dtype, default):
    data = pl.LazyFrame({"column": pl.Series(data, dtype=dtype)})
    column_schema = pa.Column(dtype, name="column", default=default)
    backend = ColumnBackend()
    validated_data = backend.set_default(data, column_schema).collect()
    assert validated_data.select(pl.col("column").eq(default).any()).item()
