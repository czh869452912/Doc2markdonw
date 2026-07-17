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
UNPACKED_PACKAGE = (
    ROOT / "dist" / "ragflow-mineru-airgap-v0.26.4-20260708-163537"
)
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

    def _run(self, *arguments: str, compose_v1: bool = True):
        self._write_stubs(compose_v1)
        env = os.environ.copy()
        env["PATH"] = os.pathsep.join((str(self.bin_dir), env["PATH"]))
        env["COMMAND_LOG"] = str(self.command_log)
        return subprocess.run(
            ["bash", str(SCRIPT), *arguments],
            cwd=ROOT,
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
        packaged_readme = UNPACKED_PACKAGE / "README.md"
        if packaged_readme.exists():
            readmes.append(packaged_readme)

        for readme in readmes:
            with self.subTest(readme=readme):
                content = readme.read_text(encoding="utf-8")
                self.assertIn("deploy-linux.sh down", content)
                self.assertIn("deploy-linux.sh rm", content)
                self.assertIn("rm --purge-data", content)
                self.assertIn("Docker images", content)

    def test_unpacked_package_uses_the_tracked_lifecycle_script(self):
        packaged_script = UNPACKED_PACKAGE / "scripts" / "deploy-linux.sh"
        if not packaged_script.exists():
            self.skipTest("unpacked air-gap package is not present")

        self.assertEqual(SCRIPT.read_bytes(), packaged_script.read_bytes())


if __name__ == "__main__":
    unittest.main()
