"""The system under test: a small ticketing API with switchable seeded defects."""

from importlib.resources import files

from qabench.target.app import create_app


def load_spec() -> str:
    return files("qabench.target").joinpath("spec.md").read_text(encoding="utf-8")


__all__ = ["create_app", "load_spec"]
