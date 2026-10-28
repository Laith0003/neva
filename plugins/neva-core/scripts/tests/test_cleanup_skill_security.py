"""Regression checks for child permissions and canvas authentication."""
from pathlib import Path
import subprocess
import importlib.util
import json
import os
import tempfile
import sys
from unittest import mock
import unittest

SKILLS = Path(__file__).resolve().parents[2] / "skills"

class SkillSecurity(unittest.TestCase):
    def test_stop_hook_sends_canvas_token(self):
        sys.path.insert(0, str(SKILLS.parent / "hooks"))
        from neva_hooks import plan_canvas
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"status":"waiting"}'
        with mock.patch.object(plan_canvas.urllib.request, "urlopen", return_value=response) as opened:
            result = plan_canvas.drain(4517, "abcdefabcdef", token="secret")
        self.assertEqual(result, {"status": "waiting"})
        request = opened.call_args.args[0]
        self.assertEqual(request.get_header("X-neva-token"), "secret")

    def fake_claude(self, directory):
        binary = directory / "claude"
        self.assertEqual(binary.resolve(), binary)
        binary.write_text("#!" + sys.executable + "\n" + r"""
import json, os, pathlib, sys
with open(os.environ['CAPTURE_ARGS'], 'a') as handle:
    handle.write(json.dumps(sys.argv[1:]) + '\n')
if '--allowedTools' in sys.argv and 'Generator' not in sys.argv[-1]:
    feedback = pathlib.Path('gan-harness/feedback/feedback-001.md')
    if feedback.parent.is_dir():
        feedback.write_text('**TOTAL** 10.0\n')
print(os.environ.get('FAKE_COMPLETION', 'fake child completed'))
""")
        binary.chmod(0o700)
        return binary

    def test_evaluator_has_no_unrestricted_shell(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd().resolve(), prefix=".security-test-") as raw:
            directory = Path(raw).resolve()
            binary = self.fake_claude(directory)
            (directory / ".git").mkdir()
            harness = directory / "gan-harness"
            harness.mkdir()
            (harness / "spec.md").write_text("Fixture specification")
            capture = directory / "args.jsonl"
            env = {**os.environ, "PATH": str(directory) + os.pathsep + os.environ["PATH"],
                   "CAPTURE_ARGS": str(capture), "GAN_PROJECT_DIR": str(directory),
                   "GAN_SKIP_PLANNER": "true", "GAN_MAX_ITERATIONS": "1",
                   "GAN_EVAL_MODE": "cli", "GAN_TEST_CMD": "python3 -m unittest", "GAN_DEV_SERVER_PORT": "4321"}
            proc = subprocess.run(["bash", str(SKILLS / "gan-style-harness/scripts/gan-harness.sh"), "fixture"],
                                  cwd=directory, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("Evaluator completed", proc.stdout)
            calls = [json.loads(line) for line in capture.read_text().splitlines()]
            self.assertEqual(len(calls), 2)
            evaluator = next(call for call in calls if "--allowedTools" in call)
            tools = evaluator[evaluator.index("--allowedTools") + 1].split(",")
            self.assertNotIn("Bash", tools)
            self.assertEqual([tool for tool in tools if tool.startswith("Bash")],
                             ["Bash(python3 -m unittest)", "Bash(curl http://localhost:4321/*)",
                              "Bash(curl http://127.0.0.1:4321/*)"])
            self.assertIn("PASS", (harness / "build-report.md").read_text())

    def test_analysis_write_is_scoped(self):
        scripts = SKILLS / "continuous-learning-v2/scripts"
        sys.path.insert(0, str(scripts))
        spec = importlib.util.spec_from_file_location("security_analysis", scripts / "instinct-analyze.py")
        analyzer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(analyzer)
        with tempfile.TemporaryDirectory(dir=Path.cwd().resolve(), prefix=".security-test-") as raw:
            directory = Path(raw).resolve()
            binary = self.fake_claude(directory)
            instincts = directory / "instincts"
            instincts.mkdir()
            temporary = directory / "analysis"
            temporary.mkdir()
            capture = directory / "args.jsonl"
            with mock.patch.dict(os.environ, {"NEVA_CLAUDE_BIN": str(binary), "CAPTURE_ARGS": str(capture),
                                              "FAKE_COMPLETION": analyzer.COMPLETION_RECORD}):
                result = analyzer.analyze_batch(temporary, "fixture", "fixture", "fixture", [b'{}\n'], instincts,
                                               {"model": "fake", "max_turns": 4, "timeout_seconds": 5})
            self.assertTrue(result)
            calls = [json.loads(line) for line in capture.read_text().splitlines()]
            self.assertEqual(len(calls), 1)
            tools = calls[0][calls[0].index("--allowedTools") + 1]
            self.assertEqual(tools, f"Read,Write({instincts}/**)")
            self.assertEqual(list(temporary.iterdir()), [])

    def test_canvas_explicit_state_directory_authenticates_shutdown(self):
        cli = SKILLS / "plan-canvas/scripts/plan-canvas.js"
        script = r"""
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert');
const {EventEmitter}=require('events');
const directory=fs.mkdtempSync(path.join(process.cwd(),'.canvas-auth-test-'));
const custom=path.join(directory,'custom'),defaults=path.join(directory,'defaults');
fs.mkdirSync(custom);fs.mkdirSync(defaults);
fs.writeFileSync(path.join(custom,'server.json'),JSON.stringify({token:'custom-token'}));
fs.writeFileSync(path.join(defaults,'server.json'),JSON.stringify({token:'wrong-token'}));
process.env.NEVA_PLAN_CANVAS_STATE_DIR=defaults;
require('child_process').spawn=()=>({unref(){}});
let healthCalls=0,shutdownToken;
http.request=(options,callback)=>{
 const req=new EventEmitter(); req.write=()=>{};
 req.end=()=>process.nextTick(()=>{
  const response=new EventEmitter();response.statusCode=200;callback(response);
  if(options.path==='/shutdown')shutdownToken=options.headers['x-neva-token'];
  const body=options.path==='/health' ? (++healthCalls===2 ? {} : {app:'neva-plan-canvas',version:'old'}) : {};
  response.emit('data',JSON.stringify(body));response.emit('end');
 });
 return req;
};
require(process.argv[1]).ensureServer({stateDir:custom,port:4517}).then(()=>{
 assert.equal(shutdownToken,'custom-token');
}).catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>fs.rmSync(directory,{recursive:true}));
"""
        proc = subprocess.run(["node", "-e", script, str(cli)], capture_output=True, text=True, timeout=5)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_canvas_persists_private_rotating_token(self):
        cli = SKILLS / "plan-canvas/scripts/plan-canvas.js"
        script = r"""
const fs=require('fs'), path=require('path'), http=require('http'), assert=require('assert');
const dir=fs.mkdtempSync(path.join(process.cwd(),'.canvas-state-test-'));
process.env.NEVA_PLAN_CANVAS_STATE_DIR=dir;
http.Server.prototype.listen=function(port,host,cb){process.nextTick(cb);return this;};
http.Server.prototype.address=function(){return {port:4517};};
require(process.argv[1]).main(['server']);
setTimeout(()=>{
 try {
  const file=path.join(dir,'server.json');
  assert.equal(fs.statSync(file).mode & 0o777,0o600);
  assert.match(JSON.parse(fs.readFileSync(file)).token,/^[a-f0-9]{64}$/);
 } catch(e){console.error(e);process.exitCode=1;}
 finally{fs.rmSync(dir,{recursive:true});process.exit(process.exitCode||0);}
},40);
"""
        proc = subprocess.run(["node", "-e", script, str(cli)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_canvas_denies_missing_token_and_symlink_escape(self):
        server = SKILLS / "plan-canvas/scripts/lib/plan-canvas/server.js"
        script = r"""
const assert = require('assert');
const {createPlanCanvasServer} = require(process.argv[1]);
const fs = require('fs');
const path = require('path');
const os = require('os');
const dir = fs.mkdtempSync(path.join(process.cwd(), '.canvas-test-'));
const plans = path.join(dir,'plans'); fs.mkdirSync(plans);
const file = path.join(plans,'plan.html'); fs.writeFileSync(file,'ok');
fs.writeFileSync(path.join(dir,'secret'),'private');
fs.symlinkSync(path.join(dir,'secret'),path.join(plans,'escape'));
const store = {list:()=>[], get:()=>({file})};
const canvas=createPlanCanvasServer({store});
function request(route,token) {
 return new Promise(resolve=>{
  const req={url:route,method:'GET',headers:{host:'127.0.0.1',...(token?{'x-neva-token':token}:{})}};
  const res={writeHead(status,headers){this.status=status;},end(body){resolve({status:this.status,body});}};
  canvas.server.emit('request',req,res);
 });
}
(async()=>{
 try {
  for(const route of ['/api/sessions','/artifact/abcdefabcdef/']) {
   assert.equal((await request(route)).status,403,route);
   assert.equal((await request(route,'wrong')).status,403,route);
  }
  assert.match(canvas.token,/^[a-f0-9]{64}$/);
  assert.equal((await request('/api/sessions',canvas.token)).status,200);
  assert.equal((await request('/artifact/abcdefabcdef/escape',canvas.token)).status,403);
  assert.notEqual(canvas.token,createPlanCanvasServer({store}).token);
 } finally {fs.rmSync(dir,{recursive:true});}
})().catch(e=>{console.error(e);process.exitCode=1});
"""
        proc = subprocess.run(["node", "-e", script, str(server)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

if __name__ == "__main__":
    unittest.main()
