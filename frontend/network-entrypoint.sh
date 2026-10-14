#!/bin/sh
set -eu
: "${ALLOWED_NETWORKS:=127.0.0.0/8,::1/128}"
allow_file=/etc/nginx/campus-allow.conf
: > "$allow_file"
old_ifs=$IFS
IFS=,
for cidr in $ALLOWED_NETWORKS; do
    case "$cidr" in ''|*[!0-9a-fA-F:./]*) echo 'Invalid ALLOWED_NETWORKS entry' >&2; exit 1;; esac
    printf 'allow %s;\n' "$cidr" >> "$allow_file"
done
IFS=$old_ifs
# Host loopback connections reach a published Docker port through this gateway.
gateway=$(ip route | awk '/^default/ {print $3; exit}')
case "$gateway" in ''|*[!0-9.]*) :;; *) printf 'allow %s/32;\n' "$gateway" >> "$allow_file";; esac
