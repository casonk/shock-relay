#!/usr/bin/env bash
set -euo pipefail

declare -gA WHATSAPP_CONFIG_MAP=()
declare -ga WHATSAPP_ALLOWED_RECIPIENTS=()
declare -ga WHATSAPP_ALLOWED_RECIPIENT_ENVS=()
declare -ga WHATSAPP_CURL_HEADERS=()
declare -ga WHATSAPP_CURL_AUTH_ARGS=()
declare -ga WHATSAPP_CURL_BASE_ARGS=()

declare -g WHATSAPP_BASE_URL=""
declare -g WHATSAPP_SEND_PATH=""
declare -g WHATSAPP_RECEIVE_PATH=""
declare -g WHATSAPP_TIMEOUT_SECONDS=""
declare -g WHATSAPP_SENDER=""
declare -g WHATSAPP_TLS_CA_CERT_PATH=""
declare -g WHATSAPP_TLS_INSECURE_SKIP_VERIFY="false"


whatsapp_script_dir() {
  cd "$(dirname "${BASH_SOURCE[0]}")" && pwd
}


whatsapp_default_config_path() {
  printf '%s\n' "${WHATSAPP_LOCAL_CONFIG:-$(whatsapp_script_dir)/config.local.yaml}"
}


whatsapp_config_error() {
  printf '%s\n' "$*" >&2
  return 2
}


whatsapp_canonical_party() {
  local value="${1,,}"
  value="${value#whatsapp:}"
  value="${value#tel:}"
  if [[ "$value" =~ ^[+()[:space:][:digit:]-]+$ ]]; then
    value="$(printf '%s' "$value" | tr -cd '0-9+')"
  else
    value="$(printf '%s' "$value" | tr -d '[:space:]')"
  fi
  printf '%s\n' "$value"
}


whatsapp_party_matches() {
  [[ "$(whatsapp_canonical_party "$1")" == "$(whatsapp_canonical_party "$2")" ]]
}


whatsapp_split_values() {
  printf '%s\n' "$1" | tr ',' '\n' | sed '/^[[:space:]]*$/d'
}


whatsapp_parse_bool() {
  local raw="${1:-}"
  local lowered="${raw,,}"
  case "$lowered" in
    "" ) printf 'false\n' ;;
    true|yes|1|on) printf 'true\n' ;;
    false|no|0|off) printf 'false\n' ;;
    * ) return 1 ;;
  esac
}


