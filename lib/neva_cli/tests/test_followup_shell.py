"""The rendered heartbeat wrapper reads HOME at run time and never executes its text."""
import os
import subprocess
from pathlib import Path
from neva_cli.tests.test_installed_prefix import InstalledPrefix
from neva_cli import core

class TestHeartbeatHome(InstalledPrefix):
    def test_rendered_wrapper_does_not_execute_home_text(self):
        marker = self.root / "HBMARK"
        home = self.root / ("home$(touch${IFS}" + str(marker).replace("/", "${IFS_PLACEHOLDER}") + ")")
        # A slash in command substitution remains a real path component in HOME.
        home = Path(str(home).replace("${IFS_PLACEHOLDER}", "/"))
        home.mkdir(parents=True)
        wrapper = self.prefix / "services" / "heartbeat-wrap.sh"
        wrapper.parent.mkdir()
        script = (core.REPO_ROOT / "install.sh").read_text()
        render = next(line for line in script.splitlines() if line.startswith("render()"))
        env = dict(os.environ, HOME=str(home), PREFIX=str(self.prefix), SERVICE_PATH="/usr/bin:/bin")
        result = subprocess.run(["bash", "-c", render + '\nrender "$1" "$2"', "render",
                                 str(core.REPO_ROOT / "services/heartbeat-wrap.sh"), str(wrapper)],
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = subprocess.run(["bash", str(wrapper), "probe", "/usr/bin/true"], env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(marker.exists(), "HOME executed as shell code")
        self.assertTrue((home / ".local/state/neva/heartbeat/probe.status").is_file())

