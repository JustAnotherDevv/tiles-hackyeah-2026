"""Secrets & credentials (gitleaks-derived, RE2-clean rules + entropy / placeholder filters)."""

from ._base import CoreView

DETECTORS = [
    CoreView("secret.aws_access_key", "AWS_KEY"),
    CoreView("secret.aws_secret_key", "AWS_SECRET"),
    CoreView("secret.github", "GITHUB_TOKEN"),
    CoreView("secret.slack", "SLACK_TOKEN"),
    CoreView("secret.stripe_access_token", "STRIPE_KEY"),
    CoreView("secret.openai_api_key", "OPENAI_KEY"),
    CoreView("secret.anthropic_api_key", "ANTHROPIC_KEY"),
    CoreView("secret.jwt", "JWT"),
    CoreView("secret.private_key", "PRIVATE_KEY"),
    CoreView("secret.password", "PASSWORD"),
    CoreView("secret.connection_string_password", "CONNECTION_STRING"),
    CoreView("secret.generic", "GENERIC_SECRET"),
]
