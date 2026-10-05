import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / 'bin/ds-compression-state-recover'
NOTE = 'Compression deferred for the fifth time; no rewrite occurred. Baseline reset to current size.'


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'project'
    root.mkdir()
    (root / '.git').mkdir()
    (root / '.agentic').mkdir()
    for name in ['MEMORY.md', 'CLAUDE.md', '.agentic/memory.md']:
        (root / name).write_text('retained knowledge\n' * 200)
    return root


def entry(**kwargs):
    return dict(last_compressed_size_bytes=546012, last_compressed_at='2026-08-23',
                original_backup_path=None, rolling_snapshots=[], note=NOTE, **kwargs)


def state(root, entries=None):
    p = root / '.agentic/compression-state.json'
    p.write_text(json.dumps({'extra': {'preserve': [1, None, False]}, 'targets': entries or {
        str(root / 'MEMORY.md'): entry(), str(root / '.agentic/memory.md'): entry(),
        str(root / 'CLAUDE.md'): dict(last_compressed_size_bytes=100, last_compressed_at='2026-08-23'),
        'unrelated': {'custom': 'untouched'},
    }}, indent=3) + '\n')
    return p


def run(root, *args, env=None):
    return subprocess.run([str(CLI), *args, '--dir', str(root)], capture_output=True, text=True,
                          env=env, timeout=10)


def review(root):
    result = run(root)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    p = root.parent / 'review.json'
    p.write_text(json.dumps(report))
    return p, report


def inventory(root):
    return [(str(p.relative_to(root)), p.lstat().st_mtime_ns, digest(p) if p.is_file() else None)
            for p in sorted(root.rglob('*'))]


def test_inspect_apply_preservation_noop_and_rollback(project):
    p = state(project)
    original = p.read_bytes()
    before = inventory(project)
    plan, report = review(project)
    assert before == inventory(project)
    assert len(report['candidates']) == 2
    result = run(project, 'apply', '--plan', str(plan))
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    backup = Path(output['backup_path'])
    assert backup.read_bytes() == original
    assert backup.stat().st_mode & 0o777 == 0o600
    assert output['backup_sha256'] == hashlib.sha256(original).hexdigest()
    updated = json.loads(p.read_text())
    assert updated['extra'] == json.loads(original)['extra']
    assert updated['targets'] == {k: v for k, v in json.loads(original)['targets'].items()
                                  if k not in output['changed_targets']}
    for name in ['MEMORY.md', '.agentic/memory.md']:
        assert str(project / name) not in updated['targets']
        assert (project / name).stat().st_size > 2000
    assert not (project / '.agentic/wrap/lock').exists()
    memory = {name: digest(project / name) for name in ['MEMORY.md', 'CLAUDE.md', '.agentic/memory.md']}
    plan, report = review(project)
    unchanged = p.read_bytes()
    noop = run(project, 'apply', '--plan', str(plan))
    assert noop.returncode == 0, noop.stderr
    assert json.loads(noop.stdout)['backup_path'] is None
    assert p.read_bytes() == unchanged
    # Restore exact bytes while using the same in-process lock API.
    script = '''const fs=require('fs');const w=require(process.argv[1]);const root=process.argv[2];
    const token='rollback';if(!w.acquireWrapLock(root,String(process.pid),null,{role:'commit',pid:process.pid,token}))process.exit(5);
    try{fs.copyFileSync(process.argv[3],process.argv[4]);}finally{if(w.releaseWrapLock(root,token)!=='released')process.exit(1);}'''
    restored = subprocess.run(['node', '-e', script, str(REPO / 'hooks/lib/wrap-marker.js'),
                               str(project), str(backup), str(p)], capture_output=True)
    assert restored.returncode == 0
    assert p.read_bytes() == original
    assert memory == {name: digest(project / name) for name in memory}


@pytest.mark.parametrize('changes', [
    {'note': 'Compression deferred; baseline reset'},
    {'note': NOTE + ' Curation successful.'}, {'note': 'not deferred'},
    {'extra_field': True}, {'original_backup_path': '/backup'}, {'rolling_snapshots': ['/snapshot']},
    {'entries_deleted_last_run': 1}, {'entries_merged_last_run': None},
    {'last_compressed_size_bytes': -1}, {'last_compressed_size_bytes': 2.5},
    {'last_compressed_at': '2026-02-30'}, {'last_compressed_at': None},
])
def test_ambiguous_preserved(project, changes):
    candidate = entry()
    candidate.update(changes)
    p = state(project, {str(project / 'MEMORY.md'): candidate})
    original = p.read_bytes()
    plan, report = review(project)
    assert not report['candidates']
    assert report['ambiguous'][0]['entry'] == candidate
    assert run(project, 'apply', '--plan', str(plan)).returncode == 0
    assert p.read_bytes() == original


