#!/usr/bin/env bash
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HELPER="$SCRIPT_DIR/upload-github-attachment.sh"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/pr-evidence-upload-test.XXXXXX")"
trap 'rm -rf -- "$TEST_ROOT"' EXIT HUP INT TERM

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

assert_contains() {
  needle="$1"
  target="$2"
  grep -Fq -- "$needle" "$target" || fail "expected text was absent"
}

assert_not_contains() {
  needle="$1"
  target="$2"
  if grep -Fq -- "$needle" "$target"; then
    fail "unexpected text was present"
  fi
}

run_expect_failure() {
  label="$1"
  shift
  if "$@" >"$TEST_ROOT/$label.out" 2>"$TEST_ROOT/$label.err"; then
    fail "$label should fail"
  fi
}

assert_temp_cleaned() {
  if [[ -s "$TEST_ROOT/temp-paths.log" ]]; then
    while IFS= read -r path; do
      [[ ! -e "$path" ]] || fail "private temporary path was not cleaned"
    done < "$TEST_ROOT/temp-paths.log"
  fi
}

assert_upload_unknown() {
  label="$1"
  assert_contains 'no success observed' "$TEST_ROOT/$label.err"
  assert_contains 'creation state unknown' "$TEST_ROOT/$label.err"
  assert_contains 'no cleanup attempted' "$TEST_ROOT/$label.err"
}

assert_no_upload_temp_dirs() {
  if find "$TEST_ROOT/tmp" -mindepth 1 -maxdepth 1 -name 'pr-evidence-upload.*' -print | grep -q .; then
    fail 'private upload temporary directory persisted'
  fi
}

assert_token_rejected_before_upload() {
  label="$1"
  secret_fragment="$2"
  assert_contains 'GitHub.com authentication is unavailable' "$TEST_ROOT/$label.err"
  assert_not_contains '--request POST' "$CURL_LOG"
  assert_not_contains '--config' "$CURL_LOG"
  if [[ -n "$secret_fragment" ]]; then
    assert_not_contains "$secret_fragment" "$TEST_ROOT/$label.out"
    assert_not_contains "$secret_fragment" "$TEST_ROOT/$label.err"
    assert_not_contains "$secret_fragment" "$GH_LOG"
    assert_not_contains "$secret_fragment" "$CURL_LOG"
    assert_not_contains "$secret_fragment" "$JQ_LOG"
  fi
  assert_no_upload_temp_dirs
}

mkdir -p "$TEST_ROOT/bin" "$TEST_ROOT/home" "$TEST_ROOT/tmp"
: > "$TEST_ROOT/gh.log"
: > "$TEST_ROOT/curl.log"
: > "$TEST_ROOT/jq.log"
: > "$TEST_ROOT/temp-paths.log"
printf 'unsafe-option = true\n' > "$TEST_ROOT/home/.curlrc"
printf 'fake png payload\n' > "$TEST_ROOT/evidence.png"
printf 'fake jpeg payload\n' > "$TEST_ROOT/evidence.jpg"
printf 'active svg payload\n' > "$TEST_ROOT/evidence.svg"
printf 'fake png payload with spaces\n' > "$TEST_ROOT/spaced evidence.png"
printf 'original race payload\n' > "$TEST_ROOT/race.png"
cp "$TEST_ROOT/race.png" "$TEST_ROOT/race-expected.bin"
tab_artifact="$TEST_ROOT/$(printf 'tab\tevidence.png')"
printf 'fake png payload with a tab\n' > "$tab_artifact"
ln -s "$TEST_ROOT/evidence.png" "$TEST_ROOT/evidence-link.png"
mkfifo "$TEST_ROOT/evidence-pipe.png"
dd if=/dev/zero of="$TEST_ROOT/oversize.png" bs=1 count=0 seek=26214401 2>/dev/null

cat > "$TEST_ROOT/bin/gh" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
: "${GH_LOG:?}"
{
  printf 'gh'
  for argument in "$@"; do
    printf ' %q' "$argument"
  done
  printf '\n'
} >> "$GH_LOG"

