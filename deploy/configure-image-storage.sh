#!/usr/bin/env bash
set -euo pipefail

# Keep the deprivileged API and the monitor's private umask compatible.
images_dir=${1:-/sdb-disk/cutedsl-images}
service_user=${2:-svc-cutedsl}
id "$service_user" >/dev/null
command -v setfacl >/dev/null

for directory in "$images_dir" "$images_dir/originals" "$images_dir/medium" "$images_dir/thumbs"; do
    mkdir -p "$directory"
    setfacl -m "u:$service_user:rwx,d:u:$service_user:rwx" "$directory"
done
