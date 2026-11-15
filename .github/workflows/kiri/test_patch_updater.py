import pathlib,tempfile,unittest
import patch_updater

SAMPLE_LINUX_RS = """pub mod setup {}

pub mod update {
    const BY_APT: &str = "on Linux, Kiri updates with your other packages (apt or dnf)";
}

pub mod import {}
"""

SAMPLE_UI_MOD_RS = """#[cfg(target_os = "linux")]
mod linux;

fn feed_check() {
    if cfg!(target_os = "linux") {
        match update::latest() {
            Ok(r) => update_state("package", update::newer(&r.version, env!("CARGO_PKG_VERSION")).then_some(r.version.as_str()), None),
            Err(e) => update_state("error", None, Some(e.to_string())),
        }
        return;
    }
}

fn reopen_after_exit() {
    let Ok(app) = update::app() else { return };
    let script = "while /bin/kill -0 \\"$1\\" 2>/dev/null; do /bin/sleep 0.2; done; exec /usr/bin/open \\"$2\\"";
}
"""

SAMPLE_MAIN_RS = """fn main() {
    match cmd {
        #[cfg(target_os = "macos")]
        Some("update") => update::run(&args[1..]),
        _ => {}
    }
}
"""

SAMPLE_K8S_RS = """fn copy(text: &str) {
    use std::io::Write;
    let done = std::process::Command::new("/usr/bin/pbcopy").stdin(std::process::Stdio::piped()).spawn().and_then(|mut c| {
        c.stdin.take().expect("piped").write_all(text.as_bytes())?;
        c.wait()
    });
    match done {
        Ok(s) if s.success() => emit(notice("ok", &super::trf("Copied {text}", &[("text", &text)]))),
        _ => emit(notice("error", &super::tr("Couldn't copy to the clipboard"))),
    }
}
"""

SAMPLE_GTK_RS = """pub(super) fn copy(text: &str) {
    let text = text.to_owned();
    glib::MainContext::default().invoke(move || {
        let clipboard = gtk::Clipboard::get(&gtk::gdk::SELECTION_CLIPBOARD);
        clipboard.set_text(&text);
        // Kept after the window quits, where the desktop has a clipboard manager.
        clipboard.store();
    });
}
"""

SAMPLE_INDEX_HTML = """@media (prefers-color-scheme: light) {
  :root {
    --bg: #F5F7FA; --side: #EDF0F5; --panel: #FFFFFF; --raised: #F3F5F9; --line: #DDE3EB;
    --text: #0F1419; --muted: #5E6773; --faint: #8A929C; --row-hover: rgba(15, 20, 25, .035);
    --sun-text: #8A6100; --red-text: #B42318; --ext-text: #6941C6;
    color-scheme: light;
  }
}
@media (prefers-color-scheme: light) { :root { --lit-hi: #0F9E6A; } }
@media (prefers-color-scheme: light) { .link { color: var(--blue); } }
@media (prefers-color-scheme: light) { .dialog.alert > .ico.info { --ink: var(--blue); } }
@media (prefers-color-scheme: light) { :root { --term-bg: #FFFFFF; --term-fg: #1F2328; } }
@media (prefers-color-scheme: light) { .htdrawer { box-shadow: 0 -8px 22px rgb(0 0 0 / .10); } }
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { themeBtn(); if (ui.view === "settings") render(); });
function applyPrefs() {
  const r = document.documentElement.style;
}
<a data-open-site="https://runkiri.com/releases/">dl</a>
"""

class PatchUpdaterTests(unittest.TestCase):
    def test_patch_wires_arch_linux_updater(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            ui_dir = root / 'crates/kiri/src/ui'
            ui_dir.mkdir(parents=True)
            (ui_dir / 'linux.rs').write_text(SAMPLE_LINUX_RS, encoding='utf-8')
            (ui_dir / 'mod.rs').write_text(SAMPLE_UI_MOD_RS, encoding='utf-8')
            (ui_dir / 'k8s.rs').write_text(SAMPLE_K8S_RS, encoding='utf-8')
            (ui_dir / 'gtk.rs').write_text(SAMPLE_GTK_RS, encoding='utf-8')
            (ui_dir / 'index.html').write_text(SAMPLE_INDEX_HTML, encoding='utf-8')
            (root / 'crates/kiri/src/main.rs').write_text(SAMPLE_MAIN_RS, encoding='utf-8')
            patch_updater.patch_tree(root, 'zamkara/kiri-archlinux')
            patched_linux = (ui_dir / 'linux.rs').read_text(encoding='utf-8')
            patched_mod = (ui_dir / 'mod.rs').read_text(encoding='utf-8')
            patched_k8s = (ui_dir / 'k8s.rs').read_text(encoding='utf-8')
            patched_gtk = (ui_dir / 'gtk.rs').read_text(encoding='utf-8')
            patched_html = (ui_dir / 'index.html').read_text(encoding='utf-8')
            patched_main = (root / 'crates/kiri/src/main.rs').read_text(encoding='utf-8')
            self.assertIn('const ARCH_REPOSITORY: &str = "zamkara/kiri-archlinux"', patched_linux)
            self.assertIn('pub fn run_cli(args: &[String])', patched_linux)
            self.assertNotIn('update_state("package"', patched_mod)
            self.assertIn('exec \\"$2\\" ui', patched_mod)
            self.assertIn('super::window::copy(text)', patched_k8s)
            self.assertIn('Command::new("wl-copy")', patched_gtk)
            self.assertIn(':root[data-theme="light"]', patched_html)
            self.assertIn('document.documentElement.dataset.theme = darkNow() ? "dark" : "light";', patched_html)
            self.assertIn('ui::linux::update::run_cli', patched_main)

if __name__ == '__main__':
    unittest.main()