whatsapp_parse_simple_yaml() {
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


whatsapp_validate_recipient() {
  local recipient="$1"
  local allowed

  if [[ "${#WHATSAPP_ALLOWED_RECIPIENTS[@]}" -eq 0 ]]; then
    return 0
  fi

  for allowed in "${WHATSAPP_ALLOWED_RECIPIENTS[@]}"; do
    if whatsapp_party_matches "$recipient" "$allowed"; then
      return 0
    fi
  done

  printf 'ERROR: Recipient is not allowed by messaging.allowed_recipients: %s\n' "$recipient" >&2
  return 2
}


whatsapp_load_config() {
  local config_path="$1"
  local key value env_name env_value
  local api_key_env api_key_header api_key
  local bearer_token_env bearer_token
  local basic_username_env basic_password_env basic_username basic_password
  local ca_cert_path_env insecure_raw

  if [[ ! -f "$config_path" ]]; then
    whatsapp_config_error "ERROR: Cannot read config file: $config_path"
    return 2
  fi

  WHATSAPP_CONFIG_MAP=()
  WHATSAPP_ALLOWED_RECIPIENTS=()
  WHATSAPP_ALLOWED_RECIPIENT_ENVS=()
  WHATSAPP_CURL_HEADERS=()
  WHATSAPP_CURL_AUTH_ARGS=()
  WHATSAPP_CURL_BASE_ARGS=()

  while IFS='=' read -r key value; do
    case "$key" in
      messaging.allowed_recipient_envs\[*\])
        [[ -n "$value" ]] && WHATSAPP_ALLOWED_RECIPIENT_ENVS+=("$value")
        ;;
      messaging.allowed_recipients\[*\])
        [[ -n "$value" ]] && WHATSAPP_ALLOWED_RECIPIENTS+=("$value")
        ;;
      *)
        WHATSAPP_CONFIG_MAP["$key"]="$value"
        ;;
    esac
  done < <(whatsapp_parse_simple_yaml "$config_path")

  WHATSAPP_BASE_URL="${WHATSAPP_CONFIG_MAP[http.base_url]-}"
  if [[ -z "$WHATSAPP_BASE_URL" ]]; then
    whatsapp_config_error "ERROR: Missing http.base_url in config.local.yaml"
    return 2
  fi
  if [[ "${WHATSAPP_BASE_URL,,}" != https://* ]]; then
    whatsapp_config_error "ERROR: http.base_url must use https://"
    return 2
  fi

  WHATSAPP_SEND_PATH="${WHATSAPP_CONFIG_MAP[http.send_path]-/messages}"
  WHATSAPP_RECEIVE_PATH="${WHATSAPP_CONFIG_MAP[http.receive_path]-/messages/inbound}"
  WHATSAPP_TIMEOUT_SECONDS="${WHATSAPP_CONFIG_MAP[http.timeout_seconds]-30}"
  if [[ ! "$WHATSAPP_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]]; then
    whatsapp_config_error "ERROR: http.timeout_seconds must be an integer"
    return 2
  fi

  WHATSAPP_TLS_CA_CERT_PATH="${WHATSAPP_CONFIG_MAP[http.tls.ca_cert_path]-}"
  ca_cert_path_env="${WHATSAPP_CONFIG_MAP[http.tls.ca_cert_path_env]-}"
  if [[ -z "$WHATSAPP_TLS_CA_CERT_PATH" && -n "$ca_cert_path_env" ]]; then
    WHATSAPP_TLS_CA_CERT_PATH="${!ca_cert_path_env-}"
    if [[ -z "$WHATSAPP_TLS_CA_CERT_PATH" ]]; then
      whatsapp_config_error "ERROR: Environment variable $ca_cert_path_env referenced by http.tls.ca_cert_path_env is not set"
      return 2
    fi
  fi

  insecure_raw="${WHATSAPP_CONFIG_MAP[http.tls.insecure_skip_verify]-false}"
  if ! WHATSAPP_TLS_INSECURE_SKIP_VERIFY="$(whatsapp_parse_bool "$insecure_raw")"; then
    whatsapp_config_error "ERROR: http.tls.insecure_skip_verify must be a boolean"
    return 2
  fi
  if [[ "$WHATSAPP_TLS_INSECURE_SKIP_VERIFY" == "true" && -n "$WHATSAPP_TLS_CA_CERT_PATH" ]]; then
    whatsapp_config_error "ERROR: Configure either http.tls.insecure_skip_verify or a CA cert path, not both"
    return 2
  fi
  if [[ -n "$WHATSAPP_TLS_CA_CERT_PATH" && ! -f "$WHATSAPP_TLS_CA_CERT_PATH" ]]; then
    whatsapp_config_error "ERROR: CA certificate file does not exist: $WHATSAPP_TLS_CA_CERT_PATH"
    return 2
  fi

  WHATSAPP_SENDER="${WHATSAPP_CONFIG_MAP[messaging.from]-}"
  if [[ -z "$WHATSAPP_SENDER" ]]; then
    env_name="${WHATSAPP_CONFIG_MAP[messaging.from_env]-}"
    if [[ -n "$env_name" ]]; then
      WHATSAPP_SENDER="${!env_name-}"
      if [[ -z "$WHATSAPP_SENDER" ]]; then
        whatsapp_config_error "ERROR: Environment variable $env_name referenced by messaging.from_env is not set"
        return 2
      fi
    fi
  fi
  if [[ -z "$WHATSAPP_SENDER" ]]; then
    whatsapp_config_error "ERROR: Missing messaging.from or messaging.from_env in config.local.yaml"
    return 2
  fi

  for env_name in "${WHATSAPP_ALLOWED_RECIPIENT_ENVS[@]}"; do
    env_value="${!env_name-}"
    if [[ -z "$env_value" ]]; then
      whatsapp_config_error "ERROR: Environment variable $env_name referenced by messaging.allowed_recipient_envs is not set"
      return 2
    fi
    while IFS= read -r value; do
      [[ -n "$value" ]] && WHATSAPP_ALLOWED_RECIPIENTS+=("$value")
    done < <(whatsapp_split_values "$env_value")
  done

  api_key_env="${WHATSAPP_CONFIG_MAP[http.api_key_env]-}"
  if [[ -n "$api_key_env" ]]; then
    api_key="${!api_key_env-}"
    if [[ -z "$api_key" ]]; then
      whatsapp_config_error "ERROR: Environment variable $api_key_env referenced by http.api_key_env is not set"
      return 2
    fi
    api_key_header="${WHATSAPP_CONFIG_MAP[http.api_key_header]-X-API-Key}"
    WHATSAPP_CURL_HEADERS+=(-H "$api_key_header: $api_key")
  fi

  bearer_token_env="${WHATSAPP_CONFIG_MAP[http.auth.bearer_token_env]-}"
  basic_username_env="${WHATSAPP_CONFIG_MAP[http.auth.basic_username_env]-}"
  basic_password_env="${WHATSAPP_CONFIG_MAP[http.auth.basic_password_env]-}"
  if [[ -n "$bearer_token_env" && ( -n "$basic_username_env" || -n "$basic_password_env" ) ]]; then
    whatsapp_config_error "ERROR: Configure either bearer auth or basic auth, not both"
    return 2
  fi

  if [[ -n "$bearer_token_env" ]]; then
    bearer_token="${!bearer_token_env-}"
    if [[ -z "$bearer_token" ]]; then
      whatsapp_config_error "ERROR: Environment variable $bearer_token_env referenced by http.auth.bearer_token_env is not set"
      return 2
    fi
    WHATSAPP_CURL_HEADERS+=(-H "Authorization: Bearer $bearer_token")
  elif [[ -n "$basic_username_env" || -n "$basic_password_env" ]]; then
    if [[ -z "$basic_username_env" || -z "$basic_password_env" ]]; then
      whatsapp_config_error "ERROR: http.auth.basic_username_env and http.auth.basic_password_env must be set together"
      return 2
    fi
    basic_username="${!basic_username_env-}"
    basic_password="${!basic_password_env-}"
    if [[ -z "$basic_username" ]]; then
      whatsapp_config_error "ERROR: Environment variable $basic_username_env referenced by http.auth.basic_username_env is not set"
      return 2
    fi
    if [[ -z "$basic_password" ]]; then
      whatsapp_config_error "ERROR: Environment variable $basic_password_env referenced by http.auth.basic_password_env is not set"
      return 2
    fi
    WHATSAPP_CURL_AUTH_ARGS=(--user "$basic_username:$basic_password")
  fi

  WHATSAPP_CURL_BASE_ARGS=(
    --silent
    --show-error
    --location
    --proto '=https'
    --proto-redir '=https'
    --connect-timeout "$WHATSAPP_TIMEOUT_SECONDS"
    --max-time "$WHATSAPP_TIMEOUT_SECONDS"
  )
  if [[ "$WHATSAPP_TLS_INSECURE_SKIP_VERIFY" == "true" ]]; then
    WHATSAPP_CURL_BASE_ARGS+=(-k)
  fi
  if [[ -n "$WHATSAPP_TLS_CA_CERT_PATH" ]]; then
    WHATSAPP_CURL_BASE_ARGS+=(--cacert "$WHATSAPP_TLS_CA_CERT_PATH")
  fi
}


whatsapp_build_url() {
  local path="$1"
  local base="${WHATSAPP_BASE_URL%/}"
  if [[ "$path" != /* ]]; then
    path="/$path"
  fi
  printf '%s%s\n' "$base" "$path"
}


whatsapp_curl_request() {
  local method="$1"
  local url="$2"
  shift 2

  local response_file http_code curl_rc body
  local curl_args=(curl "${WHATSAPP_CURL_BASE_ARGS[@]}" "${WHATSAPP_CURL_HEADERS[@]}" "${WHATSAPP_CURL_AUTH_ARGS[@]}" -X "$method")
  curl_args+=("$@" "$url")

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


whatsapp_send_message_request() {
  local recipient="$1"
  local message="$2"
  local payload

  whatsapp_validate_recipient "$recipient" || return $?
  payload="$(
    jq -cn \
      --arg from "$WHATSAPP_SENDER" \
      --arg to "$recipient" \
      --arg message "$message" \
      '{from: $from, to: $to, recipient: $to, message: $message, text: $message, type: "text"}'
  )"

  whatsapp_curl_request \
    POST \
    "$(whatsapp_build_url "$WHATSAPP_SEND_PATH")" \
    -H 'Content-Type: application/json' \
    --data "$payload"
}


whatsapp_normalize_receive_json() {
  jq -c '
    def scalar_string:
      if . == null then null
      elif type == "string" then .
      elif type == "number" or type == "boolean" then tostring
      else null
      end;

    def first_nonempty($obj; $keys):
      reduce $keys[] as $key (
        null;
        if . != null and . != "" then .
        else ($obj[$key]? | scalar_string)
        end
      );

    def looks_like_message($obj):
      ($obj.from? != null) or
      ($obj.to? != null) or
      ($obj.text? != null) or
      ($obj.message? != null) or
      ($obj.body? != null) or
      ($obj.content? != null);

    def normalize_message:
      . as $message |
      ($message.message? | if type == "object" then . else {} end) as $nested |
      {
        id: first_nonempty($message; ["id", "message_id", "sid", "wamid", "uuid"]),
        from: first_nonempty($message; ["from", "sender", "source", "author"]),
        to: first_nonempty($message; ["to", "recipient", "destination"]),
        text: (
          first_nonempty($message; ["text", "message", "body", "content"]) //
          first_nonempty($nested; ["text", "body", "message", "content"])
        ),
        timestamp: first_nonempty($message; ["timestamp", "created_at", "received_at", "date", "time"]),
        raw: $message
      };

    if type == "array" then
      {messages: map(normalize_message), next_cursor: null}
    elif type == "object" then
      if (.messages? | type) == "array" then
        {messages: (.messages | map(normalize_message)), next_cursor: (.next_cursor // .cursor // .next // null)}
      elif (.items? | type) == "array" then
        {messages: (.items | map(normalize_message)), next_cursor: (.next_cursor // .cursor // .next // null)}
      elif looks_like_message(.) then
        {messages: [normalize_message], next_cursor: (.next_cursor // .cursor // .next // null)}
      else
        error("Receive response did not contain a messages list")
      end
    else
      error("Receive response must be a JSON object or array")
    end
  '
}


whatsapp_receive_messages_request() {
  local limit="${1:-}"
  local timeout="${2:-}"
  local cursor="${3:-}"
  local since="${4:-}"
  local response
  local curl_args=()

  [[ -n "$limit" ]] && curl_args+=(--data-urlencode "limit=$limit")
  [[ -n "$timeout" ]] && curl_args+=(--data-urlencode "timeout=$timeout")
  [[ -n "$cursor" ]] && curl_args+=(--data-urlencode "cursor=$cursor")
  [[ -n "$since" ]] && curl_args+=(--data-urlencode "since=$since")
  [[ -n "$WHATSAPP_SENDER" ]] && curl_args+=(--data-urlencode "to=$WHATSAPP_SENDER")

  response="$(
    whatsapp_curl_request \
      GET \
      "$(whatsapp_build_url "$WHATSAPP_RECEIVE_PATH")" \
      --get \
      "${curl_args[@]}"
  )" || return 1

  printf '%s\n' "$response" | whatsapp_normalize_receive_json
}


whatsapp_message_fingerprint() {
  jq -rc '
    if (.id != null and (.id | tostring | length) > 0) then
      "id:" + (.id | tostring)
    else
      ((.raw // .) | tojson)
    end
  '
}
