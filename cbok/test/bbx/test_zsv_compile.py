import argparse
import configparser
import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

from cbok.bbx.zsv import compile
from cbok.bbx.zsv import groovy_test
from cbok.bbx.zsv import worktree_container
from cbok.conf import config as cbok_config


class FakeWorktreeContainerStore:
    def __init__(self):
        self.records = {}

    def get_or_create(self, defaults):
        existing = self.records.get(defaults.worktree_key)
        if existing:
            return existing, False
        self.records[defaults.worktree_key] = defaults
        return defaults, True

    def save(self, record, update_fields=None):
        self.records[record.worktree_key] = record

    def find_by_container_name(self, container_name):
        for record in self.records.values():
            if record.container_name == container_name:
                return record
        return None


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.containers = set()

    def run_command(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if isinstance(cmd, list) and cmd[:2] == ["bash", "-lc"]:
            script = cmd[-1]
            if "df -Pk /" in script:
                return SimpleNamespace(returncode=0, stdout="%d\n" % (100 * 1024 * 1024), stderr="")
            if "docker inspect" in script:
                return SimpleNamespace(returncode=1, stdout="", stderr="")
            if "docker create" in script:
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return SimpleNamespace(returncode=0, stdout="0\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")


def _conf(**values):
    parser = configparser.ConfigParser()
    parser.add_section("zsv_compile")
    base_ref = values.pop("base_ref", None)
    if base_ref is not None:
        parser.add_section("zsv")
        parser.set("zsv", "base_ref", str(base_ref))
    for key, value in values.items():
        parser.set("zsv_compile", key, str(value))
    return parser


class ZsvCompileTest(unittest.TestCase):
    def setUp(self):
        self._orig_conf = compile.settings.CONF
        self._orig_auto_detect_modules = compile.auto_detect_modules
        self._orig_git_summary = compile.git_summary
        self._orig_git = compile._git
        self._orig_validate_changed_paths_base_ref = compile.validate_changed_paths_base_ref
        self._orig_local_jar_copy_root_for_root = compile._local_jar_copy_root_for_root
        self._orig_collect_changed_web_classes_files = compile.collect_changed_web_classes_files
        self._orig_default_compile_state_store = compile.default_compile_deploy_state_store
        self._orig_default_state_store = worktree_container.default_state_store
        rebase_patch = patch.object(compile.zsv_base_ref, "rebase_worktree", return_value=True)
        self._rebase_worktree = rebase_patch.start()
        self.addCleanup(rebase_patch.stop)
        clean_patch = patch.object(compile.zsv_base_ref, "check_worktree_clean", return_value=True)
        self._check_worktree_clean = clean_patch.start()
        self.addCleanup(clean_patch.stop)
        self._worktree_store = FakeWorktreeContainerStore()
        self._compile_state_store = compile.InMemoryCompileDeployStateStore()
        compile.default_compile_deploy_state_store = lambda: self._compile_state_store
        worktree_container.default_state_store = lambda: self._worktree_store

    def tearDown(self):
        compile.settings.CONF = self._orig_conf
        compile.auto_detect_modules = self._orig_auto_detect_modules
        compile.git_summary = self._orig_git_summary
        compile._git = self._orig_git
        compile.validate_changed_paths_base_ref = self._orig_validate_changed_paths_base_ref
        compile._local_jar_copy_root_for_root = self._orig_local_jar_copy_root_for_root
        compile.collect_changed_web_classes_files = self._orig_collect_changed_web_classes_files
        compile.default_compile_deploy_state_store = self._orig_default_compile_state_store
        worktree_container.default_state_store = self._orig_default_state_store

    def _allow_changed_paths_base_ref_validation(self):
        compile.validate_changed_paths_base_ref = lambda _root: True

    def test_remote_docker_conf_reads_optional_values(self):
        compile.settings.CONF = _conf(
            remote_docker_image="zstack-buildbin:debug7-arm64",
            remote_docker_platform="linux/arm64",
            remote_docker_host="http://172.26.50.70:2375",
            remote_docker_workdir="/zwork",
            remote_docker_m2_volume="zsv-m2",
            remote_docker_min_free_gb="42",
        )

        conf = compile.remote_docker_compile_from_conf()

        self.assertEqual("zstack-buildbin:debug7-arm64", conf.image)
        self.assertEqual("linux/arm64", conf.platform)
        self.assertEqual("tcp://172.26.50.70:2375", conf.docker_host)
        self.assertEqual("/zwork", conf.workdir)
        self.assertEqual("auto", conf.container_name)
        self.assertEqual("zsv-m2", conf.m2_volume)
        self.assertEqual(42, conf.min_free_gb)
        self.assertFalse(hasattr(conf, "ee_source"))

    def test_remote_docker_conf_defaults_to_worktree_scoped_m2(self):
        compile.settings.CONF = _conf()

        conf = compile.remote_docker_compile_from_conf()

        self.assertEqual("auto", conf.m2_volume)
        self.assertEqual(20, conf.min_free_gb)
        image = "registry.docker.zstack.io:80/buildbin:debug9-zsvirt"
        self.assertEqual(image, conf.image)
        self.assertEqual(image, groovy_test.FALLBACK_IMAGE)
        option = next(opt for opt in cbok_config.ZSV_COMPILE.options if opt.name == "remote_docker_image")
        self.assertEqual(image, option.default)

    def test_compile_deploy_state_key_is_scoped_to_base_ref(self):
        compile.settings.CONF = _conf(base_ref="origin/feature")
        remote = compile.remote_docker_compile_from_conf()
        feature_key = compile.compile_worktree_key("/zstack", "/ee", remote)

        compile.settings.CONF = _conf(base_ref="origin/zsv_5.1.0")
        zsv_key = compile.compile_worktree_key("/zstack", "/ee", remote)

        self.assertNotEqual(feature_key, zsv_key)

    def test_validate_changed_paths_base_ref_fetches_upstream_branch_first(self):
        compile.settings.CONF = _conf(base_ref="origin/feature/zsv")
        calls = []

        def fake_git(repo, *args):
            calls.append(args)
            if args == ("remote", "get-url", "origin"):
                return subprocess.CompletedProcess(["git"], 0, "git@example.invalid/repo.git\n", "")
            if args == ("fetch", "origin", "+refs/heads/feature/zsv:refs/remotes/origin/feature/zsv"):
                return subprocess.CompletedProcess(["git"], 0, "", "")
            if args == ("merge-base", "--is-ancestor", "origin/feature/zsv", "HEAD"):
                return subprocess.CompletedProcess(["git"], 0, "", "")
            raise AssertionError("unexpected git command: %s" % (args,))

        compile._git = fake_git

        self.assertTrue(compile.validate_changed_paths_base_ref("/repo"))
        self.assertEqual([
            ("remote", "get-url", "origin"),
            ("fetch", "origin", "+refs/heads/feature/zsv:refs/remotes/origin/feature/zsv"),
            ("merge-base", "--is-ancestor", "origin/feature/zsv", "HEAD"),
        ], calls)

    def test_validate_changed_paths_base_ref_requires_configured_base_ref(self):
        compile.settings.CONF = _conf()

        with self.assertLogs(compile.LOG.name, level="ERROR") as logs:
            self.assertFalse(compile.validate_changed_paths_base_ref("/repo"))

        self.assertIn(
            "ZSV base_ref is not configured",
            "\n".join(logs.output),
        )

    def test_zsv_compile_config_does_not_expose_profile_switch(self):
        option_names = [opt.name for opt in cbok_config.ZSV_COMPILE.options]
        zsv_option_names = [opt.name for opt in cbok_config.ZSV.options]

        self.assertNotIn("run_maven_profile_premium", option_names)
        self.assertNotIn("remote_docker_premium_source", option_names)
        self.assertNotIn("base_ref", option_names)
        self.assertIn("base_ref", zsv_option_names)
        self.assertIn("remote_docker_min_free_gb", option_names)

    def test_run_compile_flow_requires_zsvirt_root(self):
        runner = FakeRunner()

        with self.assertLogs(compile.LOG.name, level="ERROR") as logs:
            rc = compile.run_compile_flow(
                address=None,
                remote_lib=compile.DEFAULT_REMOTE_LIB,
                no_deploy=True,
                ee_root="/repo/ee",
                runner=runner,
            )

        self.assertEqual(1, rc)
        self.assertIn("--zsvirt-root is required", "\n".join(logs.output))
        self.assertEqual([], runner.calls)

    def test_compile_cli_forwards_distinct_repository_roots(self):
        from cbok.cmd import zsv

        parser = argparse.ArgumentParser()
        for options, kwargs in zsv.ZSphereCommands.compile._args:
            parser.add_argument(*options, **kwargs)
        argv = ["--zsvirt-root", "/repo/zsvirt", "--ee-root", "/repo/zsvirt-ee", "--no-deploy",
                "--web-class", "zsvirt:premium/conf/springConfigXml/crypto.xml",
                "--web-class", "ee:conf/springConfigXml/ee/coreEe.xml"]
        with patch.object(zsv, "run_compile_flow", return_value=0) as flow:
            self.assertEqual(0, zsv.ZSphereCommands().compile(**vars(parser.parse_args(argv))))
        self.assertEqual("/repo/zsvirt", flow.call_args.kwargs["zsvirt_root"])
        self.assertEqual("/repo/zsvirt-ee", flow.call_args.kwargs["ee_root"])
        self.assertEqual([argv[-3], argv[-1]], flow.call_args.kwargs["extra_web_classes"])
        self.assertTrue(flow.call_args.kwargs["no_deploy"])
        self.assertIsNone(flow.call_args.kwargs["address"])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["--zstack-root", "/repo/main", "--premium-root", "/repo/premium"])

    def test_run_compile_flow_defaults_to_worktree_container_name(self):
        compile.settings.CONF = _conf(
            remote_docker_host="tcp://172.26.50.70:2375",
            remote_docker_image="zstack-buildbin:debug7-arm64",
            base_ref="origin/test-base",
        )
        self._allow_changed_paths_base_ref_validation()
        compile.auto_detect_modules = lambda _root, _ee_root=None: (["plugin/foo"], [])
        compile.git_summary = lambda _root: ("abc123 test", "abc123")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            ee = Path(td) / "ee"
            (root / "plugin" / "foo").mkdir(parents=True)
            ee.mkdir(parents=True)
            (root / "pom.xml").write_text("<project/>", encoding="utf-8")
            (root / "plugin" / "foo" / "pom.xml").write_text(
                "<project/>", encoding="utf-8")
            runner = FakeRunner()

            rc = compile.run_compile_flow(
                address=None,
                remote_lib=compile.DEFAULT_REMOTE_LIB,
                no_deploy=True,
                zsvirt_root=str(root),
                ee_root=str(ee),
                pr_url=(
                    "zsvirt=http://dev.zstack.io:9080/zvf/zsvirt/-/merge_requests/10001,"
                    "zsvirt-ee=http://dev.zstack.io:9080/zvf/zsvirt-ee/-/merge_requests/20002"
                ),
                runner=runner,
            )

        self.assertEqual(0, rc)
        shell_scripts = [
            cmd[-1] for cmd, _kwargs in runner.calls
            if isinstance(cmd, list) and cmd[:2] == ["bash", "-lc"]
        ]
        self.assertTrue(any("--name cbok-zsv-worktree-zstack-" in script for script in shell_scripts))
        self.assertFalse(any("zsv-remote" in script for script in shell_scripts))

    def test_run_compile_flow_uses_remote_docker_daemon_without_bind_mounts(self):
        compile.settings.CONF = _conf(
            remote_docker_image="registry.docker.zstack.io:80/buildbin:debug7",
            remote_docker_platform="linux/amd64",
            remote_docker_host="http://172.26.50.70:2375",
            remote_docker_workdir="/work",
            remote_docker_m2_volume="zsv-m2",
            base_ref="origin/test-base",
        )
        self._allow_changed_paths_base_ref_validation()
        compile.auto_detect_modules = lambda _root, _ee_root=None: (["plugin/foo"], [])
        compile.git_summary = lambda _root: ("abc123 test", "abc123")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            ee = Path(td) / "ee"
            (root / "plugin" / "foo").mkdir(parents=True)
            (root / "testlib").mkdir(parents=True)
            (ee / "tests-ee/testlib-ee").mkdir(parents=True)
            (root / "pom.xml").write_text("<project/>", encoding="utf-8")
            (root / "plugin" / "foo" / "pom.xml").write_text("<project/>", encoding="utf-8")
            runner = FakeRunner()

            rc = compile.run_compile_flow(
                address=None,
                remote_lib=compile.DEFAULT_REMOTE_LIB,
                no_deploy=True,
                zsvirt_root=str(root),
                ee_root=str(ee),
                pr_url=(
                    "zsvirt=http://dev.zstack.io:9080/zvf/zsvirt/-/merge_requests/10001,"
                    "zsvirt-ee=http://dev.zstack.io:9080/zvf/zsvirt-ee/-/merge_requests/20002"
                ),
                runner=runner,
            )

        self.assertEqual(0, rc)
        self.assertFalse(
            any(isinstance(cmd, list) and cmd[:2] == ["docker", "run"] for cmd, _kwargs in runner.calls)
        )
        shell_scripts = [
            cmd[-1] for cmd, _kwargs in runner.calls
            if isinstance(cmd, list) and cmd[:2] == ["bash", "-lc"]
        ]
        self.assertTrue(any("DOCKER_HOST=tcp://172.26.50.70:2375 docker create" in script for script in shell_scripts))
        records = list(self._worktree_store.records.values())
        self.assertEqual(
            (
                worktree_container.WorktreePullRequest(
                    repo="zsvirt",
                    pr_url="http://dev.zstack.io:9080/zvf/zsvirt/-/merge_requests/10001",
                ),
                worktree_container.WorktreePullRequest(
                    repo="zsvirt-ee",
                    pr_url="http://dev.zstack.io:9080/zvf/zsvirt-ee/-/merge_requests/20002",
                ),
            ),
            records[0].pr_refs,
        )
        self.assertTrue(any("--platform linux/amd64" in script for script in shell_scripts))
        self.assertTrue(
            any("docker exec -i cbok-zsv-worktree-zstack-" in script and "/tmp/cbok-zsv-src/zsvirt" in script for script in shell_scripts)
        )
        archive_scripts = [script for script in shell_scripts if "tar $tar_extra_opts -C" in script and "docker exec -i" in script]
        self.assertTrue(any("COPYFILE_DISABLE=1 COPY_EXTENDED_ATTRIBUTES_DISABLE=1 tar $tar_extra_opts -C" in script for script in archive_scripts))
        self.assertTrue(any("--no-xattrs" in script and "--no-mac-metadata" in script for script in archive_scripts))
        self.assertTrue(any("--exclude '._*'" in script for script in archive_scripts))
        self.assertTrue(any("--exclude '*/._*'" in script for script in archive_scripts))
        self.assertTrue(any("--exclude .DS_Store" in script for script in archive_scripts))
        docker_cp_scripts = [
            script for script in shell_scripts
            if "DOCKER_HOST=tcp://172.26.50.70:2375 docker cp cbok-zsv-worktree-zstack-" in script
            and ":/tmp/cbok-zsv-out/" in script
        ]
        self.assertTrue(docker_cp_scripts)
        self.assertFalse(any(str(root) in script for script in docker_cp_scripts))
        self.assertFalse(any(str(ee) in script for script in docker_cp_scripts))
        self.assertTrue(any("cbok-zsv-jars-" in script for script in docker_cp_scripts))
        build_scripts = [script for script in shell_scripts if "docker exec cbok-zsv-worktree-zstack-" in script and " bash -lc" in script]
        self.assertGreaterEqual(len(build_scripts), 3)
        self.assertTrue(any("./runMavenProfile ee" in script for script in build_scripts))
        self.assertFalse(any("mvn -T 12 -Dmaven.test.skip=true -P ee clean install" in script for script in build_scripts))
        self.assertFalse(any("cd /work/zsvirt/testlib" in script for script in build_scripts))
        self.assertNotIn("mvn -DskipTests clean install -pl plugin/foo", build_scripts[-1])
        self.assertIn("sync_target /work/zsvirt /tmp/cbok-zsv-out/zsvirt plugin/foo", build_scripts[-1])
        self.assertIn('local props="$target/maven-archiver/pom.properties"', build_scripts[-1])
        self.assertIn('cp "$jar" "$dest/"', build_scripts[-1])
        self.assertNotIn('rsync -a --delete "$target"/ "$dest"/', build_scripts[-1])

    def test_run_compile_flow_rejects_configured_ee_branch_mismatch(self):
        compile.settings.CONF = _conf(remote_docker_host="tcp://172.26.50.70:2375", base_ref="")
        compile.auto_detect_modules = lambda _root, _ee_root=None: (["plugin/foo"], [])

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            ee = Path(td) / "ee"
            (root / "plugin" / "foo").mkdir(parents=True)
            ee.mkdir(parents=True)
            (root / "pom.xml").write_text("<project/>", encoding="utf-8")
            (root / "plugin" / "foo" / "pom.xml").write_text(
                "<project/>", encoding="utf-8")

            branches = {
                str(root.resolve()): "feature-a",
                str(ee.resolve()): "feature-b",
            }

            def fake_git(repo, *args):
                if args == ("rev-parse", "--abbrev-ref", "HEAD"):
                    return subprocess.CompletedProcess(
                        ["git", "-C", repo, *args],
                        0,
                        branches[os.path.realpath(repo)] + "\n",
                        "",
                    )
                return subprocess.CompletedProcess(["git", "-C", repo, *args], 0, "", "")

            compile._git = fake_git
            runner = FakeRunner()

            with self.assertLogs(compile.LOG.name, level="ERROR") as logs:
                rc = compile.run_compile_flow(
                    address=None,
                    remote_lib=compile.DEFAULT_REMOTE_LIB,
                    no_deploy=True,
                    zsvirt_root=str(root),
                    ee_root=str(ee),
                    runner=runner,
                )

        self.assertEqual(1, rc)
        self.assertIn("zsvirt and ee branch names must be the same", "\n".join(logs.output))
        self.assertEqual([], runner.calls)

    def test_compile_rebases_both_sources_before_module_detection_and_container_heads(self):
        compile.settings.CONF = _conf(remote_docker_host="tcp://build:2375", base_ref="origin/main")
        compile.collect_changed_web_classes_files = lambda *_args: []
        with tempfile.TemporaryDirectory() as td:
            root, ee = Path(td) / "zsvirt", Path(td) / "zsvirt-ee"
            for module in (root / "premium/mevoco", ee / "zvf"):
                module.mkdir(parents=True)
                (module / "pom.xml").write_text("<project/>")
            (root / "pom.xml").write_text("<project/>")
            roots = [str(root.resolve()), str(ee.resolve())]
            events = []
            heads = dict.fromkeys(roots, "old-head")

            def rebase(repo):
                events.append(("rebase", repo))
                heads[repo] = "rebased-" + Path(repo).name
                return True

            def detect(main_root, ee_root):
                self.assertEqual([("rebase", roots[0]), ("rebase", roots[1])], events)
                self.assertEqual(roots, [main_root, ee_root])
                events.append(("detect", main_root))
                return ["premium/mevoco"], ["zvf"]

            self._rebase_worktree.side_effect = rebase
            compile.auto_detect_modules = detect
            compile.git_summary = lambda repo: (heads[repo], heads[repo])
            with patch.object(worktree_container, "_git_head", side_effect=lambda repo: heads[repo]):
                rc = compile.run_compile_flow(
                    address=None, remote_lib=compile.DEFAULT_REMOTE_LIB, no_deploy=True,
                    zsvirt_root=roots[0], ee_root=roots[1], runner=FakeRunner(),
                )
            self.assertEqual(0, rc)
            record = next(iter(self._worktree_store.records.values()))
            self.assertEqual("rebased-zsvirt", record.zsvirt_head)
            self.assertEqual("rebased-zsvirt-ee", record.ee_head)
            self.assertEqual([call(roots[0]), call(roots[1])], self._rebase_worktree.call_args_list)

    def test_dirty_ee_stops_before_rebasing_either_repo_or_running_docker(self):
        compile.settings.CONF = _conf(remote_docker_host="tcp://build:2375", base_ref="origin/main")
        with tempfile.TemporaryDirectory() as td:
            root, ee = Path(td) / "zsvirt", Path(td) / "zsvirt-ee"
            root.mkdir()
            ee.mkdir()
            (root / "pom.xml").write_text("<project/>")
            roots = [str(root.resolve()), str(ee.resolve())]
            self._check_worktree_clean.side_effect = lambda repo: repo != roots[1]
            runner = FakeRunner()
            with patch.object(compile, "auto_detect_modules", return_value=([], [])) as detect:
                rc = compile.run_compile_flow(
                    address=None, remote_lib=compile.DEFAULT_REMOTE_LIB, no_deploy=True,
                    zsvirt_root=roots[0], ee_root=roots[1], runner=runner,
                )

        self.assertEqual(1, rc)
        self.assertEqual([call(repo) for repo in roots], self._check_worktree_clean.call_args_list)
        self._rebase_worktree.assert_not_called()
        detect.assert_not_called()
        self.assertEqual([], runner.calls)

    def test_compile_rebase_failure_stops_before_selection_docker_or_deployment(self):
        compile.settings.CONF = _conf(remote_docker_host="tcp://build:2375", base_ref="origin/main")
        with tempfile.TemporaryDirectory() as td:
            root, ee = Path(td) / "zsvirt", Path(td) / "zsvirt-ee"
            root.mkdir()
            ee.mkdir()
            (root / "pom.xml").write_text("<project/>")
            roots = [str(root.resolve()), str(ee.resolve())]
            for failed_repo in roots:
                with self.subTest(failed_repo=failed_repo):
                    self._rebase_worktree.reset_mock()
                    self._rebase_worktree.side_effect = lambda repo: repo != failed_repo
                    runner = FakeRunner()
                    with patch.object(compile, "auto_detect_modules", return_value=([], [])) as detect, \
                            patch.object(compile, "run_mvn_in_remote_docker") as build:
                        rc = compile.run_compile_flow(
                            address="192.0.2.1", remote_lib=compile.DEFAULT_REMOTE_LIB, no_deploy=False,
                            zsvirt_root=roots[0], ee_root=roots[1], runner=runner,
                        )
                    self.assertEqual(1, rc)
                    expected_roots = roots[:roots.index(failed_repo) + 1]
                    self.assertEqual([call(repo) for repo in expected_roots], self._rebase_worktree.call_args_list)
                    detect.assert_not_called()
                    build.assert_not_called()
                    self.assertEqual([], runner.calls)
                    self.assertEqual({}, self._compile_state_store.selections_by_key)

    def test_validate_changed_paths_base_ref_rejects_unrebased_head(self):
        compile.settings.CONF = _conf(
            remote_docker_host="tcp://172.26.50.70:2375",
            base_ref="origin/feature",
        )

        def fake_git(repo, *args):
            if args == ("merge-base", "--is-ancestor", "origin/feature", "HEAD"):
                return subprocess.CompletedProcess(["git"], 1, "", "")
            return subprocess.CompletedProcess(["git"], 0, "", "")

        compile._git = fake_git
        with self.assertLogs(compile.LOG.name, level="ERROR") as logs:
            self.assertFalse(compile.validate_changed_paths_base_ref("/repo"))
        self.assertIn("Configured base ref origin/feature is not an ancestor", "\n".join(logs.output))

    def test_auto_detect_modules_combines_worktree_changes_and_head_commit(self):
        compile.settings.CONF = _conf(base_ref="")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            ee = Path(td) / "ee"
            for module in ("utils", "identity", "premium/mevoco"):
                (root / module).mkdir(parents=True)
                (root / module / "pom.xml").write_text("<project/>", encoding="utf-8")
            for module in ("zvf", "rewrite-for-ee/core-ee"):
                (ee / module).mkdir(parents=True)
                (ee / module / "pom.xml").write_text("<project/>", encoding="utf-8")

            def fake_git(repo, *args):
                repo = os.path.realpath(repo)
                if args == ("diff", "--name-only", "HEAD"):
                    out = {
                        os.path.realpath(root): "utils/src/main/java/org/zstack/utils/Digest.java\npremium/mevoco/src/main/java/org/zstack/mevoco/MevocoGlobalProperty.java\n",
                        os.path.realpath(ee): "zvf/src/main/java/org/zstack/mevoco/EnterpriseMevocoManager.java\n",
                    }.get(repo, "")
                    return subprocess.CompletedProcess(["git"], 0, out, "")
                if args == ("ls-files", "--others", "--exclude-standard"):
                    return subprocess.CompletedProcess(["git"], 0, "", "")
                if args == ("rev-parse", "--verify", "HEAD^"):
                    return subprocess.CompletedProcess(["git"], 0, "parent\n", "")
                if args == ("diff", "--name-only", "HEAD^", "HEAD"):
                    out = {
                        os.path.realpath(root): "identity/src/main/java/org/zstack/identity/Account.java\n",
                        os.path.realpath(ee): "rewrite-for-ee/core-ee/src/main/java/org/zstack/core/ee/CoreEeManager.java\n",
                    }.get(repo, "")
                    return subprocess.CompletedProcess(["git"], 0, out, "")
                return subprocess.CompletedProcess(["git"], 0, "", "")

            compile._git = fake_git

            main, ee_modules = compile.auto_detect_modules(str(root), str(ee))

        self.assertEqual(["utils", "premium/mevoco", "identity"], main)
        self.assertEqual(["zvf", "rewrite-for-ee/core-ee"], ee_modules)

    def test_auto_detect_modules_uses_groovy_test_excludes_for_test_support_modules(self):
        compile.settings.CONF = _conf(base_ref="")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            ee = Path(td) / "ee"
            for module in (root / "tests/testlib-simple", ee / "tests-ee/testlib-ee"):
                module.mkdir(parents=True)
                (module / "pom.xml").write_text("<project/>", encoding="utf-8")

            def fake_git(repo, *args):
                repo = os.path.realpath(repo)
                if args == ("diff", "--name-only", "HEAD"):
                    return subprocess.CompletedProcess(["git"], 0, "", "")
                if args == ("ls-files", "--others", "--exclude-standard"):
                    return subprocess.CompletedProcess(["git"], 0, "", "")
                if args == ("rev-parse", "--verify", "HEAD^"):
                    return subprocess.CompletedProcess(["git"], 0, "parent\n", "")
                if args == ("diff", "--name-only", "HEAD^", "HEAD"):
                    out = {
                        os.path.realpath(root): "tests/testlib-simple/src/main/java/org/zstack/testlib/EnvSpec.groovy\n",
                        os.path.realpath(ee): "tests-ee/testlib-ee/src/main/groovy/org/zstack/testlib/ee/TestEe.groovy\n",
                    }.get(repo, "")
                    return subprocess.CompletedProcess(["git"], 0, out, "")
                return subprocess.CompletedProcess(["git"], 0, "", "")

            compile._git = fake_git

            default_main, default_ee = compile.auto_detect_modules(str(root), str(ee))
            groovy_main, groovy_ee = compile.auto_detect_modules(
                str(root),
                str(ee),
                excluded_modules=groovy_test.GROOVY_TEST_AUTO_EXCLUDED_MODULES,
            )

        self.assertEqual([], default_main)
        self.assertEqual([], default_ee)
        self.assertEqual(["tests/testlib-simple"], groovy_main)
        self.assertEqual(["tests-ee/testlib-ee"], groovy_ee)

    def test_auto_detect_modules_falls_back_to_head_when_no_worktree_module_changed(self):
        compile.settings.CONF = _conf(base_ref="")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            ee = Path(td) / "ee"
            (root / "identity").mkdir(parents=True)
            (root / "identity" / "pom.xml").write_text("<project/>", encoding="utf-8")
            (ee / "zvf").mkdir(parents=True)
            (ee / "zvf" / "pom.xml").write_text("<project/>", encoding="utf-8")

            def fake_git(repo, *args):
                repo = os.path.realpath(repo)
                if args == ("diff", "--name-only", "HEAD"):
                    return subprocess.CompletedProcess(["git"], 0, "README.md\n", "")
                if args == ("ls-files", "--others", "--exclude-standard"):
                    return subprocess.CompletedProcess(["git"], 0, "", "")
                if args == ("rev-parse", "--verify", "HEAD^"):
                    return subprocess.CompletedProcess(["git"], 0, "parent\n", "")
                if args == ("diff", "--name-only", "HEAD^", "HEAD"):
                    out = {
                        os.path.realpath(root): "identity/src/main/java/org/zstack/identity/Account.java\n",
                        os.path.realpath(ee): "zvf/src/main/java/org/zstack/mevoco/EnterpriseMevocoManager.java\n",
                    }.get(repo, "")
                    return subprocess.CompletedProcess(["git"], 0, out, "")
                return subprocess.CompletedProcess(["git"], 0, "", "")

            compile._git = fake_git

            main, ee_modules = compile.auto_detect_modules(str(root), str(ee))

        self.assertEqual(["identity"], main)
        self.assertEqual(["zvf"], ee_modules)

    def test_auto_detect_modules_uses_top_commit_even_when_upstream_exists(self):
        compile.settings.CONF = _conf(base_ref="")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            ee = Path(td) / "ee"
            (root / "storage").mkdir(parents=True)
            (root / "storage" / "pom.xml").write_text("<project/>", encoding="utf-8")
            (ee / "rewrite-for-ee/core-ee").mkdir(parents=True)
            (ee / "rewrite-for-ee/core-ee" / "pom.xml").write_text("<project/>", encoding="utf-8")

            def fake_git(repo, *args):
                repo = os.path.realpath(repo)
                if args == ("diff", "--name-only", "HEAD"):
                    return subprocess.CompletedProcess(["git"], 0, "", "")
                if args == ("ls-files", "--others", "--exclude-standard"):
                    return subprocess.CompletedProcess(["git"], 0, "", "")
                if args == ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"):
                    raise AssertionError("upstream must not be used to detect changed modules")
                if args == ("merge-base", "origin/feature", "HEAD"):
                    raise AssertionError("merge-base must not be used to detect changed modules")
                if args == ("diff", "--name-only", "base", "HEAD"):
                    raise AssertionError("base ref diff must not be used to detect changed modules")
                if args == ("rev-parse", "--verify", "HEAD^"):
                    return subprocess.CompletedProcess(["git"], 0, "parent\n", "")
                if args == ("diff", "--name-only", "HEAD^", "HEAD"):
                    out = {
                        os.path.realpath(root): "storage/src/main/java/org/zstack/storage/encrypt/RemoteOnly.java\n",
                        os.path.realpath(ee): "rewrite-for-ee/core-ee/src/main/java/org/zstack/core/ee/CoreEeManager.java\n",
                    }.get(repo, "")
                    return subprocess.CompletedProcess(["git"], 0, out, "")
                return subprocess.CompletedProcess(["git"], 0, "", "")

            compile._git = fake_git

            main, ee_modules = compile.auto_detect_modules(str(root), str(ee))

        self.assertEqual(["storage"], main)
        self.assertEqual(["rewrite-for-ee/core-ee"], ee_modules)

    def test_changed_paths_uses_configured_base_ref(self):
        compile.settings.CONF = _conf(base_ref="origin/feature")
        calls = []

        def fake_git(repo, *args):
            calls.append(args)
            if args == ("diff", "--name-only", "origin/feature", "HEAD"):
                return subprocess.CompletedProcess(["git"], 0, "storage/Feature.java\n", "")
            raise AssertionError("unexpected git command: %s" % (args,))

        compile._git = fake_git

        paths = compile.changed_paths_from_head_commit("/repo")

        self.assertEqual(["storage/Feature.java"], paths)
        self.assertEqual([
            ("diff", "--name-only", "origin/feature", "HEAD"),
        ], calls)

    def test_auto_detect_modules_includes_implementers_of_changed_interfaces(self):
        compile.settings.CONF = _conf(base_ref="")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            ee = Path(td) / "ee"
            interface_file = root / "storage" / "src" / "main" / "java" / "org" / "zstack" / "storage" / "encrypt" / "VolumeEncryptedResourceKeyBackend.java"
            implementer_file = root / "premium/crypto" / "src" / "main" / "java" / "org" / "zstack" / "crypto" / "keyprovider" / "KeyProviderResourceKeyBackendVolume.java"
            caller_file = root / "premium/volumebackup" / "src" / "main" / "java" / "org" / "zstack" / "storage" / "backup" / "VolumeBackupManagerImpl.java"
            for module in (root / "storage", root / "premium/crypto", root / "premium/volumebackup"):
                module.mkdir(parents=True)
                (module / "pom.xml").write_text("<project/>", encoding="utf-8")
            interface_file.parent.mkdir(parents=True)
            interface_file.write_text(
                "package org.zstack.storage.encrypt;\n"
                "public interface VolumeEncryptedResourceKeyBackend {\n"
                "    boolean checkBackupKeyProviderAttached(String backupUuid);\n"
                "}\n",
                encoding="utf-8",
            )
            implementer_file.parent.mkdir(parents=True)
            implementer_file.write_text(
                "package org.zstack.crypto.keyprovider;\n"
                "import org.zstack.storage.encrypt.VolumeEncryptedResourceKeyBackend;\n"
                "public class KeyProviderResourceKeyBackendVolume implements VolumeEncryptedResourceKeyBackend {\n"
                "}\n",
                encoding="utf-8",
            )
            caller_file.parent.mkdir(parents=True)
            caller_file.write_text(
                "package org.zstack.storage.backup;\n"
                "public class VolumeBackupManagerImpl {}\n",
                encoding="utf-8",
            )

            def fake_git(repo, *args):
                repo = os.path.realpath(repo)
                if args == ("diff", "--name-only", "HEAD"):
                    return subprocess.CompletedProcess(["git"], 0, "", "")
                if args == ("ls-files", "--others", "--exclude-standard"):
                    return subprocess.CompletedProcess(["git"], 0, "", "")
                if args == ("rev-parse", "--verify", "HEAD^"):
                    return subprocess.CompletedProcess(["git"], 0, "parent\n", "")
                if args == ("diff", "--name-only", "HEAD^", "HEAD"):
                    out = {
                        os.path.realpath(root): "storage/src/main/java/org/zstack/storage/encrypt/VolumeEncryptedResourceKeyBackend.java\npremium/volumebackup/src/main/java/org/zstack/storage/backup/VolumeBackupManagerImpl.java\n",
                    }.get(repo, "")
                    return subprocess.CompletedProcess(["git"], 0, out, "")
                return subprocess.CompletedProcess(["git"], 0, "", "")

            compile._git = fake_git

            main, ee_modules = compile.auto_detect_modules(str(root), str(ee))

        self.assertEqual(["storage", "premium/volumebackup", "premium/crypto"], main)
        self.assertEqual([], ee_modules)

    def test_collect_built_jars_uses_maven_main_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            ee = Path(td) / "ee"
            target = root / "premium/mevoco" / "target"
            (target / "maven-archiver").mkdir(parents=True)
            (target / "maven-archiver" / "pom.properties").write_text(
                "groupId=org.zstack\nartifactId=mevoco\nversion=5.0.0\n",
                encoding="utf-8",
            )
            main_jar = target / "mevoco-5.0.0.jar"
            main_jar.write_bytes(b"main")
            (target / "mevoco-fat.jar").write_bytes(b"fat")

            jars = compile.collect_built_jars(
                str(root),
                ["premium/mevoco"],
                [],
                ee_root=str(ee),
            )

        self.assertEqual([str(main_jar)], jars)

    def test_collect_web_classes_files_maps_spring_config(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            ee = Path(td) / "ee"
            main_xml = root / "conf" / "springConfigXml" / "core.xml"
            ee_xml = ee / "conf" / "springConfigXml" / "ee" / "coreEe.xml"
            main_xml.parent.mkdir(parents=True)
            ee_xml.parent.mkdir(parents=True)
            main_xml.write_text("<beans/>", encoding="utf-8")
            ee_xml.write_text("<beans/>", encoding="utf-8")

            files = compile.collect_web_classes_files(
                str(root),
                ["conf/springConfigXml/core.xml", "identity/src/main/java/Foo.java"],
                ["conf/springConfigXml/ee/coreEe.xml"],
                str(ee),
            )

        mapped = {item.relative_path: item.source for item in files}
        self.assertEqual(str(main_xml), mapped["springConfigXml/core.xml"])
        self.assertEqual(str(ee_xml), mapped["springConfigXml/ee/coreEe.xml"])

    def test_collect_explicit_web_classes_files_maps_spring_config(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            ee = Path(td) / "ee"
            main_xml = root / "conf" / "springConfigXml" / "VolumeManager.xml"
            ee_xml = ee / "conf" / "springConfigXml" / "ee" / "coreEe.xml"
            main_xml.parent.mkdir(parents=True)
            ee_xml.parent.mkdir(parents=True)
            main_xml.write_text("<beans/>", encoding="utf-8")
            ee_xml.write_text("<beans/>", encoding="utf-8")

            files = compile.collect_explicit_web_classes_files(
                str(root),
                str(ee),
                [
                    "zsvirt:conf/springConfigXml/VolumeManager.xml",
                    "ee:conf/springConfigXml/ee/coreEe.xml",
                ],
            )

        mapped = {item.relative_path: item.source for item in files}
        self.assertEqual(str(main_xml.resolve()), mapped["springConfigXml/VolumeManager.xml"])
        self.assertEqual(str(ee_xml.resolve()), mapped["springConfigXml/ee/coreEe.xml"])

    def test_explicit_web_class_overrides_changed_file_with_same_target(self):
        compile.settings.CONF = _conf(remote_docker_host="tcp://172.26.50.70:2375", base_ref="origin/test-base")
        self._allow_changed_paths_base_ref_validation()
        compile.auto_detect_modules = lambda _root, _ee_root=None: (["identity"], [])
        compile.git_summary = lambda _root: ("abc123 test", "abc123")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            ee = Path(td) / "ee"
            zstack_xml = root / "conf" / "springConfigXml" / "HostAllocatorManager.xml"
            ee_xml = ee / "conf" / "springConfigXml" / "HostAllocatorManager.xml"
            zstack_xml.parent.mkdir(parents=True)
            ee_xml.parent.mkdir(parents=True)
            zstack_xml.write_text("<beans>zstack</beans>", encoding="utf-8")
            ee_xml.write_text("<beans>ee</beans>", encoding="utf-8")
            (root / "pom.xml").write_text("<project/>", encoding="utf-8")
            (root / "identity").mkdir()
            (root / "identity" / "pom.xml").write_text("<project/>", encoding="utf-8")
            jar_copy_root = Path(td) / "jar-copy"
            (jar_copy_root / "zsvirt").mkdir(parents=True)
            (jar_copy_root / "ee").mkdir(parents=True)
            compile._local_jar_copy_root_for_root = lambda _root: str(jar_copy_root)
            compile.collect_changed_web_classes_files = lambda _root, _ee_root=None: [
                compile.WebClassesFile(
                    str(zstack_xml),
                    "springConfigXml/HostAllocatorManager.xml",
                )
            ]

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = compile.run_compile_flow(
                    address=None,
                    remote_lib=compile.DEFAULT_REMOTE_LIB,
                    no_deploy=True,
                    zsvirt_root=str(root),
                    ee_root=str(ee),
                    extra_web_classes=[
                        "ee:conf/springConfigXml/HostAllocatorManager.xml"
                    ],
                    runner=FakeRunner(),
                )

        self.assertEqual(0, rc)
        output = stdout.getvalue()
        self.assertIn(str(ee_xml.resolve()), output)
        self.assertNotIn(str(zstack_xml.resolve()), output)

    def test_deploy_uses_unique_remote_staging_per_compile(self):
        compile.settings.CONF = _conf(remote_docker_host="tcp://172.26.50.70:2375", base_ref="origin/test-base")
        self._allow_changed_paths_base_ref_validation()
        compile.auto_detect_modules = lambda _root, _ee_root=None: (["identity"], [])
        compile.git_summary = lambda _root: ("abc123 test", "abc123")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            ee = Path(td) / "ee"
            worktree_target = root / "identity" / "target"
            worktree_target.mkdir(parents=True)
            ee.mkdir(parents=True)
            (root / "pom.xml").write_text("<project/>", encoding="utf-8")
            (root / "identity" / "pom.xml").write_text("<project/>", encoding="utf-8")
            (worktree_target / "identity-5.0.0.jar").write_bytes(b"wrong")
            jar_copy_root = Path(td) / "jar-copy"
            jar_copy_target = jar_copy_root / "zsvirt" / "identity" / "target"
            jar_copy_target.mkdir(parents=True)
            copied_jar = jar_copy_target / "identity-5.0.0.jar"
            copied_jar.write_bytes(b"jar")
            compile._local_jar_copy_root_for_root = lambda _root: str(jar_copy_root)
            runner = FakeRunner()

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = compile.run_compile_flow(
                    address="172.26.213.50",
                    remote_lib=compile.DEFAULT_REMOTE_LIB,
                    no_deploy=False,
                    zsvirt_root=str(root),
                    ee_root=str(ee),
                    runner=runner,
                )

        self.assertEqual(0, rc)
        self.assertIn(
            "WARNING: compile finished but MN has not been restarted. Run: cbok zsv restart_mn --address 172.26.213.50",
            stdout.getvalue(),
        )
        shell_scripts = [
            cmd[-1] for cmd, _kwargs in runner.calls
            if isinstance(cmd, list) and cmd[:2] == ["bash", "-lc"]
        ]
        scp_scripts = [s for s in shell_scripts if "zsv_scp_jars_to_remote" in s]
        install_scripts = [s for s in shell_scripts if "zsv_remote_install_jars_from_staging" in s]
        self.assertEqual(1, len(scp_scripts))
        self.assertEqual(1, len(install_scripts))
        staging_prefix = f"{compile.REMOTE_JAR_STAGING}-zstack-"
        self.assertIn(staging_prefix, scp_scripts[0])
        self.assertIn(staging_prefix, install_scripts[0])
        self.assertIn(str(copied_jar), scp_scripts[0])
        self.assertNotIn(str(worktree_target / "identity-5.0.0.jar"), scp_scripts[0])

    def test_deploy_syncs_changed_web_classes_archive(self):
        compile.settings.CONF = _conf(remote_docker_host="tcp://172.26.50.70:2375", base_ref="origin/test-base")
        self._allow_changed_paths_base_ref_validation()
        compile.auto_detect_modules = lambda _root, _ee_root=None: (["identity"], [])
        compile.git_summary = lambda _root: ("abc123 test", "abc123")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            ee = Path(td) / "ee"
            worktree_target = root / "identity" / "target"
            worktree_target.mkdir(parents=True)
            ee_xml = ee / "conf" / "springConfigXml" / "ee" / "coreEe.xml"
            ee_xml.parent.mkdir(parents=True)
            ee_xml.write_text("<beans/>", encoding="utf-8")
            (root / "pom.xml").write_text("<project/>", encoding="utf-8")
            (root / "identity" / "pom.xml").write_text("<project/>", encoding="utf-8")
            jar_copy_root = Path(td) / "jar-copy"
            jar_copy_target = jar_copy_root / "zsvirt" / "identity" / "target"
            jar_copy_target.mkdir(parents=True)
            (jar_copy_target / "identity-5.0.0.jar").write_bytes(b"jar")
            compile._local_jar_copy_root_for_root = lambda _root: str(jar_copy_root)
            compile.collect_changed_web_classes_files = lambda _root, _ee_root=None: [
                compile.WebClassesFile(str(ee_xml), "springConfigXml/ee/coreEe.xml")
            ]
            runner = FakeRunner()

            rc = compile.run_compile_flow(
                address="172.26.213.50",
                remote_lib=compile.DEFAULT_REMOTE_LIB,
                no_deploy=False,
                zsvirt_root=str(root),
                ee_root=str(ee),
                runner=runner,
            )

        self.assertEqual(0, rc)
        shell_scripts = [
            cmd[-1] for cmd, _kwargs in runner.calls
            if isinstance(cmd, list) and cmd[:2] == ["bash", "-lc"]
        ]
        self.assertTrue(any("zsv_scp_web_classes_archive_to_remote" in script for script in shell_scripts))
        self.assertTrue(any("zsv_remote_install_web_classes_archive" in script for script in shell_scripts))
        self.assertTrue(any("/usr/local/zstack/apache-tomcat/webapps/zstack/WEB-INF/classes" in script for script in shell_scripts))

    def test_deploy_replays_previous_modules_removed_from_current_diff(self):
        compile.settings.CONF = _conf(remote_docker_host="tcp://172.26.50.70:2375", base_ref="origin/test-base")
        self._allow_changed_paths_base_ref_validation()
        compile.auto_detect_modules = lambda _root, _ee_root=None: (["identity"], [])
        compile.collect_changed_web_classes_files = lambda _root, _ee_root=None: []
        compile.git_summary = lambda _root: ("abc123 test", "abc123")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            ee = Path(td) / "ee"
            for module in ("identity", "storage"):
                (root / module / "target").mkdir(parents=True)
                (root / module / "pom.xml").write_text("<project/>", encoding="utf-8")
            ee.mkdir(parents=True)
            (root / "pom.xml").write_text("<project/>", encoding="utf-8")
            jar_copy_root = Path(td) / "jar-copy"
            for module in ("identity", "storage"):
                target = jar_copy_root / "zsvirt" / module / "target"
                target.mkdir(parents=True)
                (target / f"{module}-5.0.0.jar").write_bytes(b"jar")
            compile._local_jar_copy_root_for_root = lambda _root: str(jar_copy_root)
            remote = compile.remote_docker_compile_from_conf()
            worktree_key = compile.compile_worktree_key(str(root), str(ee), remote)
            self._compile_state_store.save_selection(
                worktree_key,
                str(root),
                str(ee),
                compile.CompileDeploySelection(["storage"], [], []),
            )
            runner = FakeRunner()

            rc = compile.run_compile_flow(
                address="172.26.213.50",
                remote_lib=compile.DEFAULT_REMOTE_LIB,
                no_deploy=False,
                zsvirt_root=str(root),
                ee_root=str(ee),
                runner=runner,
            )

        self.assertEqual(0, rc)
        shell_scripts = [
            cmd[-1] for cmd, _kwargs in runner.calls
            if isinstance(cmd, list) and cmd[:2] == ["bash", "-lc"]
        ]
        scp_scripts = [s for s in shell_scripts if "zsv_scp_jars_to_remote" in s]
        self.assertEqual(1, len(scp_scripts))
        self.assertIn("identity-5.0.0.jar", scp_scripts[0])
        self.assertIn("storage-5.0.0.jar", scp_scripts[0])
        selection = self._compile_state_store.load_selection(worktree_key)
        self.assertEqual(["identity"], selection.main_modules)
        self.assertEqual([], selection.ee_modules)

    def test_deploy_replays_previous_web_classes_when_current_diff_is_empty(self):
        compile.settings.CONF = _conf(remote_docker_host="tcp://172.26.50.70:2375", base_ref="origin/test-base")
        self._allow_changed_paths_base_ref_validation()
        compile.auto_detect_modules = lambda _root, _ee_root=None: ([], [])
        compile.collect_changed_web_classes_files = lambda _root, _ee_root=None: []
        compile.git_summary = lambda _root: ("abc123 test", "abc123")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "zstack"
            ee = Path(td) / "ee"
            ee_xml = ee / "conf" / "springConfigXml" / "ee" / "coreEe.xml"
            ee_xml.parent.mkdir(parents=True)
            ee_xml.write_text("<beans/>", encoding="utf-8")
            (root / "pom.xml").parent.mkdir(parents=True, exist_ok=True)
            (root / "pom.xml").write_text("<project/>", encoding="utf-8")
            jar_copy_root = Path(td) / "jar-copy"
            compile._local_jar_copy_root_for_root = lambda _root: str(jar_copy_root)
            remote = compile.remote_docker_compile_from_conf()
            worktree_key = compile.compile_worktree_key(str(root), str(ee), remote)
            self._compile_state_store.save_selection(
                worktree_key,
                str(root),
                str(ee),
                compile.CompileDeploySelection(
                    [],
                    [],
                    [
                        compile.CompileWebClassesState(
                            "ee",
                            "conf/springConfigXml/ee/coreEe.xml",
                            "springConfigXml/ee/coreEe.xml",
                        )
                    ],
                ),
            )
            runner = FakeRunner()

            rc = compile.run_compile_flow(
                address="172.26.213.50",
                remote_lib=compile.DEFAULT_REMOTE_LIB,
                no_deploy=False,
                zsvirt_root=str(root),
                ee_root=str(ee),
                runner=runner,
            )

        self.assertEqual(0, rc)
        shell_scripts = [
            cmd[-1] for cmd, _kwargs in runner.calls
            if isinstance(cmd, list) and cmd[:2] == ["bash", "-lc"]
        ]
        self.assertTrue(any("zsv_scp_web_classes_archive_to_remote" in script for script in shell_scripts))
        self.assertTrue(any("zsv_remote_install_web_classes_archive" in script for script in shell_scripts))
        selection = self._compile_state_store.load_selection(worktree_key)
        self.assertEqual([], selection.main_modules)
        self.assertEqual([], selection.ee_modules)
        self.assertEqual([], selection.web_classes)

if __name__ == "__main__":
    unittest.main()
