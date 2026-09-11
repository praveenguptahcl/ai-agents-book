# Figure spec — Chapter 13: Sandboxes, SSRF, and the Agent That Writes Code

## Figure 13.1 — The two boundaries (one figure, two panels)

**Panel A — SSRF attack paths against the market-data tool.** Left: the
agent's quote tool with its allowlist (`api.polygon.io`,
`api.alphavantage.co`). Four red attack arrows, each labeled with the
mechanism and the defense that stops it:
1. Direct fetch of `169.254.169.254` → stopped by the resolved-address
   check (link-local refused).
2. DNS rebinding: `quotes.vendor.example` resolving first to a public IP,
   then to `10.0.0.5` → stopped by resolve-then-check on EVERY request
   ("the name is not the address").
3. Redirect laundering: allowlisted hop → `302` → metadata endpoint →
   stopped by manual per-hop re-gating.
4. Resolve→connect TOCTOU window → named residual; the verdict's
   `resolved_ips` feed connection pinning.
Each arrow terminates at the gate icon, never at the target. Caption:
"The gate checks the address, not the name — on every hop."

**Panel B — The sandbox cell.** A box labeled "worktree" containing the
research agent. Two keys on two separate rings: `run_bash` (process
cell: argv-only, allowlist, timeout, output cap, scrubbed env) and
`apply_patch` (file cell: propose → review → apply; confinement checks
for absolute paths, `..`, symlink components). Arrows show allowed
effects: bash may run listed commands; patches may modify in-tree files
only after a review verdict. Red X marks on: `curl` (not allowlisted),
a patch to `/etc/cron.d`, a symlink pointing out of the tree, an
unreviewed patch. Caption: "Two authorities, two keys. The agent never
holds the cell's configuration."

**Style:** flat technical diagram, red for attacks/refusals, green for
the allowed paths, monospace for hostnames/IPs/symbols. No screenshots.
