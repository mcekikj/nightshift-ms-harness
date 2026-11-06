# Host Night Shift on Microsoft Foundry (Foundry Hosted Agents)

The hosted entry point is [`hosted.py`](../hosted.py) at the repository root. `azd ai agent init` generates
`azure.yaml`, which names your Foundry project, so it is not committed (see `.gitignore`); the version used for
the article is shown below with the project replaced by placeholders.
This follows the Python path of Microsoft's "Agent Harness: Making your claw production-ready" post and the
Foundry hosted agents guide. Foundry Hosted Agents is generally available; the Python
`agent-framework-foundry-hosting` integration is still pre-release.

## What gets created

Nothing new at the subscription level when you target an existing project. `azd deploy` uploads the
repository as a ZIP (code deploy, dependencies resolved remotely from `requirements.txt`), creates the
hosted agent `nightshift` in the project (or a new version of it) and gives it its own Entra identity.
The platform sets `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_AGENT_INSTANCE_CLIENT_ID` and
`APPLICATIONINSIGHTS_CONNECTION_STRING` in the container; `AZURE_AI_MODEL_DEPLOYMENT_NAME` comes from the
`env` map in `azure.yaml`.

## Commands used

```bash
# one-time tooling (no sudo, no Docker needed for code deploy)
curl -fsSL https://aka.ms/install-azd.sh | bash -s -- -i ~/.local/azd -s ~/.local/bin
azd extension install azure.ai.agents
azd config set auth.useAzCliAuth true          # reuse `az login`

# initialise against an existing Foundry project and model deployment
azd ai agent init --no-prompt -e nightshift \
  -p /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<account>/projects/<project> \
  --deploy-mode code --runtime python_3_13 --entry-point hosted.py \
  --agent-name nightshift -d gpt-6-luna --protocol responses

# then add PYTHONNOUSERSITE, NIGHTSHIFT_SCENARIO and ENABLE_SENSITIVE_DATA to the agent's env map (see azure.yaml below)

# local check over the Responses protocol (outside Foundry the server binds to 127.0.0.1)
FOUNDRY_PROJECT_ENDPOINT=... FOUNDRY_MODEL=gpt-6-luna PORT=8089 python hosted.py
curl -X POST http://127.0.0.1:8089/responses -H "Content-Type: application/json" \
     -d '{"input":"List the open alerts for this shift and summarise them.","stream":false}'

# deploy, then talk to it and watch its logs
azd deploy --no-prompt -e nightshift
TOKEN=$(az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv)
curl -X POST "https://<account>.services.ai.azure.com/api/projects/<project>/agents/nightshift/endpoint/protocols/openai/responses?api-version=v1" \
     -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
     -d '{"input":"List the open alerts for this shift and summarise them in three lines.","stream":false}'
azd ai agent monitor --follow
```

`azd ai agent invoke` keeps reusing one conversation, and in my tests it failed while an earlier turn in that
conversation was still in flight. A plain POST without `previous_response_id` starts a fresh conversation.

## azure.yaml

What `azd ai agent init` generated, plus the three `env` entries added by hand. `PYTHONNOUSERSITE: "1"` is
the setting Microsoft's hosted-agent guide asks for in Python agents.

```yaml
infra:
    provider: microsoft.foundry
name: nightshift-ms-harness
services:
    nightshift:
        codeConfiguration:
            dependencyResolution: remote_build
            entryPoint: hosted.py
            runtime: python_3_13
        container:
            resources:
                cpu: "0.5"
                memory: 1Gi
        env:
            AZURE_AI_MODEL_DEPLOYMENT_NAME: ${AZURE_AI_MODEL_DEPLOYMENT_NAME}
            PYTHONNOUSERSITE: "1"
            NIGHTSHIFT_SCENARIO: shift-01
            ENABLE_SENSITIVE_DATA: "false"
        host: azure.ai.agent
        kind: hosted
        language: python
        name: nightshift
        project: .
        protocols:
            - protocol: responses
              version: 2.0.0
        uses:
            - <project>
    <project>:
        endpoint: https://<account>.services.ai.azure.com/api/projects/<project>
        host: azure.ai.project
```

## What is different in the hosted build

| Concern | Console (`run_shift.py`) | Hosted (`hosted.py`) |
| --- | --- | --- |
| Credential | `AzureCliCredential` | `ManagedIdentityCredential` (`FOUNDRY_AGENT_INSTANCE_CLIENT_ID`) |
| File access (reports) | on, `workspace/reports` | off; use a blob-backed `AgentFileStore` if needed |
| File memory | on, `.nightshift/memory`, shared by every shift | on, under `$HOME`, which Foundry persists per session; a notebook shared across sessions needs an external `AgentFileStore` |
| History | harness `InMemoryHistoryProvider` | same, with `history_source="agent"` so the host persists the `AgentSession` |
| Telemetry | you pick an exporter | Foundry exports to the project's Application Insights |
| Approvals | terminal prompt | returned as an `mcp_approval_request` output item; answer with an `mcp_approval_response` and `previous_response_id` |

The host calls `create_agent` for every request, so the simulated world is rebuilt each time: alert state
does not carry over between requests in the hosted build, while the session state (transcript, todos, mode,
standing approvals) does. A real deployment would put the world behind a service. The chat client is created
once at startup and shared by every request.

Approvals were tested on the deployed agent: the first request came back with an `mcp_approval_request` for
`restart_device`, and a second request carrying the `mcp_approval_response` and `previous_response_id` ran the
restart, verified telemetry and resolved the alert.

`.agentignore` keeps the virtual environment, local state, results and the article out of the package.
