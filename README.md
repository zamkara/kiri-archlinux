# Kiri for Arch Linux

Native Arch Linux and Omarchy packages for [Kiri](https://github.com/libracoder/kiri),
a tiny, fast container runtime that speaks the Docker Engine API and works with
`docker`, Compose, and `buildx`.

```sh
curl -fsSL https://github.com/zamkara/kiri-archlinux/releases/latest/download/install.sh | bash
```

The installer verifies the SHA-256 checksum of the release package and installs
or upgrades `kiri` through `pacman`. Upstream `libracoder/kiri` is checked
daily at 00:00 Asia/Jakarta (17:00 UTC); new upstream revisions are built from
source in a clean Arch Linux container and published automatically, while
unchanged revisions are skipped.

This is a community packaging repository, not an official Kiri project.
Source code, issues, and development belong to [libracoder/kiri](https://github.com/libracoder/kiri).

---

## Kiri upstream overview

Kiri is a lightweight replacement for Docker Desktop and OrbStack, written in
Rust. On Linux it runs containers directly on the host kernel (`clone3` into
namespaces and cgroups, with no `runc`, no shim, and no `dockerd`) and exposes
the Docker Engine API at `/run/kiri/docker.sock` (and `/var/run/docker.sock`
when no other Docker engine is running).

- **Fast.** Starts and exits a container in ~2.5 ms through the Docker Engine
  API, with minimal daemon memory overhead.
- **Compatible.** Works out of the box with `docker`, `docker compose`,
  `docker buildx`, `docker login`, and Testcontainers.
- **Bundled CLI & plugins.** Includes the pinned `docker` CLI, Compose, and
  `buildx` under `/usr/libexec/kiri`, exposed on `PATH` automatically when no
  conflicting system Docker CLI is installed.
- **Native GTK / WebKitGTK window.** Ships `/usr/lib/kiri/kiri-window` (`kiri ui`)
  for inspecting containers, Compose stacks, images, volumes, networks, builds,
  and resource usage in 38 languages.
- **More than containers.** Built-in single-node Kubernetes (`kiri k8s start`),
  Linux machines (`kiri machine`), and instant port sharing (`kiri share`).

## Included Components

| Component            | Path / Command                                                                 |
| -------------------- | ------------------------------------------------------------------------------ |
| **Engine & CLI**     | `/usr/bin/kiri`, `/usr/bin/kiri-init`                                          |
| **Desktop Window**   | `/usr/lib/kiri/kiri-window` (`kiri ui` or application launcher)                |
| **Systemd Service**  | `/usr/lib/systemd/system/kiri.service` (`sudo kiri host-access $USER`)         |
| **Polkit Policy**    | `/usr/share/polkit-1/actions/dev.kiri.host-access.policy`                      |
| **Bundled Docker**   | `/usr/libexec/kiri/bin/docker`, `docker-compose`, `docker-buildx`              |

## Downloads

- **Arch Linux / Omarchy:** grab the latest build from the [Releases page of this repository](https://github.com/zamkara/kiri-archlinux/releases) or run the one-line installer above.
- **Other platforms (macOS, Windows, Debian/Ubuntu, Fedora/RHEL):** grab official builds from [libracoder/kiri releases](https://github.com/libracoder/kiri/releases) or [runkiri.com/releases](https://runkiri.com/releases/).

## Documentation

- [Upstream repository](https://github.com/libracoder/kiri)
- [Features overview](https://github.com/libracoder/kiri/blob/main/docs/features.md)
- [Architecture & build guide](https://github.com/libracoder/kiri/blob/main/docs/development.md)
- [Upstream license](https://github.com/libracoder/kiri/blob/main/LICENSE)

## License

Kiri itself remains under its [upstream Apache-2.0 license](https://github.com/libracoder/kiri/blob/main/LICENSE).
The build setup in this repository is released under the [Almatera Incubator License](LICENSE).
