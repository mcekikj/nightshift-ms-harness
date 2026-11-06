"""Runtime settings, read from the environment (and a .env file if present)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

PROVIDERS = ("foundry", "azure-openai", "openai")
TELEMETRY_MODES = ("none", "console", "otlp", "azure-monitor", "foundry")


@dataclass(frozen=True)
class Settings:
    provider: str
    foundry_project_endpoint: str | None
    foundry_model: str | None
    azure_openai_endpoint: str | None
    azure_openai_deployment: str | None
    openai_model: str | None
    telemetry: str

    @classmethod
    def from_env(cls, *, provider: str | None = None, model: str | None = None, telemetry: str | None = None) -> Settings:
        load_dotenv()  # Agent Framework does not load .env files for you
        provider = (provider or os.environ.get("NIGHTSHIFT_PROVIDER") or "foundry").lower()
        if provider not in PROVIDERS:
            raise ValueError(f"NIGHTSHIFT_PROVIDER must be one of {PROVIDERS}, got {provider!r}")
        telemetry = (telemetry or os.environ.get("NIGHTSHIFT_TELEMETRY") or "none").lower()
        if telemetry not in TELEMETRY_MODES:
            raise ValueError(f"NIGHTSHIFT_TELEMETRY must be one of {TELEMETRY_MODES}, got {telemetry!r}")
        return cls(
            provider=provider,
            foundry_project_endpoint=os.environ.get("FOUNDRY_PROJECT_ENDPOINT"),
            foundry_model=model or os.environ.get("FOUNDRY_MODEL"),
            azure_openai_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT"),
            azure_openai_deployment=model or os.environ.get("AZURE_OPENAI_DEPLOYMENT"),
            openai_model=model or os.environ.get("OPENAI_CHAT_MODEL_ID"),
            telemetry=telemetry,
        )

    @property
    def model_label(self) -> str:
        if self.provider == "foundry":
            return f"foundry:{self.foundry_model}"
        if self.provider == "azure-openai":
            return f"azure-openai:{self.azure_openai_deployment}"
        return f"openai:{self.openai_model}"