@pytest.mark.parametrize('raw', ['{"targets":{},"targets":{}}', '{"targets":{"x":null}}',
                                '{"targets":[]}', '[]', '{broken',
                                '{"targets":{"x":{"a":1,"\\u0061":2}}}'])
def test_bad_state(project, raw):
    p = state(project)
    p.write_text(raw)
    original = p.read_bytes()
    assert run(project).returncode == 1
    assert p.read_bytes() == original
    assert not (project / '.agentic/wrap').exists()


@pytest.mark.parametrize('args', [['bogus'], ['--bad'], ['--plan', 'file'], ['apply'],
                                 ['--dir'], ['inspect', 'apply'], ['--dir', '/tmp']])
def test_usage(project, args):
    assert run(project, *args).returncode == 2


def test_missing_state_target_and_subdirectory(project):
    before = inventory(project)
    result = run(project)
    assert result.returncode == 0
    assert json.loads(result.stdout)['state_sha256'] is None
    assert inventory(project) == before
    state(project)
    (project / 'MEMORY.md').unlink()
    plan, report = review(project)
    assert report['targets'][str(project / 'MEMORY.md')] == {'exists': False}
    sub = project / 'sub'
    sub.mkdir()
    nested = run(sub)
    assert json.loads(nested.stdout)['project_root'] == str(project)
    assert run(project, 'apply', '--plan', str(plan)).returncode == 0


@pytest.mark.parametrize('mutation', ['state', 'content', 'deleted', 'replaced', 'report'])
def test_stale_review(project, mutation):
    p = state(project)
    plan, _ = review(project)
    target = project / 'MEMORY.md'
    if mutation == 'state':
        p.write_text(p.read_text() + ' ')
    elif mutation == 'content':
        st = target.stat()
        target.write_bytes(b'x' * st.st_size)
        os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns))
    elif mutation == 'deleted':
        target.unlink()
    elif mutation == 'replaced':
        content = target.read_bytes()
        target.unlink()
        target.write_bytes(content)
    else:
        report = json.loads(plan.read_text())
        report['ambiguous'] = []
        plan.write_text(json.dumps(report))
    original = p.read_bytes()
    assert run(project, 'apply', '--plan', str(plan)).returncode == 1
    assert p.read_bytes() == original
    assert not (project / '.agentic/wrap/lock').exists()


@pytest.mark.parametrize('where', ['state', 'target', 'ancestry', 'lock'])
def test_symlink_refusal(project, where):
    p = state(project)
    plan, _ = review(project)
    external = project.parent / 'external'
    external.mkdir()
    sentinel = external / 'sentinel'
    sentinel.write_text('never change')
    before = digest(sentinel)
    if where == 'state':
        p.unlink(); p.symlink_to(sentinel)
    elif where == 'target':
        target = project / 'MEMORY.md'
        target.unlink(); target.symlink_to(sentinel)
    elif where == 'ancestry':
        old = project / '.agentic'
        old.rename(external / 'agentic')
        old.symlink_to(external / 'agentic', target_is_directory=True)
    else:
        wrap = project / '.agentic/wrap'
        wrap.mkdir()
        (wrap / 'lock').symlink_to(external, target_is_directory=True)
    assert run(project, 'apply', '--plan', str(plan)).returncode == 1
    assert digest(sentinel) == before


