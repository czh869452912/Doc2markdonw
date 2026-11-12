from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
STACK = ROOT / "deploy" / "ragflow-mineru"
SCRIPT = ROOT / "deploy" / "ragflow-mineru" / "scripts" / "deploy-linux.sh"
COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.mineru.yml",
    "docker-compose.office-gateway.yml",
    "docker-compose.md-convert.yml",
    "docker-compose.gateway.yml",
)


class DeployLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.package = self.base / "package"
        self.project = self.base / "project"
        self.bin_dir = self.base / "bin"
        self.command_log = self.base / "commands.log"
        self.bin_dir.mkdir()
        self._create_package()
        self._create_runtime()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _create_package(self):
        docker_dir = self.package / "ragflow" / "docker"
        self._write_compose_files(docker_dir)
        (self.package / "images").mkdir(parents=True)
        (self.package / "images" / "test.tar").write_bytes(b"test-image")
        (self.package / "scripts").mkdir()
        shutil.copyfile(SCRIPT.parent / "runtime-common.sh", self.package / "scripts/runtime-common.sh")

    def _create_runtime(self):
        docker_dir = self.project / "ragflow" / "docker"
        self._write_compose_files(docker_dir)
        (docker_dir / "data.sentinel").write_text("keep", encoding="utf-8")

    @staticmethod
    def _write_compose_files(docker_dir: Path):
        docker_dir.mkdir(parents=True)
        for name in COMPOSE_FILES:
            (docker_dir / name).write_text("services: {}\n", encoding="utf-8")
        (docker_dir / ".env").write_text(
            "PUBLIC_PORT=18080\n",
            encoding="utf-8",
        )

    def _write_stubs(self, compose_v1: bool):
        docker_script = """#!/usr/bin/env bash
set -eu
if [[ "${1:-}" == "compose" && "${2:-}" == "version" ]]; then
  exit 0
fi
printf 'docker %s\\n' "$*" >> "$COMMAND_LOG"
"""
        self._write_executable(self.bin_dir / "docker", docker_script)
        if compose_v1:
            compose_script = """#!/usr/bin/env bash
set -eu
printf 'docker-compose %s\\n' "$*" >> "$COMMAND_LOG"
"""
            self._write_executable(
                self.bin_dir / "docker-compose",
                compose_script,
            )

    @staticmethod
    def _write_executable(path: Path, content: str):
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def _run(
        self, *arguments: str, compose_v1: bool = True,
        cwd: Path = ROOT, script: Path = SCRIPT,
    ):
        self._write_stubs(compose_v1)
        env = os.environ.copy()
        env["PATH"] = os.pathsep.join((str(self.bin_dir), env["PATH"]))
        env["COMMAND_LOG"] = str(self.command_log)
        env.pop("COMPOSE_PROJECT_NAME", None)
        env.pop("OFFICE_PIDS_LIMIT", None)
        return subprocess.run(
            ["bash", str(script), *arguments],
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
        )

    def _commands(self) -> list[str]:
        if not self.command_log.exists():
            return []
        return self.command_log.read_text(encoding="utf-8").splitlines()

    def test_no_action_keeps_default_deployment_flow(self):
        result = self._run(
            "--package-dir",
            str(self.package),
            "--project-dir",
            str(self.project),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self._commands()
        self.assertTrue(
            any(command.startswith("docker load -i ") for command in commands),
            commands,
        )
        self.assertTrue(commands[-1].endswith("up -d"), commands)

    def test_up_in_place_from_unpacked_package(self):
        packaged_script = self.package / "scripts" / "deploy-linux.sh"
        shutil.copyfile(SCRIPT, packaged_script)
        docker_dir = self.package / "ragflow" / "docker"
        sentinel = docker_dir / "data.sentinel"
        sentinel.write_text("keep", encoding="utf-8")

        result = self._run(
            "up", "--project-dir", "./",
            cwd=self.package, script=packaged_script,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skipping file copy", result.stdout)
        self.assertTrue(self._commands()[0].startswith("docker load -i "))
        self.assertTrue(self._commands()[-1].endswith("up -d"))
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        self.assertTrue((docker_dir / "docker-compose.v1.yml").exists())
        self.assertTrue((docker_dir / "md-convert-data").is_dir())

    def test_up_in_place_through_project_symlink(self):
        project_link = self.base / "package-link"
        project_link.symlink_to(self.package, target_is_directory=True)

        result = self._run(
            "up", "--package-dir", str(self.package),
            "--project-dir", str(project_link), "--skip-load",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skipping file copy", result.stdout)
        self.assertTrue(self._commands()[-1].endswith("up -d"))

    def test_up_copies_to_new_relative_project_directory(self):
        result = self._run(
            "up", "--package-dir", "./package",
            "--project-dir", "./new runtime", "--skip-load", cwd=self.base,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        docker_dir = self.base / "new runtime" / "ragflow" / "docker"
        self.assertEqual((docker_dir / ".env").read_text(), "PUBLIC_PORT=18080\n")
        self.assertTrue((docker_dir / "docker-compose.v1.yml").exists())
        self.assertTrue(self._commands()[-1].endswith("up -d"))

    def test_down_stops_the_full_compose_stack(self):
        result = self._run("down", "--project-dir", str(self.project))

        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self._commands()
        self.assertTrue(commands[-1].endswith("stop"), commands)
        for compose_file in COMPOSE_FILES:
            expected = compose_file.replace(".yml", ".v1.yml")
            self.assertIn(expected, commands[-1])

    def test_rm_removes_containers_but_preserves_data(self):
        sentinel = self.project / "ragflow" / "docker" / "data.sentinel"

        result = self._run("rm", "--project-dir", str(self.project))

        self.assertEqual(result.returncode, 0, result.stderr)
        command = self._commands()[-1]
        self.assertTrue(command.endswith("down --remove-orphans"), command)
        self.assertNotIn("--volumes", command)
        self.assertTrue(sentinel.exists())

    def test_rm_purge_data_removes_volumes_and_project_directory(self):
        result = self._run(
            "rm",
            "--purge-data",
            "--project-dir",
            str(self.project),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        command = self._commands()[-1]
        self.assertTrue(
            command.endswith("down --volumes --remove-orphans"),
            command,
        )
        self.assertFalse(self.project.exists())
        self.assertIn(str(self.project), result.stdout)

    def test_lifecycle_actions_reject_invalid_option_combinations(self):
        cases = (
            (("down", "--purge-data"), "--purge-data"),
            (("down", "--skip-load"), "--skip-load"),
            (("rm", "--package-dir", str(self.package)), "--package-dir"),
        )
        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                self.command_log.unlink(missing_ok=True)
                result = self._run(
                    *arguments,
                    "--project-dir",
                    str(self.project),
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(expected, result.stderr)
                self.assertEqual(self._commands(), [])

    def test_purge_refuses_dangerous_project_path(self):
        for project_dir in ("/", "/opt", "/usr", "/var", "/home"):
            with self.subTest(project_dir=project_dir):
                self.command_log.unlink(missing_ok=True)
                result = self._run(
                    "rm",
                    "--purge-data",
                    "--project-dir",
                    project_dir,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Refusing", result.stderr)
                self.assertEqual(self._commands(), [])

    def test_lifecycle_action_requires_an_installed_runtime(self):
        missing_project = self.base / "missing-project"

        result = self._run(
            "down",
            "--project-dir",
            str(missing_project),
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not exist", result.stderr)
        self.assertEqual(self._commands(), [])

    def test_unknown_action_is_rejected(self):
        result = self._run("unknown-action")

        self.assertEqual(result.returncode, 2)
        self.assertIn("Unknown", result.stderr)

    def test_down_supports_compose_v1_and_v2(self):
        result_v1 = self._run("down", "--project-dir", str(self.project))
        self.assertEqual(result_v1.returncode, 0, result_v1.stderr)
        self.assertTrue(self._commands()[-1].startswith("docker-compose "))

        self.command_log.unlink()
        (self.bin_dir / "docker-compose").unlink()
        result_v2 = self._run(
            "down",
            "--project-dir",
            str(self.project),
            compose_v1=False,
        )
        self.assertEqual(result_v2.returncode, 0, result_v2.stderr)
        self.assertTrue(self._commands()[-1].startswith("docker compose "))

    def test_documentation_describes_lifecycle_and_image_preservation(self):
        readmes = [STACK / "README.md"]

        for readme in readmes:
            with self.subTest(readme=readme):
                content = readme.read_text(encoding="utf-8")
                self.assertIn("deploy-linux.sh down", content)
                self.assertIn("deploy-linux.sh rm", content)
                self.assertIn("rm --purge-data", content)
                self.assertIn("Docker images", content)

    def test_namespace_is_used_for_up_and_lifecycle_actions(self):
        for action in ("up", "down", "rm"):
            with self.subTest(action=action):
                arguments = [action, "--project-dir", str(self.project)]
                if action == "up":
                    arguments += ["--package-dir", str(self.package), "--skip-load",
                                  "--project-name", "internal-docs"]
                result = self._run(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("-p internal-docs ", self._commands()[-1])

    def test_namespace_cannot_be_changed_for_existing_runtime(self):
        docker_dir = self.project / "ragflow/docker"
        (docker_dir / ".compose-project-name").write_text("internal-docs\n")
        result = self._run("up", "--project-dir", str(self.project),
                           "--package-dir", str(self.package), "--project-name", "other")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("belongs to Compose project", result.stderr)
        self.assertEqual(self._commands(), [])

    def test_prepare_only_renders_config_without_starting_or_overwriting_data(self):
        for base, value in ((self.package, "package"), (self.project, "keep")):
            directory = base / "ragflow/docker/md-convert-data"
            directory.mkdir()
            (directory / "job.data").write_text(value)
        result = self._run("up", "--project-dir", str(self.project),
                           "--package-dir", str(self.package), "--skip-load", "--skip-up")
        self.assertEqual(result.returncode, 0, result.stderr)
        docker_dir = self.project / "ragflow/docker"
        self.assertTrue((docker_dir / "docker-compose.v1.yml").exists())
        self.assertEqual((docker_dir / "md-convert-data/job.data").read_text(), "keep")
        self.assertEqual(self._commands(), [])

    def test_upgrade_preserves_server_environment_and_namespace(self):
        docker_dir = self.project / "ragflow/docker"
        environment = "PUBLIC_PORT=8007\nREDIS_PASSWORD=keep-secret\nCOMPOSE_PROJECT_NAME=internal-docs\n"
        (docker_dir / ".env").write_text(environment)
        result = self._run("up", "--project-dir", str(self.project),
                           "--package-dir", str(self.package), "--skip-load")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((docker_dir / ".env").read_text(), environment)
        self.assertIn("-p internal-docs ", self._commands()[-1])

    def test_generated_compose_scopes_upstream_and_uses_integer_pids(self):
        docker_dir = self.project / "ragflow/docker"
        (docker_dir / ".env").write_text("OFFICE_PIDS_LIMIT=512\n")
        (docker_dir / "docker-compose.yml").write_text(
            "include:\n  - ./docker-compose-base.yml\nservices:\n  ragflow-gpu:\n"
            "    container_name: ragflow-server\n    image: ragflow:test\n")
        (docker_dir / "docker-compose-base.yml").write_text(
            "services:\n  redis:\n    container_name: docker_redis_1\n    image: redis:test\n"
            "    volumes:\n      - redis_data:/data\nvolumes:\n  redis_data:\n")
        (docker_dir / "docker-compose.office-gateway.yml").write_text(
            (STACK / "docker-compose.office-gateway.yml").read_text())
        result = self._run("down", "--project-dir", str(self.project))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("-p doc2markdown ", self._commands()[-1])
        for name in ("docker-compose.v1.yml", "docker-compose-base.v1.yml"):
            content = (docker_dir / name).read_text()
            self.assertNotIn("container_name:", content)
            self.assertNotIn("include:", content)
        office = (docker_dir / "docker-compose.office-gateway.v1.yml").read_text()
        self.assertIn("    pids_limit: 512\n", office)
        self.assertNotIn("${OFFICE_PIDS_LIMIT", office)

    def test_invalid_pids_and_namespace_fail_before_compose(self):
        docker_dir = self.project / "ragflow/docker"
        (docker_dir / ".env").write_text("OFFICE_PIDS_LIMIT=oops\n")
        result = self._run("down", "--project-dir", str(self.project))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("positive integer", result.stderr)
        result = self._run("down", "--project-dir", str(self.project), "--project-name", "../bad")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid Compose project name", result.stderr)
        self.assertEqual(self._commands(), [])


if __name__ == "__main__":
    unittest.main()
