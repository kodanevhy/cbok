import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cbok.bbx.zsv import compile, worktree_container
from cbok.test.zsv.test_worktree_container import FakeRunner, FakeWorktreeContainerStore


class EeCompileLayoutTest(unittest.TestCase):
    def spec(self, root='/repo/zsvirt', ee='/repo/zsvirt-ee'):
        return worktree_container.WorktreeContainerSpec(
            zstack_root=root, ee_root=ee, docker_host='tcp://build:2375',
            image='builder', build_profile='ee')

    def test_builtin_premium_and_external_ee_use_the_same_ee_reactor(self):
        plan = compile.maven_build_plan(['plugin/kvm', 'premium/mevoco'], ['zvf'])
        self.assertEqual(['plugin/kvm', 'premium/mevoco', 'zsvirt-ee/zvf'], plan.modules)
        self.assertEqual(['ee'], plan.profiles)
        self.assertEqual(['ee'], compile.maven_build_plan(['plugin/kvm'], []).profiles)
        targets = compile._docker_sync_target_lines(plan, '/work/zstack', '/work/zstack/zsvirt-ee')
        self.assertIn('sync_target /work/zstack /out/zstack premium/mevoco', targets)
        self.assertIn('sync_target /work/zstack/zsvirt-ee /out/ee zvf', targets)

    def test_ee_container_cannot_reuse_premium_build_state(self):
        spec = self.spec()
        legacy = replace(spec, build_profile='premium')
        self.assertNotEqual(worktree_container.worktree_key_for_spec(spec),
                            worktree_container.worktree_key_for_spec(legacy))
        script = worktree_container.full_compile_script(spec)
        self.assertIn('./runMavenProfile ee', script)
        self.assertNotIn('/testlib', script)
        self.assertNotIn('runMavenProfile premium', script)

    def test_main_archive_keeps_builtin_premium_and_excludes_external_ee(self):
        with tempfile.TemporaryDirectory(prefix='cbok ee ') as td:
            root = Path(td) / 'zsvirt'
            for file in ('premium/mevoco/source.java', 'plugin/kvm/source.java',
                         'zsvirt-ee/stale.java', 'premium/mevoco/target/stale.class'):
                path = root / file
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('data')
            runner = FakeRunner()
            worktree_container.sync_sources_to_container(runner, self.spec(str(root)), 'test-container')
            scripts = [cmd[-1] for cmd, _ in runner.commands]
            archive = next(s for s in scripts if 'tar $tar_extra_opts -C' in s and str(root) in s)
            tar_command = archive.split(' | ', 1)[0]
            listing = subprocess.check_output(['bash', '-lc', tar_command + ' | tar -tzf -'], text=True)
            self.assertIn('./premium/mevoco/source.java', listing)
            self.assertIn('./plugin/kvm/source.java', listing)
            self.assertNotIn('stale.java', listing)
            self.assertNotIn('stale.class', listing)
            sync = next(s for s in scripts if 'rsync -a --delete' in s)
            self.assertIn('/work/zstack/zsvirt-ee', sync)
            self.assertNotIn('--exclude premium', sync)

    def test_ee_profile_survives_container_spec_normalization_and_reuse(self):
        runner = FakeRunner()
        store = FakeWorktreeContainerStore()
        rc, handle = worktree_container.ensure_worktree_container(runner, self.spec(), state_store=store)
        self.assertEqual(0, rc)
        self.assertEqual('/work/zstack/zsvirt-ee', handle.work_ee)
        self.assertTrue(handle.full_compile_ran)
        rc, reused = worktree_container.ensure_worktree_container(runner, self.spec(), state_store=store)
        self.assertEqual(0, rc)
        self.assertFalse(reused.full_compile_ran)
        scripts = [cmd[-1] for cmd, _ in runner.commands]
        self.assertEqual(1, sum('./runMavenProfile ee' in s for s in scripts))

    def test_embedded_premium_spring_files_follow_war_overlay_order(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'zsvirt'
            ee = Path(td) / 'ee'
            relative = 'conf/springConfigXml/Service.xml'
            for base in (root, root / 'premium', ee):
                path = base / relative
                path.parent.mkdir(parents=True)
                path.write_text('<beans/>')
            files = compile.collect_web_classes_files(str(root), [relative], [], str(ee))
            self.assertEqual(str(ee / relative), files[0].source)
            (ee / relative).unlink()
            files = compile.collect_web_classes_files(str(root), ['premium/' + relative], [], str(ee))
            self.assertEqual(str(root / 'premium' / relative), files[0].source)
            self.assertEqual('springConfigXml/Service.xml', files[0].relative_path)

    def test_test_modules_are_not_deployed_as_runtime_jars(self):
        for module in ('tests/test-simple', 'tests/testlib-simple', 'tests-ee/test-ee',
                       'premium/test-premium', 'premium/testlib-premium'):
            self.assertTrue(compile._is_auto_excluded(module), module)
        self.assertFalse(compile._is_auto_excluded('premium/mevoco'))

    def test_ee_state_never_uses_premium_fields(self):
        spec = compile._compile_worktree_spec('/repo/zsvirt', '/repo/zsvirt-ee',
                                             compile.RemoteDockerCompileConfig(image='builder', docker_host='tcp://build:2375', platform='', workdir='/work', container_name='auto', m2_volume='auto'))
        self.assertIsNone(spec.premium_root)
        self.assertEqual('/repo/zsvirt-ee', spec.ee_root)
        record = worktree_container._default_record(spec)
        self.assertEqual('', record.premium_root)
        self.assertEqual('/repo/zsvirt-ee', record.ee_root)
        runner = FakeRunner()
        store = FakeWorktreeContainerStore()
        rc, handle = worktree_container.ensure_worktree_container(runner, spec, state_store=store)
        self.assertEqual(0, rc)
        self.assertEqual('/work/zstack/premium', handle.work_premium)
        self.assertEqual('/work/zstack/zsvirt-ee', handle.work_ee)
        self.assertNotEqual(worktree_container.worktree_key_for_spec(spec),
                            worktree_container.worktree_key_for_spec(replace(spec, ee_root='/repo/other-ee')))

        obj = SimpleNamespace(premium_root='/old/premium', last_premium_modules='["old"]', save=Mock())
        manager = Mock()
        manager.get_or_create.return_value = (obj, False)
        manager.filter.return_value.first.return_value = obj
        with patch.object(compile.ZsvCompileState, 'objects', manager):
            db = compile.DjangoCompileDeployStateStore()
            selection = compile.CompileDeploySelection(['premium/mevoco'], ['zvf'], [])
            db.save_selection('key', spec.zstack_root, spec.ee_root, selection)
            self.assertEqual(selection, db.load_selection('key'))
        self.assertEqual('/old/premium', obj.premium_root)
        self.assertEqual('["old"]', obj.last_premium_modules)
        self.assertEqual(spec.ee_root, obj.ee_root)
        self.assertNotIn('premium_root', obj.save.call_args.kwargs['update_fields'])