def test_busy_lock(project):
    state(project)
    plan, _ = review(project)
    holder = subprocess.Popen(['node', '-e', '''const w=require(process.argv[1]);
    if(!w.acquireWrapLock(process.argv[2],String(process.pid),null,{role:'commit',pid:process.pid,token:'holder'}))process.exit(1);
    console.log('held');setInterval(()=>{},1000);''', str(REPO / 'hooks/lib/wrap-marker.js'), str(project)],
                              stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == 'held'
        assert run(project, 'apply', '--plan', str(plan)).returncode == 5
        assert (project / '.agentic/wrap/lock/owner.json').exists()
    finally:
        holder.terminate(); holder.wait(timeout=5)


@pytest.mark.parametrize('phase', ['before', 'after'])
@pytest.mark.parametrize('replacement', ['symlink', 'foreign', 'malformed'])
def test_lock_replacement_preserved(project, phase, replacement):
    p = state(project)
    original = p.read_bytes()
    plan, _ = review(project)
    external = project.parent / 'external'
    external.mkdir()
    sentinel = external / 'sentinel'
    sentinel.write_text('external immutable')
    preload = project.parent / 'inject.js'
    preload.write_text('''const fs=require('fs'),path=require('path');const rename=fs.renameSync;
    const root=process.env.TEST_ROOT,lock=path.join(root,'.agentic/wrap/lock');
    const initialLstat=fs.lstatSync;let fired=false;
    function replace(){if(fired)return;fired=true;rename(lock,lock+'-original');
      if(process.env.REPLACEMENT==='symlink')fs.symlinkSync(process.env.EXTERNAL,lock,'dir');
      else{fs.mkdirSync(lock);let owner=JSON.parse(fs.readFileSync(lock+'-original/owner.json'));
        fs.writeFileSync(lock+'/owner.json',process.env.REPLACEMENT==='foreign'?JSON.stringify({...owner,token:'foreign'}):'{bad');}}
    fs.renameSync=function(from,to){if(to===path.join(root,'.agentic/compression-state.json')){
      if(process.env.PHASE==='before'){replace();return rename(from,to);}
      const result=rename(from,to);replace();return result;}return rename(from,to);};
    const sync=fs.fsyncSync;fs.fsyncSync=function(fd){const result=sync(fd);
      if(process.env.PHASE==='before'&&!fired){let name;try{name=fs.readlinkSync('/proc/self/fd/'+fd);}catch{}
        // macOS has no /proc: inspect the just-created recovery backup instead.
        if(fs.existsSync(lock)&&fs.readdirSync(path.join(root,'.agentic')).some(x=>x.startsWith('compression-state.recovery-')))replace();}
      return result;};
    ''')
    env = dict(os.environ, NODE_OPTIONS=f'--require={preload}', TEST_ROOT=str(project),
               PHASE=phase, REPLACEMENT=replacement, EXTERNAL=str(external))
    result = run(project, 'apply', '--plan', str(plan), env=env)
    assert result.returncode == 1, result.stderr
    output = json.loads(result.stdout)
    lock = project / '.agentic/wrap/lock'
    assert lock.is_symlink() if replacement == 'symlink' else lock.is_dir()
    assert sentinel.read_text() == 'external immutable'
    assert output['published'] == (phase == 'after')
    assert (p.read_bytes() == original) == (phase == 'before')
    assert Path(output['backup_path']).read_bytes() == original


@pytest.mark.parametrize('failure', ['race', 'write', 'rename'])
def test_publication_failure(project, failure):
    p = state(project)
    plan, _ = review(project)
    original = p.read_bytes()
    preload = project.parent / 'failure.js'
    preload.write_text('''const fs=require('fs'),path=require('path');const root=process.env.TEST_ROOT;
    const sync=fs.fsyncSync;let fired=false;fs.fsyncSync=function(fd){const result=sync(fd);
    if(!fired&&fs.readdirSync(path.join(root,'.agentic')).some(x=>x.startsWith('compression-state.recovery-'))){
      fired=true;if(process.env.FAILURE==='race')fs.appendFileSync(path.join(root,'.agentic/compression-state.json'),' ');
      if(process.env.FAILURE==='write')throw Error('injected fsync failure');}return result;};
    const rename=fs.renameSync;fs.renameSync=function(a,b){if(process.env.FAILURE==='rename'&&b.endsWith('/compression-state.json'))throw Error('injected rename failure');return rename(a,b);};''')
    env = dict(os.environ, NODE_OPTIONS=f'--require={preload}', TEST_ROOT=str(project), FAILURE=failure)
    result = run(project, 'apply', '--plan', str(plan), env=env)
    assert result.returncode == 1, result.stderr
    assert p.read_bytes() == original + (b' ' if failure == 'race' else b'')
    output = json.loads(result.stdout)
    assert Path(output['backup_path']).read_bytes() == original
    assert not (project / '.agentic/wrap/lock').exists()
    assert not list((project / '.agentic').glob('*.tmp'))
