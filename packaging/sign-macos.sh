#!/bin/bash
set -euo pipefail
umask 077

app=${1:?Usage: bash packaging/sign-macos.sh APP_BUNDLE}
: "${MACOS_SIGNING_P12:?Missing signing certificate}"
: "${MACOS_SIGNING_PASSWORD:?Missing signing password}"
temporary=$(mktemp -d)
keychain="$temporary/signing.keychain-db"
keychains=()
while read -r existing; do
  existing=${existing#\"}
  existing=${existing%\"}
  keychains+=("$existing")
done < <(security list-keychains -d user)
cleanup() {
  security list-keychains -d user -s "${keychains[@]}" >/dev/null 2>&1 || true
  security delete-keychain "$keychain" >/dev/null 2>&1 || true
  rm -rf "$temporary"
}
trap cleanup EXIT
printf '%s' "$MACOS_SIGNING_P12" | base64 --decode > "$temporary/signing.p12"
keychain_password=$(openssl rand -base64 32)
security create-keychain -p "$keychain_password" "$keychain"
security set-keychain-settings -lut 3600 "$keychain"
security unlock-keychain -p "$keychain_password" "$keychain"
security list-keychains -d user -s "$keychain" "${keychains[@]}"
security import "$temporary/signing.p12" -k "$keychain" \
  -P "$MACOS_SIGNING_PASSWORD" -T /usr/bin/codesign >/dev/null
security set-key-partition-list -S apple-tool:,apple:,codesign: -s \
  -k "$keychain_password" "$keychain" >/dev/null
identity=$(security find-certificate -c 'Meikipop Signing' -Z "$keychain" | awk '/SHA-1 hash:/ {print $3}')
[[ "$identity" =~ ^[[:xdigit:]]{40}$ ]]
# PyInstaller has already signed nested libraries ad hoc. Sign the main app
# without enabling hardened runtime, which rejects libraries without a Team ID.
codesign --force --sign "$identity" --keychain "$keychain" \
  --options 0 --timestamp=none "$app"
codesign --verify --deep --strict -R "=certificate leaf = H\"$identity\"" "$app"
