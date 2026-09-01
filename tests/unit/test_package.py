from unittest.mock import patch

import pytest

import tadween_preprocess
from tadween_preprocess import (
    create_batch_from_directory,
    scan_directory_for_media,
)


def test_package_root_lazy_attribute_resolution():
    assert tadween_preprocess.Orchestrator is not None
    assert tadween_preprocess.run is not None
    assert tadween_preprocess.notify_webhook is not None
    assert callable(create_batch_from_directory)
    assert callable(scan_directory_for_media)

    with pytest.raises(
        AttributeError,
        match="module 'tadween_preprocess' has no attribute 'non_existent'",
    ):
        _ = tadween_preprocess.non_existent  # type: ignore


def test_package_root_missing_dependencies_raises_import_error():
    real_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if (
            "orchestrator" in name
            or "runner" in name
            or "discovery" in name
            or (
                fromlist
                and any(x in ("runner", "discovery", "orchestrator") for x in fromlist)
            )
        ):
            raise ImportError(f"No module named '{name}'")
        return real_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", side_effect=fake_import):
        with pytest.raises(ImportError, match="requires worker dependencies"):
            tadween_preprocess.__getattr__("Orchestrator")

        with pytest.raises(ImportError, match="requires worker dependencies"):
            tadween_preprocess.__getattr__("run")

        with pytest.raises(ImportError, match="requires worker dependencies"):
            tadween_preprocess.__getattr__("create_batch_from_directory")
