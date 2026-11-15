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

        old_media_root = """@media (prefers-color-scheme: light) {
  :root {
    --bg: #F5F7FA; --side: #EDF0F5; --panel: #FFFFFF; --raised: #F3F5F9; --line: #DDE3EB;
    --text: #0F1419; --muted: #5E6773; --faint: #8A929C; --row-hover: rgba(15, 20, 25, .035);
    --sun-text: #8A6100; --red-text: #B42318; --ext-text: #6941C6;
    color-scheme: light;
  }
}"""
        new_media_root = """@media (prefers-color-scheme: light) {
  :root:not([data-theme="dark"]) {
    --bg: #F5F7FA; --side: #EDF0F5; --panel: #FFFFFF; --raised: #F3F5F9; --line: #DDE3EB;
    --text: #0F1419; --muted: #5E6773; --faint: #8A929C; --row-hover: rgba(15, 20, 25, .035);
    --sun-text: #8A6100; --red-text: #B42318; --ext-text: #6941C6;
    color-scheme: light;
  }
}
:root[data-theme="light"] {
  --bg: #F5F7FA; --side: #EDF0F5; --panel: #FFFFFF; --raised: #F3F5F9; --line: #DDE3EB;
  --text: #0F1419; --muted: #5E6773; --faint: #8A929C; --row-hover: rgba(15, 20, 25, .035);
  --sun-text: #8A6100; --red-text: #B42318; --ext-text: #6941C6;
  color-scheme: light;
}"""
        if old_media_root in html:
            html = html.replace(old_media_root, new_media_root, 1)

        html = html.replace(
            '@media (prefers-color-scheme: light) { :root { --lit-hi: #0F9E6A; } }',
            '@media (prefers-color-scheme: light) { :root:not([data-theme="dark"]) { --lit-hi: #0F9E6A; } }\n:root[data-theme="light"] { --lit-hi: #0F9E6A; }',
            1,
        )
        html = html.replace(
            '@media (prefers-color-scheme: light) { .link { color: var(--blue); } }',
            '@media (prefers-color-scheme: light) { :root:not([data-theme="dark"]) .link { color: var(--blue); } }\n:root[data-theme="light"] .link { color: var(--blue); }',
            1,
        )
        html = html.replace(
            '@media (prefers-color-scheme: light) { .dialog.alert > .ico.info { --ink: var(--blue); } }',
            '@media (prefers-color-scheme: light) { :root:not([data-theme="dark"]) .dialog.alert > .ico.info { --ink: var(--blue); } }\n:root[data-theme="light"] .dialog.alert > .ico.info { --ink: var(--blue); }',
            1,
        )
        html = html.replace(
            '@media (prefers-color-scheme: light) { :root { --term-bg: #FFFFFF; --term-fg: #1F2328; } }',
            '@media (prefers-color-scheme: light) { :root:not([data-theme="dark"]) { --term-bg: #FFFFFF; --term-fg: #1F2328; } }\n:root[data-theme="light"] { --term-bg: #FFFFFF; --term-fg: #1F2328; }',
            1,
        )
        html = html.replace(
            '@media (prefers-color-scheme: light) { .htdrawer { box-shadow: 0 -8px 22px rgb(0 0 0 / .10); } }',
            '@media (prefers-color-scheme: light) { :root:not([data-theme="dark"]) .htdrawer { box-shadow: 0 -8px 22px rgb(0 0 0 / .10); } }\n:root[data-theme="light"] .htdrawer { box-shadow: 0 -8px 22px rgb(0 0 0 / .10); }',
            1,
        )
        html = html.replace(
            'function applyPrefs() {\n  const r = document.documentElement.style;',
            'function applyPrefs() {\n  document.documentElement.dataset.theme = darkNow() ? "dark" : "light";\n  const r = document.documentElement.style;',
            1,
        )
        html = html.replace(
            'matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { themeBtn(); if (ui.view === "settings") render(); });',
            'matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { applyPrefs(); themeBtn(); if (ui.view === "settings") render(); });',
            1,
        )
        index_html.write_text(html, encoding='utf-8')

    k8s_rs = root / 'crates/kiri/src/ui/k8s.rs'
    if k8s_rs.is_file():
        k8s_text = k8s_rs.read_text(encoding='utf-8')
        old_k8s_copy = """fn copy(text: &str) {
    use std::io::Write;
    let done = std::process::Command::new("/usr/bin/pbcopy").stdin(std::process::Stdio::piped()).spawn().and_then(|mut c| {
        c.stdin.take().expect("piped").write_all(text.as_bytes())?;
        c.wait()
    });
    match done {
        Ok(s) if s.success() => emit(notice("ok", &super::trf("Copied {text}", &[("text", &text)]))),
        _ => emit(notice("error", &super::tr("Couldn't copy to the clipboard"))),
    }
}"""
        new_k8s_copy = """#[cfg(target_os = "linux")]
fn copy(text: &str) {
    super::window::copy(text);
    emit(notice("ok", &super::trf("Copied {text}", &[("text", &text)])));
}

#[cfg(not(target_os = "linux"))]
fn copy(text: &str) {
    use std::io::Write;
    let done = std::process::Command::new("/usr/bin/pbcopy").stdin(std::process::Stdio::piped()).spawn().and_then(|mut c| {
        c.stdin.take().expect("piped").write_all(text.as_bytes())?;
        c.wait()
    });
    match done {
        Ok(s) if s.success() => emit(notice("ok", &super::trf("Copied {text}", &[("text", &text)]))),
        _ => emit(notice("error", &super::tr("Couldn't copy to the clipboard"))),
    }
}"""
        if old_k8s_copy not in k8s_text:
            raise SystemExit('Could not find fn copy in crates/kiri/src/ui/k8s.rs')
        k8s_text = k8s_text.replace(old_k8s_copy, new_k8s_copy, 1)
        k8s_rs.write_text(k8s_text, encoding='utf-8')

    gtk_rs = root / 'crates/kiri/src/ui/gtk.rs'
    if gtk_rs.is_file():
        gtk_text = gtk_rs.read_text(encoding='utf-8')
        old_gtk_copy = """pub(super) fn copy(text: &str) {
    let text = text.to_owned();
    glib::MainContext::default().invoke(move || {
        let clipboard = gtk::Clipboard::get(&gtk::gdk::SELECTION_CLIPBOARD);
        clipboard.set_text(&text);
        // Kept after the window quits, where the desktop has a clipboard manager.
        clipboard.store();
    });
}"""
        new_gtk_copy = """pub(super) fn copy(text: &str) {
    let text = text.to_owned();
    if std::env::var_os("WAYLAND_DISPLAY").is_some() {
        let wl_text = text.clone();
        std::thread::spawn(move || {
            use std::io::Write;
            if let Ok(mut c) = std::process::Command::new("wl-copy")
                .stdin(std::process::Stdio::piped())
                .stdout(std::process::Stdio::null())
                .stderr(std::process::Stdio::null())
                .spawn()
            {
                let _ = c.stdin.take().map(|mut i| i.write_all(wl_text.as_bytes()));
                let _ = c.wait();
            }
        });
    }
    glib::MainContext::default().invoke(move || {
        let clipboard = gtk::Clipboard::get(&gtk::gdk::SELECTION_CLIPBOARD);
        clipboard.set_text(&text);
        // Kept after the window quits, where the desktop has a clipboard manager.
        clipboard.store();
    });
}"""
        if old_gtk_copy not in gtk_text:
            raise SystemExit('Could not find pub(super) fn copy in crates/kiri/src/ui/gtk.rs')
        gtk_text = gtk_text.replace(old_gtk_copy, new_gtk_copy, 1)
        gtk_rs.write_text(gtk_text, encoding='utf-8')

    logins_rs = root / 'crates/kiri/src/ui/logins.rs'
    if logins_rs.is_file():
        logins_text = logins_rs.read_text(encoding='utf-8')
        old_linux_os = """/// Elsewhere there's no store of the system's to keep a sign-in in.
#[cfg(not(any(target_os = "macos", windows)))]
mod os {
    use std::io;

    use super::Login;

    pub const NAME: &str = "a credential helper";

    pub fn get(_key: &str) -> Option<Login> {
        None
    }

    pub fn set(_key: &str, _login: &Login) -> io::Result<()> {
        Err(io::Error::other("set credsStore in ~/.docker/config.json to a credential helper"))
    }

    pub fn delete(_key: &str) {}

    pub fn list() -> Vec<(String, String)> {
        Vec::new()
    }
}"""
        new_linux_os = """/// On Linux without a credential helper, keep credentials in ~/.docker/config.json
/// (`auths`) with mode 0600, matching standard `docker login` fallback behavior.
#[cfg(not(any(target_os = "macos", windows)))]
mod os {
    use std::io;
    use serde_json::json;

    use super::{Login, TOKEN_USER, auths_entry, b64, config_dir, edit_auths, inline, read_config, server_key};

    pub const NAME: &str = "~/.docker/config.json";

    pub fn get(key: &str) -> Option<Login> {
        let cfg = read_config();
        auths_entry(&cfg, key).and_then(inline)
    }

    pub fn set(key: &str, login: &Login) -> io::Result<()> {
        edit_auths(|a| {
            let k = a.keys().find(|k| server_key(k) == key).cloned().unwrap_or_else(|| key.to_owned());
            let entry = if login.username == TOKEN_USER {
                json!({"identitytoken": login.secret})
            } else {
                let auth = b64::encode(format!("{}:{}", login.username, login.secret).as_bytes());
                json!({"auth": auth})
            };
            a.insert(k, entry);
        })?;
        if let Some(path) = config_dir().map(|d| d.join("config.json")) {
            use std::os::unix::fs::PermissionsExt;
            let _ = std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600));
        }
        Ok(())
    }

    pub fn delete(key: &str) {
        let _ = edit_auths(|a| a.retain(|k, _| server_key(k) != key));
    }

    pub fn list() -> Vec<(String, String)> {
        Vec::new()
    }
}"""
        if old_linux_os not in logins_text:
            raise SystemExit('Could not find Linux mod os in crates/kiri/src/ui/logins.rs')
        logins_text = logins_text.replace(old_linux_os, new_linux_os, 1)
        logins_rs.write_text(logins_text, encoding='utf-8')




if __name__ == '__main__':
    repo = sys.argv[2] if len(sys.argv) > 2 else 'zamkara/kiri-archlinux'
    patch_tree(pathlib.Path(sys.argv[1]), repo)
