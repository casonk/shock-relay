#!/usr/bin/env bash
set -euo pipefail

declare -gA TWILIO_CONFIG_MAP=()
declare -ga TWILIO_ALLOWED_RECIPIENTS=()

declare -g TWILIO_API_BASE_URL=""
declare -g TWILIO_ACCOUNT_SID=""
declare -g TWILIO_AUTH_TOKEN=""
declare -g TWILIO_FROM_PHONE=""
declare -g TWILIO_TIMEOUT_SECONDS=""
declare -g TWILIO_TLS_CA_CERT_PATH=""
declare -g TWILIO_TLS_INSECURE_SKIP_VERIFY="false"


twilio_script_dir() {
  cd "$(dirname "${BASH_SOURCE[0]}")" && pwd
}


twilio_default_config_path() {
  printf '%s\n' "${TWILIO_LOCAL_CONFIG:-$(twilio_script_dir)/config.local.yaml}"
}


twilio_config_error() {
  printf '%s\n' "$*" >&2
  return 2
}


twilio_canonical_phone() {
  printf '%s\n' "${1:-}" | tr -cd '0-9+'
}


twilio_phone_matches() {
  [[ "$(twilio_canonical_phone "$1")" == "$(twilio_canonical_phone "$2")" ]]
}


twilio_split_values() {
  printf '%s\n' "$1" | tr ',' '\n' | sed '/^[[:space:]]*$/d'
}


twilio_parse_bool() {
  local raw="${1:-}"
  local lowered="${raw,,}"
  case "$lowered" in
    "" ) printf 'false\n' ;;
    true|yes|1|on) printf 'true\n' ;;
    false|no|0|off) printf 'false\n' ;;
    * ) return 1 ;;
  esac
}


