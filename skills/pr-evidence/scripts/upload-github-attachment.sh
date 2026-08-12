#!/usr/bin/env bash
set +x
set -euo pipefail
umask 077

readonly MAX_ARTIFACT_BYTES=26214400
readonly MAX_RESPONSE_BYTES=65536
readonly UPLOAD_UNKNOWN='GitHub attachment upload: no success observed; creation state unknown; no cleanup attempted.'
SCRIPT_DIR="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  printf 'Usage: %s --authorized-upload <owner/repo> <artifact-path>\n' "$0" >&2
  exit 2
}

fail_input() {
  printf '%s\n' "$1" >&2
  exit 2
}

fail_runtime() {
  printf '%s\n' "$1" >&2
  exit 1
}

if [[ $# -ne 3 || "$1" != "--authorized-upload" ]]; then
  usage
fi

repository="$2"
artifact_path="$3"

if [[ ! "$repository" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,37}[A-Za-z0-9])?/[A-Za-z0-9._-]{1,100}$ ]]; then
  fail_input 'Invalid repository; expected a GitHub.com owner/repo name.'
fi
repo_name="${repository#*/}"
if [[ "$repo_name" == "." || "$repo_name" == ".." ]]; then
  fail_input 'Invalid repository; expected a GitHub.com owner/repo name.'
fi

if ! filename="$(basename -- "$artifact_path")"; then
  fail_input 'Could not inspect artifact filename.'
fi
case "$filename" in
  *.*) extension="${filename##*.}" ;;
  *) fail_input 'Artifact filename must have a supported extension.' ;;
esac
extension="$(printf '%s' "$extension" | LC_ALL=C tr '[:upper:]' '[:lower:]')"

for command_name in gh curl file jq mktemp python3; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    fail_runtime "Required command is unavailable: $command_name"
  fi
done

if [[ -n "${GH_HOST:-}" && "${GH_HOST}" != "github.com" ]]; then
  fail_input 'Only GitHub.com host context is supported.'
fi

if ! curl_version_output="$(curl -q --version 2>/dev/null)"; then
  fail_runtime 'Could not verify the curl version before upload.'
fi
if [[ ! "$curl_version_output" =~ ^curl[[:space:]]+([0-9]+)\.([0-9]+)\.([0-9]+)([[:space:]-]|$) ]]; then
  fail_runtime 'Could not verify the curl version before upload.'
