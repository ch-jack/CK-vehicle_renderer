import importlib.util
import sys
import tempfile
import types
import unittest
from enum import Enum, auto
from pathlib import Path
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def load_renderer_module():
    fake_bpy = types.ModuleType("bpy")
    fake_mathutils = types.ModuleType("mathutils")
    fake_mathutils.Matrix = type("Matrix", (), {})
    fake_mathutils.Vector = type("Vector", (), {})
    spec = importlib.util.spec_from_file_location(
        "blender_render_vehicle_test",
        REPOSITORY_ROOT / "blender_render_vehicle.py",
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"bpy": fake_bpy, "mathutils": fake_mathutils}):
        spec.loader.exec_module(module)
    return module


RENDERER = load_renderer_module()


class DependencyState(Enum):
    UNINSTALLED = auto()
    INSTALLED = auto()


class Dependency:
    def __init__(self, name, supported=True):
        self.name = name
        self.supported = supported


class FakeDependencies:
    def __init__(self, root, install_succeeds=True):
        self.root = Path(root)
        self.szio = Dependency("szio")
        self.pymateria = Dependency("pymateria")
        self.unsupported = Dependency("unsupported", supported=False)
        self.DEPENDENCIES = (self.szio, self.pymateria, self.unsupported)
        self.DEPENDENCIES_OPTIONAL = (self.pymateria, self.unsupported)
        self.states = {
            "szio": DependencyState.UNINSTALLED,
            "pymateria": DependencyState.UNINSTALLED,
            "unsupported": DependencyState.UNINSTALLED,
        }
        self.install_succeeds = install_succeeds
        self.install_calls = 0
        self.mount_calls = 0
        self.unmount_calls = 0

    def dependencies_available_state(self):
        return dict(self.states)

    def requirements_path(self):
        return self.root / "requirements.txt"

    def mount_dependencies(self):
        self.mount_calls += 1

    def unmount_dependencies(self):
        self.unmount_calls += 1

    def install_dependencies(self, online_access_override, optional_dependencies_to_install):
        self.install_calls += 1
        if not online_access_override:
            raise AssertionError("online access override is required")
        if optional_dependencies_to_install != {"pymateria"}:
            raise AssertionError(optional_dependencies_to_install)
        if self.install_succeeds:
            self.states["szio"] = DependencyState.INSTALLED
            self.states["pymateria"] = DependencyState.INSTALLED
        return self.install_succeeds


class SollumzDependencyTests(unittest.TestCase):
    def test_installs_missing_dependencies_once_and_removes_lock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            dependencies = FakeDependencies(temp_dir)
            module_name = "fake_sollumz_dependencies_success"
            fake_module = types.ModuleType(module_name)
            fake_module.dependencies = dependencies
            with patch.dict(sys.modules, {module_name: fake_module}):
                RENDERER.ensure_sollumz_dependencies(module_name)
                RENDERER.ensure_sollumz_dependencies(module_name)

            self.assertEqual(1, dependencies.install_calls)
            self.assertFalse((Path(temp_dir) / ".ck-dependency-install.lock").exists())
            self.assertEqual([], RENDERER.missing_sollumz_dependencies(dependencies))

    def test_failed_install_releases_lock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            dependencies = FakeDependencies(temp_dir, install_succeeds=False)
            module_name = "fake_sollumz_dependencies_failure"
            fake_module = types.ModuleType(module_name)
            fake_module.dependencies = dependencies
            with patch.dict(sys.modules, {module_name: fake_module}):
                with self.assertRaisesRegex(RuntimeError, "failure status"):
                    RENDERER.ensure_sollumz_dependencies(module_name)

            self.assertEqual(1, dependencies.install_calls)
            self.assertFalse((Path(temp_dir) / ".ck-dependency-install.lock").exists())

    def test_unsupported_optional_dependency_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            dependencies = FakeDependencies(temp_dir)
            dependencies.states["szio"] = DependencyState.INSTALLED
            dependencies.states["pymateria"] = DependencyState.INSTALLED
            self.assertEqual([], RENDERER.missing_sollumz_dependencies(dependencies))


if __name__ == "__main__":
    unittest.main()
