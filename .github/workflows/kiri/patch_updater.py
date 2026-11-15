"""Wire Kiri's in-app updater and CLI update command on Arch Linux / Omarchy to zamkara/kiri-archlinux releases."""
import pathlib,sys

LINUX_UPDATE_MOD = """pub mod update {
    use std::io::{self, Read, Write};
    use std::path::PathBuf;
    use std::process::{Command, Stdio};
    use std::sync::atomic::{AtomicBool, Ordering};
    use sha2::{Digest, Sha256};

    const ARCH_REPOSITORY: &str = "@REPOSITORY@";
    const ARCH_API_LATEST: &str = "https://api.github.com/repos/@REPOSITORY@/releases/latest";

    #[derive(serde::Serialize, serde::Deserialize, Clone, Debug)]
    pub struct Release {
        pub version: String,
        #[serde(default)]
        pub url: String,
        #[serde(default)]
        pub sha256: String,
        #[serde(default)]
        pub pkg_name: String,
        #[serde(default)]
        pub notes: String,
        #[serde(default)]
        pub notes_url: String,
    }

    fn current_arch_version() -> String {
        if let Ok(out) = Command::new("pacman").args(["-Q", "kiri"]).stderr(Stdio::null()).output()
            && out.status.success()
            && let Some(ver) = String::from_utf8_lossy(&out.stdout).split_whitespace().nth(1)
        {
            return ver.to_owned();
        }
        if let Ok(raw) = std::fs::read_to_string("/usr/lib/kiri/arch-release.json")
            && let Ok(meta) = serde_json::from_str::<serde_json::Value>(&raw)
            && let Some(ver) = meta["version"].as_str()
            && !ver.is_empty()
        {
            return ver.to_owned();
        }
        env!("CARGO_PKG_VERSION").to_owned()
    }

    pub fn newer(candidate: &str, current: &str) -> bool {
        let cur = if current == env!("CARGO_PKG_VERSION") {
            current_arch_version()
        } else {
            current.to_owned()
        };
        if let Ok(out) = Command::new("vercmp").args([candidate, &cur]).stderr(Stdio::null()).output()
            && out.status.success()
            && let Ok(cmp) = String::from_utf8_lossy(&out.stdout).trim().parse::<i32>()
        {
            return cmp > 0;
        }
        let parts = |v: &str| -> Vec<u64> {
            v.trim_start_matches('v').split(['.', '-']).map(|p| p.parse().unwrap_or(0)).collect()
        };
        parts(candidate) > parts(&cur)
    }

    fn agent() -> ureq::Agent {
        ureq::Agent::config_builder()
            .timeout_connect(Some(std::time::Duration::from_secs(15)))
            .user_agent(concat!("kiri-archlinux-updater/", env!("CARGO_PKG_VERSION")))
            .build()
            .into()
    }

    fn stage_dir() -> PathBuf {
        std::env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("/tmp"))
            .join(".cache/kiri-arch-update")
    }

    pub fn latest() -> io::Result<Release> {
        let url = std::env::var("KIRI_UPDATE_URL").unwrap_or_else(|_| ARCH_API_LATEST.to_owned());
        let body = agent()
            .get(&url)
            .header("Accept", "application/vnd.github+json")
            .call()
            .map_err(io::Error::other)?
            .body_mut()
            .with_config()
            .limit(2 << 20)
            .read_to_vec()
            .map_err(io::Error::other)?;
        let json: serde_json::Value = serde_json::from_slice(&body)
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e.to_string()))?;
        let assets = json["assets"]
            .as_array()
            .ok_or_else(|| io::Error::other("release has no assets array"))?;
        let pkg = assets
            .iter()
            .find(|a| {
                a["name"]
                    .as_str()
                    .is_some_and(|n| n.starts_with("kiri-") && n.ends_with("-x86_64.pkg.tar.zst"))
            })
            .ok_or_else(|| io::Error::other("no Arch Linux package asset in latest release"))?;
        let pkg_name = pkg["name"].as_str().unwrap_or_default().to_owned();
        let pkg_url = pkg["browser_download_url"].as_str().unwrap_or_default().to_owned();
        let sums = assets
            .iter()
            .find(|a| a["name"].as_str() == Some("SHA256SUMS"))
            .and_then(|a| a["browser_download_url"].as_str())
            .ok_or_else(|| io::Error::other("no SHA256SUMS asset in latest release"))?;
        let sums_body = agent()
            .get(sums)
            .call()
            .map_err(io::Error::other)?
            .body_mut()
            .with_config()
            .limit(256 << 10)
            .read_to_string()
            .map_err(io::Error::other)?;
        let sha256 = sums_body
            .lines()
            .filter_map(|line| {
                let mut parts = line.split_whitespace();
                let hash = parts.next()?;
                let name = parts.next()?;
                (name == pkg_name && hash.len() == 64).then(|| hash.to_owned())
            })
            .next()
            .ok_or_else(|| io::Error::other(format!("missing SHA-256 for {pkg_name}")))?;
        let remote_version = pkg_name
            .strip_prefix("kiri-")
            .and_then(|s| s.strip_suffix("-x86_64.pkg.tar.zst"))
            .ok_or_else(|| io::Error::other("invalid package filename"))?
            .to_owned();
        let notes = json["body"].as_str().unwrap_or_default().to_owned();
        let notes_url = json["html_url"]
            .as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| format!("https://github.com/{ARCH_REPOSITORY}/releases/latest"));
        Ok(Release {
            version: remote_version,
            url: pkg_url,
            sha256,
            pkg_name,
            notes,
            notes_url,
        })
    }

    pub fn download(
        release: &Release,
        progress: &mut dyn FnMut(u64, Option<u64>),
        cancel: &AtomicBool,
    ) -> io::Result<()> {
        let dir = stage_dir();
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir)?;
        let pkg_path = dir.join(&release.pkg_name);
        let mut resp = agent().get(&release.url).call().map_err(io::Error::other)?;
        let total = resp
            .headers()
            .get("content-length")
            .and_then(|v| v.to_str().ok()?.parse::<u64>().ok());
        let mut reader = resp.body_mut().with_config().limit(2 << 30).reader();
        let mut out = std::fs::File::create(&pkg_path)?;
        let mut hash = Sha256::new();
        let mut buf = vec![0u8; 256 * 1024];
        let mut got = 0u64;
        loop {
            if cancel.load(Ordering::Relaxed) {
                let _ = std::fs::remove_dir_all(&dir);
                return Err(io::Error::new(io::ErrorKind::Interrupted, "cancelled"));
            }
            let n = reader.read(&mut buf)?;
            if n == 0 {
                break;
            }
            hash.update(&buf[..n]);
            out.write_all(&buf[..n])?;
            got += n as u64;
            progress(got, total);
        }
        out.sync_all()?;
        let actual: String = hash.finalize().iter().map(|b| format!("{b:02x}")).collect();
        if !actual.eq_ignore_ascii_case(release.sha256.trim()) {
            let _ = std::fs::remove_dir_all(&dir);
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("package SHA-256 mismatch (got {actual})"),
            ));
        }
        std::fs::write(
            dir.join("staged.json"),
            serde_json::to_vec(release).map_err(io::Error::other)?,
        )?;
        Ok(())
    }

    pub fn staged() -> Option<String> {
        let dir = stage_dir();
        let raw = std::fs::read(dir.join("staged.json")).ok()?;
        let rel: Release = serde_json::from_slice(&raw).ok()?;
        let pkg = dir.join(&rel.pkg_name);
        (pkg.is_file() && newer(&rel.version, &current_arch_version())).then_some(rel.version)
    }

    pub fn install_staged() -> io::Result<String> {
        let dir = stage_dir();
        let raw = std::fs::read(dir.join("staged.json"))
            .map_err(|_| io::Error::other("no staged Arch Linux update"))?;
        let rel: Release = serde_json::from_slice(&raw).map_err(io::Error::other)?;
        let pkg = dir.join(&rel.pkg_name);
        let mut hash = Sha256::new();
        let mut f = std::fs::File::open(&pkg)?;
        let mut buf = vec![0u8; 256 * 1024];
        loop {
            let n = f.read(&mut buf)?;
            if n == 0 {
                break;
            }
            hash.update(&buf[..n]);
        }
        let actual: String = hash.finalize().iter().map(|b| format!("{b:02x}")).collect();
        if !actual.eq_ignore_ascii_case(rel.sha256.trim()) {
            let _ = std::fs::remove_dir_all(&dir);
            return Err(io::Error::other("staged package checksum mismatch"));
        }
        let status = if let Ok(tty) = std::fs::OpenOptions::new().read(true).write(true).open("/dev/tty") {
            Command::new("sudo")
                .args(["--", "/usr/bin/pacman", "-U", "--", &pkg.to_string_lossy()])
                .stdin(Stdio::from(tty))
                .status()?
        } else {
            Command::new("pkexec")
                .args(["/usr/bin/pacman", "-U", "--noconfirm", "--", &pkg.to_string_lossy()])
                .stdin(Stdio::null())
                .status()?
        };
        if !status.success() {
            return Err(io::Error::other("pacman -U failed or was cancelled"));
        }
        let _ = std::fs::remove_dir_all(&dir);
        Ok(env!("CARGO_PKG_VERSION").to_owned())
    }

    pub fn run_cli(args: &[String]) -> io::Result<()> {
        let current = current_arch_version();
        let rel = latest()?;
        if !newer(&rel.version, &current) {
            println!("Kiri {current} is up to date");
            return Ok(());
        }
        println!("Kiri {} is available (installed: {current})", rel.version);
        if args.iter().any(|a| a == "--check") {
            return Ok(());
        }
        println!("Downloading {}...", rel.pkg_name);
        download(&rel, &mut |_, _| {}, &AtomicBool::new(false))?;
        install_staged()?;
        println!("Kiri {} installed.", rel.version);
        Ok(())
    }

    pub fn app() -> io::Result<PathBuf> {
        std::env::current_exe()
    }

    pub fn restart_engine(expect: &str) -> io::Result<String> {
        crate::diag::info!("restarting the engine", version = expect);
        super::onboarding::restart_engine()?;
        let began = std::time::Instant::now();
        let mut last = None;
        while began.elapsed() < std::time::Duration::from_secs(60) {
            if let Some(v) = crate::client::request("GET", "/version", None)
                .ok()
                .filter(|r| r.ok())
                .and_then(|r| crate::client::kiri_version(&r.json()).map(str::to_owned))
            {
                if v == expect || expect.starts_with(&format!("{v}.")) {
                    return Ok(v);
                }
                last = Some(v);
            }
            std::thread::sleep(std::time::Duration::from_millis(250));
        }
        Err(io::Error::other(match last {
            Some(v) => format!("the engine came back on {v}, not {expect}: is the kiri package upgraded?"),
            None => "the engine did not come back: journalctl -u kiri says why".to_owned(),
        }))
    }

    pub fn start_engine() -> io::Result<()> {
        Err(super::engine_down())
    }
}"""


