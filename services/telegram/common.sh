#!/usr/bin/env bash
set -euo pipefail

declare -gA TELEGRAM_CONFIG_MAP=()
declare -ga TELEGRAM_ALLOWED_CHAT_IDS=()
declare -ga TELEGRAM_ALLOWED_UPDATES=()

declare -g TELEGRAM_API_BASE_URL=""
declare -g TELEGRAM_BOT_TOKEN=""
declare -g TELEGRAM_TIMEOUT_SECONDS=""
declare -g TELEGRAM_DEFAULT_PARSE_MODE=""
declare -g TELEGRAM_TLS_CA_CERT_PATH=""
declare -g TELEGRAM_TLS_INSECURE_SKIP_VERIFY="false"


telegram_script_dir() {
  cd "$(dirname "${BASH_SOURCE[0]}")" && pwd
}


telegram_default_config_path() {
  printf '%s\n' "${TELEGRAM_LOCAL_CONFIG:-$(telegram_script_dir)/config.local.yaml}"
}


telegram_config_error() {
  printf '%s\n' "$*" >&2
  return 2
}


telegram_canonical_chat_id() {
  local value="${1:-}"
  if [[ -z "$value" ]]; then
    printf '\n'
    return
  fi
  if [[ "$value" == @* ]]; then
    printf '%s\n' "${value,,}"
    return
  fi
  if [[ "$value" =~ ^-?[0-9]+$ ]]; then
    jq -nr --arg value "$value" '$value | tonumber | tostring'
    return
  fi
  printf '%s\n' "$value"
}


telegram_chat_matches() {
  [[ "$(telegram_canonical_chat_id "$1")" == "$(telegram_canonical_chat_id "$2")" ]]
}


telegram_parse_bool() {
  local raw="${1:-}"
  local lowered="${raw,,}"
  case "$lowered" in
    "" ) printf 'false\n' ;;
    true|yes|1|on) printf 'true\n' ;;
    false|no|0|off) printf 'false\n' ;;
    * ) return 1 ;;
  esac
}


