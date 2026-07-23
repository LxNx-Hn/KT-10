"""Checksummed, non-executable XGBoost ranker artifact format."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from xgboost import XGBRanker

ARTIFACT_SCHEMA_VERSION = "xgboost-ranker-archive-v1"
MANIFEST_NAME = "manifest.json"
MAX_MODEL_BYTES = 64 * 1024 * 1024


class ArtifactError(ValueError):
    """Artifact structure, checksum, or model bytes are invalid."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_ranker_artifact(
    path: Path,
    *,
    metadata: dict[str, Any],
    rankers: dict[str, XGBRanker],
) -> dict[str, Any]:
    if not rankers:
        raise ArtifactError("저장할 프로필 ranker가 없습니다.")
    model_bytes: dict[str, bytes] = {}
    model_entries: dict[str, dict[str, Any]] = {}
    for profile, ranker in sorted(rankers.items()):
        raw = bytes(ranker.get_booster().save_raw(raw_format="json"))
        if not raw or len(raw) > MAX_MODEL_BYTES:
            raise ArtifactError(f"{profile}: XGBoost JSON 모델 크기가 올바르지 않습니다.")
        filename = f"models/{profile}.json"
        model_bytes[filename] = raw
        model_entries[profile] = {
            "path": filename,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }

    manifest = {
        **metadata,
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "profiles": sorted(rankers),
        "models": model_entries,
    }
    manifest_bytes = (
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST_NAME, manifest_bytes)
        for filename, raw in model_bytes.items():
            archive.writestr(filename, raw)
    temporary.replace(path)
    return manifest


def read_ranker_artifact(
    path: Path,
    *,
    load_models: bool,
) -> tuple[dict[str, Any], dict[str, XGBRanker]]:
    try:
        with ZipFile(path, "r") as archive:
            names = set(archive.namelist())
            if MANIFEST_NAME not in names:
                raise ArtifactError("ranker artifact manifest가 없습니다.")
            manifest_info = archive.getinfo(MANIFEST_NAME)
            if manifest_info.file_size > 1024 * 1024:
                raise ArtifactError("ranker artifact manifest가 너무 큽니다.")
            try:
                manifest = json.loads(archive.read(MANIFEST_NAME))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ArtifactError("ranker artifact manifest JSON이 올바르지 않습니다.") from exc
            if not isinstance(manifest, dict):
                raise ArtifactError("ranker artifact manifest는 JSON 객체여야 합니다.")
            if manifest.get("artifact_schema_version") != ARTIFACT_SCHEMA_VERSION:
                raise ArtifactError("지원하지 않는 ranker artifact schema입니다.")
            profiles = manifest.get("profiles")
            models = manifest.get("models")
            if (
                not isinstance(profiles, list)
                or not profiles
                or not isinstance(models, dict)
                or set(models) != set(profiles)
            ):
                raise ArtifactError("ranker artifact 프로필 manifest가 올바르지 않습니다.")

            expected_names = {MANIFEST_NAME}
            verified: dict[str, bytes] = {}
            for profile in profiles:
                entry = models.get(profile)
                if not isinstance(entry, dict):
                    raise ArtifactError(f"{profile}: 모델 manifest가 올바르지 않습니다.")
                filename = entry.get("path")
                if (
                    not isinstance(filename, str)
                    or filename != f"models/{profile}.json"
                    or filename not in names
                ):
                    raise ArtifactError(f"{profile}: 모델 파일 경로가 올바르지 않습니다.")
                info = archive.getinfo(filename)
                if info.file_size <= 0 or info.file_size > MAX_MODEL_BYTES:
                    raise ArtifactError(f"{profile}: 모델 파일 크기가 올바르지 않습니다.")
                raw = archive.read(filename)
                if len(raw) != entry.get("bytes"):
                    raise ArtifactError(f"{profile}: 모델 파일 크기 manifest가 일치하지 않습니다.")
                if hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
                    raise ArtifactError(f"{profile}: 모델 checksum이 일치하지 않습니다.")
                expected_names.add(filename)
                verified[profile] = raw
            if names != expected_names:
                raise ArtifactError("ranker artifact에 manifest 밖의 파일이 있습니다.")
    except (BadZipFile, KeyError, OSError) as exc:
        if isinstance(exc, ArtifactError):
            raise
        raise ArtifactError("ranker artifact archive를 읽을 수 없습니다.") from exc

    rankers: dict[str, XGBRanker] = {}
    if load_models:
        for profile, raw in verified.items():
            ranker = XGBRanker()
            try:
                ranker.load_model(bytearray(raw))
            except Exception as exc:
                raise ArtifactError(
                    f"{profile}: 검증된 XGBoost JSON 모델을 불러올 수 없습니다."
                ) from exc
            rankers[profile] = ranker
    return manifest, rankers
