from __future__ import annotations

import hashlib
from pathlib import Path


def artifact_sha256(
    path: Path,
) -> str:
    """Return deterministic SHA-256 for a file or directory."""

    if path.is_file():
        digest = hashlib.sha256()

        with path.open("rb") as handle:
            for chunk in iter(
                lambda: handle.read(
                    1024 * 1024
                ),
                b"",
            ):
                digest.update(chunk)

        return digest.hexdigest()

    if path.is_dir():
        digest = hashlib.sha256()

        files = sorted(
            file_path
            for file_path
            in path.rglob("*")
            if file_path.is_file()
        )

        if not files:
            raise ValueError(
                "Artifact directory "
                f"is empty: {path}"
            )

        for file_path in files:
            relative = (
                file_path
                .relative_to(path)
                .as_posix()
                .encode("utf-8")
            )

            digest.update(
                len(relative)
                .to_bytes(
                    8,
                    "big",
                )
            )

            digest.update(relative)

            with file_path.open(
                "rb"
            ) as handle:
                for chunk in iter(
                    lambda: handle.read(
                        1024 * 1024
                    ),
                    b"",
                ):
                    digest.update(
                        chunk
                    )

        return digest.hexdigest()

    raise FileNotFoundError(
        "Artifact path not found: "
        f"{path}"
    )


def verify_artifact_sha256(
    path: Path,
    expected: str | None,
) -> None:
    if not expected:
        return

    actual = artifact_sha256(
        path
    )

    if (
        actual.lower()
        != expected.lower()
    ):
        raise ValueError(
            "Artifact SHA-256 mismatch "
            f"for {path}: "
            f"expected={expected}, "
            f"actual={actual}"
        )