# tests/test_tools_stubs.py
"""Tests for mas/tools/__init__.py stub classes."""

import pytest
from mas.tools import MLToolbox, RAGEngine, SQLSandbox


class TestSQLSandboxStub:
    def test_raises_import_error(self):
        with pytest.raises(ImportError, match="TEP dataset"):
            SQLSandbox()

    def test_error_message_mentions_public_release(self):
        with pytest.raises(ImportError, match="public release"):
            SQLSandbox()


class TestRAGEngineStub:
    def test_raises_import_error(self):
        with pytest.raises(ImportError, match="TEP docs"):
            RAGEngine()

    def test_error_message_mentions_public_release(self):
        with pytest.raises(ImportError, match="public release"):
            RAGEngine()


class TestMLToolboxStub:
    def test_raises_import_error(self):
        with pytest.raises(ImportError):
            MLToolbox()

    def test_error_message_mentions_public_release(self):
        with pytest.raises(ImportError, match="public release"):
            MLToolbox()


def test_all_stubs_exported():
    from mas import tools
    assert hasattr(tools, "SQLSandbox")
    assert hasattr(tools, "RAGEngine")
    assert hasattr(tools, "MLToolbox")
