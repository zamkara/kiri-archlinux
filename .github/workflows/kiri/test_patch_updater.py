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

class PatchUpdaterTests(unittest.TestCase):
    def test_patch_wires_arch_linux_updater(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            ui_dir = root / 'crates/kiri/src/ui'
            ui_dir.mkdir(parents=True)
            (ui_dir / 'linux.rs').write_text(SAMPLE_LINUX_RS, encoding='utf-8')
            (ui_dir / 'mod.rs').write_text(SAMPLE_UI_MOD_RS, encoding='utf-8')
            (ui_dir / 'index.html').write_text('<a data-open-site="https://runkiri.com/releases/">dl</a>', encoding='utf-8')
            (root / 'crates/kiri/src/main.rs').write_text(SAMPLE_MAIN_RS, encoding='utf-8')
            patch_updater.patch_tree(root, 'zamkara/kiri-archlinux')
            patched_linux = (ui_dir / 'linux.rs').read_text(encoding='utf-8')
            patched_mod = (ui_dir / 'mod.rs').read_text(encoding='utf-8')
            patched_main = (root / 'crates/kiri/src/main.rs').read_text(encoding='utf-8')
            self.assertIn('const ARCH_REPOSITORY: &str = "zamkara/kiri-archlinux"', patched_linux)
            self.assertIn('pub fn run_cli(args: &[String])', patched_linux)
            self.assertNotIn('update_state("package"', patched_mod)
            self.assertIn('exec \\"$2\\" ui', patched_mod)
            self.assertIn('ui::linux::update::run_cli', patched_main)

if __name__ == '__main__':
    unittest.main()
