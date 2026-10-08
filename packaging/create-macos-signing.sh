#!/bin/bash
set -euo pipefail
umask 077

# Keep this directory outside the checkout and back it up securely.
destination=${1:?Usage: bash packaging/create-macos-signing.sh BACKUP_DIRECTORY}
mkdir "$destination"
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT
openssl rand -base64 32 > "$destination/password.txt"
openssl req -x509 -newkey rsa:3072 -sha256 -days 3650 -nodes \
  -subj '/CN=Meikipop Signing' \
  -addext 'basicConstraints=critical,CA:FALSE' \
  -addext 'keyUsage=critical,digitalSignature' \
  -addext 'extendedKeyUsage=codeSigning' \
  -keyout "$temporary/key.pem" -out "$destination/certificate.pem" 2>/dev/null
# Legacy PKCS#12 encryption is needed by macOS security import.
openssl pkcs12 -export -legacy -name 'Meikipop Signing' \
  -inkey "$temporary/key.pem" -in "$destination/certificate.pem" \
  -out "$destination/signing.p12" -passout "file:$destination/password.txt"
printf 'Signing identity created. Keep signing.p12 and password.txt private and backed up.\n'
