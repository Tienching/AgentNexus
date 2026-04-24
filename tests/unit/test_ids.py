# -*- coding: utf-8 -*-
"""Unit tests for shared ID generation helpers."""

from src.runtime.utils import ids


class TestIdGeneration:
    """ID generation should stay prefix-compatible and collision-resistant."""

    def test_short_id_uses_32_bits_of_entropy(self, monkeypatch):
        monkeypatch.setattr(ids.time, "time", lambda: 0x12345678)

        sizes = []

        def fake_urandom(size):
            sizes.append(size)
            return b"\xAB" * size

        monkeypatch.setattr(ids.os, "urandom", fake_urandom)

        assert ids._short_id() == "12345678" + "abababab"
        assert sizes == [4]

    def test_gen_session_id_keeps_expected_prefix(self):
        session_id = ids.gen_session_id()

        assert session_id.startswith("session_")
        assert len(session_id.removeprefix("session_")) >= 16

    def test_gen_run_id_keeps_expected_prefix(self):
        run_id = ids.gen_run_id()

        assert run_id.startswith("run_")
        assert len(run_id.removeprefix("run_")) >= 16
