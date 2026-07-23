from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from osgeo import gdal
from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureSink,
    QgsFields,
    QgsField,
    QgsGeometry,
    QgsLineSymbol,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingLayerPostProcessorInterface,
    QgsProcessingParameterDistance,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFile,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
    QgsRendererCategory,
    QgsSimpleLineSymbolLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QMetaType


class _SlopeStylePostProcessor(QgsProcessingLayerPostProcessorInterface):
    instances = []

    def postProcessLayer(self, layer, context, feedback):
        styles = (
            ("gentle_0_2", "완만 0~2%", "#2ca25f"),
            ("moderate_2_5", "보통 2~5%", "#f2cf4a"),
            ("steep_5_8", "급경사 5~8%", "#f28e2b"),
            ("very_steep_over_8", "매우 급경사 8% 초과", "#d73027"),
        )
        categories = []
        for value, label, color in styles:
            symbol = _slope_symbol(color)
            categories.append(QgsRendererCategory(value, symbol, label))
        layer.setRenderer(QgsCategorizedSymbolRenderer("grade_class", categories))
        layer.triggerRepaint()


def _slope_symbol(color):
    symbol = QgsLineSymbol.createSimple(
        {
            "color": color,
            "width": "2.0",
            "capstyle": "round",
            "joinstyle": "round",
        }
    )
    casing = QgsSimpleLineSymbolLayer.create(
        {
            "color": "#000000",
            "width": "3.2",
            "capstyle": "round",
            "joinstyle": "round",
        }
    )
    symbol.insertSymbolLayer(0, casing)
    return symbol


