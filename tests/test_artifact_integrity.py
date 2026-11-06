from pathlib import Path

import pytest

from src.predictors.integrity import (
    artifact_sha256,
    verify_artifact_sha256,
)


def test_artifact_sha256_detects_mismatch(
    tmp_path: Path,
):
    path = (
        tmp_path
        / "artifact.bin"
    )

    path.write_bytes(
        b"v2-artifact"
    )

    digest = artifact_sha256(
        path
    )

    verify_artifact_sha256(
        path,
        digest,
    )

    with pytest.raises(
        ValueError
    ):
        verify_artifact_sha256(
            path,
            "0" * 64,
        )