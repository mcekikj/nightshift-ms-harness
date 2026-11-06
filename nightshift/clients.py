"""Chat client factory. The harness takes any chat client; this is the only provider-specific code."""

from __future__ import annotations

from .config import Settings


def _check(name: str, value: str | None) -> str:
    if not value:
        raise ValueError(f"Set {name} (see .env.example).")
    if "<" in value or ">" in value:
        raise ValueError(f"{name} still holds the placeholder from .env.example: {value}")
    return value


def build_chat_client(settings: Settings):
    """Return a chat client for the configured provider.

    - foundry:      Microsoft Foundry project (Responses API, Entra ID). Supports hosted web search,
                    Foundry tracing and the hosted-agent deployment path.
    - azure-openai: Azure OpenAI resource through the OpenAI client (Responses API, Entra ID).
    - openai:       OpenAI directly (OPENAI_API_KEY), handy for a quick local comparison.
    """
    if settings.provider == "foundry":
        from agent_framework.foundry import FoundryChatClient
        from azure.identity import AzureCliCredential

        return FoundryChatClient(
            project_endpoint=_check("FOUNDRY_PROJECT_ENDPOINT", settings.foundry_project_endpoint),
            model=_check("FOUNDRY_MODEL", settings.foundry_model),
            credential=AzureCliCredential(),
        )

    if settings.provider == "azure-openai":
        from agent_framework.openai import OpenAIChatClient
        from azure.identity import AzureCliCredential

        return OpenAIChatClient(
            model=_check("AZURE_OPENAI_DEPLOYMENT", settings.azure_openai_deployment),
            azure_endpoint=_check("AZURE_OPENAI_ENDPOINT", settings.azure_openai_endpoint),
            credential=AzureCliCredential(),
        )

    from agent_framework.openai import OpenAIChatClient

    return OpenAIChatClient(model=_check("OPENAI_CHAT_MODEL_ID", settings.openai_model))
