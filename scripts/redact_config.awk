# Redact secret values from `docker compose config` output for `make config`.
# Handles cases the earlier sed-only version missed:
#   1. Multi-line YAML block-scalar secrets (continuation lines indented
#      deeper than the key are skipped, not just the key's own line).
#   2. Connection-string userinfo (user, password, or both). The authority is
#      everything after "://" up to the LAST "/" on the line (if any); within
#      that authority, everything up to its LAST "@" is userinfo and gets
#      redacted. This covers an empty username (`scheme://:pass@host`), a
#      username containing "@" (`scheme://user@corp:pass@host`), a password
#      containing a literal "/" or a space (common in base64-generated
#      secrets, which would otherwise be mistaken for a path separator), and
#      an IPv6 host — while still leaving a bare "@" in a URL path alone
#      (`http://host/path@x` has no userinfo and is not touched).
#   3. Secret-shaped keys containing "." or "-", not only "_".
function lastpos(s, c,    p, r, i) {
    r = 0
    p = 0
    while ((i = index(substr(s, p + 1), c)) > 0) {
        p = p + i
        r = p
    }
    return r
}
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

    p = index(line, "://")
    if (p > 0) {
        rest = substr(line, p + 3)
        slashpos = lastpos(rest, "/")
        limit = (slashpos > 0) ? slashpos - 1 : length(rest)
        atpos = lastpos(substr(rest, 1, limit), "@")
        if (atpos > 0) {
            line = substr(line, 1, p + 2) "REDACTED@" substr(rest, atpos + 1)
        }
    }

    print line
}
