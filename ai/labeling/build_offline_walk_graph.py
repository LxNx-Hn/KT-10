"""공개 OSM PBF에서 부산 보행 그래프를 한 번 생성한다.

실시간 요청이 공개 Overpass 서버 상태에 좌우되지 않도록 Geofabrik의
대한민국 PBF를 내려받고 부산 경계로 자른 walking network를 GraphML로
고정한다. 이 스크립트는 빌드 전용이며 실행 환경에는 ``pyrosm``이
추가로 필요하다. 생성물과 원본 PBF는 ``ai/data/cache`` 아래에 저장되어
Git에 포함되지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import httpx
import networkx as nx
import osmnx as ox

SOURCE_URL = (
    "https://download.geofabrik.de/asia/south-korea-latest.osm.pbf"
)
SOURCE_MD5_URL = SOURCE_URL + ".md5"
DEFAULT_BOUNDARY = Path(
    "data/da/colab/hangjeongdong_부산광역시.geojson"
)
DEFAULT_SOURCE = Path(
    "ai/data/cache/osmnx/source/south-korea-latest.osm.pbf"
)
DEFAULT_OUTPUT = Path("ai/data/cache/osmnx/busan-walk.graphml")
BUILDER_VERSION = "busan-offline-walk-v1"


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_expected_md5(client: httpx.Client) -> str:
    response = client.get(SOURCE_MD5_URL)
    response.raise_for_status()
    token = response.text.strip().split()[0].casefold()
    if len(token) != 32 or any(character not in "0123456789abcdef" for character in token):
        raise ValueError("Geofabrik MD5 응답이 올바르지 않습니다.")
    return token


def _download_source(
    destination: Path,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    with httpx.Client(
        timeout=httpx.Timeout(timeout_seconds, connect=30.0),
        follow_redirects=True,
    ) as client:
        expected_md5 = _download_expected_md5(client)
        if destination.exists() and _md5(destination) == expected_md5:
            return {
                "path": str(destination),
                "md5": expected_md5,
                "downloaded": False,
                "bytes": destination.stat().st_size,
            }

        existing_size = partial.stat().st_size if partial.exists() else 0
        headers = {"Range": f"bytes={existing_size}-"} if existing_size else {}
        mode = "ab" if existing_size else "wb"
        with client.stream("GET", SOURCE_URL, headers=headers) as response:
            if existing_size and response.status_code != 206:
                existing_size = 0
                mode = "wb"
            response.raise_for_status()
            with partial.open(mode) as handle:
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())

        actual_md5 = _md5(partial)
        if actual_md5 != expected_md5:
            raise ValueError(
                "대한민국 OSM PBF MD5가 Geofabrik 제공값과 일치하지 않습니다."
            )
        partial.replace(destination)
        return {
            "path": str(destination),
            "md5": actual_md5,
            "downloaded": True,
            "bytes": destination.stat().st_size,
        }


def _busan_boundary(path: Path):
    frame = gpd.read_file(path).to_crs("EPSG:4326")
    if frame.empty:
        raise ValueError("부산 행정경계가 비어 있습니다.")
    geometry = frame.geometry.union_all()
    if geometry.is_empty:
        raise ValueError("부산 행정경계 geometry가 비어 있습니다.")
    return geometry


def _compact_graph(graph) -> nx.MultiDiGraph:
    """경로 계산에 필요한 좌표·길이만 남기고 병렬 간선을 축약한다."""
    digraph = ox.convert.to_digraph(graph, weight="length")
    compact = nx.MultiDiGraph()
    for node_id, data in digraph.nodes(data=True):
        try:
            x = float(data["x"])
            y = float(data["y"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"OSM 보행 노드 {node_id}에 유효한 좌표가 없습니다."
            ) from exc
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError(f"OSM 보행 노드 {node_id} 좌표가 유한하지 않습니다.")
        compact.add_node(node_id, x=x, y=y)
    for start, end, data in digraph.edges(data=True):
        try:
            length = float(data["length"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"OSM 보행 간선 {start}->{end}에 유효한 길이가 없습니다."
            ) from exc
        if not math.isfinite(length) or length <= 0:
            raise ValueError(
                f"OSM 보행 간선 {start}->{end} 길이가 양수가 아닙니다."
            )
        compact.add_edge(start, end, length=length)
    return compact


def build(
    *,
    boundary_path: Path = DEFAULT_BOUNDARY,
    source_path: Path = DEFAULT_SOURCE,
    output_path: Path = DEFAULT_OUTPUT,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    try:
        from pyrosm import OSM
    except ImportError as exc:
        raise RuntimeError(
            "오프라인 보행 그래프 빌드에는 pyrosm이 필요합니다."
        ) from exc

    source = _download_source(
        source_path,
        timeout_seconds=timeout_seconds,
    )
    boundary = _busan_boundary(boundary_path)
    reader = OSM(
        str(source_path),
        bounding_box=boundary,
        keep_metadata=False,
        engine="out_of_core",
        workers="auto",
    )
    nodes, edges = reader.get_network(
        network_type="walking",
        nodes=True,
        tags_to_keep=[
            "access",
            "bridge",
            "foot",
            "highway",
            "layer",
            "name",
            "oneway",
            "service",
            "surface",
            "tunnel",
        ],
    )
    if nodes is None or edges is None or nodes.empty or edges.empty:
        raise ValueError("부산 보행 네트워크를 추출하지 못했습니다.")
    graph = OSM.to_graph(
        nodes,
        edges,
        graph_type="networkx",
        network_type="walking",
        retain_all=True,
    )
    source_node_count = graph.number_of_nodes()
    source_edge_count = graph.number_of_edges()
    graph = _compact_graph(graph)
    graph.graph["crs"] = "EPSG:4326"
    graph.graph["network_type"] = "walk"
    graph.graph["source"] = SOURCE_URL
    graph.graph["builder_version"] = BUILDER_VERSION

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".tmp.graphml")
    ox.save_graphml(graph, temporary)
    temporary.replace(output_path)

    bounds = [round(value, 7) for value in boundary.bounds]
    metadata = {
        "schema_version": "offline-walk-graph-v1",
        "builder_version": BUILDER_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "source_url": SOURCE_URL,
        "source_md5": source["md5"],
        "source_bytes": source["bytes"],
        "boundary_path": str(boundary_path),
        "boundary_bounds": bounds,
        "crs": "EPSG:4326",
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "source_node_count": source_node_count,
        "source_edge_count": source_edge_count,
        "output": str(output_path),
    }
    output_path.with_suffix(".metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(
        description="부산 오프라인 보행 GraphML 생성"
    )
    parser.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    args = parser.parse_args()
    print(json.dumps(build(
        boundary_path=args.boundary,
        source_path=args.source,
        output_path=args.output,
        timeout_seconds=args.timeout_seconds,
    ), ensure_ascii=False))


if __name__ == "__main__":
    main()
