# Redact secret values from `docker compose config` output for `make config`.
# Handles two cases the earlier sed-only version missed:
#   1. Multi-line YAML block-scalar secrets (continuation lines indented
#      deeper than the key are skipped, not just the key's own line).
#   2. Connection-string passwords containing a literal "@" (greedy match to
#      the LAST "@" before the host, not the first).
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
    if (upline ~ /^[[:space:]]*[A-Z0-9_]*(SECRET|PASSWORD|API_KEY|TOKEN)[A-Z0-9_]*:/) {
        n = index(line, ":")
        printf "%s REDACTED\n", substr(line, 1, n)
        skip = 1
        indent = cur_indent
        next
    }

    if (line ~ /:\/\/[^:@[:space:]]+:.*@/) {
        sub(/:\/\/[^:@[:space:]]+:.*@/, "://REDACTEDUSER:REDACTED@", line)
    }

    print line
}
