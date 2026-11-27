# -*- coding: utf-8 -*-
"""Global test isolation.

Every test gets its own expert-context directory. Without this, routing tests
write `result-*.json` into the real `~/.zcode/expert-system/context`, and the
200-file LRU can delete a user's genuine history.
"""

import pytest


@pytest.fixture(autouse=True)
def isolate_expert_context(tmp_path, monkeypatch):
    store = tmp_path / "expert-context"
    store.mkdir()
    monkeypatch.setenv("ZCODE_EXPERT_CONTEXT_DIR", str(store))
    return store
