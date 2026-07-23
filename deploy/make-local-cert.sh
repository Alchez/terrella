#!/usr/bin/env bash
# Self-signed cert for the local prod-sim's :443 server block (browsers only
# speak HTTP/2 over TLS, so simulating h2 multiplexing needs a cert — any
# cert). Output lands in deploy/certs/ (gitignored). Chrome will interstitial
# on first visit; Advanced -> Proceed is expected and fine for localhost.
set -euo pipefail
cert_dir="$(dirname "$0")/certs"
mkdir -p "$cert_dir"
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
    -keyout "$cert_dir/localhost.key" -out "$cert_dir/localhost.crt" \
    -days 365 -nodes -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
echo "wrote $cert_dir/localhost.{crt,key}"
