"""The sandbox: the agent that writes code gets a cell, not the building.

Two authorities, deliberately SEPARATE:

- ``run_bash`` — execute a command. Cannot modify files through the
  patch path, and the command allowlist is narrow.
- ``apply_patch`` — modify files inside the worktree. Cannot execute
  anything.

Running commands is not the same authority as modifying files, so they
are different flags on ``SandboxPermissions``. A research agent that
backtests strategy variants holds both; a market-data fetcher holds
neither.

run_bash rules (the process cell):

- **argv only, never ``shell=True``.** ``["echo", "; rm -rf /"]`` passes
  the semicolon as a LITERAL argument — there is no shell to interpret
  it. Command injection as a class dies here, not in a denylist.
- **Command allowlist.** The first argv element must name a registered
  command (name -> absolute executable). Absolute paths the agent invents
  are refused; only the map's targets run.
- **Resource limits.** Wall-clock timeout kills the runaway; a byte cap
  on output truncates WITH A FLAG, never silently.
- **Scrubbed environment.** The child gets a fixed minimal env
  (``PATH``, ``LANG``) — never the parent's secrets. An agent that can
  read ``os.environ`` in a subprocess can read your API keys; this one
  cannot.
- **cwd pinned to the worktree.**

apply_patch rules (the file cell):

- **Propose, review, THEN apply.** ``apply()`` without a review verdict
  refuses. This is Chapter 2's Decide-before-Act, in a diff: the patch is
  an intention until a reviewer — human or automated policy — says so.
- **Unified-diff subset, exact context match.** ``---``/``+++`` headers,
  ``@@`` hunks, `` ``/``-``/``+`` lines. Fuzzy matching is refused: a
  patch that does not apply cleanly is a patch you do not understand.
- **Confinement.** Every target path must resolve INSIDE the worktree:
  no absolute paths, no ``..`` escapes, and no symlink components (each
  path prefix is checked with ``islink`` at apply time — the symlink race
  is a real escape class, not a footnote).

HONEST RESIDUALS — what this module is NOT:

- It is a PROCESS-level boundary, not a container. True filesystem and
  network isolation needs namespaces/cgroups (containers, gVisor,
  Firecracker). This module assumes the network boundary (the companion
  module in this chapter) and an OS user boundary as outer layers.
- ``python3 -c`` with attacker-chosen code IS arbitrary code execution —
  by design, when the ``can_run_bash`` permission is granted. The
  permission is the control; the allowlist, timeout, output cap, scrubbed
  env, and pinned cwd are the leash. Grant it the way you would grant a
  human a shell: narrowly, and never to the agent that also holds your
  deploy keys.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Callable


# --------------------------------------------------------------------------
# Exceptions: every refusal is named, so the trace says WHY it stopped.
# --------------------------------------------------------------------------


class SandboxError(Exception):
    """Base: the sandbox refused something on purpose."""


class SandboxPermissionDenied(SandboxError):
    """The sandbox does not hold the permission this call needs."""


class CommandNotAllowlisted(SandboxError):
    """The command name is not in the allowlist map. Refused."""


class SandboxTimeout(SandboxError):
    """The command exceeded its wall-clock budget and was killed."""


class PatchOutsideWorktree(SandboxError):
    """A patch target escapes the worktree (absolute, .., symlink)."""


class PatchContextMismatch(SandboxError):
    """Hunk context does not match the file exactly. Refused, not fuzzed."""


class UnreviewedPatch(SandboxError):
    """apply() called without a review verdict. Decide before Act."""


class PatchRejected(SandboxError):
    """The reviewer said no. The patch is not applied."""


# --------------------------------------------------------------------------
# Permissions: two authorities, two flags.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SandboxPermissions:
    """What this sandbox instance may do. Grant narrowly."""

    can_run_bash: bool = False
    can_apply_patch: bool = False


_CHILD_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}


@dataclass(frozen=True)
class BashResult:
    """The outcome of one sandboxed command."""

    returncode: int
    output: bytes
    truncated: bool
    timed_out: bool = False


class Sandbox:
    """A process-and-file cell rooted at a worktree directory."""

    def __init__(
        self,
        worktree: str,
        permissions: SandboxPermissions,
        command_allowlist: dict[str, str],
        default_timeout: float = 30.0,
        output_cap: int = 1_048_576,
    ) -> None:
        self._worktree = os.path.realpath(worktree)
        os.makedirs(self._worktree, exist_ok=True)
        self._permissions = permissions
        # Resolve every allowlisted command to an absolute path NOW, at
        # construction: the agent names a key, never a path.
        self._commands = {
            name: os.path.realpath(exe)
            for name, exe in command_allowlist.items()
        }
        for name, exe in self._commands.items():
            if not (os.path.isfile(exe) and os.access(exe, os.X_OK)):
                raise SandboxError(
                    f"allowlisted command {name!r} -> {exe!r} "
                    "is not an executable file"
                )
        self._default_timeout = default_timeout
        self._output_cap = output_cap

    # -- the process cell ------------------------------------------------

    def run_bash(
        self,
        argv: list[str],
        timeout: float | None = None,
    ) -> BashResult:
        """Run a command. argv only — there is no shell to inject into.

        ``argv[0]`` must be a key in the allowlist map. The semicolon in
        ``["echo", "; rm -rf /"]`` is a literal argument to echo, because
        no shell ever sees it. Resource limits: wall-clock timeout kills
        the runaway; output past the cap truncates with ``truncated=True``.
        """
        if not self._permissions.can_run_bash:
            raise SandboxPermissionDenied("run_bash: permission not granted")
        if not argv:
            raise CommandNotAllowlisted("empty argv")
        name = argv[0]
        if name not in self._commands:
            raise CommandNotAllowlisted(
                f"{name!r} is not an allowlisted command"
            )
        budget = self._default_timeout if timeout is None else timeout
        proc = subprocess.Popen(
            [self._commands[name], *argv[1:]],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=self._worktree,
            env=dict(_CHILD_ENV),
        )
        killed = {"timeout": False}

        def _kill_on_timeout() -> None:
            killed["timeout"] = True
            proc.kill()

        timer = threading.Timer(budget, _kill_on_timeout)
        timer.start()
        out = bytearray()
        truncated = False
        try:
            assert proc.stdout is not None
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                out.extend(chunk)
                if len(out) > self._output_cap:
                    truncated = True
                    proc.kill()
                    break
            proc.wait()
        finally:
            timer.cancel()
        if killed["timeout"] and not truncated:
            raise SandboxTimeout(
                f"{name!r} exceeded {budget}s and was killed"
            )
        return BashResult(
            returncode=proc.returncode,
            output=bytes(out[: self._output_cap]),
            truncated=truncated,
            timed_out=killed["timeout"],
        )

    # -- the file cell ---------------------------------------------------

    def _confine(self, relpath: str) -> str:
        """Resolve a patch target inside the worktree, or refuse.

        Three escape classes, three checks: absolute paths, ``..``
        traversal, and symlink components (the symlink race — checked at
        apply time, when it matters).
        """
        if os.path.isabs(relpath):
            raise PatchOutsideWorktree(f"absolute path {relpath!r} refused")
        # Normalize a/ b/ prefixes from diff headers before joining.
        for prefix in ("a/", "b/"):
            if relpath.startswith(prefix):
                relpath = relpath[len(prefix):]
                break
        if relpath in ("", ".", "/dev/null"):
            raise PatchOutsideWorktree(f"empty target {relpath!r} refused")
        # Symlink race FIRST, so the error names the escape class: walk
        # each component of the relative path and refuse symlinks — a
        # symlinked directory would redirect the write outside the tree.
        probe = self._worktree
        # Diff headers use forward slashes even on Windows, so tokenize
        # on "/" explicitly — os.sep would miss foo/bar.py on a Windows
        # host and skip the symlink check below.
        for part in relpath.replace("\\", "/").split("/"):
            if part in ("", ".", ".."):
                raise PatchOutsideWorktree(
                    f"suspicious component {part!r} in {relpath!r}"
                )
            probe = os.path.join(probe, part)
            if os.path.islink(probe):
                raise PatchOutsideWorktree(
                    f"symlink component {probe!r} refused"
                )
        # Backstop: resolve everything and require containment.
        candidate = os.path.realpath(os.path.join(self._worktree, relpath))
        if os.path.commonpath([candidate, self._worktree]) != self._worktree:
            raise PatchOutsideWorktree(
                f"{relpath!r} escapes the worktree"
            )
        return candidate

    def propose_patch(self, diff_text: str) -> "ProposedPatch":
        """Parse a unified diff into a proposal. Parsing is not approval."""
        if not self._permissions.can_apply_patch:
            raise SandboxPermissionDenied(
                "apply_patch: permission not granted"
            )
        files = _parse_unified_diff(diff_text)
        # Confinement is checked at PROPOSAL time too, so the reviewer sees
        # only in-tree targets — but re-checked at apply time (TOCTOU).
        for fp in files:
            self._confine(fp.path)
        return ProposedPatch(files=files, sandbox=self)

    def apply(self, reviewed: "ReviewedPatch") -> list[str]:
        """Apply a REVIEWED patch. Unreviewed or rejected: refused."""
        if not self._permissions.can_apply_patch:
            raise SandboxPermissionDenied(
                "apply_patch: permission not granted"
            )
        if not reviewed.reviewed:
            raise UnreviewedPatch(
                "Decide before Act: no review verdict on this patch"
            )
        if not reviewed.verdict.approved:
            raise PatchRejected(
                f"reviewer said no: {reviewed.verdict.reason}"
            )
        written: list[str] = []
        for fp in reviewed.proposal.files:
            target = self._confine(fp.path)  # re-check at apply time
            _apply_file_patch(target, fp)
            written.append(target)
        return written


# --------------------------------------------------------------------------
# Unified-diff subset: ---/+++ headers, @@ hunks, exact context match.
# --------------------------------------------------------------------------

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_MAX_DIFF_BYTES = 1_048_576


@dataclass(frozen=True)
class Hunk:
    old_start: int
    lines: tuple[tuple[str, str], ...]  # (kind, text); kind in " ", "-", "+"


@dataclass(frozen=True)
class FilePatch:
    path: str
    old_path: str
    hunks: tuple[Hunk, ...]


def _parse_unified_diff(diff_text: str) -> tuple[FilePatch, ...]:
    """Parse a unified diff. Anything ambiguous is a hard error."""
    if len(diff_text.encode()) > _MAX_DIFF_BYTES:
        raise SandboxError("diff exceeds 1 MiB; refused")
    files: list[FilePatch] = []
    old_path = new_path = ""
    hunks: list[Hunk] = []
    cur: list[tuple[str, str]] = []
    old_start = 0
    in_hunk = False

    def _flush_hunk() -> None:
        nonlocal cur, in_hunk
        if in_hunk:
            hunks.append(Hunk(old_start=old_start, lines=tuple(cur)))
            cur = []
            in_hunk = False

    def _flush_file() -> None:
        nonlocal old_path, new_path, hunks
        _flush_hunk()
        if new_path or old_path:
            path = new_path if new_path != "/dev/null" else old_path
            files.append(
                FilePatch(path=path, old_path=old_path, hunks=tuple(hunks))
            )
        old_path = new_path = ""
        hunks = []

    for raw in diff_text.splitlines():
        line = raw.rstrip("\n")
        if line.startswith("--- "):
            _flush_file()
            old_path = line[4:].strip()
        elif line.startswith("+++ "):
            new_path = line[4:].strip()
        elif line.startswith("@@"):
            _flush_hunk()
            m = _HUNK_RE.match(line)
            if not m:
                raise SandboxError(f"malformed hunk header: {line!r}")
            old_start = int(m.group(1))
            in_hunk = True
        elif in_hunk and line[:1] in (" ", "-", "+"):
            cur.append((line[0], line[1:]))
        elif in_hunk and line == "":
            # Trailing blank context line may arrive stripped of its
            # leading space by careless tooling; treat as empty context.
            cur.append((" ", ""))
        elif line.startswith("diff ") or line.startswith("index "):
            continue
        elif not line.strip():
            continue
        else:
            raise SandboxError(f"unrecognized diff line: {line!r}")
    _flush_file()
    if not files:
        raise SandboxError("diff contains no file patches")
    return tuple(files)


def _apply_file_patch(target: str, fp: FilePatch) -> None:
    """Apply hunks with EXACT context matching. No fuzz, ever."""
    if os.path.exists(target):
        with open(target, "r", encoding="utf-8") as fh:
            current = fh.read().splitlines()
    else:
        current = []
    for hunk in reversed(fp.hunks):
        # Bottom-to-top: hunk old_start values are relative to the
        # ORIGINAL file, so applying the last hunk first keeps every
        # index valid. Forward iteration corrupts offsets the moment an
        # earlier hunk adds or removes lines.
        # old_start=0 means "new file": the hunk starts before line 1.
        idx = hunk.old_start - 1 if hunk.old_start > 0 else 0
        if idx < 0 or idx > len(current):
            raise PatchContextMismatch(
                f"hunk at line {hunk.old_start} starts outside the file"
            )
        rebuilt: list[str] = []
        for kind, text in hunk.lines:
            if kind in (" ", "-"):
                if idx >= len(current) or current[idx] != text:
                    found = current[idx] if idx < len(current) else "<EOF>"
                    raise PatchContextMismatch(
                        f"context mismatch at line {idx + 1}: "
                        f"expected {text!r}, found {found!r}"
                    )
                idx += 1
            if kind in (" ", "+"):
                rebuilt.append(text)
        # Replace exactly the consumed span: no fuzz, no drift.
        start = idx - sum(1 for k, _ in hunk.lines if k in (" ", "-"))
        current[start:idx] = rebuilt
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write("\n".join(current) + ("\n" if current else ""))


# --------------------------------------------------------------------------
# Review: the patch is an intention until someone says otherwise.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PatchSummary:
    paths: tuple[str, ...]
    additions: int
    deletions: int


@dataclass(frozen=True)
class ReviewVerdict:
    approved: bool
    reason: str


@dataclass(frozen=True)
class ProposedPatch:
    files: tuple[FilePatch, ...]
    sandbox: "Sandbox" = field(compare=False, repr=False)

    def summarize(self) -> PatchSummary:
        adds = dels = 0
        for fp in self.files:
            for hunk in fp.hunks:
                for kind, _ in hunk.lines:
                    if kind == "+":
                        adds += 1
                    elif kind == "-":
                        dels += 1
        return PatchSummary(
            paths=tuple(fp.path for fp in self.files),
            additions=adds,
            deletions=dels,
        )

    def review(
        self, policy: Callable[[PatchSummary, str], ReviewVerdict]
    ) -> "ReviewedPatch":
        """Run the review policy. Human or automated — but SOMETHING.

        The policy receives the summary AND the concatenated added text,
        so a content-aware reviewer can refuse dangerous imports while a
        size-only reviewer can ignore the second argument.
        """
        return ReviewedPatch(
            proposal=self,
            verdict=policy(self.summarize(), self.added_text()),
            reviewed=True,
        )

    def added_text(self) -> str:
        """Every line the patch adds, for content-aware reviewers."""
        out: list[str] = []
        for fp in self.files:
            for hunk in fp.hunks:
                for kind, text in hunk.lines:
                    if kind == "+":
                        out.append(text)
        return "\n".join(out)


@dataclass(frozen=True)
class ReviewedPatch:
    proposal: ProposedPatch
    verdict: ReviewVerdict
    reviewed: bool = False


def automated_policy(
    max_additions: int = 200,
    forbidden_substrings: tuple[str, ...] = ("os.system", "subprocess",
                                             "socket", "urllib", "requests"),
) -> Callable[[PatchSummary, str], ReviewVerdict]:
    """A strict-enough default reviewer for tests and small agents.

    Refuses patches that add networking/process-spawning imports or that
    are too large to have been read. This is a POLICY, not a proof — a
    human reviewer is the stronger control, and the chapter says so.
    """
    def _policy(summary: PatchSummary, added_text: str = "") -> ReviewVerdict:
        if summary.additions > max_additions:
            return ReviewVerdict(
                False,
                f"{summary.additions} additions exceed the "
                f"{max_additions}-line review budget",
            )
        for bad in forbidden_substrings:
            if bad in added_text:
                return ReviewVerdict(
                    False, f"added code references {bad!r}"
                )
        return ReviewVerdict(True, "within automated review budget")

    return _policy