telegram_parse_simple_yaml() {
  local config_path="$1"
  awk '
    function trim(s) {
      gsub(/^[ \t]+|[ \t]+$/, "", s)
      return s
    }

    function strip_comment(s,    i, ch, out, in_single, in_double) {
      out = ""
      in_single = 0
      in_double = 0
      for (i = 1; i <= length(s); i++) {
        ch = substr(s, i, 1)
        if (ch == "'"'"'" && !in_double) {
          in_single = !in_single
        } else if (ch == "\"" && !in_single) {
          in_double = !in_double
        } else if (ch == "#" && !in_single && !in_double) {
          break
        }
        out = out ch
      }
      sub(/[ \t]+$/, "", out)
      return out
    }

    function unquote(s,    q) {
      s = trim(s)
      if (length(s) >= 2) {
        q = substr(s, 1, 1)
        if ((q == "\"" || q == "'"'"'") && substr(s, length(s), 1) == q) {
          s = substr(s, 2, length(s) - 2)
          if (q == "\"") {
            gsub(/\\"/, "\"", s)
            gsub(/\\\\/, "\\", s)
          } else {
            gsub(/'\'''\''/, "'\''", s)
          }
        }
      }
      return s
    }

    function join_path(level,    i, result) {
      result = keys[1]
      for (i = 2; i <= level; i++) {
        result = result "." keys[i]
      }
      return result
    }

    function next_kind(start_idx, current_indent,    j, line, indent, trimmed) {
      for (j = start_idx + 1; j <= line_count; j++) {
        line = strip_comment(lines[j])
        if (line ~ /^[ \t]*$/) {
          continue
        }
        indent = match(line, /[^ ]/) - 1
        if (indent <= current_indent) {
          return "scalar"
        }
        trimmed = substr(line, indent + 1)
        if (trimmed ~ /^- /) {
          return "list"
        }
        return "map"
      }
      return "scalar"
    }

    {
      lines[++line_count] = $0
    }

    END {
      depth = 0
      for (i = 1; i <= line_count; i++) {
        line = strip_comment(lines[i])
        if (line ~ /^[ \t]*$/) {
          continue
        }

        indent = match(line, /[^ ]/) - 1
        trimmed = substr(line, indent + 1)

        while (depth > 0 && indent <= indents[depth]) {
          depth--
        }

        if (trimmed ~ /^- /) {
          key = join_path(depth)
          value = unquote(substr(trimmed, 3))
          list_indexes[key]++
          printf "%s[%d]=%s\n", key, list_indexes[key] - 1, value
          continue
        }

        separator = index(trimmed, ":")
        if (separator == 0) {
          continue
        }

        key = trim(substr(trimmed, 1, separator - 1))
        value = trim(substr(trimmed, separator + 1))
        keys[depth + 1] = key
        indents[depth + 1] = indent
        depth++

        full_key = join_path(depth)
        if (value != "") {
          printf "%s=%s\n", full_key, unquote(value)
          continue
        }

        if (next_kind(i, indent) == "scalar") {
          printf "%s=\n", full_key
        }
      }
    }
  ' "$config_path"
}


telegram_load_config() {
  local config_path="$1"
  local key value
  local insecure_raw ca_cert_path_env bot_token_env

  if [[ ! -f "$config_path" ]]; then
    telegram_config_error "ERROR: Cannot read config file: $config_path"
    return 2
  fi

  TELEGRAM_CONFIG_MAP=()
  TELEGRAM_ALLOWED_CHAT_IDS=()
  TELEGRAM_ALLOWED_UPDATES=()

  while IFS='=' read -r key value; do
    case "$key" in
      telegram.allowed_chat_ids\[*\])
        [[ -n "$value" ]] && TELEGRAM_ALLOWED_CHAT_IDS+=("$value")
        ;;
      telegram.allowed_updates\[*\])
        [[ -n "$value" ]] && TELEGRAM_ALLOWED_UPDATES+=("$value")
        ;;
      *)
        TELEGRAM_CONFIG_MAP["$key"]="$value"
        ;;
    esac
  done < <(telegram_parse_simple_yaml "$config_path")

  TELEGRAM_API_BASE_URL="${TELEGRAM_CONFIG_MAP[telegram.api_base_url]-https://api.telegram.org}"
  if [[ "${TELEGRAM_API_BASE_URL,,}" != https://* ]]; then
    telegram_config_error "ERROR: telegram.api_base_url must use https://"
    return 2
  fi

  TELEGRAM_BOT_TOKEN="${TELEGRAM_CONFIG_MAP[telegram.bot_token]-}"
  if [[ -z "$TELEGRAM_BOT_TOKEN" ]]; then
    bot_token_env="${TELEGRAM_CONFIG_MAP[telegram.bot_token_env]-}"
    if [[ -n "$bot_token_env" ]]; then
      TELEGRAM_BOT_TOKEN="${!bot_token_env-}"
      if [[ -z "$TELEGRAM_BOT_TOKEN" ]]; then
        telegram_config_error "ERROR: Environment variable $bot_token_env referenced by telegram.bot_token_env is not set"
        return 2
      fi
    fi
  fi
  if [[ -z "$TELEGRAM_BOT_TOKEN" ]]; then
    telegram_config_error "ERROR: Missing telegram.bot_token or telegram.bot_token_env in config.local.yaml"
    return 2
  fi

  TELEGRAM_TIMEOUT_SECONDS="${TELEGRAM_CONFIG_MAP[telegram.timeout_seconds]-30}"
  if [[ ! "$TELEGRAM_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]]; then
    telegram_config_error "ERROR: telegram.timeout_seconds must be an integer"
    return 2
  fi

  TELEGRAM_DEFAULT_PARSE_MODE="${TELEGRAM_CONFIG_MAP[telegram.default_parse_mode]-}"

  TELEGRAM_TLS_CA_CERT_PATH="${TELEGRAM_CONFIG_MAP[telegram.tls.ca_cert_path]-}"
  ca_cert_path_env="${TELEGRAM_CONFIG_MAP[telegram.tls.ca_cert_path_env]-}"
  if [[ -z "$TELEGRAM_TLS_CA_CERT_PATH" && -n "$ca_cert_path_env" ]]; then
    TELEGRAM_TLS_CA_CERT_PATH="${!ca_cert_path_env-}"
    if [[ -z "$TELEGRAM_TLS_CA_CERT_PATH" ]]; then
      telegram_config_error "ERROR: Environment variable $ca_cert_path_env referenced by telegram.tls.ca_cert_path_env is not set"
      return 2
    fi
  fi

  insecure_raw="${TELEGRAM_CONFIG_MAP[telegram.tls.insecure_skip_verify]-false}"
  if ! TELEGRAM_TLS_INSECURE_SKIP_VERIFY="$(telegram_parse_bool "$insecure_raw")"; then
    telegram_config_error "ERROR: telegram.tls.insecure_skip_verify must be a boolean"
    return 2
  fi
  if [[ "$TELEGRAM_TLS_INSECURE_SKIP_VERIFY" == "true" && -n "$TELEGRAM_TLS_CA_CERT_PATH" ]]; then
    telegram_config_error "ERROR: Configure either telegram.tls.insecure_skip_verify or a CA cert path, not both"
    return 2
  fi
  if [[ -n "$TELEGRAM_TLS_CA_CERT_PATH" && ! -f "$TELEGRAM_TLS_CA_CERT_PATH" ]]; then
    telegram_config_error "ERROR: CA certificate file does not exist: $TELEGRAM_TLS_CA_CERT_PATH"
    return 2
  fi

  if [[ "${#TELEGRAM_ALLOWED_UPDATES[@]}" -eq 0 ]]; then
    TELEGRAM_ALLOWED_UPDATES=("message")
  fi
}


telegram_validate_chat_id() {
  local chat_id="$1"
  local allowed
  if [[ "${#TELEGRAM_ALLOWED_CHAT_IDS[@]}" -eq 0 ]]; then
    return 0
  fi

  for allowed in "${TELEGRAM_ALLOWED_CHAT_IDS[@]}"; do
    if telegram_chat_matches "$chat_id" "$allowed"; then
      return 0
    fi
  done

  printf 'ERROR: Chat ID is not allowed by telegram.allowed_chat_ids: %s\n' "$chat_id" >&2
  return 2
}


telegram_build_url() {
  local method_name="$1"
  printf '%s/bot%s/%s\n' "${TELEGRAM_API_BASE_URL%/}" "$TELEGRAM_BOT_TOKEN" "$method_name"
}


telegram_curl_request() {
  local method="$1"
  local method_name="$2"
  local client_timeout="$3"
  shift 3

  local response_file http_code curl_rc body
  local curl_args=(
    curl
    --silent
    --show-error
    --location
    --proto '=https'
    --proto-redir '=https'
    --connect-timeout "$client_timeout"
    --max-time "$client_timeout"
    -H 'Content-Type: application/json'
    -X "$method"
  )
  if [[ "$TELEGRAM_TLS_INSECURE_SKIP_VERIFY" == "true" ]]; then
    curl_args+=(-k)
  fi
  if [[ -n "$TELEGRAM_TLS_CA_CERT_PATH" ]]; then
    curl_args+=(--cacert "$TELEGRAM_TLS_CA_CERT_PATH")
  fi
  curl_args+=("$@" "$(telegram_build_url "$method_name")")

  response_file="$(mktemp)"
  http_code="$("${curl_args[@]}" -o "$response_file" -w '%{http_code}')" || curl_rc=$?
  if [[ -n "${curl_rc:-}" ]]; then
    if [[ -s "$response_file" ]]; then
      cat "$response_file" >&2
    fi
    rm -f "$response_file"
    return "$curl_rc"
  fi

  if [[ ! "$http_code" =~ ^2 ]]; then
    body="$(tr '\n' ' ' < "$response_file" | sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//')"
    printf 'ERROR: HTTP %s: %s\n' "$http_code" "${body:-request failed}" >&2
    rm -f "$response_file"
    return 1
  fi

  cat "$response_file"
  rm -f "$response_file"
}


telegram_api_call() {
  local method_name="$1"
  local payload="$2"
  local client_timeout="$3"
  local response

  response="$(telegram_curl_request POST "$method_name" "$client_timeout" --data "$payload")" || return 1
  if ! printf '%s\n' "$response" | jq -e '.ok == true' >/dev/null; then
    printf 'ERROR: Telegram API error: %s\n' "$(printf '%s\n' "$response" | jq -r '.description // "request failed"')" >&2
    return 1
  fi
  printf '%s\n' "$response"
}


telegram_send_message_request() {
  local chat_id="$1"
  local message="$2"
  local parse_mode="${3:-}"
  local parse_mode_to_use payload

  telegram_validate_chat_id "$chat_id" || return $?
  parse_mode_to_use="$parse_mode"
  if [[ -z "$parse_mode_to_use" ]]; then
    parse_mode_to_use="$TELEGRAM_DEFAULT_PARSE_MODE"
  fi

  payload="$(
    jq -cn \
      --arg chat_id "$chat_id" \
      --arg text "$message" \
      --arg parse_mode "$parse_mode_to_use" \
      '{
        chat_id: $chat_id,
        text: $text
      } + (if $parse_mode != "" then {parse_mode: $parse_mode} else {} end)'
  )"

  telegram_api_call "sendMessage" "$payload" "$TELEGRAM_TIMEOUT_SECONDS"
}


telegram_get_updates_request() {
  local offset="${1:-}"
  local limit="${2:-}"
  local timeout="${3:-}"
  local client_timeout="$TELEGRAM_TIMEOUT_SECONDS"
  local allowed_updates_json payload response

  if [[ -n "$timeout" && "$timeout" =~ ^[0-9]+$ ]]; then
    if [[ "$((timeout + 5))" -gt "$client_timeout" ]]; then
      client_timeout="$((timeout + 5))"
    fi
  fi

  allowed_updates_json="$(printf '%s\n' "${TELEGRAM_ALLOWED_UPDATES[@]}" | jq -Rsc 'split("\n") | map(select(length > 0))')"
  payload="$(
    jq -cn \
      --arg offset "$offset" \
      --arg limit "$limit" \
      --arg timeout "$timeout" \
      --argjson allowed_updates "$allowed_updates_json" \
      '(
        (if $offset != "" then {offset: ($offset | tonumber)} else {} end) +
        (if $limit != "" then {limit: ($limit | tonumber)} else {} end) +
        (if $timeout != "" then {timeout: ($timeout | tonumber)} else {} end) +
        (if ($allowed_updates | length) > 0 then {allowed_updates: $allowed_updates} else {} end)
      )'
  )"

  response="$(telegram_api_call "getUpdates" "$payload" "$client_timeout")" || return 1
  printf '%s\n' "$response" | jq -c '
    def normalize_update:
      . as $update |
      (
        if .message? then ["message", .message]
        elif .edited_message? then ["edited_message", .edited_message]
        elif .channel_post? then ["channel_post", .channel_post]
        elif .edited_channel_post? then ["edited_channel_post", .edited_channel_post]
        else [null, {}]
        end
      ) as $pair |
      {
        update_id: ($update.update_id // null),
        type: ($pair[0]),
        message_id: ($pair[1].message_id // null),
        chat_id: ($pair[1].chat.id // null),
        chat_type: ($pair[1].chat.type // null),
        chat_title: ($pair[1].chat.title // $pair[1].chat.username // $pair[1].chat.first_name // null),
        from_id: ($pair[1].from.id // null),
        from_username: ($pair[1].from.username // null),
        from_first_name: ($pair[1].from.first_name // null),
        text: ($pair[1].text // $pair[1].caption // ""),
        date: ($pair[1].date // null),
        raw: $update
      };

    .result as $result |
    {
      updates: ($result | map(normalize_update)),
      next_offset: (if ($result | length) > 0 then (($result | map(.update_id // 0) | max) + 1) else null end)
    }
  '
}


telegram_get_me_request() {
  local response
  response="$(telegram_api_call "getMe" '{}' "$TELEGRAM_TIMEOUT_SECONDS")" || return 1
  printf '%s\n' "$response"
}


telegram_update_fingerprint() {
  jq -rc '
    if (.update_id != null) then
      "update:" + (.update_id | tostring)
    else
      ((.raw // .) | tojson)
    end
  '
}
