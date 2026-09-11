# FIG 7-1 — Layout direction (Chapter 7)

**Title:** Stateless MCP exchange (modern era).

**Layout.** Three horizontal lanes, left to right: **AlphaForge host**,
**MCP client**, **market-data server**.

- **Message 1:** `server/discover` with `_meta`
  (protocolVersion, clientInfo, clientCapabilities) → response carrying
  `resultType: complete`, `supportedVersions`, `capabilities`, serverInfo.
- **Message 2:** `tools/list` with `_meta` → tool catalog.
- **Annotation between messages 2 and 3:** "client validates listing
  against local Pydantic contract — refuse on mismatch, no bytes sent."
- **Message 3:** `tools/call` `get_quote` with `_meta` and arguments →
  `content` with the quote and `provenance: SYNTHETIC`.

**Constraints.** No session box anywhere in the diagram. A small note
reads: "each request carries its own _meta — there is no handshake."

**Style.** Clean technical sequence diagram, monospace labels, one accent
color for the `_meta` payload on every message (to make the stateless
point visually: the same metadata block repeats on all three arrows).
