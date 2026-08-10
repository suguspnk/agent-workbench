#!/usr/bin/env python3
"""Check Agent Workbench's portable package invariants without dependencies."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"{path.relative_to(ROOT)} is not valid JSON: {error}")
    if not isinstance(value, dict):
        fail(f"{path.relative_to(ROOT)} must contain a JSON object")
    return value


def require(path: Path) -> None:
    if not path.is_file():
        fail(f"missing required file: {path.relative_to(ROOT)}")


def check_skill(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        fail("skills/orchestrate-task/SKILL.md must start with YAML frontmatter")
    frontmatter, separator, _ = text[4:].partition("\n---\n")
    if not separator:
        fail("skills/orchestrate-task/SKILL.md has unterminated YAML frontmatter")
    if not re.search(r"^name: orchestrate-task$", frontmatter, re.MULTILINE):
        fail("skills/orchestrate-task/SKILL.md must declare name: orchestrate-task")
    if not re.search(r"^description: .+", frontmatter, re.MULTILINE):
        fail("skills/orchestrate-task/SKILL.md must declare a description")


def main() -> None:
    required = [
        ROOT / "README.md",
        ROOT / "LICENSE",
        ROOT / "SECURITY.md",
        ROOT / ".codex-plugin/plugin.json",
        ROOT / ".claude-plugin/plugin.json",
        ROOT / ".claude-plugin/marketplace.json",
        ROOT / "skills/orchestrate-task/SKILL.md",
        ROOT / "skills/orchestrate-task/agents/openai.yaml",
        ROOT / "skills/orchestrate-task/references/portable-contract.md",
        ROOT / "skills/orchestrate-task/references/model-selection.md",
    ]
    for path in required:
        require(path)

    codex = load_json(ROOT / ".codex-plugin/plugin.json")
    claude = load_json(ROOT / ".claude-plugin/plugin.json")
    marketplace = load_json(ROOT / ".claude-plugin/marketplace.json")
    for manifest_name, manifest in (("Codex", codex), ("Claude", claude)):
        if manifest.get("name") != "agent-workbench":
            fail(f"{manifest_name} manifest name must be agent-workbench")
        version = manifest.get("version")
        if not isinstance(version, str) or not SEMVER.fullmatch(version):
            fail(f"{manifest_name} manifest version must be semantic versioning")
        if manifest.get("license") != "Apache-2.0":
            fail(f"{manifest_name} manifest license must be Apache-2.0")
    if codex["version"] != claude["version"]:
        fail("Codex and Claude manifests must have the same version")
    if codex.get("skills") != "./skills/":
        fail("Codex manifest must point skills to ./skills/")
    if marketplace.get("name") != "agent-workbench":
        fail("Claude marketplace name must be agent-workbench")
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list) or len(plugins) != 1 or not isinstance(plugins[0], dict):
        fail("Claude marketplace must contain exactly one plugin object")
    if plugins[0].get("name") != "agent-workbench" or plugins[0].get("source") != "./":
        fail("Claude marketplace must expose the root agent-workbench plugin")

    interface = codex.get("interface")
    if not isinstance(interface, dict):
        fail("Codex manifest must contain an interface object")
    prompts = interface.get("defaultPrompt")
    if not isinstance(prompts, list) or not 1 <= len(prompts) <= 3:
        fail("Codex manifest must have one to three default prompts")
    if any(not isinstance(prompt, str) or len(prompt) > 128 for prompt in prompts):
        fail("Codex default prompts must be strings no longer than 128 characters")

    check_skill(ROOT / "skills/orchestrate-task/SKILL.md")
    model_reference = (ROOT / "skills/orchestrate-task/references/model-selection.md").read_text(encoding="utf-8")
    if "provider-neutral policy" not in model_reference:
        fail("model-selection reference must retain its provider-neutral boundary")
    print("Repository invariants passed.")


if __name__ == "__main__":
    main()
