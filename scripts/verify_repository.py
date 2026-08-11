#!/usr/bin/env python3
"""Check Agent Workbench package, skill, routing, and adapter invariants."""

from __future__ import annotations

import sys

if sys.version_info < (3, 11):
    print("ERROR: Python 3.11 or newer is required", file=sys.stderr)
    raise SystemExit(2)

import json
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.7.0"
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
EXPECTED_ROLES = {
    "awb_planner": ("gpt-5.6-sol", "high", "read-only"),
    "awb_fast_investigator": ("gpt-5.6-luna", "low", "read-only"),
    "awb_builder": ("gpt-5.6-terra", "medium", "workspace-write"),
    "awb_deep_worker": ("gpt-5.6-sol", "high", "workspace-write"),
    "awb_migration_worker": ("gpt-5.6-sol", "xhigh", "workspace-write"),
    "awb_verifier": ("gpt-5.6-terra", "medium", "workspace-write"),
    "awb_test_engineer": ("gpt-5.6-terra", "high", "workspace-write"),
    "awb_reviewer": ("gpt-5.6-sol", "high", "read-only"),
    "awb_security_reviewer": ("gpt-5.6-sol", "xhigh", "read-only"),
}
CLAUDE_PROFILES = {
    "awb-planner": ("opus", "high", True),
    "awb-fast-investigator": ("haiku", "low", True),
    "awb-builder": ("sonnet", "medium", False),
    "awb-deep-worker": ("opus", "high", False),
    "awb-migration-worker": ("opus", "xhigh", False),
    "awb-verifier": ("sonnet", "medium", True),
    "awb-test-engineer": ("sonnet", "high", True),
    "awb-reviewer": ("opus", "high", True),
    "awb-security-reviewer": ("opus", "xhigh", True),
}


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def load_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                fail(f"{relative(path)} contains a duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates)
    except (OSError, json.JSONDecodeError, RecursionError, ValueError) as error:
        fail(f"{relative(path)} is not valid JSON: {error}")
    if not isinstance(value, dict):
        fail(f"{relative(path)} must contain a JSON object")
    return value


def require(path: Path) -> None:
    if not path.is_file():
        fail(f"missing required file: {relative(path)}")
    if path.is_symlink():
        fail(f"required package file must not be a symlink: {relative(path)}")


def parse_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        fail(f"{relative(path)} must start with YAML frontmatter")
    frontmatter, separator, body = text[4:].partition("\n---\n")
    if not separator:
        fail(f"{relative(path)} has unterminated YAML frontmatter")
    values: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, marker, value = line.partition(":")
        if not marker or not key.strip() or not value.strip():
            fail(f"{relative(path)} has unsupported frontmatter line: {line!r}")
        if key.strip() in values:
            fail(f"{relative(path)} has a duplicate frontmatter key: {key.strip()}")
        values[key.strip()] = value.strip().strip('"')
    return values, body


def check_manifests() -> None:
    codex = load_json(ROOT / ".codex-plugin/plugin.json")
    claude = load_json(ROOT / ".claude-plugin/plugin.json")
    claude_marketplace = load_json(ROOT / ".claude-plugin/marketplace.json")
    codex_marketplace = load_json(ROOT / ".agents/plugins/marketplace.json")

    for label, manifest in (("Codex", codex), ("Claude", claude)):
        if manifest.get("name") != "agent-workbench":
            fail(f"{label} manifest name must be agent-workbench")
        version = manifest.get("version")
        if not isinstance(version, str) or not SEMVER.fullmatch(version):
            fail(f"{label} manifest version must use semantic versioning")
        if version != VERSION:
            fail(f"{label} manifest version must be {VERSION}")
        if manifest.get("license") != "Apache-2.0":
            fail(f"{label} manifest license must be Apache-2.0")
        if manifest.get("repository") != "https://github.com/suguspnk/agent-workbench":
            fail(f"{label} manifest repository URL is incorrect")
        keywords = manifest.get("keywords")
        if not isinstance(keywords, list) or not {"loop-discovery", "agent-loop"}.issubset(keywords):
            fail(f"{label} manifest must include loop-discovery and agent-loop keywords")

    if codex.get("skills") != "./skills/":
        fail("Codex manifest must point skills to ./skills/")
    interface = codex.get("interface")
    if not isinstance(interface, dict):
        fail("Codex manifest must contain an interface object")
    for field in ("displayName", "shortDescription", "longDescription", "developerName", "category"):
        if not isinstance(interface.get(field), str) or not interface[field].strip():
            fail(f"Codex interface.{field} must be a non-empty string")
    prompts = interface.get("defaultPrompt")
    if not isinstance(prompts, list) or not 1 <= len(prompts) <= 3:
        fail("Codex manifest must have one to three default prompts")
    if any(not isinstance(prompt, str) or len(prompt) > 128 for prompt in prompts):
        fail("Codex default prompts must be strings no longer than 128 characters")
    if "architecture" in interface["longDescription"] or "lead agent responsible" in interface["longDescription"]:
        fail("Codex interface copy must not assign delegated work to the lead")

    if claude.get("$schema") != "https://json.schemastore.org/claude-code-plugin-manifest.json":
        fail("Claude manifest must declare the official JSON schema")
    if claude.get("displayName") != "Agent Workbench":
        fail("Claude manifest displayName must be Agent Workbench")

    for label, marketplace in (("Claude", claude_marketplace), ("Codex", codex_marketplace)):
        if marketplace.get("name") != "agent-workbench":
            fail(f"{label} marketplace name must be agent-workbench")
        plugins = marketplace.get("plugins")
        if not isinstance(plugins, list) or len(plugins) != 1 or not isinstance(plugins[0], dict):
            fail(f"{label} marketplace must contain exactly one plugin object")
        if plugins[0].get("name") != "agent-workbench":
            fail(f"{label} marketplace must expose agent-workbench")

    if claude_marketplace["plugins"][0].get("source") != "./":
        fail("Claude marketplace must expose the root plugin with source ./")
    if claude_marketplace["plugins"][0].get("version") != VERSION:
        fail(f"Claude marketplace plugin version must be {VERSION}")
    claude_entry = claude_marketplace["plugins"][0]
    for field in ("keywords", "tags"):
        values = claude_entry.get(field)
        if not isinstance(values, list) or not {"loop-discovery", "agent-loop"}.issubset(values):
            fail(f"Claude marketplace {field} must include loop-discovery and agent-loop")
    claude_description = claude_marketplace.get("description")
    claude_metadata = claude_marketplace.get("metadata")
    if not isinstance(claude_description, str) or not claude_description.strip():
        fail("Claude marketplace root description must be a non-empty string")
    if not isinstance(claude_metadata, dict):
        fail("Claude marketplace must contain a metadata object")
    metadata_description = claude_metadata.get("description")
    if not isinstance(metadata_description, str) or not metadata_description.strip():
        fail("Claude marketplace metadata.description must be a non-empty string")
    for phrase in ("orchestrate-task", "proposal-only", "discover-loops"):
        if phrase not in claude_description or phrase not in metadata_description:
            fail(f"Claude marketplace descriptions must cover both workflows: {phrase}")
    codex_entry = codex_marketplace["plugins"][0]
    if codex_entry.get("source") != {"source": "local", "path": "./"}:
        fail("Codex marketplace must expose the root plugin as a local source")
    if codex_entry.get("policy") != {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}:
        fail("Codex marketplace policy must declare installation and authentication")
    if codex_entry.get("category") != "Productivity":
        fail("Codex marketplace entry must declare a category")


def check_skill() -> None:
    skill_path = ROOT / "skills/orchestrate-task/SKILL.md"
    frontmatter, body = parse_frontmatter(skill_path)
    if frontmatter.get("name") != "orchestrate-task":
        fail("orchestrate-task skill name is incorrect")
    if not frontmatter.get("description"):
        fail("orchestrate-task must declare a description")
    for phrase in (
        "orchestration-only",
        "route_subagent.py",
        "Do not investigate, edit implementation files, run acceptance checks",
        "If delegation or stable identity is unavailable",
    ):
        if phrase not in body:
            fail(f"orchestrate-task must retain boundary text: {phrase}")

    portable = (ROOT / "skills/orchestrate-task/references/portable-contract.md").read_text(encoding="utf-8")
    forbidden = (
        "otherwise run the phases in one task",
        "The lead must validate the paths, diff, and evidence independently",
    )
    for phrase in forbidden:
        if phrase in portable:
            fail(f"portable contract contains a lead-boundary contradiction: {phrase}")

    model_reference = (ROOT / "skills/orchestrate-task/references/model-selection.md").read_text(encoding="utf-8")
    for phrase in (
        "provider-neutral",
        "Route in two stages",
        "must_not_downgrade",
        "tests/routing-cases.json",
        "required_followups",
    ):
        if phrase not in model_reference:
            fail(f"model-selection reference is missing: {phrase}")
    if "## Contents" not in model_reference:
        fail("long model-selection reference must contain a table of contents")

    openai_yaml = (ROOT / "skills/orchestrate-task/agents/openai.yaml").read_text(encoding="utf-8")
    if "plan-build-verify" in openai_yaml or "plan, delegate, verify" in openai_yaml:
        fail("OpenAI skill UI copy assigns delegated phases to the lead")


def check_discover_loops_skill() -> None:
    skill_root = ROOT / "skills/discover-loops"
    skill_path = skill_root / "SKILL.md"
    frontmatter, body = parse_frontmatter(skill_path)
    if frontmatter.get("name") != "discover-loops":
        fail("discover-loops skill name is incorrect")
    if not frontmatter.get("description"):
        fail("discover-loops must declare a description")
    for phrase in (
        "Never activate, schedule, install, publish",
        "score_loop_readiness.py",
        "validate_loop_contract.py",
        "independent verifier",
        "`lifecycle.proposal_status` as `draft`",
        "SKILL_ROOT",
        "Python 3.11 or newer",
        "descriptor-relative safe operations",
        "best-effort",
    ):
        if phrase not in body:
            fail(f"discover-loops must retain proposal boundary text: {phrase}")

    if len(body.splitlines()) >= 500:
        fail("discover-loops/SKILL.md must remain under 500 lines")
    if (skill_root / "README.md").exists():
        fail("discover-loops must not contain an auxiliary README")

    readiness = (skill_root / "references/loop-readiness.md").read_text(encoding="utf-8")
    for phrase in (
        "read_only_triage_loop",
        "supervised_loop",
        "embedded-secret",
        "activation_allowed",
        "demonstrated value",
        "supervised requested autonomy",
        "inconsistent external/sensitive permissions",
        "retained state paired with read-only action scope",
        "require `state_scope: none`",
    ):
        if phrase not in readiness:
            fail(f"loop-readiness reference is missing: {phrase}")

    contract = (skill_root / "references/loop-contract.md").read_text(encoding="utf-8")
    for phrase in (
        '"artifact_type": "loop-contract-proposal"',
        '"card": {',
        '"card_sha256"',
        '"operation_id": "workspace.observe"',
        '"binding_status": "unbound"',
        '"semantic_review": {"required": true, "status": "pending"}',
        '"proposal_status": "draft"',
        '"activation_status": "pending"',
        '"scheduler_status": "inactive"',
        "cannot prove semantic truth",
        "external-reversible",
        "credential-access",
        "lifecycle-administration",
        '"status": "pending"',
        '"activate", "schedule", "install", "publish"',
        "max_iterations` 1..50",
        "Terminal states are exactly",
        "Realpath or symlink checks alone",
        "best-effort",
        "structurally_valid: true",
        "descriptor-relative operations",
        "opaque citations",
        "host-owned operation registry",
        "exact writable files only",
        "canonical lowercase components",
        "casefold identity",
        "Mutable `host-managed` state is rejected",
        "rolling 8,192-character cap",
        "categories `Cc`, `Cf`, `Cs`, `Zl`, and `Zp`",
    ):
        if phrase not in contract:
            fail(f"loop-contract reference is missing: {phrase}")

    approvals = (skill_root / "references/approval-policy.md").read_text(encoding="utf-8")
    for phrase in (
        "Always require exact human approval",
        "every allowed unbound capability proposal",
        "never grants authority",
        "Do not place tokens",
        "schedule-proposal",
        "best-effort",
        "recomputes the embedded card's digest",
    ):
        if phrase not in approvals:
            fail(f"approval-policy reference is missing: {phrase}")

    scorer = (skill_root / "scripts/score_loop_readiness.py").read_text(encoding="utf-8")
    validator = (skill_root / "scripts/validate_loop_contract.py").read_text(encoding="utf-8")
    for phrase in (
        "MAX_INPUT_BYTES + 1", 'source_text == "-"', "O_NOFOLLOW", "S_ISREG",
        "RESULT_FIELDS", "READ_ONLY_ACTION_SCOPES", "read-only-retained-state",
        "remove retained state from read-only work",
    ):
        if phrase not in scorer:
            fail(f"loop-readiness scorer is missing safe-input/replay invariant: {phrase}")
    for phrase in (
        '"artifact_type"', '"readiness"', '"operation_id"', '"binding_status"',
        "OPERATION_MAP", "LIFECYCLE_TOKENS", "DESTRUCTIVE_TOKENS",
        "OBVIOUS_DENIED_NAMES", "SENSITIVE_PATH_TOKENS", "SECRET_VALUES",
        "MAX_SECRET_SCALARS", "MAX_SECRET_ADJACENT_CHARS", "ADJACENT_SECRET_VALUES",
        "_contains_adjacent_secret", "_scan_secret_material",
        'in {"Cc", "Cf", "Cs", "Zl", "Zp"}', "WRITE_ROOTS",
        "WRITE_EXTENSIONS", "WINDOWS_DEVICES", "TERMINAL_STATES",
        "READINESS_SCORER.score", "hashlib.sha256", '"semantic_review"',
        '"structurally_valid"', '"semantic_review_required"', '"activation_allowed"',
        "normalized_path_identities", "canonical lowercase output components",
        "MAX_INPUT_BYTES + 1", 'source_text == "-"', "O_NOFOLLOW", "S_ISREG",
    ):
        if phrase not in validator:
            fail(f"loop-contract validator is missing contract/security invariant: {phrase}")

    openai_yaml = (skill_root / "agents/openai.yaml").read_text(encoding="utf-8")
    for phrase in (
        'display_name: "Discover Loops"',
        'short_description: "Find and draft evidence-backed agent loops"',
        'Use $discover-loops to find recurring work',
    ):
        if phrase not in openai_yaml:
            fail(f"discover-loops OpenAI metadata is missing: {phrase}")


def check_codex_profiles() -> None:
    directory = ROOT / "adapters/codex/.codex/agents"
    files = sorted(directory.glob("*.toml"))
    if len(files) != len(EXPECTED_ROLES):
        fail(f"expected {len(EXPECTED_ROLES)} Codex profiles, found {len(files)}")
    seen: set[str] = set()
    for path in files:
        try:
            profile = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as error:
            fail(f"{relative(path)} is not valid TOML: {error}")
        name = profile.get("name")
        if not isinstance(name, str) or name not in EXPECTED_ROLES:
            fail(f"{relative(path)} has an unknown name")
        if name in seen:
            fail(f"duplicate Codex profile name: {name}")
        seen.add(name)
        if path.stem != name.replace("_", "-"):
            fail(f"{relative(path)} filename does not match profile name {name}")
        expected_model, expected_effort, expected_sandbox = EXPECTED_ROLES[name]
        if (profile.get("model"), profile.get("model_reasoning_effort"), profile.get("sandbox_mode")) != (
            expected_model,
            expected_effort,
            expected_sandbox,
        ):
            fail(f"{relative(path)} model, effort, or sandbox differs from the routing policy")
        instructions = profile.get("developer_instructions")
        if not isinstance(instructions, str) or "unless the harness already supplied it as a higher-priority instruction surface" not in instructions:
            fail(f"{relative(path)} must retain the trust boundary")
        if name in {"awb_verifier", "awb_test_engineer"} and "status before and after" not in instructions:
            fail(f"{relative(path)} must require before/after status evidence")


def check_claude_profiles() -> None:
    directory = ROOT / "agents"
    files = sorted(directory.glob("*.md"))
    if len(files) != len(CLAUDE_PROFILES):
        fail(f"expected {len(CLAUDE_PROFILES)} Claude profiles, found {len(files)}")
    seen: set[str] = set()
    for path in files:
        frontmatter, body = parse_frontmatter(path)
        name = frontmatter.get("name")
        if name not in CLAUDE_PROFILES:
            fail(f"{relative(path)} has an unknown name")
        if name in seen:
            fail(f"duplicate Claude profile name: {name}")
        seen.add(name)
        if path.stem != name:
            fail(f"{relative(path)} filename does not match profile name {name}")
        expected_model, expected_effort, behaviorally_read_only = CLAUDE_PROFILES[name]
        if (frontmatter.get("model"), frontmatter.get("effort")) != (expected_model, expected_effort):
            fail(f"{relative(path)} model or effort differs from the routing policy")
        if "permissionMode" in frontmatter:
            fail(f"{relative(path)} cannot rely on permissionMode in a plugin agent")
        tools = {item.strip() for item in frontmatter.get("tools", "").split(",") if item.strip()}
        if behaviorally_read_only and tools.intersection({"Edit", "Write", "NotebookEdit"}):
            fail(f"{relative(path)} read-only role exposes an edit tool")
        if not behaviorally_read_only and not {"Edit", "Write"}.issubset(tools):
            fail(f"{relative(path)} implementation role must expose Edit and Write")
        if "unless the harness already supplied it as a higher-priority instruction surface" not in body:
            fail(f"{relative(path)} must retain the trust boundary")
        if behaviorally_read_only and "Bash" in tools and "status before and after" not in body:
            fail(f"{relative(path)} shell-capable read-only role must require status evidence")


def check_replays_and_unit_tests() -> None:
    command = [
        sys.executable,
        str(ROOT / "skills/orchestrate-task/scripts/route_subagent.py"),
        "--replay",
        str(ROOT / "skills/orchestrate-task/tests/routing-cases.json"),
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False, timeout=60)
    if result.returncode:
        fail(f"routing replay failed:\n{result.stdout}{result.stderr}")
    print(result.stdout.strip())

    loop_result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "skills/discover-loops/scripts/score_loop_readiness.py"),
            "--replay",
            str(ROOT / "skills/discover-loops/tests/readiness-cases.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if loop_result.returncode:
        fail(f"loop-readiness replay failed:\n{loop_result.stdout}{loop_result.stderr}")
    print(loop_result.stdout.strip())

    unit_result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if unit_result.returncode:
        fail(f"unit tests failed:\n{unit_result.stdout}{unit_result.stderr}")
    print("Repository unit tests passed.")


def check_release_and_ci() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## {VERSION} -" not in changelog:
        fail(f"CHANGELOG.md must document {VERSION}")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for phrase in (
        "codex plugin marketplace add suguspnk/agent-workbench",
        "claude plugin marketplace add suguspnk/agent-workbench",
        "Automatic subagent routing",
        "Loop discovery and proposal drafting",
        "$discover-loops",
        "permissionMode",
        "Python 3.11 or newer",
        "claude plugin validate .",
        "SKILL_ROOT",
        "structurally_valid: true",
        "descriptor-relative safe operations",
        "opaque `workspace:` or `source:` citations",
    ):
        if phrase not in readme:
            fail(f"README.md is missing required guidance: {phrase}")

    workflow = (ROOT / ".github/workflows/validate.yml").read_text(encoding="utf-8")
    for action in ("actions/checkout@11d5960a326750d5838078e36cf38b85af677262", "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065"):
        if action not in workflow:
            fail(f"CI action must be pinned to the reviewed commit: {action}")
    if "permissions:\n  contents: read" not in workflow or "timeout-minutes:" not in workflow:
        fail("CI must retain least privilege and an execution timeout")


def check_local_markdown_links() -> None:
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for path in ROOT.rglob("*.md"):
        if ".git" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for target in link_pattern.findall(text):
            target = target.strip().strip("<>")
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            local_target = target.split("#", 1)[0]
            resolved = (path.parent / local_target).resolve()
            try:
                resolved.relative_to(ROOT.resolve())
            except ValueError:
                fail(f"{relative(path)} links outside the package: {target}")
            if not resolved.exists():
                fail(f"{relative(path)} has a broken local link: {target}")


def main() -> None:
    required = [
        "README.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "SECURITY.md",
        ".codex-plugin/plugin.json",
        ".claude-plugin/plugin.json",
        ".claude-plugin/marketplace.json",
        ".agents/plugins/marketplace.json",
        ".github/workflows/validate.yml",
        "skills/orchestrate-task/SKILL.md",
        "skills/orchestrate-task/agents/openai.yaml",
        "skills/orchestrate-task/references/portable-contract.md",
        "skills/orchestrate-task/references/model-selection.md",
        "skills/orchestrate-task/scripts/route_subagent.py",
        "skills/orchestrate-task/tests/routing-cases.json",
        "skills/discover-loops/SKILL.md",
        "skills/discover-loops/agents/openai.yaml",
        "skills/discover-loops/references/loop-readiness.md",
        "skills/discover-loops/references/loop-contract.md",
        "skills/discover-loops/references/approval-policy.md",
        "skills/discover-loops/scripts/score_loop_readiness.py",
        "skills/discover-loops/scripts/validate_loop_contract.py",
        "skills/discover-loops/tests/readiness-cases.json",
        "tests/test_route_subagent.py",
        "tests/test_loop_readiness.py",
        "tests/test_loop_contract.py",
        "adapters/codex/README.md",
    ]
    for item in required:
        require(ROOT / item)

    check_manifests()
    check_skill()
    check_discover_loops_skill()
    check_codex_profiles()
    check_claude_profiles()
    check_replays_and_unit_tests()
    check_release_and_ci()
    check_local_markdown_links()
    print("Repository invariants passed.")


if __name__ == "__main__":
    main()