fi
curl_major=$((10#${BASH_REMATCH[1]}))
curl_minor=$((10#${BASH_REMATCH[2]}))
curl_patch=$((10#${BASH_REMATCH[3]}))
if ((curl_major < 8 || (curl_major == 8 && curl_minor < 4))); then
  fail_runtime 'curl 8.4.0 or newer is required before upload.'
fi
unset curl_version_output curl_major curl_minor curl_patch

temp_parent="${TMPDIR:-/tmp}"
temp_dir="$(mktemp -d "$temp_parent/pr-evidence-upload.XXXXXX")" ||
  fail_runtime 'Could not create a private temporary directory.'
chmod 700 "$temp_dir"
snapshot_path="$temp_dir/artifact.snapshot.$extension"
response_file="$temp_dir/response.json"
error_file="$temp_dir/curl-error.txt"
curl_config_file="$temp_dir/curl.conf"
cleanup() {
  unset github_token
  rm -rf -- "$temp_dir"
}
trap cleanup EXIT HUP INT TERM

if ! python3 "$SCRIPT_DIR/snapshot_artifact.py" \
  "$artifact_path" "$snapshot_path" "$MAX_ARTIFACT_BYTES" >/dev/null 2>&1; then
  fail_input 'Artifact must be a stable, readable, non-symlink regular file between 1 byte and 25 MiB.'
fi
chmod 600 "$snapshot_path"

if ! artifact_size="$(wc -c < "$snapshot_path" | tr -d '[:space:]')"; then
  fail_input 'Could not inspect private artifact snapshot size.'
fi
if [[ ! "$artifact_size" =~ ^[0-9]+$ ]] || ((artifact_size == 0 || artifact_size > MAX_ARTIFACT_BYTES)); then
  fail_input 'Private artifact snapshot has an invalid size.'
fi

if ! mime_type="$(file -b --mime-type -- "$snapshot_path" 2>/dev/null)"; then
  fail_input 'Could not inspect private artifact snapshot MIME type.'
fi
case "$extension:$mime_type" in
  png:image/png|jpg:image/jpeg|jpeg:image/jpeg|gif:image/gif|webp:image/webp|mp4:video/mp4|mov:video/quicktime|webm:video/webm)
    ;;
  png:*|jpg:*|jpeg:*|gif:*|webp:*|mp4:*|mov:*|webm:*)
    fail_input 'Artifact MIME type does not match its extension.'
    ;;
  *)
    fail_input 'Unsupported artifact type; use PNG, JPEG, GIF, WebP, MP4, MOV, or WebM.'
    ;;
esac

if ! repository_metadata="$(gh api --hostname github.com "repos/${repository}" \
  --jq '[.id, .full_name] | @tsv' 2>/dev/null)"; then
  fail_runtime 'GitHub.com canonical repository lookup failed before upload.'
fi
tab_character=$'\t'
if [[ "$repository_metadata" != *"$tab_character"* ]]; then
  fail_runtime 'Could not resolve GitHub.com repository identity.'
fi
repository_id="${repository_metadata%%"$tab_character"*}"
canonical_repository="${repository_metadata#*"$tab_character"}"
if [[ ! "$repository_id" =~ ^[0-9]+$ || "$canonical_repository" != "$repository" ]]; then
  fail_runtime 'GitHub.com canonical repository does not exactly match the requested owner/repo.'
fi

if ! encoded_filename="$(printf '%s' "$filename" | jq -sRr @uri)"; then
  fail_runtime 'Could not encode artifact filename.'
fi
if ! encoded_mime_type="$(printf '%s' "$mime_type" | jq -sRr @uri)"; then
  fail_runtime 'Could not encode artifact MIME type.'
fi
if [[ -z "$encoded_filename" || -z "$encoded_mime_type" ]]; then
  fail_runtime 'Could not encode artifact metadata.'
fi
upload_url="https://uploads.github.com/user-attachments/assets?name=${encoded_filename}&content_type=${encoded_mime_type}&repository_id=${repository_id}"

if ! github_token="$(gh auth token --hostname github.com 2>/dev/null)"; then
  unset github_token
  fail_runtime 'GitHub.com authentication lookup failed before upload.'
fi
if [[ -z "$github_token" || ! "$github_token" =~ ^[A-Za-z0-9_]+$ ]]; then
  unset github_token
  fail_runtime 'GitHub.com authentication is unavailable.'
fi

{
  printf 'header = "Authorization: Bearer '
  printf '%s' "$github_token"
  printf '"\n'
} > "$curl_config_file"
chmod 600 "$curl_config_file"
unset github_token

if ! http_status="$(curl -q \
  --config "$curl_config_file" \
  --silent \
  --show-error \
  --request POST \
  --proto '=https' \
  --proto-redir '=https' \
  --max-redirs 0 \
  --connect-timeout 10 \
  --max-time 60 \
  --max-filesize "$MAX_RESPONSE_BYTES" \
  --output "$response_file" \
  --write-out '%{http_code}' \
  --header 'Content-Type: application/octet-stream' \
  --header 'Accept: application/json' \
  --header 'X-GitHub-Api-Version: 2022-11-28' \
  --data-binary "@${snapshot_path}" \
  "$upload_url" 2>"$error_file")"; then
  fail_runtime "$UPLOAD_UNKNOWN"
fi

if [[ ! "$http_status" =~ ^[0-9]{3}$ ]]; then
  fail_runtime "$UPLOAD_UNKNOWN"
fi
if [[ "$http_status" != "201" ]]; then
  fail_runtime "$UPLOAD_UNKNOWN"
fi

if ! response_size="$(wc -c 2>/dev/null < "$response_file" | tr -d '[:space:]')"; then
  fail_runtime "$UPLOAD_UNKNOWN"
fi
if [[ ! "$response_size" =~ ^[0-9]+$ ]] || ((response_size > MAX_RESPONSE_BYTES)); then
  fail_runtime "$UPLOAD_UNKNOWN"
fi

if ! asset_url="$(jq -er 'if type == "object" and (.url | type == "string") then .url else empty end' "$response_file" 2>/dev/null)"; then
  fail_runtime "$UPLOAD_UNKNOWN"
fi
if [[ ! "$asset_url" =~ ^https://github\.com/user-attachments/assets/[A-Za-z0-9_-]+$ ]]; then
  fail_runtime "$UPLOAD_UNKNOWN"
fi

printf '%s\n' "$asset_url"
