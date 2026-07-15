import pytest
from pydantic import TypeAdapter, ValidationError
from datacompare.config.models import (
    GaussDBAConnection, GaussDBTConnection, GaussDBConnection, AnyConnection,
)


def test_a_variant_defaults_when_omitted():
    """variant field defaults to 'a' when not provided (backward compat)"""
    data = {
        "type": "gaussdb", "host": "h", "database": "d",
        "user": "u", "password": "p",
    }
    conn = TypeAdapter(AnyConnection).validate_python(data)
    assert isinstance(conn, GaussDBAConnection)
    assert conn.variant == "a"
    assert conn.port == 5432
    assert conn.ssl == "require"


def test_a_variant_explicit():
    data = {
        "type": "gaussdb", "variant": "a",
        "host": "h", "database": "d", "user": "u", "password": "p",
    }
    conn = TypeAdapter(AnyConnection).validate_python(data)
    assert isinstance(conn, GaussDBAConnection)


def test_t_variant_requires_jdbc_fields():
    data = {"type": "gaussdb", "variant": "t", "user": "u", "password": "p"}
    with pytest.raises(ValidationError) as exc:
        TypeAdapter(AnyConnection).validate_python(data)
    errors = str(exc.value)
    assert "jdbc_url" in errors
    assert "jdbc_jar_path" in errors
    assert "jdbc_driver_class" in errors


def test_t_variant_complete():
    data = {
        "type": "gaussdb", "variant": "t",
        "jdbc_url": "jdbc:zenith:@//h:1611/svc",
        "jdbc_jar_path": "/opt/gsjdbc4.jar",
        "jdbc_driver_class": "com.huawei.gauss.jdbc.ZenithDriver",
        "user": "u", "password": "p",
    }
    conn = TypeAdapter(AnyConnection).validate_python(data)
    assert isinstance(conn, GaussDBTConnection)
    assert conn.jdbc_properties == {}


def test_t_variant_with_properties():
    data = {
        "type": "gaussdb", "variant": "t",
        "jdbc_url": "jdbc:zenith:@//h:1611/svc",
        "jdbc_jar_path": "/opt/gsjdbc4.jar",
        "jdbc_driver_class": "com.huawei.gauss.jdbc.ZenithDriver",
        "user": "u", "password": "p",
        "jdbc_properties": {"loginTimeout": "30", "fetchSize": "1000"},
    }
    conn = TypeAdapter(AnyConnection).validate_python(data)
    assert conn.jdbc_properties["loginTimeout"] == "30"


def test_a_variant_rejects_jdbc_fields():
    """extra=forbid: A variant with jdbc_url should be rejected"""
    data = {
        "type": "gaussdb", "variant": "a",
        "host": "h", "database": "d", "user": "u", "password": "p",
        "jdbc_url": "jdbc:...",
    }
    with pytest.raises(ValidationError, match="extra"):
        TypeAdapter(AnyConnection).validate_python(data)


def test_t_variant_rejects_host_field():
    """extra=forbid: T variant with host should be rejected"""
    data = {
        "type": "gaussdb", "variant": "t", "host": "h",
        "jdbc_url": "j", "jdbc_jar_path": "p", "jdbc_driver_class": "c",
        "user": "u", "password": "p",
    }
    with pytest.raises(ValidationError, match="extra"):
        TypeAdapter(AnyConnection).validate_python(data)


def test_isinstance_check_works_on_union_type():
    """Python 3.10+ isinstance(x, X | Y) support — required by runner.py:27"""
    a = GaussDBAConnection(host="h", database="d", user="u", password="p")
    assert isinstance(a, GaussDBConnection)
    t = GaussDBTConnection(
        variant="t", jdbc_url="j", jdbc_jar_path="p",
        jdbc_driver_class="c", user="u", password="p",
    )
    assert isinstance(t, GaussDBConnection)
