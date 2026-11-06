#!/usr/bin/env python
"""Foundry Hosted Agent entry point.

The same `build_nightshift_agent` factory runs behind Foundry's Responses protocol. Differences from the
console host, following Microsoft's own guidance for hosted claws:

- Managed identity instead of the Azure CLI credential.
- File access is off, following Microsoft's production sample: arbitrary reads and writes on the container
  filesystem are a risk in a shared hosted environment. Shift reports would go to a blob-backed AgentFileStore.
- Memory is kept under the home directory, which the platform persists per session: every hosted session has
  its own sandbox and $HOME. A notebook shared by every shift needs an external AgentFileStore.
- No OpenTelemetry setup here: Foundry injects APPLICATIONINSIGHTS_CONNECTION_STRING and exports for you.

Run locally:   FOUNDRY_PROJECT_ENDPOINT=... FOUNDRY_MODEL=... python hosted.py   (serves http://127.0.0.1:8088/responses;
               set PORT to change the port)
Deploy:        see deploy/README.md (azd ai agent init ... --entry-point hosted.py, then azd deploy)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from agent_framework.foundry import FoundryChatClient, ResponsesHostServer
from azure.identity import AzureCliCredential, ManagedIdentityCredential

from nightshift.agent import HarnessOptions, Paths, build_nightshift_agent
from nightshift.world import World

ROOT = Path(__file__).resolve().parent


def _credential():
    client_id = os.environ.get("FOUNDRY_AGENT_INSTANCE_CLIENT_ID")
    return ManagedIdentityCredential(client_id=client_id) if client_id else AzureCliCredential()


async def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)  # hosted containers surface stderr
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
    model = os.environ.get("FOUNDRY_MODEL") or os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME")
    if not endpoint or not model:
        sys.exit("Set FOUNDRY_PROJECT_ENDPOINT and FOUNDRY_MODEL (or AZURE_AI_MODEL_DEPLOYMENT_NAME).")
    scenario = ROOT / "scenarios" / f"{os.environ.get('NIGHTSHIFT_SCENARIO', 'shift-01')}.json"
    client = FoundryChatClient(project_endpoint=endpoint, model=model, credential=_credential())  # shared by all requests
    paths = Paths(ROOT).with_state_root(Path.home() / ".nightshift")
    options = HarnessOptions(start_mode="execute", file_access=False)

    async def create_agent():
        """Called by the host for every request: a fresh agent over a fresh simulated world."""
        return build_nightshift_agent(client, World.load(scenario), paths, options).agent

    # Inside Foundry the platform routes traffic to the container; on a laptop, stay on localhost.
    host = "0.0.0.0" if os.environ.get("FOUNDRY_HOSTING_ENVIRONMENT") else "127.0.0.1"
    # history_source="agent": the harness's own history provider owns the transcript. The transcript, todos,
    # mode and standing approvals live in the AgentSession, which the host persists per session.
    await ResponsesHostServer(agent=create_agent, history_source="agent").run_async(host=host)


if __name__ == "__main__":
    asyncio.run(main())
