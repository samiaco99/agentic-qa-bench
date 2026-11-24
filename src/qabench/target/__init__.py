"""The system under test: a small ticketing API with switchable seeded defects."""

from importlib.resources import files

from qabench.target.app import create_app

# Bumped whenever the spec, the seed data, or the bug/decoy registries change, because
# results from different exam versions are not comparable.
EXAM_VERSION = "0.2"


def load_spec() -> str:
    return files("qabench.target").joinpath("spec.md").read_text(encoding="utf-8")


__all__ = ["EXAM_VERSION", "create_app", "load_spec"]
