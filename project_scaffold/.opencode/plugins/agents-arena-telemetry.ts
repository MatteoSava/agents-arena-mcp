// Optional OpenCode plugin scaffold for recording arena-related telemetry.
// Copy into your OpenCode plugin setup and adapt to your event schema/version.
export const AgentsArenaTelemetry = async ({ app, client, $ }) => {
  return {
    event: async ({ event }) => {
      if (event.type === "tool.execute.after" || event.type === "session.diff") {
        // Intentionally minimal: Agents Arena's Python run ledger is the source of truth.
        // You can forward selected event metadata into .agents-arena/state/open-code-events.jsonl.
      }
    }
  }
}
