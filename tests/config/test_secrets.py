from __future__ import annotations

import pytest

from db_mcp_server.config.secrets import EmptySecretError, MissingSecretError, ResolvedSecret, resolve_env_secret, resolve_env_secrets, secret_refs_from_mapping


def test_resolve_env_secret_raises_for_missing_and_empty_values() -> None:
    with pytest.raises(MissingSecretError) as missing_exc:
        resolve_env_secret(
            "PRIMARY_PASSWORD",
            field_name="password",
            connection_name="primary",
            env={},
        )

    assert missing_exc.value.env_var == "PRIMARY_PASSWORD"
    assert "connection 'primary'" in str(missing_exc.value)
    assert "field 'password'" in str(missing_exc.value)

    with pytest.raises(EmptySecretError) as empty_exc:
        resolve_env_secret(
            "PRIMARY_PASSWORD",
            field_name="password",
            connection_name="primary",
            env={"PRIMARY_PASSWORD": ""},
        )

    assert empty_exc.value.env_var == "PRIMARY_PASSWORD"
    assert "connection 'primary'" in str(empty_exc.value)
    assert "field 'password'" in str(empty_exc.value)


def test_resolved_secret_repr_and_str_are_redacted() -> None:
    secret = resolve_env_secret(
        "PRIMARY_PASSWORD",
        field_name="password",
        connection_name="primary",
        env={"PRIMARY_PASSWORD": "super-secret-value"},
    )

    assert isinstance(secret, ResolvedSecret)
    assert secret.reveal() == "super-secret-value"
    assert str(secret) == "<redacted>"
    assert "super-secret-value" not in repr(secret)
    assert "value=<redacted>" in repr(secret)


def test_secret_refs_from_mapping_and_batch_resolution_ignore_optional_values() -> None:
    refs = secret_refs_from_mapping(
        {
            "dsn_env": "PRIMARY_DSN",
            "password_env": "PRIMARY_PASSWORD",
            "catalog": "analytics",
            "role_env": None,
        }
    )

    assert refs == {
        "dsn": "PRIMARY_DSN",
        "password": "PRIMARY_PASSWORD",
        "role": None,
    }

    resolved = resolve_env_secrets(
        refs,
        connection_name="primary",
        env={"PRIMARY_DSN": "dsn://example", "PRIMARY_PASSWORD": "secret"},
    )

    assert set(resolved) == {"dsn", "password"}
    assert resolved["dsn"].reveal() == "dsn://example"
    assert resolved["password"].reveal() == "secret"
