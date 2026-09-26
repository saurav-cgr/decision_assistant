# Redact secret values from `docker compose config` output for `make config`.
# Handles cases the earlier sed-only version missed:
#   1. Multi-line YAML block-scalar secrets (continuation lines indented
#      deeper than the key are skipped, not just the key's own line).
#   2. Connection-string userinfo (user, password, or both): everything
#      between "://" and the LAST "@" on the line is redacted. `u:pa/ss@host`
#      and `host/path@x` are textually indistinguishable (checker V42), so a
#      password containing "/" is treated as higher risk than a path
#      containing "@" — this deliberately over-redacts the rare, non-secret
#      `http://host/path@x` shape (not present in `compose.yaml` today) in
#      exchange for never leaking a "/"-containing password (base64-generated
#      secrets commonly contain one). Also covers an empty username
#      (`scheme://:pass@host`), a username containing "@"
#      (`scheme://user@corp:pass@host`), a space in the password, and an IPv6
#      host.
#   3. Secret-shaped keys containing "." or "-", not only "_".
BEGIN { skip = 0; indent = -1 }
{
    line = $0
    tmp = line
    gsub(/[^ ].*/, "", tmp)
    cur_indent = length(tmp)

    if (skip == 1) {
        if (line ~ /^[[:space:]]*$/ || cur_indent > indent) {
            next
        }
        skip = 0
    }

    upline = toupper(line)
    if (upline ~ /^[[:space:]]*[A-Z0-9_.-]*(SECRET|PASSWORD|API_KEY|TOKEN)[A-Z0-9_.-]*:/) {
        n = index(line, ":")
        printf "%s REDACTED\n", substr(line, 1, n)
        skip = 1
        indent = cur_indent
        next
    }

    if (line ~ /:\/\/.*@/) {
        sub(/:\/\/.*@/, "://REDACTED@", line)
    }

    print line
}
