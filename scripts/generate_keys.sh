#!/usr/bin/env bash
# Generate RS256 key pair for JWT signing.
#
# Usage:
#   scripts/generate_keys.sh [output_dir] [kid]
#
# Defaults:
#   output_dir = ./keys
#   kid        = $(date +%Y%m%d)
#
# Output files:
#   {output_dir}/jwt_{kid}_private.pem
#   {output_dir}/jwt_{kid}_public.pem
#
# For local dev, mount ./keys into the API container and set:
#   JWT_PRIVATE_KEY_PATH=/app/keys/jwt_<kid>_private.pem
#   JWT_PUBLIC_KEY_PATH=/app/keys/jwt_<kid>_public.pem
#   JWT_KID=<kid>
set -euo pipefail

OUT_DIR="${1:-./keys}"
KID="${2:-$(date +%Y%m%d)}"

mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR"

PRIV="$OUT_DIR/jwt_${KID}_private.pem"
PUB="$OUT_DIR/jwt_${KID}_public.pem"

if [[ -f "$PRIV" || -f "$PUB" ]]; then
  echo "ERROR: key files already exist for kid=$KID in $OUT_DIR" >&2
  exit 1
fi

openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$PRIV" >/dev/null 2>&1
openssl rsa -in "$PRIV" -pubout -out "$PUB" >/dev/null 2>&1

chmod 600 "$PRIV"
chmod 644 "$PUB"

echo "Generated RS256 key pair:"
echo "  kid:         $KID"
echo "  private key: $PRIV"
echo "  public key:  $PUB"