twilio_parse_simple_yaml() {
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


twilio_load_config() {
  local config_path="$1"
  local key value env_name env_value
  local insecure_raw ca_cert_path_env
  local account_sid_env auth_token_env from_phone_env
  local sms_enabled

  if [[ ! -f "$config_path" ]]; then
    twilio_config_error "ERROR: Cannot read config file: $config_path"
    return 2
  fi

  TWILIO_CONFIG_MAP=()
  TWILIO_ALLOWED_RECIPIENTS=()

  while IFS='=' read -r key value; do
    case "$key" in
      twilio.sms.allowed_recipients\[*\])
        [[ -n "$value" ]] && TWILIO_ALLOWED_RECIPIENTS+=("$value")
        ;;
      twilio.sms.allowed_recipient_envs\[*\])
        env_name="$value"
        env_value="${!env_name-}"
        if [[ -z "$env_value" ]]; then
          twilio_config_error "ERROR: Environment variable $env_name referenced by twilio.sms.allowed_recipient_envs is not set"
          return 2
        fi
        while IFS= read -r value; do
          [[ -n "$value" ]] && TWILIO_ALLOWED_RECIPIENTS+=("$value")
        done < <(twilio_split_values "$env_value")
        ;;
      *)
        TWILIO_CONFIG_MAP["$key"]="$value"
        ;;
    esac
  done < <(twilio_parse_simple_yaml "$config_path")

  TWILIO_API_BASE_URL="${TWILIO_CONFIG_MAP[twilio.api_base_url]-https://api.twilio.com}"
  if [[ "${TWILIO_API_BASE_URL,,}" != https://* ]]; then
    twilio_config_error "ERROR: twilio.api_base_url must use https://"
    return 2
  fi

  TWILIO_ACCOUNT_SID="${TWILIO_CONFIG_MAP[twilio.account_sid]-}"
  account_sid_env="${TWILIO_CONFIG_MAP[twilio.account_sid_env]-}"
  if [[ -z "$TWILIO_ACCOUNT_SID" && -n "$account_sid_env" ]]; then
    TWILIO_ACCOUNT_SID="${!account_sid_env-}"
    if [[ -z "$TWILIO_ACCOUNT_SID" ]]; then
      twilio_config_error "ERROR: Environment variable $account_sid_env referenced by twilio.account_sid_env is not set"
      return 2
    fi
  fi

  TWILIO_AUTH_TOKEN="${TWILIO_CONFIG_MAP[twilio.auth_token]-}"
  auth_token_env="${TWILIO_CONFIG_MAP[twilio.auth_token_env]-}"
  if [[ -z "$TWILIO_AUTH_TOKEN" && -n "$auth_token_env" ]]; then
    TWILIO_AUTH_TOKEN="${!auth_token_env-}"
    if [[ -z "$TWILIO_AUTH_TOKEN" ]]; then
      twilio_config_error "ERROR: Environment variable $auth_token_env referenced by twilio.auth_token_env is not set"
      return 2
    fi
  fi

  TWILIO_FROM_PHONE="${TWILIO_CONFIG_MAP[twilio.from_phone]-}"
  from_phone_env="${TWILIO_CONFIG_MAP[twilio.from_phone_env]-}"
  if [[ -z "$TWILIO_FROM_PHONE" && -n "$from_phone_env" ]]; then
    TWILIO_FROM_PHONE="${!from_phone_env-}"
    if [[ -z "$TWILIO_FROM_PHONE" ]]; then
      twilio_config_error "ERROR: Environment variable $from_phone_env referenced by twilio.from_phone_env is not set"
      return 2
    fi
  fi

  if [[ -z "$TWILIO_ACCOUNT_SID" ]]; then
    twilio_config_error "ERROR: Missing twilio.account_sid or twilio.account_sid_env in config.local.yaml"
    return 2
  fi
  if [[ -z "$TWILIO_AUTH_TOKEN" ]]; then
    twilio_config_error "ERROR: Missing twilio.auth_token or twilio.auth_token_env in config.local.yaml"
    return 2
  fi
  if [[ -z "$TWILIO_FROM_PHONE" ]]; then
    twilio_config_error "ERROR: Missing twilio.from_phone or twilio.from_phone_env in config.local.yaml"
    return 2
  fi

  TWILIO_TIMEOUT_SECONDS="${TWILIO_CONFIG_MAP[twilio.timeout_seconds]-30}"
  if [[ ! "$TWILIO_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]]; then
    twilio_config_error "ERROR: twilio.timeout_seconds must be an integer"
    return 2
  fi

  sms_enabled="${TWILIO_CONFIG_MAP[twilio.sms.enabled]-true}"
  if ! sms_enabled="$(twilio_parse_bool "$sms_enabled")"; then
    twilio_config_error "ERROR: twilio.sms.enabled must be a boolean"
    return 2
  fi
  if [[ "$sms_enabled" != "true" ]]; then
    twilio_config_error "ERROR: twilio.sms.enabled must be true to use the SMS scripts"
    return 2
  fi

  TWILIO_TLS_CA_CERT_PATH="${TWILIO_CONFIG_MAP[twilio.tls.ca_cert_path]-}"
  ca_cert_path_env="${TWILIO_CONFIG_MAP[twilio.tls.ca_cert_path_env]-}"
  if [[ -z "$TWILIO_TLS_CA_CERT_PATH" && -n "$ca_cert_path_env" ]]; then
    TWILIO_TLS_CA_CERT_PATH="${!ca_cert_path_env-}"
    if [[ -z "$TWILIO_TLS_CA_CERT_PATH" ]]; then
      twilio_config_error "ERROR: Environment variable $ca_cert_path_env referenced by twilio.tls.ca_cert_path_env is not set"
      return 2
    fi
  fi

  insecure_raw="${TWILIO_CONFIG_MAP[twilio.tls.insecure_skip_verify]-false}"
  if ! TWILIO_TLS_INSECURE_SKIP_VERIFY="$(twilio_parse_bool "$insecure_raw")"; then
    twilio_config_error "ERROR: twilio.tls.insecure_skip_verify must be a boolean"
    return 2
  fi
  if [[ "$TWILIO_TLS_INSECURE_SKIP_VERIFY" == "true" && -n "$TWILIO_TLS_CA_CERT_PATH" ]]; then
    twilio_config_error "ERROR: Configure either twilio.tls.insecure_skip_verify or a CA cert path, not both"
    return 2
  fi
  if [[ -n "$TWILIO_TLS_CA_CERT_PATH" && ! -f "$TWILIO_TLS_CA_CERT_PATH" ]]; then
    twilio_config_error "ERROR: CA certificate file does not exist: $TWILIO_TLS_CA_CERT_PATH"
    return 2
  fi
}


twilio_validate_recipient() {
  local recipient="$1"
  local allowed

  if [[ "${#TWILIO_ALLOWED_RECIPIENTS[@]}" -eq 0 ]]; then
    return 0
  fi

  for allowed in "${TWILIO_ALLOWED_RECIPIENTS[@]}"; do
    if twilio_phone_matches "$recipient" "$allowed"; then
      return 0
    fi
  done

  printf 'ERROR: Recipient is not allowed by twilio.sms.allowed_recipients: %s\n' "$recipient" >&2
  return 2
}


twilio_build_url() {
  printf '%s/2010-04-01/Accounts/%s/Messages.json\n' "${TWILIO_API_BASE_URL%/}" "$TWILIO_ACCOUNT_SID"
}


twilio_curl_request() {
  local method="$1"
  shift

  local response_file http_code curl_rc body
  local curl_args=(
    curl
    --silent
    --show-error
    --location
    --proto '=https'
    --proto-redir '=https'
    --connect-timeout "$TWILIO_TIMEOUT_SECONDS"
    --max-time "$TWILIO_TIMEOUT_SECONDS"
    --user "$TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN"
    -X "$method"
  )
  if [[ "$TWILIO_TLS_INSECURE_SKIP_VERIFY" == "true" ]]; then
    curl_args+=(-k)
  fi
  if [[ -n "$TWILIO_TLS_CA_CERT_PATH" ]]; then
    curl_args+=(--cacert "$TWILIO_TLS_CA_CERT_PATH")
  fi
  curl_args+=("$@" "$(twilio_build_url)")

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


twilio_send_sms_request() {
  local to_number="$1"
  local message="$2"

  twilio_validate_recipient "$to_number" || return $?
  twilio_curl_request \
    POST \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode "From=$TWILIO_FROM_PHONE" \
    --data-urlencode "To=$to_number" \
    --data-urlencode "Body=$message"
}


twilio_list_messages_request() {
  local to_number="${1:-}"
  local from_number="${2:-}"
  local page_size="${3:-}"
  local response
  local args=()

  [[ -n "$to_number" ]] && args+=(--data-urlencode "To=$to_number")
  [[ -n "$from_number" ]] && args+=(--data-urlencode "From=$from_number")
  [[ -n "$page_size" ]] && args+=(--data-urlencode "PageSize=$page_size")

  response="$(
    twilio_curl_request \
      GET \
      --get \
      "${args[@]}"
  )" || return 1

  printf '%s\n' "$response" | jq -c '
    .messages as $messages |
    {
      messages: ($messages | map({
        sid: (.sid // ""),
        direction: (.direction // ""),
        from: (.from // ""),
        to: (.to // ""),
        body: (.body // ""),
        status: (.status // ""),
        date_created: (.date_created // ""),
        date_sent: (.date_sent // ""),
        raw: .
      }))
    }
  '
}


twilio_message_fingerprint() {
  jq -rc '
    if (.sid != null and (.sid | tostring | length) > 0) then
      "sid:" + (.sid | tostring)
    else
      ((.raw // .) | tojson)
    end
  '
}
