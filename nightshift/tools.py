"""The seven domain tools. Read-only tools never need approval; the two risky ones always do.

The approval requirement lives on the tool itself (`approval_mode="always_require"`), so it holds
for any agent that uses the tool, harness or not. The harness adds the queueing, the standing
"don't ask again" rules and the auto-approval callbacks on top.
"""

from __future__ import annotations

from typing import Annotated, Any

from agent_framework import tool

from .world import World, WorldError

# The seven Northwatch tools, as opposed to the tools the harness adds (todos, modes, skills, memory, files).
DOMAIN_TOOLS = (
    "list_open_alerts", "get_site_profile", "get_telemetry", "run_remote_diagnostic",
    "restart_device", "dispatch_technician", "resolve_alert",
)


def _safe(fn, *args: Any) -> Any:
    try:
        return fn(*args)
    except WorldError as e:
        return {"error": str(e)}


def build_tools(world: World) -> list:
    @tool(name="list_open_alerts", approval_mode="never_require")
    def list_open_alerts() -> list[dict[str, Any]]:
        """List every open alert in the NOC queue for this shift, oldest first. Read-only."""
        return world.list_open_alerts()

    @tool(name="get_site_profile", approval_mode="never_require")
    def get_site_profile(site_id: Annotated[str, "Site id, for example S-114."]) -> dict[str, Any]:
        """Return a site's name, kind, critical load, remote restart policy, firmware and devices. Read-only."""
        return _safe(world.site_profile, site_id)

    @tool(name="get_telemetry", approval_mode="never_require")
    def get_telemetry(
        site_id: Annotated[str, "Site id, for example S-114."],
        device_id: Annotated[str, "Device id at that site, for example INV-02 or GW-01."],
    ) -> dict[str, Any]:
        """Current telemetry for one device (inverter, BMS or gateway). Use it to verify the effect of an action. Read-only."""
        return _safe(world.telemetry, site_id, device_id)

    @tool(name="run_remote_diagnostic", approval_mode="never_require")
    def run_remote_diagnostic(
        site_id: Annotated[str, "Site id, for example S-114."],
        device_id: Annotated[str, "Device id at that site, for example INV-02 or GW-01."],
    ) -> dict[str, Any]:
        """Run the remote self-test on a device: fault classification, measurements, carrier status and whether a restart is safe. Read-only."""
        return _safe(world.diagnostic, site_id, device_id)

    @tool(name="restart_device", approval_mode="always_require")
    def restart_device(
        site_id: Annotated[str, "Site id, for example S-114."],
        device_id: Annotated[str, "Device id to restart, for example INV-02 or GW-01."],
        reason: Annotated[str, "One-line justification shown to the approver."],
    ) -> dict[str, Any]:
        """Remotely restart an inverter or gateway. Risky: interrupts the device, subject to site policy and operator approval."""
        return _safe(world.restart, site_id, device_id, reason)

    @tool(name="dispatch_technician", approval_mode="always_require")
    def dispatch_technician(
        site_id: Annotated[str, "Site id, for example S-114."],
        priority: Annotated[str, "urgent | next-business-day | routine"],
        reason: Annotated[str, "One-line justification shown to the approver and the technician."],
    ) -> dict[str, Any]:
        """Open a field-technician ticket. Costs money and, at 'urgent', wakes people up. Requires operator approval."""
        return _safe(world.dispatch, site_id, priority, reason)

    @tool(name="resolve_alert", approval_mode="never_require")
    def resolve_alert(
        alert_id: Annotated[str, "Alert id, for example A-1001."],
        resolution: Annotated[str, "transient | restarted | dispatched | known_issue | carrier_outage | escalated"],
        note: Annotated[str, "One or two sentences for the audit log."],
    ) -> dict[str, Any]:
        """Close an alert with a resolution category and a note. Call it exactly once per alert, after any action is done and verified."""
        return _safe(world.resolve, alert_id, resolution, note)

    return [list_open_alerts, get_site_profile, get_telemetry, run_remote_diagnostic, restart_device, dispatch_technician, resolve_alert]
