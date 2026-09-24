"""Opt-in delayed hook: PYTHONPATH this directory in every Ray worker."""

import importlib.abc
import importlib.machinery
import os
import sys


class AuditFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != "verl.trainer.distillation.losses":
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec is None or spec.loader is None:
            raise RuntimeError("OPD audit cannot locate native losses module")
        original = spec.loader

        class Loader(importlib.abc.Loader):
            def create_module(self, spec):
                return original.create_module(spec)

            def exec_module(self, module):
                original.exec_module(module)
                from capture import install

                install(module)

        spec.loader = Loader()
        return spec


if os.environ.get("OPD_LIVE_AUDIT_DIR"):
    sys.meta_path.insert(0, AuditFinder())