def patch_tree(root: pathlib.Path, repository: str = 'zamkara/kiri-archlinux') -> None:
    linux_rs = root / 'crates/kiri/src/ui/linux.rs'
    text = linux_rs.read_text(encoding='utf-8')
    start_marker = 'pub mod update {'
    end_marker = '\npub mod import {'
    if start_marker not in text or end_marker not in text:
        raise SystemExit('Could not find pub mod update block in crates/kiri/src/ui/linux.rs')
    start_idx = text.index(start_marker)
    end_idx = text.index(end_marker, start_idx)
    text = (
        text[:start_idx]
        + LINUX_UPDATE_MOD.replace('@REPOSITORY@', repository)
        + '\n'
        + text[end_idx:]
    )
    linux_rs.write_text(text, encoding='utf-8')

    main_rs = root / 'crates/kiri/src/main.rs'
    if main_rs.is_file():
        main_text = main_rs.read_text(encoding='utf-8')
        old_update_cmd = """        #[cfg(target_os = "macos")]
        Some("update") => update::run(&args[1..]),"""
        new_update_cmd = """        #[cfg(target_os = "macos")]
        Some("update") => update::run(&args[1..]),
        #[cfg(all(target_os = "linux", feature = "window"))]
        Some("update") => ui::linux::update::run_cli(&args[1..]),
        #[cfg(all(target_os = "linux", not(feature = "window")))]
        Some("update") => window(&args),"""
        if old_update_cmd not in main_text:
            raise SystemExit('Could not find Some("update") branch in crates/kiri/src/main.rs')
        main_text = main_text.replace(old_update_cmd, new_update_cmd, 1)
        main_rs.write_text(main_text, encoding='utf-8')

    ui_mod = root / 'crates/kiri/src/ui/mod.rs'
    if ui_mod.is_file():
        mod_text = ui_mod.read_text(encoding='utf-8')
        mod_text = mod_text.replace('#[cfg(target_os = "linux")]\nmod linux;', '#[cfg(target_os = "linux")]\npub(crate) mod linux;', 1)
        old_linux_branch = """    if cfg!(target_os = "linux") {
        match update::latest() {
            Ok(r) => update_state("package", update::newer(&r.version, env!("CARGO_PKG_VERSION")).then_some(r.version.as_str()), None),
            Err(e) => update_state("error", None, Some(e.to_string())),
        }
        return;
    }"""
        if old_linux_branch not in mod_text:
            raise SystemExit('Could not find Linux update_state("package") branch in crates/kiri/src/ui/mod.rs')
        mod_text = mod_text.replace(old_linux_branch, '', 1)

        old_reopen = '    let script = "while /bin/kill -0 \\"$1\\" 2>/dev/null; do /bin/sleep 0.2; done; exec /usr/bin/open \\"$2\\"";'
        new_reopen = '    let script = if cfg!(target_os = "macos") { "while /bin/kill -0 \\"$1\\" 2>/dev/null; do /bin/sleep 0.2; done; exec /usr/bin/open \\"$2\\"" } else { "while /bin/kill -0 \\"$1\\" 2>/dev/null; do /bin/sleep 0.2; done; exec \\"$2\\" ui" };'
        if old_reopen not in mod_text:
            raise SystemExit('Could not find reopen_after_exit script in crates/kiri/src/ui/mod.rs')
        mod_text = mod_text.replace(old_reopen, new_reopen, 1)

        old_open = 'msg.name == "https://github.com/libracoder/kiri"'
        new_open = f'msg.name == "https://github.com/libracoder/kiri" || msg.name == "https://github.com/{repository}/releases/latest"'
        if old_open in mod_text:
            mod_text = mod_text.replace(old_open, new_open, 1)

        old_notes = 'msg.name.strip_prefix("https://runkiri.com/")'
        new_notes = f'msg.name.strip_prefix("https://runkiri.com/").or_else(|| msg.name.strip_prefix("https://github.com/{repository}/"))'
        if old_notes in mod_text:
            mod_text = mod_text.replace(old_notes, new_notes, 1)

        ui_mod.write_text(mod_text, encoding='utf-8')

    index_html = root / 'crates/kiri/src/ui/index.html'
    if index_html.is_file():
        html = index_html.read_text(encoding='utf-8')
        old_deb = 'https://runkiri.com/releases/'
        new_deb = f'https://github.com/{repository}/releases/latest'
        html = html.replace(old_deb, new_deb)
        index_html.write_text(html, encoding='utf-8')


if __name__ == '__main__':
    repo = sys.argv[2] if len(sys.argv) > 2 else 'zamkara/kiri-archlinux'
    patch_tree(pathlib.Path(sys.argv[1]), repo)