case "${1:-}" in
  api)
    [[ "${2:-}" == "--hostname" && "${3:-}" == "github.com" ]]
    [[ "${4:-}" == repos/* && "${5:-}" == "--jq" && "${6:-}" == '[.id, .full_name] | @tsv' ]]
    requested_repository="${4#repos/}"
    printf '%s\t%s\n' \
      "${FAKE_REPOSITORY_ID:-1242935770}" \
      "${FAKE_CANONICAL_REPOSITORY:-$requested_repository}"
    [[ "${FAKE_GH_API_EXIT_NONZERO:-0}" == 0 ]] || exit 9
    ;;
  auth)
    [[ "${2:-}" == "token" && "${3:-}" == "--hostname" && "${4:-}" == "github.com" ]]
    if [[ "${FAKE_GH_TOKEN_SET:-0}" == 1 ]]; then
      printf '%s' "${FAKE_GH_TOKEN:-}"
    else
      printf '%s\n' 'fake_token_not_for_production'
    fi
    [[ "${FAKE_GH_AUTH_EXIT_NONZERO:-0}" == 0 ]] || exit 9
    ;;
  *)
    exit 2
    ;;
esac
STUB

cat > "$TEST_ROOT/bin/file" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
artifact=''
for argument in "$@"; do
  artifact="$argument"
done
if [[ -n "${REPLACE_SOURCE_PATH:-}" ]]; then
  printf 'replacement race payload\n' > "$REPLACE_SOURCE_PATH"
fi
if [[ -n "${FAKE_MIME:-}" ]]; then
  printf '%s\n' "$FAKE_MIME"
  [[ "${FAKE_FILE_EXIT_NONZERO:-0}" == 0 ]] || exit 9
  exit 0
fi
case "$artifact" in
  *.png|*.PNG) printf '%s\n' 'image/png' ;;
  *.jpg|*.jpeg|*.JPG|*.JPEG) printf '%s\n' 'image/jpeg' ;;
  *.gif|*.GIF) printf '%s\n' 'image/gif' ;;
  *.webp|*.WEBP) printf '%s\n' 'image/webp' ;;
  *.mp4|*.MP4) printf '%s\n' 'video/mp4' ;;
  *.mov|*.MOV) printf '%s\n' 'video/quicktime' ;;
  *.webm|*.WEBM) printf '%s\n' 'video/webm' ;;
  *.svg|*.SVG) printf '%s\n' 'image/svg+xml' ;;
  *) printf '%s\n' 'application/octet-stream' ;;
esac
[[ "${FAKE_FILE_EXIT_NONZERO:-0}" == 0 ]] || exit 9
STUB

cat > "$TEST_ROOT/bin/jq" <<'STUB'
#!/usr/bin/env python3
import json
import os
import sys
import urllib.parse

with open(os.environ["JQ_LOG"], "a", encoding="utf-8") as log:
    log.write("jq " + " ".join(sys.argv[1:]) + "\n")

if sys.argv[1:] == ["-sRr", "@uri"]:
    sys.stdout.write(urllib.parse.quote(sys.stdin.read(), safe="") + "\n")
elif len(sys.argv) == 4 and sys.argv[1] == "-er":
    try:
        value = json.loads(open(sys.argv[3], encoding="utf-8").read())
        url = value["url"]
        if not isinstance(value, dict) or not isinstance(url, str) or not url:
            raise ValueError
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise SystemExit(1)
    sys.stdout.write(url + "\n")
else:
    raise SystemExit(2)
STUB

cat > "$TEST_ROOT/bin/curl" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
: "${CURL_LOG:?}"
: "${TEMP_PATH_LOG:?}"

[[ "${1:-}" == "-q" ]] || {
  printf '%s\n' 'curlrc isolation flag must be first' >&2
  exit 90
}

{
  printf 'curl'
  for argument in "$@"; do
    printf ' %q' "$argument"
  done
  printf '\n'
} >> "$CURL_LOG"

if [[ "${2:-}" == "--version" ]]; then
  printf 'curl %s (offline test stub)\n' "${FAKE_CURL_VERSION:-8.4.0}"
  [[ "${FAKE_CURL_VERSION_EXIT_NONZERO:-0}" == 0 ]] || exit 9
  exit 0
fi

config=''
output=''
request=''
url=''
proto=''
proto_redir=''
max_redirs=''
connect_timeout=''
max_time=''
max_filesize=''
write_out=''
data_binary=''
saw_retry=0
saw_location=0

while (($#)); do
  case "$1" in
    -q|--silent|--show-error)
      shift
      ;;
    --config)
      config="$2"
      shift 2
      ;;
    --output)
      output="$2"
      shift 2
      ;;
    --request)
      request="$2"
      shift 2
      ;;
    --proto)
      proto="$2"
      shift 2
      ;;
    --proto-redir)
      proto_redir="$2"
      shift 2
      ;;
    --max-redirs)
      max_redirs="$2"
      shift 2
      ;;
    --connect-timeout)
      connect_timeout="$2"
      shift 2
      ;;
    --max-time)
      max_time="$2"
      shift 2
      ;;
    --max-filesize)
      max_filesize="$2"
      shift 2
      ;;
    --write-out)
      write_out="$2"
      shift 2
      ;;
    --header)
      shift 2
      ;;
    --data-binary)
      data_binary="$2"
      shift 2
      ;;
    --retry|--retry-all-errors|--retry-connrefused)
      saw_retry=1
      shift
      ;;
    -L|--location|--location-trusted)
      saw_location=1
      shift
      ;;
    https://*)
      url="$1"
      shift
      ;;
    *)
      printf 'unexpected curl argument: %s\n' "$1" >&2
      exit 91
      ;;
  esac
done

[[ "$request" == "POST" ]] || exit 92
[[ "$proto" == "=https" && "$proto_redir" == "=https" ]] || exit 93
[[ "$max_redirs" == "0" && "$connect_timeout" == "10" && "$max_time" == "60" ]] || exit 94
[[ "$max_filesize" == "65536" ]] || exit 104
[[ "$write_out" == "%{http_code}" && "$data_binary" == @* ]] || exit 95
[[ "$saw_retry" == 0 && "$saw_location" == 0 ]] || exit 96
[[ "$url" == https://uploads.github.com/user-attachments/assets\?* ]] || exit 97
[[ -f "$config" && -n "$output" ]] || exit 98
upload_path="${data_binary#@}"
[[ -f "$upload_path" && "$upload_path" != "${REPLACE_SOURCE_PATH:-}" ]] || exit 102
if [[ -n "${EXPECTED_UPLOAD_BYTES_FILE:-}" ]]; then
  cmp "$upload_path" "$EXPECTED_UPLOAD_BYTES_FILE" || exit 103
fi

if stat -f '%Lp' "$config" >/dev/null 2>&1; then
  config_mode="$(stat -f '%Lp' "$config")"
else
  config_mode="$(stat -c '%a' "$config")"
fi
[[ "$config_mode" == "600" ]] || exit 99
grep -Fq 'Authorization: Bearer fake_token_not_for_production' "$config" || exit 100
if grep -Fq 'fake_token_not_for_production' "$CURL_LOG"; then
  exit 101
fi

printf '%s\n' "$config" "$output" "$upload_path" >> "$TEMP_PATH_LOG"

if [[ "${FAKE_CURL_MODE:-success}" == "transport" ]]; then
  printf '%s\n' 'simulated path and token-like diagnostic that must be suppressed' >&2
  exit 28
fi
if [[ "${FAKE_CURL_MODE:-success}" == "oversize" ]]; then
  dd if=/dev/zero of="$output" bs=65537 count=1 2>/dev/null
  printf '%s' '201'
  exit 63
fi
if [[ "${FAKE_CURL_MODE:-success}" == "oversize-zero" ]]; then
  dd if=/dev/zero of="$output" bs=65537 count=1 2>/dev/null
  printf '%s' '201'
  exit 0
fi

status="${FAKE_UPLOAD_STATUS:-201}"
case "${FAKE_RESPONSE_KIND:-valid}" in
  valid)
    printf '{"url":"%s"}' "${FAKE_ASSET_URL:-https://github.com/user-attachments/assets/test-asset_123}" > "$output"
    ;;
  malformed)
    printf '%s' '{not-json' > "$output"
    ;;
  missing-url)
    printf '%s' '{"message":"no url"}' > "$output"
    ;;
esac
printf '%s' "$status"
STUB

chmod +x "$TEST_ROOT/bin/gh" "$TEST_ROOT/bin/file" "$TEST_ROOT/bin/jq" "$TEST_ROOT/bin/curl"
export PATH="$TEST_ROOT/bin:$PATH"
export GH_LOG="$TEST_ROOT/gh.log"
export CURL_LOG="$TEST_ROOT/curl.log"
export JQ_LOG="$TEST_ROOT/jq.log"
export TEMP_PATH_LOG="$TEST_ROOT/temp-paths.log"
export HOME="$TEST_ROOT/home"
export TMPDIR="$TEST_ROOT/tmp"
unset GH_HOST

success_url="$("$HELPER" --authorized-upload example-owner/example.repo "$TEST_ROOT/evidence.png")"
[[ "$success_url" == 'https://github.com/user-attachments/assets/test-asset_123' ]] || fail 'successful upload URL'
assert_contains 'gh api --hostname github.com repos/example-owner/example.repo' "$GH_LOG"
assert_contains 'full_name' "$GH_LOG"
assert_contains 'gh auth token --hostname github.com' "$GH_LOG"
assert_contains 'curl -q --config' "$CURL_LOG"
assert_contains '--proto =https --proto-redir =https --max-redirs 0' "$CURL_LOG"
assert_contains '--connect-timeout 10 --max-time 60' "$CURL_LOG"
assert_contains '--max-filesize 65536' "$CURL_LOG"
assert_contains 'uploads.github.com/user-attachments/assets' "$CURL_LOG"
assert_contains 'repository_id=1242935770' "$CURL_LOG"
assert_contains 'content_type=image%2Fpng' "$CURL_LOG"
assert_not_contains 'fake_token_not_for_production' "$CURL_LOG"
assert_temp_cleaned

space_url="$("$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/spaced evidence.png")"
[[ "$space_url" == "$success_url" ]] || fail 'space-safe filename'
tab_url="$("$HELPER" --authorized-upload example-owner/example-repo "$tab_artifact")"
[[ "$tab_url" == "$success_url" ]] || fail 'control-safe filename'
race_url="$(env \
  REPLACE_SOURCE_PATH="$TEST_ROOT/race.png" \
  EXPECTED_UPLOAD_BYTES_FILE="$TEST_ROOT/race-expected.bin" \
  "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/race.png")"
[[ "$race_url" == "$success_url" ]] || fail 'replacement-race upload URL'
assert_contains 'replacement race payload' "$TEST_ROOT/race.png"

run_expect_failure missing-authorization "$HELPER" example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_contains 'Usage:' "$TEST_ROOT/missing-authorization.err"

: > "$GH_LOG"
run_expect_failure host env GH_HOST=enterprise.example "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_contains 'Only GitHub.com' "$TEST_ROOT/host.err"
[[ ! -s "$GH_LOG" ]] || fail 'non-GitHub host must fail before gh use'

: > "$GH_LOG"
: > "$CURL_LOG"
run_expect_failure old-curl env \
  FAKE_CURL_VERSION=8.3.0 \
  "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_contains 'curl 8.4.0 or newer is required before upload' "$TEST_ROOT/old-curl.err"
assert_not_contains 'gh ' "$GH_LOG"
assert_not_contains '--request POST' "$CURL_LOG"

: > "$GH_LOG"
: > "$CURL_LOG"
run_expect_failure file-nonzero env \
  FAKE_FILE_EXIT_NONZERO=1 \
  FAKE_MIME=image/png \
  "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_contains 'Could not inspect private artifact snapshot MIME type' "$TEST_ROOT/file-nonzero.err"
assert_not_contains 'image/png' "$TEST_ROOT/file-nonzero.err"
[[ ! -s "$GH_LOG" ]] || fail 'file failure must stop before GitHub'
assert_not_contains '--request POST' "$CURL_LOG"

: > "$GH_LOG"
: > "$CURL_LOG"
run_expect_failure gh-api-nonzero env \
  FAKE_GH_API_EXIT_NONZERO=1 \
  "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_contains 'canonical repository lookup failed before upload' "$TEST_ROOT/gh-api-nonzero.err"
assert_not_contains '1242935770' "$TEST_ROOT/gh-api-nonzero.err"
assert_contains 'gh api' "$GH_LOG"
assert_not_contains 'gh auth token' "$GH_LOG"
assert_not_contains '--request POST' "$CURL_LOG"

: > "$GH_LOG"
: > "$CURL_LOG"
run_expect_failure gh-auth-nonzero env \
  FAKE_GH_AUTH_EXIT_NONZERO=1 \
  "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_contains 'authentication lookup failed before upload' "$TEST_ROOT/gh-auth-nonzero.err"
assert_not_contains 'fake_token_not_for_production' "$TEST_ROOT/gh-auth-nonzero.err"
assert_contains 'gh auth token' "$GH_LOG"
assert_not_contains '--request POST' "$CURL_LOG"

: > "$GH_LOG"
run_expect_failure canonical-mismatch env \
  FAKE_CANONICAL_REPOSITORY=canonical-owner/example-repo \
  "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_contains 'canonical repository does not exactly match' "$TEST_ROOT/canonical-mismatch.err"
assert_not_contains 'gh auth token' "$GH_LOG"

: > "$GH_LOG"
: > "$CURL_LOG"
: > "$JQ_LOG"
run_expect_failure token-empty env \
  FAKE_GH_TOKEN_SET=1 \
  FAKE_GH_TOKEN='' \
  "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_token_rejected_before_upload token-empty ''

: > "$GH_LOG"
: > "$CURL_LOG"
: > "$JQ_LOG"
multiline_token="multiline_secret_part_one
multiline_secret_part_two"
run_expect_failure token-multiline env \
  FAKE_GH_TOKEN_SET=1 \
  FAKE_GH_TOKEN="$multiline_token" \
  "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_token_rejected_before_upload token-multiline multiline_secret_part_one
assert_not_contains 'multiline_secret_part_two' "$TEST_ROOT/token-multiline.out"
assert_not_contains 'multiline_secret_part_two' "$TEST_ROOT/token-multiline.err"

: > "$GH_LOG"
: > "$CURL_LOG"
: > "$JQ_LOG"
run_expect_failure token-quote env \
  FAKE_GH_TOKEN_SET=1 \
  'FAKE_GH_TOKEN=quote_secret_value"suffix' \
  "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_token_rejected_before_upload token-quote quote_secret_value

: > "$GH_LOG"
: > "$CURL_LOG"
: > "$JQ_LOG"
directive_token='directive_secret_value"
header = "X-Test: injected'
run_expect_failure token-directive env \
  FAKE_GH_TOKEN_SET=1 \
  FAKE_GH_TOKEN="$directive_token" \
  "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_token_rejected_before_upload token-directive directive_secret_value
assert_not_contains 'header = ' "$TEST_ROOT/token-directive.out"
assert_not_contains 'header = ' "$TEST_ROOT/token-directive.err"

run_expect_failure malformed-repo "$HELPER" --authorized-upload invalid-repository "$TEST_ROOT/evidence.png"
assert_contains 'Invalid repository' "$TEST_ROOT/malformed-repo.err"
control_repo="example-owner/$(printf 'bad\nrepo')"
run_expect_failure control-repo "$HELPER" --authorized-upload "$control_repo" "$TEST_ROOT/evidence.png"
assert_contains 'Invalid repository' "$TEST_ROOT/control-repo.err"

run_expect_failure symlink "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence-link.png"
assert_contains 'non-symlink regular file' "$TEST_ROOT/symlink.err"
run_expect_failure nonregular "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence-pipe.png"
assert_contains 'non-symlink regular file' "$TEST_ROOT/nonregular.err"
run_expect_failure oversize "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/oversize.png"
assert_contains '25 MiB' "$TEST_ROOT/oversize.err"
run_expect_failure disallowed "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.svg"
assert_contains 'Unsupported artifact type' "$TEST_ROOT/disallowed.err"
run_expect_failure mismatch env FAKE_MIME=image/jpeg "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_contains 'does not match' "$TEST_ROOT/mismatch.err"
assert_not_contains "$TEST_ROOT/evidence.png" "$TEST_ROOT/mismatch.err"

run_expect_failure invalid-json env FAKE_RESPONSE_KIND=malformed "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_upload_unknown invalid-json
assert_not_contains '{not-json' "$TEST_ROOT/invalid-json.err"
run_expect_failure missing-url env FAKE_RESPONSE_KIND=missing-url "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_upload_unknown missing-url
run_expect_failure lookalike env FAKE_ASSET_URL=https://github.com.evil.example/user-attachments/assets/id "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_upload_unknown lookalike
run_expect_failure query-url env FAKE_ASSET_URL='https://github.com/user-attachments/assets/id?token=bad' "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_upload_unknown query-url
run_expect_failure nested-url env FAKE_ASSET_URL=https://github.com/user-attachments/assets/id/extra "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_upload_unknown nested-url
run_expect_failure punctuation-url env FAKE_ASSET_URL=https://github.com/user-attachments/assets/id.with-dot "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_upload_unknown punctuation-url
run_expect_failure percent-url env FAKE_ASSET_URL=https://github.com/user-attachments/assets/id%29bad "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_upload_unknown percent-url
run_expect_failure markdown-url env 'FAKE_ASSET_URL=https://github.com/user-attachments/assets/id)![x]' "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_upload_unknown markdown-url

run_expect_failure non-201 env FAKE_UPLOAD_STATUS=500 "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_upload_unknown non-201
run_expect_failure redirect env FAKE_UPLOAD_STATUS=302 "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_upload_unknown redirect
run_expect_failure timeout env FAKE_CURL_MODE=transport "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_upload_unknown timeout
assert_not_contains 'simulated path' "$TEST_ROOT/timeout.err"
run_expect_failure oversize-response env FAKE_CURL_MODE=oversize "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_upload_unknown oversize-response
: > "$JQ_LOG"
run_expect_failure oversize-zero-response env FAKE_CURL_MODE=oversize-zero "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_upload_unknown oversize-zero-response
[[ ! -s "$TEST_ROOT/oversize-zero-response.out" ]] || fail 'oversized response must not emit a success URL'
assert_not_contains '-er' "$JQ_LOG"

run_expect_failure bad-id env FAKE_REPOSITORY_ID=not-numeric "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.png"
assert_contains 'canonical repository does not exactly match' "$TEST_ROOT/bad-id.err"

bash -x "$HELPER" --authorized-upload example-owner/example-repo "$TEST_ROOT/evidence.jpg" > "$TEST_ROOT/xtrace.out" 2> "$TEST_ROOT/xtrace.err"
assert_not_contains 'fake_token_not_for_production' "$TEST_ROOT/xtrace.out"
assert_not_contains 'fake_token_not_for_production' "$TEST_ROOT/xtrace.err"

assert_temp_cleaned
if grep -Fq -- 'fake_token_not_for_production' "$TEST_ROOT"/*.out "$TEST_ROOT"/*.err "$TEST_ROOT"/*.log; then
  fail 'fake token leaked into runtime output or logs'
fi

printf '%s\n' 'upload helper offline tests passed'
