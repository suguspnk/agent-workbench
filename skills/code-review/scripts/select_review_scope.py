#!/usr/bin/env python3
"""Select one review target and its composable technology overlays.

The selector is deliberately pure: callers collect Git/PR and repository facts,
then pass one normalized JSON card. The selector performs no GitHub, Git, network,
or filesystem discovery and has no write side effects.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any


MAX_INPUT_BYTES = 1_048_576
OVERLAY_ORDER = (
    "javascript-typescript",
    "node-nestjs",
    "react-nextjs",
    "react-native",
)
SPECIALIST_OVERLAYS = set(OVERLAY_ORDER[1:])
REQUIRED_CARD_FIELDS = {
    "target_request",
    "git",
    "pr_probe",
    "local_changes",
    "workspace_files",
    "manifests",
    "imports",
    "overlay_override",
}
OPTIONAL_CARD_FIELDS = {"before_manifests", "before_imports"}
PR_FIELDS = {"number", "base_ref", "head_ref", "head_oid", "files", "patch"}
LOCAL_FIELDS = {"staged", "unstaged", "untracked"}
BOUNDARY_CONFIG_NAMES = {
    "package.json",
    "nest-cli.json",
    "react-native.config.js",
    "react-native.config.cjs",
}
JS_CONFIG_PREFIXES = (
    "tsconfig",
    "jsconfig",
    "eslint.config.",
    "babel.config.",
)
NEXT_CONFIG_PREFIXES = ("next.config.",)
RN_CONFIG_PREFIXES = ("metro.config.", "app.config.", "react-native.config.")
EXPO_CONFIG_NAMES = {"app.json"}
JS_EXTENSIONS = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}
NODE_IMPORTS = {
    "assert", "buffer", "child_process", "cluster", "crypto", "dgram", "dns",
    "events", "fs", "http", "http2", "https", "net", "os", "path",
    "perf_hooks", "process", "readline", "stream", "timers", "tls", "url",
    "util", "v8", "vm", "worker_threads", "zlib",
}
NODE_DEPENDENCIES = {"express", "fastify", "koa", "hapi", "@hapi/hapi"}


class ScopeError(ValueError):
    """Raised when a scope card is incomplete, ambiguous, or unsupported."""


def parse_json(text: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ScopeError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=reject_duplicates)


def load_json(path: Path) -> Any:
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ScopeError(f"input exceeds {MAX_INPUT_BYTES} bytes")
    return parse_json(path.read_text(encoding="utf-8"))


def _exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScopeError(f"{label} must be an object")
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing:
        raise ScopeError(f"{label} is missing fields: {', '.join(missing)}")
    if extra:
        raise ScopeError(f"{label} has unknown fields: {', '.join(extra)}")
    return value


def _closed_keys(
    value: Any,
    required: set[str],
    optional: set[str],
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScopeError(f"{label} must be an object")
    missing = sorted(required - set(value))
    extra = sorted(set(value) - required - optional)
    if missing:
        raise ScopeError(f"{label} is missing fields: {', '.join(missing)}")
    if extra:
        raise ScopeError(f"{label} has unknown fields: {', '.join(extra)}")
    return value


def normalize_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ScopeError(f"{label} must be a non-empty relative path")
    raw = value.replace("\\", "/")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ScopeError(f"{label} must stay within the repository")
    parts = [part for part in path.parts if part not in {"", "."}]
    if not parts:
        raise ScopeError(f"{label} must identify a file")
    return "/".join(parts)


def _path_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ScopeError(f"{label} must be an array")
    normalized = [normalize_path(item, f"{label} item") for item in value]
    return list(dict.fromkeys(normalized))


def _string(value: Any, label: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ScopeError(f"{label} must be a non-empty string")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ScopeError(f"{label} must be a string")
    return value


def validate_pr(value: Any, label: str) -> dict[str, Any]:
    pr = _exact_keys(value, PR_FIELDS, label)
    number = pr["number"]
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise ScopeError(f"{label}.number must be a positive integer")
    return {
        "number": number,
        "base_ref": _string(pr["base_ref"], f"{label}.base_ref"),
        "head_ref": _string(pr["head_ref"], f"{label}.head_ref"),
        "head_oid": _string(pr["head_oid"], f"{label}.head_oid"),
        "files": _path_list(pr["files"], f"{label}.files"),
        "patch": _text(pr["patch"], f"{label}.patch"),
    }


def _validate_override(value: Any) -> str | dict[str, list[str]]:
    if value == "auto":
        return "auto"
    if not isinstance(value, dict) or set(value) not in ({"add"}, {"exact"}):
        raise ScopeError("overlay_override must be 'auto', {'add': [...]}, or {'exact': [...]}")
    key = next(iter(value))
    raw = value[key]
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise ScopeError(f"overlay_override.{key} must be an array of overlay IDs")
    unknown = sorted(set(raw) - set(OVERLAY_ORDER))
    if unknown:
        raise ScopeError(f"unknown overlay IDs: {', '.join(unknown)}")
    return {key: list(dict.fromkeys(raw))}


def _validate_manifests(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ScopeError(f"{label} must be an array")
    manifests: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for index, item in enumerate(value):
        manifest = _exact_keys(item, {"path", "dependencies"}, f"{label}[{index}]")
        path = normalize_path(manifest["path"], f"{label}[{index}].path")
        if PurePosixPath(path).name != "package.json":
            raise ScopeError(f"{label}[{index}].path must end in package.json")
        if path in seen_paths:
            raise ScopeError(f"{label} contains duplicate normalized path: {path}")
        seen_paths.add(path)
        dependencies = manifest["dependencies"]
        if not isinstance(dependencies, list) or any(
            not isinstance(dep, str) or not dep for dep in dependencies
        ):
            raise ScopeError(f"{label}[{index}].dependencies must contain package names")
        manifests.append({"path": path, "dependencies": sorted(set(dependencies))})
    return manifests


def _validate_imports(value: Any, label: str) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise ScopeError(f"{label} must be an object keyed by repository-relative file")
    imports: dict[str, list[str]] = {}
    for raw_path, raw_imports in value.items():
        path = normalize_path(raw_path, f"{label} key")
        if path in imports:
            raise ScopeError(f"{label} contains duplicate normalized key: {path}")
        if not isinstance(raw_imports, list) or any(
            not isinstance(item, str) or not item for item in raw_imports
        ):
            raise ScopeError(f"{label}[{path}] must contain module specifiers")
        imports[path] = sorted(set(raw_imports))
    return imports


def validate_card(value: Any) -> dict[str, Any]:
    card = _closed_keys(value, REQUIRED_CARD_FIELDS, OPTIONAL_CARD_FIELDS, "scope card")

    request = card["target_request"]
    if not isinstance(request, dict) or request.get("kind") not in {"auto", "local", "pr"}:
        raise ScopeError("target_request.kind must be auto, local, or pr")
    if request["kind"] in {"auto", "local"}:
        _exact_keys(request, {"kind"}, "target_request")
        target_request = {"kind": request["kind"]}
    else:
        _exact_keys(request, {"kind", "pr"}, "target_request")
        target_request = {"kind": "pr", "pr": validate_pr(request["pr"], "target_request.pr")}

    git = _exact_keys(card["git"], {"branch", "head_oid"}, "git")
    normalized_git = {
        "branch": _string(git["branch"], "git.branch", nullable=True),
        "head_oid": _string(git["head_oid"], "git.head_oid"),
    }

    probe = _exact_keys(card["pr_probe"], {"status", "candidates"}, "pr_probe")
    if probe["status"] not in {"ok", "unavailable"}:
        raise ScopeError("pr_probe.status must be ok or unavailable")
    if not isinstance(probe["candidates"], list):
        raise ScopeError("pr_probe.candidates must be an array")
    candidates = [validate_pr(item, f"pr_probe.candidates[{index}]") for index, item in enumerate(probe["candidates"])]
    if probe["status"] == "unavailable" and candidates:
        raise ScopeError("an unavailable pr_probe cannot contain candidates")

    local = _exact_keys(card["local_changes"], LOCAL_FIELDS, "local_changes")
    normalized_local = {key: _path_list(local[key], f"local_changes.{key}") for key in sorted(LOCAL_FIELDS)}

    workspace_files = _path_list(card["workspace_files"], "workspace_files")

    manifests = _validate_manifests(card["manifests"], "manifests")
    before_manifests = _validate_manifests(
        card.get("before_manifests", []),
        "before_manifests",
    )
    imports = _validate_imports(card["imports"], "imports")
    before_imports = _validate_imports(card.get("before_imports", {}), "before_imports")

    return {
        "target_request": target_request,
        "git": normalized_git,
        "pr_probe": {"status": probe["status"], "candidates": candidates},
        "local_changes": normalized_local,
        "workspace_files": workspace_files,
        "manifests": manifests,
        "before_manifests": before_manifests,
        "imports": imports,
        "before_imports": before_imports,
        "overlay_override": _validate_override(card["overlay_override"]),
    }


def _local_target(local: dict[str, list[str]]) -> dict[str, Any]:
    changed = list(dict.fromkeys(local["staged"] + local["unstaged"] + local["untracked"]))
    return {"kind": "local", **local, "files": changed}


def select_target(card: dict[str, Any]) -> tuple[str, dict[str, Any] | None, str]:
    request = card["target_request"]
    if request["kind"] == "pr":
        return "selected", {"kind": "pr", **request["pr"]}, "explicit-pr"
    if request["kind"] == "local":
        return "selected", _local_target(card["local_changes"]), "explicit-local"

    probe = card["pr_probe"]
    if probe["status"] == "unavailable":
        return "needs_input", None, "pr-discovery-unavailable"

    branch = card["git"]["branch"]
    if branch is None:
        candidates = [pr for pr in probe["candidates"] if pr["head_oid"] == card["git"]["head_oid"]]
        association = "detached-head-oid"
    else:
        candidates = [pr for pr in probe["candidates"] if pr["head_ref"] == branch]
        association = "branch-pr"

    if len(candidates) == 1:
        return "selected", {"kind": "pr", **candidates[0]}, association
    if len(candidates) > 1:
        return "needs_input", None, f"ambiguous-{association}"
    return "selected", _local_target(card["local_changes"]), "conclusive-no-associated-pr"


def _directory(path: str) -> str:
    parent = str(PurePosixPath(path).parent)
    return "" if parent == "." else parent


def _is_boundary_config(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return (
        name in BOUNDARY_CONFIG_NAMES
        or name.startswith(JS_CONFIG_PREFIXES + NEXT_CONFIG_PREFIXES + RN_CONFIG_PREFIXES)
    )


def _nearest_boundary(path: str, boundary_dirs: set[str]) -> str:
    current = _directory(path)
    while True:
        if current in boundary_dirs:
            return current
        if not current:
            return ""
        parent = str(PurePosixPath(current).parent)
        current = "" if parent == "." else parent


def _module_root(specifier: str) -> str:
    value = specifier[5:] if specifier.startswith("node:") else specifier
    if value.startswith("@"):
        return "/".join(value.split("/")[:2])
    return value.split("/", 1)[0]


def _is_nest_module(specifier: str) -> bool:
    return specifier.startswith("@nestjs/") and len(specifier) > len("@nestjs/")


def _is_expo_module(specifier: str) -> bool:
    return (
        specifier == "expo"
        or specifier.startswith("expo/")
        or specifier.startswith("expo-")
        or specifier.startswith("@expo/")
    )


def _platform_path(path: str) -> bool:
    lower = path.lower()
    name = PurePosixPath(lower).name
    return (
        "/android/" in f"/{lower}/"
        or "/ios/" in f"/{lower}/"
        or any(token in name for token in (".native.", ".android.", ".ios."))
    )


def detect_overlays(card: dict[str, Any], changed_files: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    workspace_files = set(card["workspace_files"]) | set(changed_files)
    manifests = card["manifests"]
    before_manifests = card["before_manifests"]
    boundary_dirs = {
        _directory(item["path"])
        for item in manifests + before_manifests
    }
    boundary_dirs.update(
        _directory(path) for path in workspace_files if _is_boundary_config(path)
    )
    boundary_dirs.add("")

    evidence: dict[str, set[str]] = {overlay: set() for overlay in OVERLAY_ORDER}
    manifest_by_dir = {_directory(item["path"]): item for item in manifests}
    before_manifest_by_dir = {
        _directory(item["path"]): item for item in before_manifests
    }

    native_files_by_boundary: dict[str, set[str]] = {}
    nest_configs_by_boundary: dict[str, set[str]] = {}
    rn_configs_by_boundary: dict[str, set[str]] = {}
    expo_configs_by_boundary: dict[str, set[str]] = {}
    next_configs_by_boundary: dict[str, set[str]] = {}
    for workspace_path in workspace_files:
        direct_directory = _directory(workspace_path)
        workspace_name = PurePosixPath(workspace_path).name.lower()
        if workspace_name == "nest-cli.json":
            nest_configs_by_boundary.setdefault(direct_directory, set()).add(
                workspace_path
            )
        if workspace_name.startswith(RN_CONFIG_PREFIXES):
            rn_configs_by_boundary.setdefault(direct_directory, set()).add(
                workspace_path
            )
        if workspace_name in EXPO_CONFIG_NAMES:
            expo_configs_by_boundary.setdefault(direct_directory, set()).add(
                workspace_path
            )
        if workspace_name.startswith(NEXT_CONFIG_PREFIXES):
            next_configs_by_boundary.setdefault(direct_directory, set()).add(
                workspace_path
            )
        if _platform_path(workspace_path):
            nearest = _nearest_boundary(workspace_path, boundary_dirs)
            native_files_by_boundary.setdefault(nearest, set()).add(workspace_path)

    for path in changed_files:
        boundary = _nearest_boundary(path, boundary_dirs)
        boundary_label = boundary or "."
        name = PurePosixPath(path).name.lower()
        suffix = PurePosixPath(path).suffix.lower()

        relevant_imports = set(card["imports"].get(path, []))
        before_imports = set(card["before_imports"].get(path, []))
        removed_imports = before_imports - relevant_imports
        effective_imports = relevant_imports | removed_imports
        import_roots = {_module_root(item) for item in effective_imports}

        manifest = manifest_by_dir.get(boundary)
        before_manifest = before_manifest_by_dir.get(boundary)
        dependencies = set(manifest["dependencies"]) if manifest else set()
        before_dependencies = (
            set(before_manifest["dependencies"]) if before_manifest else set()
        )
        removed_dependencies = before_dependencies - dependencies
        effective_dependencies = dependencies | removed_dependencies
        code_or_config = (
            suffix in JS_EXTENSIONS
            or name == "package.json"
            or _is_boundary_config(path)
        )

        if suffix in JS_EXTENSIONS:
            evidence["javascript-typescript"].add(f"extension:{suffix}@{path}")
        if name == "package.json" or name.startswith(JS_CONFIG_PREFIXES):
            evidence["javascript-typescript"].add(f"config:{path}")

        node_imports = sorted(
            item for item in relevant_imports
            if item.startswith("node:")
            or _module_root(item) in NODE_IMPORTS | NODE_DEPENDENCIES
            or _is_nest_module(_module_root(item))
        )
        removed_node_imports = sorted(
            item for item in removed_imports
            if item.startswith("node:")
            or _module_root(item) in NODE_IMPORTS | NODE_DEPENDENCIES
            or _is_nest_module(_module_root(item))
        )
        node_dependencies = sorted(
            item for item in dependencies
            if item in NODE_DEPENDENCIES or _is_nest_module(item)
        )
        removed_node_dependencies = sorted(
            item for item in removed_dependencies
            if item in NODE_DEPENDENCIES or _is_nest_module(item)
        )
        nest_configs = nest_configs_by_boundary.get(boundary, set())
        if code_or_config and (
            node_imports
            or removed_node_imports
            or node_dependencies
            or removed_node_dependencies
            or nest_configs
        ):
            evidence["node-nestjs"].update(
                f"import:{item}@{path}" for item in node_imports
            )
            evidence["node-nestjs"].update(
                f"removed-import:{item}@{path}" for item in removed_node_imports
            )
            if manifest:
                evidence["node-nestjs"].update(
                    f"dependency:{item}@{manifest['path']}"
                    for item in node_dependencies
                )
            if before_manifest:
                evidence["node-nestjs"].update(
                    f"removed-dependency:{item}@{before_manifest['path']}"
                    for item in removed_node_dependencies
                )
            evidence["node-nestjs"].update(
                f"config:{item}" for item in nest_configs
            )

        rn_imports = sorted(
            item for item in relevant_imports
            if _module_root(item) == "react-native" or _is_expo_module(item)
        )
        removed_rn_imports = sorted(
            item for item in removed_imports
            if _module_root(item) == "react-native" or _is_expo_module(item)
        )
        rn_dependencies = sorted(
            item for item in dependencies
            if item == "react-native" or _is_expo_module(item)
        )
        removed_rn_dependencies = sorted(
            item for item in removed_dependencies
            if item == "react-native" or _is_expo_module(item)
        )
        expo_evidence = any(
            _is_expo_module(item)
            for item in (
                rn_imports
                + removed_rn_imports
                + rn_dependencies
                + removed_rn_dependencies
            )
        )
        rn_configs = set(rn_configs_by_boundary.get(boundary, set()))
        if expo_evidence:
            rn_configs.update(expo_configs_by_boundary.get(boundary, set()))
        native_files = native_files_by_boundary.get(boundary, set())
        rn_signal = bool(
            rn_imports
            or removed_rn_imports
            or rn_dependencies
            or removed_rn_dependencies
            or rn_configs
            or _platform_path(path)
            or native_files
        )
        rn_framework_evidence = bool(
            rn_imports
            or removed_rn_imports
            or rn_dependencies
            or removed_rn_dependencies
            or rn_configs
        )
        rn_code_or_config = (
            code_or_config
            or (name in EXPO_CONFIG_NAMES and path in rn_configs)
            or (_platform_path(path) and rn_framework_evidence)
        )
        if rn_code_or_config and rn_signal:
            evidence["react-native"].update(
                f"import:{item}@{path}" for item in rn_imports
            )
            evidence["react-native"].update(
                f"removed-import:{item}@{path}" for item in removed_rn_imports
            )
            if manifest:
                evidence["react-native"].update(
                    f"dependency:{item}@{manifest['path']}"
                    for item in rn_dependencies
                )
            if before_manifest:
                evidence["react-native"].update(
                    f"removed-dependency:{item}@{before_manifest['path']}"
                    for item in removed_rn_dependencies
                )
            evidence["react-native"].update(
                f"config:{item}" for item in rn_configs
            )
            if _platform_path(path):
                evidence["react-native"].add(f"platform-file:{path}")
            elif native_files:
                evidence["react-native"].add(f"native-tree:{boundary_label}")

        web_imports = sorted(
            item for item in relevant_imports
            if _module_root(item) in {"react", "react-dom", "next"}
        )
        removed_web_imports = sorted(
            item for item in removed_imports
            if _module_root(item) in {"react", "react-dom", "next"}
        )
        next_or_dom_dependencies = sorted(dependencies & {"react-dom", "next"})
        removed_next_or_dom_dependencies = sorted(
            removed_dependencies & {"react-dom", "next"}
        )
        next_configs = next_configs_by_boundary.get(boundary, set())
        unambiguous_web = bool(
            {"react-dom", "next"} & import_roots
            or next_or_dom_dependencies
            or removed_next_or_dom_dependencies
            or next_configs
        )
        react_only_without_rn = bool(
            "react" in import_roots | effective_dependencies
            and not rn_signal
        )
        if code_or_config and (unambiguous_web or react_only_without_rn):
            evidence["react-nextjs"].update(
                f"import:{item}@{path}" for item in web_imports
            )
            evidence["react-nextjs"].update(
                f"removed-import:{item}@{path}" for item in removed_web_imports
            )
            if manifest:
                evidence["react-nextjs"].update(
                    f"dependency:{item}@{manifest['path']}"
                    for item in sorted(dependencies & {"react", "react-dom", "next"})
                )
            if before_manifest:
                evidence["react-nextjs"].update(
                    f"removed-dependency:{item}@{before_manifest['path']}"
                    for item in sorted(
                        removed_dependencies & {"react", "react-dom", "next"}
                    )
                )
            evidence["react-nextjs"].update(
                f"config:{item}" for item in next_configs
            )

    detected = [overlay for overlay in OVERLAY_ORDER if evidence[overlay]]
    override = card["overlay_override"]
    if override == "auto":
        selected = detected
        override_mode = None
        override_items: set[str] = set()
    elif "add" in override:
        override_mode = "add"
        override_items = set(override["add"])
        selected = [overlay for overlay in OVERLAY_ORDER if overlay in set(detected) | override_items]
    else:
        override_mode = "exact"
        override_items = set(override["exact"])
        selected = [overlay for overlay in OVERLAY_ORDER if overlay in override_items]

    if override_mode:
        for overlay in override_items:
            evidence[overlay].add(f"caller-override:{override_mode}:{overlay}")

    if set(selected) & SPECIALIST_OVERLAYS and "javascript-typescript" not in selected:
        selected = [overlay for overlay in OVERLAY_ORDER if overlay == "javascript-typescript" or overlay in selected]
        evidence["javascript-typescript"].add("implied-by-specialist-overlay")
        for overlay in sorted(override_items & SPECIALIST_OVERLAYS):
            evidence["javascript-typescript"].add(f"caller-override:implied-by:{overlay}")

    return selected, {overlay: sorted(evidence[overlay]) for overlay in selected}


def select_scope(card_value: Any) -> dict[str, Any]:
    card = validate_card(card_value)
    status, target, reason = select_target(card)
    if target is None:
        return {
            "status": status,
            "reason": reason,
            "target": None,
            "changed_files": [],
            "overlays": [],
            "overlay_evidence": {},
        }
    changed_files = target["files"]
    overlays, evidence = detect_overlays(card, changed_files)
    return {
        "status": status,
        "reason": reason,
        "target": target,
        "changed_files": changed_files,
        "overlays": overlays,
        "overlay_evidence": evidence,
    }


def check_replay(path: Path) -> int:
    data = load_json(path)
    if not isinstance(data, list):
        raise ScopeError("replay file must contain an array")
    failures: list[str] = []
    seen: set[str] = set()
    for index, case in enumerate(data):
        if not isinstance(case, dict) or set(case) != {"id", "card", "expected"}:
            failures.append(f"case {index}: fields must be exactly id, card, expected")
            continue
        case_id = case["id"]
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            failures.append(f"case {index}: id must be a unique non-empty string")
            continue
        seen.add(case_id)
        expected = case["expected"]
        if not isinstance(expected, dict):
            failures.append(f"{case_id}: expected must be an object")
            continue
        try:
            actual = select_scope(case["card"])
        except (ScopeError, KeyError, TypeError) as error:
            if expected == {"error": str(error)}:
                continue
            failures.append(f"{case_id}: selection failed: {error}")
            continue
        projected = {
            "status": actual["status"],
            "reason": actual["reason"],
            "target_kind": actual["target"]["kind"] if actual["target"] else None,
            "target_number": actual["target"].get("number") if actual["target"] else None,
            "overlays": actual["overlays"],
        }
        if projected != expected:
            failures.append(f"{case_id}: expected {expected!r}, got {projected!r}")
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    print(f"Code-review scope replay passed ({len(data)} cases).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--card", type=Path, help="normalized JSON scope card")
    source.add_argument("--replay", type=Path, help="JSON replay cases")
    args = parser.parse_args()
    try:
        if args.replay:
            return check_replay(args.replay)
        print(json.dumps(select_scope(load_json(args.card)), indent=2, sort_keys=True))
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ScopeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