class ODsayWalkingSlopeAnalysis(QgsProcessingAlgorithm):
    SERVER_URL = "SERVER_URL"
    ODSAY_PROJECT_DIR = "ODSAY_PROJECT_DIR"
    ORIGIN_LONGITUDE = "ORIGIN_LONGITUDE"
    ORIGIN_LATITUDE = "ORIGIN_LATITUDE"
    DESTINATION_LONGITUDE = "DESTINATION_LONGITUDE"
    DESTINATION_LATITUDE = "DESTINATION_LATITUDE"
    DEM = "DEM"
    INTERVAL = "INTERVAL"
    TRANSIT = "TRANSIT"
    SEGMENTS = "SEGMENTS"
    SUMMARY = "SUMMARY"

    def name(self):
        return "odsay_walking_slope_analysis"

    def displayName(self):
        return "ODsay 도보 경로 경사 분석"

    def group(self):
        return "ODsay 이동편의시설 경로"

    def groupId(self):
        return "odsay_accessible_route"

    def shortHelpString(self):
        return (
            "ODsay 추천 경로 전체의 도보 궤적을 가져와 DEM 기반 경사율을 계산합니다.\n\n"
            "로컬 ODsay 서버 상태 확인 및 자동 실행, 경로 조회, 출발·환승·도착 "
            "도보 분리, DEM 고도 추출, 선분별 경사와 경로별 요약을 한 번에 수행합니다.\n\n"
            "기본 출력은 임시 레이어입니다. DEM이 90m라면 결과는 보도 실측값이 "
            "아니라 주변 지형 경사 추정치입니다."
        )

    def createInstance(self):
        return ODsayWalkingSlopeAnalysis()

    def initAlgorithm(self, config=None):
        discovered = self._discover_odsay_project()
        self.addParameter(
            QgsProcessingParameterString(
                self.SERVER_URL,
                "ODsay 로컬 서버 주소",
                defaultValue="http://127.0.0.1:8080",
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.ODSAY_PROJECT_DIR,
                "ODsay 프로젝트 폴더",
                behavior=QgsProcessingParameterFile.Folder,
                defaultValue=str(discovered) if discovered else None,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.ORIGIN_LONGITUDE,
                "출발지 경도",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=129.041575693763,
                minValue=120,
                maxValue=135,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.ORIGIN_LATITUDE,
                "출발지 위도",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=35.1849136186692,
                minValue=30,
                maxValue=40,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.DESTINATION_LONGITUDE,
                "목적지 경도",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=128.990036594514,
                minValue=120,
                maxValue=135,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.DESTINATION_LATITUDE,
                "목적지 위도",
                type=QgsProcessingParameterNumber.Double,
                defaultValue=35.1972959413305,
                minValue=30,
                maxValue=40,
            )
        )
        self.addParameter(QgsProcessingParameterRasterLayer(self.DEM, "고도 DEM"))
        self.addParameter(
            QgsProcessingParameterDistance(
                self.INTERVAL,
                "경사 계산 선분 간격",
                defaultValue=10.0,
                minValue=1.0,
                maxValue=500.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.TRANSIT,
                "대중교통 경로선",
                type=QgsProcessing.TypeVectorLine,
                defaultValue=QgsProcessing.TEMPORARY_OUTPUT,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.SEGMENTS,
                "도보 경사 선분",
                type=QgsProcessing.TypeVectorLine,
                defaultValue=QgsProcessing.TEMPORARY_OUTPUT,
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.SUMMARY,
                "경로별 경사 요약",
                type=QgsProcessing.TypeVector,
                defaultValue=QgsProcessing.TEMPORARY_OUTPUT,
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        server_url = self.parameterAsString(
            parameters, self.SERVER_URL, context
        ).rstrip("/")
        project_text = self.parameterAsString(
            parameters, self.ODSAY_PROJECT_DIR, context
        ).strip()
        project_dir = Path(project_text) if project_text else None
        sx = self.parameterAsDouble(parameters, self.ORIGIN_LONGITUDE, context)
        sy = self.parameterAsDouble(parameters, self.ORIGIN_LATITUDE, context)
        ex = self.parameterAsDouble(parameters, self.DESTINATION_LONGITUDE, context)
        ey = self.parameterAsDouble(parameters, self.DESTINATION_LATITUDE, context)
        interval = self.parameterAsDouble(parameters, self.INTERVAL, context)
        dem_layer = self.parameterAsRasterLayer(parameters, self.DEM, context)

        if not dem_layer or not dem_layer.isValid():
            raise QgsProcessingException("유효한 DEM을 선택해야 합니다.")
        if interval <= 0:
            raise QgsProcessingException("선분 간격은 0보다 커야 합니다.")

        feedback.pushInfo("ODsay 서버 상태를 확인합니다.")
        self._ensure_server(server_url, project_dir, feedback)
        query = urllib.parse.urlencode({"sx": sx, "sy": sy, "ex": ex, "ey": ey})
        routes = self._get_json(f"{server_url}/api/routes?{query}")
        route_items = routes.get("routes") or []
        if not route_items:
            raise QgsProcessingException("ODsay 추천 경로가 없습니다.")
        feedback.pushInfo(f"ODsay 추천 경로 {len(route_items)}개를 찾았습니다.")

        dem_dataset = gdal.Open(dem_layer.source())
        if dem_dataset is None:
            raise QgsProcessingException(f"DEM을 열 수 없습니다: {dem_layer.source()}")
        dem_band = dem_dataset.GetRasterBand(1)
        dem_array = dem_band.ReadAsArray()
        nodata = dem_band.GetNoDataValue()
        geo_transform = dem_dataset.GetGeoTransform()
        inverse_transform = gdal.InvGeoTransform(geo_transform)
        dem_resolution = abs(geo_transform[1])
        output_crs = dem_layer.crs()
        if not output_crs.isValid():
            raise QgsProcessingException("DEM 좌표계를 확인할 수 없습니다.")
        transform = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:4326"),
            output_crs,
            context.transformContext(),
        )

        transit_fields = self._transit_fields()
        transit_sink, transit_destination = self.parameterAsSink(
            parameters,
            self.TRANSIT,
            context,
            transit_fields,
            QgsWkbTypes.LineString,
            output_crs,
        )
        if transit_sink is None:
            raise QgsProcessingException("대중교통 경로선 레이어를 만들 수 없습니다.")
        segment_fields = self._segment_fields()
        segment_sink, segment_destination = self.parameterAsSink(
            parameters,
            self.SEGMENTS,
            context,
            segment_fields,
            QgsWkbTypes.LineString,
            output_crs,
        )
        if segment_sink is None:
            raise QgsProcessingException("도보 경사 선분 레이어를 만들 수 없습니다.")

        stats = {}
        created = 0
        skipped = 0
        total_routes = len(route_items)
        for position, route in enumerate(route_items, start=1):
            if feedback.isCanceled():
                break
            route_number = int(route["routeNumber"])
            response = self._get_json(
                f"{server_url}/api/routes/{route_number}/geometry?{query}"
            )
            for line_index, transit in enumerate(
                response.get("transitLines") or [], start=1
            ):
                transit_points = [
                    QgsPointXY(float(point["longitude"]), float(point["latitude"]))
                    for point in transit.get("points") or []
                    if point.get("longitude") is not None
                    and point.get("latitude") is not None
                ]
                if len(transit_points) < 2:
                    continue
                transit_geometry = QgsGeometry.fromPolylineXY(transit_points)
                transit_geometry.transform(transform)
                traffic_class = int(transit.get("trafficClass") or 0)
                transit_feature = QgsFeature(transit_fields)
                transit_feature.setGeometry(transit_geometry)
                transit_feature.setAttributes(
                    [
                        route_number,
                        line_index,
                        traffic_class,
                        "subway" if traffic_class == 1 else "bus",
                    ]
                )
                transit_sink.addFeature(
                    transit_feature, QgsFeatureSink.FastInsert
                )
            itinerary = response.get("itinerary") or []
            transit_indices = [
                int(item["segmentIndex"])
                for item in itinerary
                if item.get("mode") != "walk"
            ]
            first_transit = min(transit_indices) if transit_indices else None
            last_transit = max(transit_indices) if transit_indices else None

            for walking in response.get("walkingLines") or []:
                points = [
                    QgsPointXY(float(p["longitude"]), float(p["latitude"]))
                    for p in walking.get("points") or []
                    if p.get("longitude") is not None and p.get("latitude") is not None
                ]
                if len(points) < 2:
                    continue
                geometry = QgsGeometry.fromPolylineXY(points)
                geometry.transform(transform)
                length = geometry.length()
                if length <= 0:
                    continue
                segment_index = int(walking.get("segmentIndex", -1))
                if first_transit is None or segment_index < first_transit:
                    role = "origin_access"
                elif segment_index > last_transit:
                    role = "destination_access"
                else:
                    role = "transfer"

                distances = [0.0]
                distance = interval
                while distance < length:
                    distances.append(distance)
                    distance += interval
                distances.append(length)

                for part_index, (start_m, end_m) in enumerate(
                    zip(distances[:-1], distances[1:]), start=1
                ):
                    start_point = geometry.interpolate(start_m).asPoint()
                    end_point = geometry.interpolate(end_m).asPoint()
                    start_z = self._bilinear_elevation(
                        start_point.x(),
                        start_point.y(),
                        dem_array,
                        nodata,
                        inverse_transform,
                    )
                    end_z = self._bilinear_elevation(
                        end_point.x(),
                        end_point.y(),
                        dem_array,
                        nodata,
                        inverse_transform,
                    )
                    horizontal = end_m - start_m
                    if start_z is None or end_z is None or horizontal <= 0:
                        skipped += 1
                        continue
                    elevation_diff = end_z - start_z
                    grade = elevation_diff / horizontal * 100.0
                    absolute = abs(grade)

                    feature = QgsFeature(segment_fields)
                    feature.setGeometry(
                        QgsGeometry.fromPolylineXY(
                            [QgsPointXY(start_point), QgsPointXY(end_point)]
                        )
                    )
                    feature.setAttributes(
                        [
                            route_number,
                            segment_index,
                            role,
                            part_index,
                            start_m,
                            end_m,
                            horizontal,
                            start_z,
                            end_z,
                            elevation_diff,
                            grade,
                            absolute,
                            self._grade_class(absolute),
                            dem_resolution,
                            walking.get("geometryQuality"),
                        ]
                    )
                    segment_sink.addFeature(feature, QgsFeatureSink.FastInsert)
                    created += 1
                    self._update_stats(
                        stats,
                        route_number,
                        role,
                        horizontal,
                        elevation_diff,
                        grade,
                    )
            feedback.pushInfo(
                f"{route_number}번 경로 완료 "
                f"({position}/{total_routes}, 경사 선분 누적 {created}개)"
            )
            feedback.setProgress(position / total_routes * 90)

        summary_fields = self._summary_fields()
        summary_sink, summary_destination = self.parameterAsSink(
            parameters,
            self.SUMMARY,
            context,
            summary_fields,
            QgsWkbTypes.NoGeometry,
            output_crs,
        )
        if summary_sink is None:
            raise QgsProcessingException("경로별 요약 테이블을 만들 수 없습니다.")
        for route_number in sorted(stats):
            values = stats[route_number]
            length = values["length"]
            feature = QgsFeature(summary_fields)
            feature.setAttributes(
                [
                    route_number,
                    values["segments"],
                    length,
                    values["weighted_abs"] / length if length else None,
                    self._weighted_percentile(values["samples"], 0.95),
                    values["max_abs"],
                    values["uphill_gain"],
                    values["downhill_gain"],
                    values["over_5"],
                    values["over_5"] / length if length else None,
                    values["over_8"],
                    values["over_8"] / length if length else None,
                    self._role_mean(values, "origin_access"),
                    self._role_mean(values, "transfer"),
                    self._role_mean(values, "destination_access"),
                    dem_resolution,
                    interval,
                ]
            )
            summary_sink.addFeature(feature, QgsFeatureSink.FastInsert)

        if context.willLoadLayerOnCompletion(segment_destination):
            details = context.layerToLoadOnCompletionDetails(segment_destination)
            details.name = "ODsay 도보 경사도"
            processor = _SlopeStylePostProcessor()
            _SlopeStylePostProcessor.instances.append(processor)
            details.setPostProcessor(processor)
        if context.willLoadLayerOnCompletion(transit_destination):
            context.layerToLoadOnCompletionDetails(
                transit_destination
            ).name = "ODsay 대중교통 경로"
        if context.willLoadLayerOnCompletion(summary_destination):
            context.layerToLoadOnCompletionDetails(
                summary_destination
            ).name = "ODsay 경로별 경사 요약"

        feedback.setProgress(100)
        feedback.pushInfo(
            f"완료: 경로 {len(stats)}개, 경사 선분 {created}개, "
            f"DEM 범위 밖 선분 {skipped}개"
        )
        feedback.pushWarning(
            "경사도는 선택한 DEM 해상도 기반 추정값입니다. "
            "90m DEM은 보도·계단·경사로의 실측값이 아닙니다."
        )
        dem_dataset = None
        return {
            self.TRANSIT: transit_destination,
            self.SEGMENTS: segment_destination,
            self.SUMMARY: summary_destination,
        }

    @staticmethod
    def _discover_odsay_project():
        try:
            script_path = Path(__file__).resolve()
            for parent in script_path.parents:
                candidate = parent / "ODsay"
                if (candidate / "server.mjs").exists():
                    return candidate
        except (IndexError, OSError):
            pass
        return None

    @staticmethod
    def _get_json(url, timeout=60):
        try:
            request = urllib.request.Request(
                url, headers={"Accept": "application/json"}
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raise QgsProcessingException(
                f"API HTTP {error.code}: {body[:500]}"
            ) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise QgsProcessingException(f"API 연결 실패: {error}") from error
        except json.JSONDecodeError as error:
            raise QgsProcessingException("API 응답이 유효한 JSON이 아닙니다.") from error
        if isinstance(result, dict) and result.get("error"):
            raise QgsProcessingException(str(result["error"]))
        return result

    def _ensure_server(self, server_url, project_dir, feedback):
        try:
            self._get_json(f"{server_url}/api/health", timeout=3)
            feedback.pushInfo("ODsay 서버가 이미 실행 중입니다.")
            return
        except QgsProcessingException:
            pass
        if not project_dir:
            project_dir = self._discover_odsay_project()
        if not project_dir:
            raise QgsProcessingException(
                "ODsay 서버가 꺼져 있고 프로젝트 폴더가 지정되지 않았습니다."
            )
        project_dir = Path(project_dir)
        if not (project_dir / "server.mjs").exists():
            raise QgsProcessingException(
                f"server.mjs가 없습니다: {project_dir / 'server.mjs'}"
            )
        if not (project_dir / ".env").exists():
            raise QgsProcessingException(f".env가 없습니다: {project_dir / '.env'}")
        node = self._find_node()
        if not node:
            raise QgsProcessingException(
                "Node.js 실행 파일을 찾을 수 없습니다. Node.js 설치 또는 PATH를 확인하세요."
            )
        try:
            subprocess.Popen(
                [node, "--env-file=.env", "server.mjs"],
                cwd=str(project_dir),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except OSError as error:
            raise QgsProcessingException(
                f"Node 서버를 실행하지 못했습니다: {error}"
            ) from error
        feedback.pushInfo("ODsay 서버를 시작했습니다. 준비 상태를 기다립니다.")
        for _ in range(20):
            time.sleep(0.5)
            try:
                self._get_json(f"{server_url}/api/health", timeout=2)
                return
            except QgsProcessingException:
                continue
        raise QgsProcessingException(
            "ODsay 서버가 10초 안에 준비되지 않았습니다. .env와 포트를 확인하세요."
        )

    @staticmethod
    def _find_node():
        found = shutil.which("node")
        if found:
            return found
        candidates = []
        for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            root = os.environ.get(variable)
            if root:
                candidates.append(Path(root) / "nodejs" / "node.exe")
        candidates.extend(
            [
                Path(r"C:\Program Files\nodejs\node.exe"),
                Path(r"C:\Program Files (x86)\nodejs\node.exe"),
            ]
        )
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return None

    @staticmethod
    def _bilinear_elevation(x, y, array, nodata, inverse_transform):
        pixel_x, pixel_y = gdal.ApplyGeoTransform(inverse_transform, x, y)
        pixel_x -= 0.5
        pixel_y -= 0.5
        x0 = math.floor(pixel_x)
        y0 = math.floor(pixel_y)
        dx = pixel_x - x0
        dy = pixel_y - y0
        if (
            x0 < 0
            or y0 < 0
            or x0 + 1 >= array.shape[1]
            or y0 + 1 >= array.shape[0]
        ):
            return None
        values = [
            float(array[y0, x0]),
            float(array[y0, x0 + 1]),
            float(array[y0 + 1, x0]),
            float(array[y0 + 1, x0 + 1]),
        ]
        for value in values:
            if not math.isfinite(value):
                return None
            if nodata is not None and abs(value - nodata) < 1e-6:
                return None
        return (
            values[0] * (1 - dx) * (1 - dy)
            + values[1] * dx * (1 - dy)
            + values[2] * (1 - dx) * dy
            + values[3] * dx * dy
        )

    @staticmethod
    def _grade_class(value):
        if value <= 2:
            return "gentle_0_2"
        if value <= 5:
            return "moderate_2_5"
        if value <= 8:
            return "steep_5_8"
        return "very_steep_over_8"

    @staticmethod
    def _new_stats():
        return {
            "segments": 0,
            "length": 0.0,
            "weighted_abs": 0.0,
            "max_abs": 0.0,
            "uphill_gain": 0.0,
            "downhill_gain": 0.0,
            "over_5": 0.0,
            "over_8": 0.0,
            "samples": [],
            "roles": {},
        }

    def _update_stats(self, stats, route_number, role, length, elevation_diff, grade):
        values = stats.setdefault(route_number, self._new_stats())
        absolute = abs(grade)
        values["segments"] += 1
        values["length"] += length
        values["weighted_abs"] += absolute * length
        values["max_abs"] = max(values["max_abs"], absolute)
        values["uphill_gain"] += max(elevation_diff, 0)
        values["downhill_gain"] += max(-elevation_diff, 0)
        if absolute > 5:
            values["over_5"] += length
        if absolute > 8:
            values["over_8"] += length
        values["samples"].append((absolute, length))
        role_values = values["roles"].setdefault(
            role, {"length": 0.0, "weighted_abs": 0.0}
        )
        role_values["length"] += length
        role_values["weighted_abs"] += absolute * length

    @staticmethod
    def _weighted_percentile(samples, percentile):
        if not samples:
            return None
        ordered = sorted(samples)
        target = sum(weight for _, weight in ordered) * percentile
        cumulative = 0.0
        for value, weight in ordered:
            cumulative += weight
            if cumulative >= target:
                return value
        return ordered[-1][0]

    @staticmethod
    def _role_mean(values, role):
        role_values = values["roles"].get(role)
        if not role_values or not role_values["length"]:
            return None
        return role_values["weighted_abs"] / role_values["length"]

    @staticmethod
    def _segment_fields():
        fields = QgsFields()
        definitions = (
            ("route_no", QMetaType.Type.Int),
            ("seg_idx", QMetaType.Type.Int),
            ("walk_role", QMetaType.Type.QString),
            ("part_idx", QMetaType.Type.Int),
            ("from_m", QMetaType.Type.Double),
            ("to_m", QMetaType.Type.Double),
            ("length_m", QMetaType.Type.Double),
            ("elev_start", QMetaType.Type.Double),
            ("elev_end", QMetaType.Type.Double),
            ("elev_diff", QMetaType.Type.Double),
            ("grade_pct", QMetaType.Type.Double),
            ("abs_grade", QMetaType.Type.Double),
            ("grade_class", QMetaType.Type.QString),
            ("dem_res_m", QMetaType.Type.Double),
            ("geom_quality", QMetaType.Type.QString),
        )
        for name, field_type in definitions:
            fields.append(QgsField(name, field_type))
        return fields

    @staticmethod
    def _transit_fields():
        fields = QgsFields()
        definitions = (
            ("route_no", QMetaType.Type.Int),
            ("line_idx", QMetaType.Type.Int),
            ("traffic_class", QMetaType.Type.Int),
            ("mode", QMetaType.Type.QString),
        )
        for name, field_type in definitions:
            fields.append(QgsField(name, field_type))
        return fields

    @staticmethod
    def _summary_fields():
        fields = QgsFields()
        definitions = (
            ("route_no", QMetaType.Type.Int),
            ("segment_cnt", QMetaType.Type.Int),
            ("walk_len_m", QMetaType.Type.Double),
            ("mean_abs", QMetaType.Type.Double),
            ("p95_abs", QMetaType.Type.Double),
            ("max_abs", QMetaType.Type.Double),
            ("uphill_m", QMetaType.Type.Double),
            ("downhill_m", QMetaType.Type.Double),
            ("over5_m", QMetaType.Type.Double),
            ("over5_ratio", QMetaType.Type.Double),
            ("over8_m", QMetaType.Type.Double),
            ("over8_ratio", QMetaType.Type.Double),
            ("origin_mean", QMetaType.Type.Double),
            ("transfer_mean", QMetaType.Type.Double),
            ("dest_mean", QMetaType.Type.Double),
            ("dem_res_m", QMetaType.Type.Double),
            ("interval_m", QMetaType.Type.Double),
        )
        for name, field_type in definitions:
            fields.append(QgsField(name, field_type))
        return fields


def _run_cli():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--odsay-project-dir", required=True)
    parser.add_argument("--origin-longitude", type=float, required=True)
    parser.add_argument("--origin-latitude", type=float, required=True)
    parser.add_argument("--destination-longitude", type=float, required=True)
    parser.add_argument("--destination-latitude", type=float, required=True)
    parser.add_argument("--dem", required=True)
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--transit", required=True)
    parser.add_argument("--segments", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--project")
    args = parser.parse_args()

    from qgis.analysis import QgsNativeAlgorithms
    from processing.core.Processing import Processing

    application = QgsApplication([], False)
    application.initQgis()
    Processing.initialize()
    if not application.processingRegistry().providerById("native"):
        application.processingRegistry().addProvider(QgsNativeAlgorithms())
    try:
        algorithm = ODsayWalkingSlopeAnalysis()
        context = QgsProcessingContext()
        context.setProject(QgsProject.instance())
        feedback = QgsProcessingFeedback()
        result = algorithm.run(
            {
                algorithm.SERVER_URL: args.server_url,
                algorithm.ODSAY_PROJECT_DIR: args.odsay_project_dir,
                algorithm.ORIGIN_LONGITUDE: args.origin_longitude,
                algorithm.ORIGIN_LATITUDE: args.origin_latitude,
                algorithm.DESTINATION_LONGITUDE: args.destination_longitude,
                algorithm.DESTINATION_LATITUDE: args.destination_latitude,
                algorithm.DEM: args.dem,
                algorithm.INTERVAL: args.interval,
                algorithm.TRANSIT: QgsProcessing.TEMPORARY_OUTPUT,
                algorithm.SEGMENTS: QgsProcessing.TEMPORARY_OUTPUT,
                algorithm.SUMMARY: QgsProcessing.TEMPORARY_OUTPUT,
            },
            context,
            feedback,
        )
        if not result[1]:
            raise RuntimeError("QGIS 경사도 분석이 실패했습니다.")
        segment_layer = QgsProcessingUtils.mapLayerFromString(
            result[0][algorithm.SEGMENTS], context
        )
        transit_layer = QgsProcessingUtils.mapLayerFromString(
            result[0][algorithm.TRANSIT], context
        )
        summary_layer = QgsProcessingUtils.mapLayerFromString(
            result[0][algorithm.SUMMARY], context
        )
        if not transit_layer or not segment_layer or not summary_layer:
            raise RuntimeError("QGIS 임시 분석 레이어를 찾을 수 없습니다.")
        output_path = args.segments.split("|", 1)[0]
        if (
            args.transit.split("|", 1)[0] != output_path
            or args.summary.split("|", 1)[0] != output_path
        ):
            raise RuntimeError("세 출력은 같은 GeoPackage 경로여야 합니다.")
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "current_slope_segments"
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile
        written = QgsVectorFileWriter.writeAsVectorFormatV3(
            segment_layer, output_path, context.transformContext(), options
        )
        if written[0] != QgsVectorFileWriter.NoError:
            raise RuntimeError(f"경사 구간 저장 실패: {written[1]}")
        options.layerName = "current_route_summary"
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        written = QgsVectorFileWriter.writeAsVectorFormatV3(
            summary_layer, output_path, context.transformContext(), options
        )
        if written[0] != QgsVectorFileWriter.NoError:
            raise RuntimeError(f"경로 요약 저장 실패: {written[1]}")
        options.layerName = "current_transit_lines"
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        written = QgsVectorFileWriter.writeAsVectorFormatV3(
            transit_layer, output_path, context.transformContext(), options
        )
        if written[0] != QgsVectorFileWriter.NoError:
            raise RuntimeError(f"대중교통 경로 저장 실패: {written[1]}")
        if args.project:
            project = QgsProject.instance()
            if not project.read(args.project):
                raise RuntimeError("busan_slope QGIS 프로젝트를 읽을 수 없습니다.")
            expected = str(Path(output_path).resolve()).lower()
            for layer in list(project.mapLayers().values()):
                source = layer.source().split("|", 1)[0].lower()
                source_name = Path(source).name
                if (
                    expected in source
                    or source_name == "current_odsay_analysis.gpkg"
                    or layer.name().startswith(("01 ", "02 "))
                ):
                    project.removeMapLayer(layer.id())
            root = project.layerTreeRoot()
            for group_name in (
                "01 경로별 경사도",
                "01 경로별 전체 이동 경로",
            ):
                old_group = root.findGroup(group_name)
                if old_group:
                    root.removeChildNode(old_group)
            group = root.insertGroup(0, "01 경로별 전체 이동 경로")
            group.setExpanded(True)
            styles = (
                ("gentle_0_2", "완만 0~2%", "#2ca25f"),
                ("moderate_2_5", "보통 2~5%", "#f2cf4a"),
                ("steep_5_8", "급경사 5~8%", "#f28e2b"),
                ("very_steep_over_8", "매우 급경사 8% 초과", "#d73027"),
            )
            summary_rows = sorted(
                summary_layer.getFeatures(), key=lambda feature: feature["route_no"]
            )
            for position, row in enumerate(summary_rows):
                route_number = int(row["route_no"])
                walk_length = float(row["walk_len_m"] or 0)
                mean_grade = float(row["mean_abs"] or 0)
                max_grade = float(row["max_abs"] or 0)
                name = (
                    f"경로 {route_number:02d} · 도보 {walk_length:.0f}m · "
                    f"평균 {mean_grade:.1f}% · 최대 {max_grade:.1f}%"
                )
                route_group = group.addGroup(name)
                route_group.setExpanded(position == 0)
                route_group.setItemVisibilityChecked(position == 0)
                route_layer = QgsVectorLayer(
                    output_path + "|layername=current_slope_segments",
                    "도보 경사도",
                    "ogr",
                )
                if not route_layer.isValid():
                    raise RuntimeError(f"{route_number}번 경사 레이어가 유효하지 않습니다.")
                route_layer.setSubsetString(f'"route_no" = {route_number}')
                categories = []
                for value, label, color in styles:
                    symbol = _slope_symbol(color)
                    categories.append(QgsRendererCategory(value, symbol, label))
                route_layer.setRenderer(
                    QgsCategorizedSymbolRenderer("grade_class", categories)
                )
                project.addMapLayer(route_layer, False)
                route_group.addLayer(route_layer)
                transit_route_layer = QgsVectorLayer(
                    output_path + "|layername=current_transit_lines",
                    "대중교통 경로 (버스 보라 · 지하철 파랑)",
                    "ogr",
                )
                if not transit_route_layer.isValid():
                    raise RuntimeError(
                        f"{route_number}번 대중교통 레이어가 유효하지 않습니다."
                    )
                transit_route_layer.setSubsetString(
                    f'"route_no" = {route_number}'
                )
                transit_categories = []
                for mode, label, color in (
                    ("bus", "버스", "#8e44ad"),
                    ("subway", "지하철", "#2468df"),
                ):
                    symbol = QgsLineSymbol.createSimple(
                        {
                            "color": color,
                            "width": "1.6",
                            "line_style": "dash",
                            "capstyle": "flat",
                        }
                    )
                    transit_categories.append(
                        QgsRendererCategory(mode, symbol, label)
                    )
                transit_route_layer.setRenderer(
                    QgsCategorizedSymbolRenderer("mode", transit_categories)
                )
                project.addMapLayer(transit_route_layer, False)
                route_group.addLayer(transit_route_layer)
            project_summary = QgsVectorLayer(
                output_path + "|layername=current_route_summary",
                "02 현재 ODsay 경로별 경사 요약",
                "ogr",
            )
            if not project_summary.isValid():
                raise RuntimeError("프로젝트의 경로 요약 테이블이 유효하지 않습니다.")
            project.addMapLayer(project_summary, False)
            root.insertLayer(1, project_summary)
            if not project.write(args.project):
                raise RuntimeError("busan_slope QGIS 프로젝트 저장에 실패했습니다.")
        print(
            json.dumps(
                {
                    "output": output_path,
                    "routeCount": summary_layer.featureCount(),
                    "segmentCount": segment_layer.featureCount(),
                },
                ensure_ascii=False,
            )
        )
        sys.stdout.flush()
        if os.name == "nt":
            os._exit(0)
    finally:
        application.exitQgis()


if __name__ == "__main__":
    from qgis.core import (
        QgsApplication,
        QgsProcessingContext,
        QgsProcessingFeedback,
        QgsProcessingUtils,
        QgsProject,
        QgsVectorLayer,
        QgsVectorFileWriter,
    )

    _run_cli()
