#!/usr/bin/env bash
# Runs inside the disposable Arch Linux container, never on the user's host.
set -euo pipefail
job_dir=$1
scripts_dir=$2
pacman -Syu --noconfirm --needed \
  rust pkgconf python desktop-file-utils polkit \
  gtk3 webkit2gtk-4.1 hicolor-icon-theme systemd
useradd --create-home --uid 1000 builder
chown -R builder:builder "$job_dir"
export MAKEFLAGS='-j2'
export KIRI_BUILD_JOBS=2
runuser -u builder -- bash -c 'cd "$1"; makepkg --cleanbuild --noconfirm; makepkg --printsrcinfo > .SRCINFO' bash "$job_dir"
python "$scripts_dir/validate.py" "$job_dir"
