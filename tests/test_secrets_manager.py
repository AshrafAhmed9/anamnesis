from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_get_database_url_resolves_from_secrets_manager(monkeypatch):
    """DATABASE_SECRET_ARN (set by infra/template.yaml on the deployed
    Lambda stack, never DATABASE_URL directly there) should be resolved
    via Secrets Manager, not read as a plaintext env var.
    """
    import anamnesis.db.engine as engine_module

    monkeypatch.setenv("DATABASE_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123:secret:anamnesis/db-url")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    engine_module._secrets_manager_url_cache = None

    mock_client = MagicMock()
    mock_client.get_secret_value.return_value = {
        "SecretString": "cockroachdb+psycopg://root@example.com:26257/anamnesis?sslmode=verify-full"
    }

    with patch("boto3.client", return_value=mock_client) as mock_boto3_client:
        url = engine_module.get_database_url()

    assert url == "cockroachdb+psycopg://root@example.com:26257/anamnesis?sslmode=verify-full"
    mock_boto3_client.assert_called_once_with("secretsmanager", region_name=None)
    mock_client.get_secret_value.assert_called_once_with(
        SecretId="arn:aws:secretsmanager:us-east-1:123:secret:anamnesis/db-url"
    )

    engine_module._secrets_manager_url_cache = None


def test_get_database_url_secrets_manager_result_is_cached(monkeypatch):
    """A warm Lambda invocation shouldn't re-fetch the secret on every call."""
    import anamnesis.db.engine as engine_module

    monkeypatch.setenv("DATABASE_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123:secret:anamnesis/db-url")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    engine_module._secrets_manager_url_cache = None

    mock_client = MagicMock()
    mock_client.get_secret_value.return_value = {"SecretString": "cockroachdb+psycopg://cached@example.com/db"}

    with patch("boto3.client", return_value=mock_client):
        first = engine_module.get_database_url()
        second = engine_module.get_database_url()

    assert first == second == "cockroachdb+psycopg://cached@example.com/db"
    mock_client.get_secret_value.assert_called_once()  # not called twice

    engine_module._secrets_manager_url_cache = None


def test_get_database_url_falls_back_to_plain_env_var(monkeypatch):
    """Local dev / tests: no DATABASE_SECRET_ARN set, use DATABASE_URL directly."""
    import anamnesis.db.engine as engine_module

    monkeypatch.delenv("DATABASE_SECRET_ARN", raising=False)
    monkeypatch.setenv("DATABASE_URL", "cockroachdb+psycopg://local@localhost:26257/anamnesis?sslmode=disable")

    url = engine_module.get_database_url()

    assert url == "cockroachdb+psycopg://local@localhost:26257/anamnesis?sslmode=disable"
