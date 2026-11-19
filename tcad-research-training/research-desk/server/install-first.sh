#!/usr/bin/env bash
set -euo pipefail
stage=${1:?staging directory required}
revision=${2:?release revision required}
[[ $revision =~ ^[0-9a-f]{12}$ && $stage == /root/desk-stage.* ]]
cd "$stage"
sha256sum --quiet -c SHA256SUMS
config=/etc/caddy/Caddyfile
original=ada850a3d06d41e4a5e9c4ad0c1d783c8cf7d52525d5567e0ce91da18e94cd28
check_original() { printf '%s  %s\n' "$original" "$config" | sha256sum --quiet -c -; }
check_original
base=/srv/dram-see-desk
private=/root/.config/dram-see-desk
netrc=$private/owner.netrc
install -d -m 0700 "$private"
install -d -m 0750 -o root -g caddy /etc/caddy/dram-desk
if [[ ! -f $netrc ]]; then
    (umask 077; printf 'machine tcad.xjtu.shop login owner password %s\n' "$(openssl rand -hex 24)" > "$netrc")
fi
hash=$(awk '{print $6}' "$netrc" | caddy hash-password)
[[ $hash == '$2'* ]]
printf 'owner %s\n' "$hash" > /etc/caddy/dram-desk/users
chown root:caddy /etc/caddy/dram-desk/users
chmod 0640 /etc/caddy/dram-desk/users
install -m 0644 desk.caddy /etc/caddy/dram-desk/desk.caddy
restorecon -R /etc/caddy/dram-desk
release=$base/releases/$revision
install -d -m 0755 "$release"
install -m 0644 dist/index.html dist/material.bundle.js dist/waveform.js dist/LICENSE-*.txt "$release/"
if ! semanage fcontext -l -C | grep -Fq '/srv/dram-see-desk(/.*)?'; then
    semanage fcontext -a -t httpd_sys_content_t '/srv/dram-see-desk(/.*)?'
fi
ln -sfn "releases/$revision" "$base/current"
restorecon -R "$base"
backup=$stage/Caddyfile.before
cp -a "$config" "$backup"
candidate=$(mktemp /etc/caddy/.desk-config.XXXXXX)
sed '/^tcad\.xjtu\.shop {$/a\    import /etc/caddy/dram-desk/desk.caddy' "$config" > "$candidate"
grep -qF 'import /etc/caddy/dram-desk/desk.caddy' "$candidate"
chmod --reference="$config" "$candidate"
chown --reference="$config" "$candidate"
chcon --reference="$config" "$candidate"
caddy validate --adapter caddyfile --config "$candidate" >/dev/null
check_original
mv -T "$candidate" "$config"
rollback() { cp -a "$backup" "$config"; systemctl reload caddy; }
trap rollback ERR
systemctl reload caddy
site=https://tcad.xjtu.shop
curl_origin() { curl --max-time 12 --noproxy '*' --resolve tcad.xjtu.shop:443:127.0.0.1 -sS "$@"; }
code() { curl_origin -o /dev/null -w '%{http_code}' "$@"; }
[[ $(code "$site/desk/") == 401 ]]
[[ $(code "$site/desk/api/v1/catalog") == 401 ]]
[[ $(curl_origin -f --netrc-file "$netrc" "$site/desk/" | sha256sum | cut -d' ' -f1) == $(sha256sum dist/index.html | cut -d' ' -f1) ]]
curl_origin -f --netrc-file "$netrc" "$site/desk/api/v1/catalog" | jq -e '.models==[] and .datasets==[] and .archive_ids==["WHR-01"]' >/dev/null
for tool in predict-r predict-f; do
    status=$(curl_origin --netrc-file "$netrc" -X POST -o "$stage/$tool.json" -w '%{http_code}' "$site/desk/api/v1/$tool")
    [[ $status == 503 ]]
    jq -e '.placeholder == true and .status == "model_pending" and has("prediction") and .prediction == null' "$stage/$tool.json" >/dev/null
done
[[ $(code "$site/") == 200 ]]
curl --max-time 12 --noproxy '*' --resolve status.xjtu.shop:443:127.0.0.1 -fsS https://status.xjtu.shop/status.json | jq -e '.schema_version == 2' >/dev/null
trap - ERR
printf 'release=%s authenticated_page_hash=verified catalog=200 predictors=503 anonymous=401 original_sites=ok\n' "$revision"
