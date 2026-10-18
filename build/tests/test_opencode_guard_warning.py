"""Exercise the generated OpenCode system hook without calling a model."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("warning_adapters", ROOT / "build/adapters.py")
adapters = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapters)


@unittest.skipUnless(shutil.which("node"), "node is required to execute the bridge")
class TestOpenCodeGuardWarning(unittest.TestCase):
    def system_context(self, root):
        encoded = base64.b64encode(adapters.OPENCODE_BRIDGE.encode()).decode()
        script = """
const { NevaHooks } = await import(process.argv[1]);
const hooks = await NevaHooks({ directory: process.cwd() });
const turns = [];
for (const sessionID of ["first", "second", "first"]) {
  const output = { system: ["Owner context"] };
  await hooks["experimental.chat.system.transform"]({ sessionID }, output);
  turns.push(output.system);
}
console.log(JSON.stringify(turns));
"""
        env = dict(os.environ)
        env.pop("NEVA_ROOT", None)
        if root is not None:
            env["NEVA_ROOT"] = root
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script,
             "data:text/javascript;base64," + encoded],
            env=env, text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)

    def test_unset_root_warns_on_each_session_and_turn(self):
        for system in self.system_context(None):
            self.assertEqual(system[0], "Owner context")
            self.assertEqual(len(system), 2)
            self.assertIn("Neva guards are off because NEVA_ROOT is unset", system[1])
            self.assertIn("set NEVA_ROOT", system[1])

    def test_configured_root_does_not_claim_guards_are_off(self):
        self.assertEqual(self.system_context(str(ROOT)), [["Owner context"]] * 3)


if __name__ == "__main__":
    unittest.main()
