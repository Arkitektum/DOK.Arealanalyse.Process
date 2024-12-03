from sys import maxsize
from io import BytesIO
from typing import List
from osgeo import ogr
from lxml import etree as ET
from uuid import UUID
from .analysis import Analysis
from .result_status import ResultStatus
from .config.dataset_config import DatasetConfig
from .config.layer import Layer
from ..services.geolett import get_geolett_data
from ..services.raster_result import get_raster_result, get_cartography_url
from ..utils.helpers.common import parse_string, evaluate_condition, xpath_select_one
from ..utils.helpers.geometry import create_buffered_geometry, geometry_from_gml
from ..http_clients.wfs import query_wfs


class WfsAnalysis(Analysis):
    def __init__(self, dataset_id: UUID, config: DatasetConfig, geometry: ogr.Geometry, epsg: int, orig_epsg: int, buffer: int):
        super().__init__(dataset_id, config, geometry, epsg, orig_epsg, buffer)

    async def run_queries(self) -> None:
        first_layer = self.config.layers[0]
        geolett_data = await get_geolett_data(first_layer.geolett_id)

        for layer in self.config.layers:
            if layer.filter is not None:
                self.add_run_algorithm(f'query {layer.filter}')

            status_code, api_response = await query_wfs(
                self.config.wfs, layer.wfs, self.config.geom_field, self.run_on_input_geometry, self.epsg)

            if status_code == 408:
                self.result_status = ResultStatus.TIMEOUT
                break
            elif status_code != 200:
                self.result_status = ResultStatus.ERROR
                break

            self.add_run_algorithm(f'intersect {layer.wfs}')

            if api_response is not None:
                response = self.__parse_response(api_response, layer)

                if len(response['properties']) > 0:
                    geolett_data = await get_geolett_data(layer.geolett_id)

                    self.geometries = response['geometries']
                    self.data = response['properties']
                    self.raster_result = get_raster_result(
                        self.config.wms, layer.wms)
                    self.cartography = await get_cartography_url(
                        self.config.wms, layer.wms)
                    self.result_status = layer.result_status
                    break

        self.geolett = geolett_data

    async def set_distance_to_object(self) -> None:
        buffered_geom = create_buffered_geometry(
            self.geometry, 20000, self.epsg)
        layer = self.config.layers[0]

        _, response = await query_wfs(self.config.wfs, layer.wfs, self.config.geom_field, buffered_geom, self.epsg)

        if response is None:
            self.distance_to_object = maxsize
            return

        source = BytesIO(response.encode('utf-8'))
        context = ET.iterparse(source, huge_tree=True)
        distances = []

        for _, elem in context:
            localname = ET.QName(elem).localname

            if localname != self.config.geom_field:
                continue

            geom_elem = xpath_select_one(elem, './*')

            if geom_elem is None:
                continue

            gml_str = ET.tostring(geom_elem, encoding='unicode')
            feature_geom = geometry_from_gml(gml_str)

            if feature_geom:
                distance = round(
                    self.run_on_input_geometry.Distance(feature_geom))
                distances.append(distance)

        distances.sort()
        self.add_run_algorithm('get distance')

        if len(distances) == 0:
            self.distance_to_object = maxsize
        else:
            self.distance_to_object = distances[0]

    def __parse_response(self, wfs_response: str, layer: dict) -> dict[str, List]:
        data = {
            'properties': [],
            'geometries': []
        }

        source = BytesIO(wfs_response.encode('utf-8'))
        context = ET.iterparse(source, huge_tree=True)

        for _, elem in context:
            localname = ET.QName(elem).localname

            if localname != 'member':
                continue

            props = self.__map_properties(elem)

            if self.__filter_member(props, layer):
                data['properties'].append(props)
                data['geometries'].append(
                    self.__get_geometry_from_response(elem))

        return data

    def __filter_member(self, props: dict, layer: Layer) -> bool:
        if not layer.filter:
            return True

        return evaluate_condition(layer.filter, props)

    def __map_properties(self, member: ET._Element) -> dict:
        props = {}

        for mapping in self.config.properties:
            path = f'.//*[local-name() = "{mapping}"]/text()'
            value = xpath_select_one(member, path)

            if value:
                prop_name = mapping
                props[prop_name] = parse_string(value)

        return props

    def __get_geometry_from_response(self, member) -> ogr.Geometry:
        geom_field = self.config.geom_field
        path = f'.//*[local-name() = "{geom_field}"]/*'
        geom_elem = xpath_select_one(member, path)

        if geom_elem is None:
            return None

        gml_str = ET.tostring(geom_elem, encoding='unicode')

        return geometry_from_gml(gml_str)
