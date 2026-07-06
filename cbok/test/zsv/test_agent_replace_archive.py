import os
import shutil
import tarfile
import tempfile
import unittest

from cbok.bbx.zsv import agent_replace


class AgentReplaceArchiveTest(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.repo)

    def touch(self, path, content="# test\n"):
        full_path = os.path.join(self.repo, *path.split("/"))
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as fd:
            fd.write(content)

    def test_archive_contains_runtime_paths_only(self):
        self.touch("kvmagent/kvmagent/plugins/vm_plugin.py", "vm")
        self.touch("zstacklib/zstacklib/utils/linux.py", "linux")
        files = agent_replace.validate_changed_files(
            self.repo,
            [
                "kvmagent/kvmagent/plugins/vm_plugin.py",
                "zstacklib/zstacklib/utils/linux.py",
            ],
        )

        archive_path = agent_replace.create_agent_archive(files)
        self.addCleanup(lambda: os.path.exists(archive_path) and os.unlink(archive_path))

        with tarfile.open(archive_path, "r:gz") as tar:
            self.assertEqual(
                [
                    "kvmagent/plugins/vm_plugin.py",
                    "zstacklib/utils/linux.py",
                ],
                sorted(tar.getnames()),
            )

    def test_remote_apply_script_backs_up_compiles_imports_and_restarts(self):
        self.touch("kvmagent/kvmagent/plugins/vm_plugin.py")
        files = agent_replace.validate_changed_files(
            self.repo,
            ["kvmagent/kvmagent/plugins/vm_plugin.py"],
        )

        script = agent_replace.build_remote_apply_script(
            "/tmp/cbok-zsv-agent",
            files,
            site_packages="/var/lib/zstack/virtualenv/kvm/lib/python2.7/site-packages",
            virtualenv="/var/lib/zstack/virtualenv/kvm",
            backup_root="/var/lib/zstack/agent-replace-backup",
            restart_agent=True,
        )

        self.assertIn('cp -a "$SITE_PACKAGES/$pkg" "$BACKUP_DIR/$pkg"', script)
        self.assertIn("packages=(kvmagent)", script)
        self.assertIn('backup_package "$pkg"', script)
        self.assertIn('cp -f "$src" "$dst"', script)
        self.assertIn('-m compileall -q "$SITE_PACKAGES/$pkg"', script)
        self.assertIn('PYTHONPATH="$SITE_PACKAGES${PYTHONPATH:+:$PYTHONPATH}"', script)
        self.assertIn("import kvmagent", script)
        self.assertIn("zstack-kvmagent", script)
        self.assertNotIn('SITE_PACKAGES" == "auto"', script)
        self.assertNotIn("distutils.sysconfig", script)

    def test_remote_apply_script_can_restart_ceph_primary_agent(self):
        self.touch("cephprimarystorage/cephprimarystorage/cephagent.py")
        files = agent_replace.validate_changed_files(
            self.repo,
            ["cephprimarystorage/cephprimarystorage/cephagent.py"],
        )

        script = agent_replace.build_remote_apply_script(
            "/tmp/cbok-zsv-agent",
            files,
            site_packages="/var/lib/zstack/virtualenv/cephp/lib/python2.7/site-packages",
            virtualenv="/var/lib/zstack/virtualenv/cephp",
            backup_root="/var/lib/zstack/agent-replace-backup",
            restart_agent=True,
            service_name="zstack-ceph-primarystorage",
            process_pattern="from cephprimarystorage import cdaemon",
        )

        self.assertIn("packages=(cephprimarystorage)", script)
        self.assertIn("zstack-ceph-primarystorage", script)
        self.assertIn("import cephprimarystorage", script)

    def test_remote_apply_script_can_restart_zbs_primary_agent(self):
        self.touch("zbsprimarystorage/zbsprimarystorage/zbsagent.py")
        files = agent_replace.validate_changed_files(
            self.repo,
            ["zbsprimarystorage/zbsprimarystorage/zbsagent.py"],
        )

        script = agent_replace.build_remote_apply_script(
            "/tmp/cbok-zsv-agent",
            files,
            site_packages="/var/lib/zstack/virtualenv/zbsp/lib/python2.7/site-packages",
            virtualenv="/var/lib/zstack/virtualenv/zbsp",
            backup_root="/var/lib/zstack/agent-replace-backup",
            restart_agent=True,
            service_name="zstack-zbs-primarystorage",
            process_pattern="from zbsprimarystorage import zdaemon",
        )

        self.assertIn("packages=(zbsprimarystorage)", script)
        self.assertIn("zstack-zbs-primarystorage", script)
        self.assertIn("import zbsprimarystorage", script)
