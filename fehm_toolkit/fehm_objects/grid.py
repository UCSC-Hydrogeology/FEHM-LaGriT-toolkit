import logging
from pathlib import Path
from typing import Optional, Iterable, Union

import numpy as np
from scipy import interpolate

from ..file_interface import read_fehm, read_zones
from .element import Element
from .node import Node
from .vector import Vector


logger = logging.getLogger(__name__)


class Grid:
    """Class representing a mesh or grid object."""

    def __init__(
        self,
        nodes_by_number: dict[int, Node],
        elements_by_number: dict[int, Element],
        *,
        node_numbers_by_material_zone_number: Optional[dict[int, tuple[int]]] = None,
        node_numbers_by_outside_zone_number: Optional[dict[int, tuple[int]]] = None,
        outside_zone_number_by_name: Optional[dict[str, int]] = None,
    ):
        self._nodes_by_number = nodes_by_number
        self._elements_by_number = elements_by_number
        self._node_numbers_by_material_zone_number = node_numbers_by_material_zone_number
        self._node_numbers_by_outside_zone_number = node_numbers_by_outside_zone_number
        self._outside_zone_number_by_name = outside_zone_number_by_name

    def node(self, number: int) -> Node:
        try:
            return self._nodes_by_number[number]
        except KeyError:
            raise KeyError(f'Node ({number}) not found in grid.')

    def element(self, number: int) -> Element:
        try:
            return self._elements_by_number[number]
        except KeyError:
            raise KeyError(f'Element ({number}) not found in grid.')

    @property
    def n_nodes(self) -> int:
        return len(self._nodes_by_number)

    @property
    def nodes(self) -> Iterable[Node]:
        return self._nodes_by_number.values()

    @property
    def n_elements(self) -> int:
        return len(self._elements_by_number)

    @property
    def elements(self) -> Iterable[Element]:
        return self._elements_by_number.values()

    @property
    def material_zones(self) -> set[int]:
        if self._node_numbers_by_material_zone_number is None:
            raise ValueError('Grid has not been loaded with zone data.')
        return set(self._node_numbers_by_material_zone_number.keys())

    @property
    def outside_zones(self) -> set[int]:
        if self._node_numbers_by_outside_zone_number is None:
            raise ValueError('Grid has not been loaded with zone data.')
        return set(self._node_numbers_by_outside_zone_number.keys())

    def get_nodes_in_material_zone(self, zone_number: Union[int, Iterable[int]]) -> tuple[Node]:
        try:
            nodes = []
            for number in zone_number:
                for node in self._get_nodes_in_material_zone(number):
                    nodes.append(node)
            return tuple(nodes)
        except TypeError:
            return tuple(node for node in self._get_nodes_in_material_zone(zone_number))

    def _get_nodes_in_material_zone(self, zone_number: int) -> Iterable[Node]:
        if self._node_numbers_by_material_zone_number is None:
            raise ValueError('Grid has not been loaded with zone data.')

        try:
            node_numbers = self._node_numbers_by_material_zone_number[zone_number]
        except KeyError:
            raise KeyError(f'Zone "{zone_number}" not found in grid.')

        for node_number in node_numbers:
            yield self._nodes_by_number[node_number]

    def get_nodes_in_outside_zone(self, zone_number_or_name: Union[int, str]):
        if self._node_numbers_by_outside_zone_number is None:
            raise ValueError('Grid has not been loaded with zone data.')

        try:
            node_numbers = self._node_numbers_by_outside_zone_number[zone_number_or_name]
        except KeyError as e:
            if self._outside_zone_number_by_name is None:
                raise e

            try:
                zone_number = self._outside_zone_number_by_name[zone_number_or_name]
                node_numbers = self._node_numbers_by_outside_zone_number[zone_number]
            except KeyError:
                raise KeyError(f'Zone "{zone_number_or_name}" not found in grid.')

        for node_number in node_numbers:
            yield self._nodes_by_number[node_number]

    @classmethod
    def from_files(
        cls,
        fehm_file: Path,
        *,
        material_zone_file: Optional[Path] = None,
        outside_zone_file: Optional[Path] = None,
        area_file: Optional[Path] = None,
        read_elements: Optional[bool] = True,
    ) -> 'Grid':
        if area_file and not outside_zone_file:
            raise NotImplementedError('Must specify an outside_zone_file to load area data.')

        logger.debug(f'Reading nodes and elements from {fehm_file}')
        coordinates_by_number, elements_by_number = read_fehm(fehm_file, read_elements=read_elements)

        material_zone_lookup = None
        if material_zone_file:
            logger.debug(f'Reading material zones from {material_zone_file}')
            material_zone_lookup, _ = read_zones(material_zone_file)

        outside_zone_lookup, outside_zone_number_by_name, area_by_number, depth_by_number = (None, None, None, None)
        if outside_zone_file:
            logger.debug(f'Reading outside zones from {outside_zone_file}')
            outside_zone_lookup, outside_zone_number_by_name = read_zones(outside_zone_file)

            if area_file:
                logger.debug(f'Reading outside area from {area_file}')
                area_lookup, area_outside_zone_number_by_name = read_zones(area_file)
                _validate_outside_zone_lookups_match(outside_zone_number_by_name, area_outside_zone_number_by_name)
                area_by_number = _get_area_by_node_number(
                    areas_by_zone=area_lookup,
                    nodes_by_zone=outside_zone_lookup,
                )

            logger.debug('Calculating node depths')
            top_zone = outside_zone_number_by_name.get('top')
            top_nodes = outside_zone_lookup.get(top_zone)
            depth_by_number = calculate_node_depths(coordinates_by_number, top_nodes)

        logger.debug('Constructing nodes lookup')
        nodes_by_number = _construct_nodes_lookup(coordinates_by_number, area_by_number, depth_by_number)

        grid = cls(
            nodes_by_number=nodes_by_number,
            elements_by_number=elements_by_number,
            node_numbers_by_material_zone_number=material_zone_lookup,
            node_numbers_by_outside_zone_number=outside_zone_lookup,
            outside_zone_number_by_name=outside_zone_number_by_name,
        )
        return grid


def _construct_nodes_lookup(
    coordinates_by_number: dict[int, Vector],
    area_by_number: Optional[dict[int, Vector]],
    depth_by_number: Optional[dict[int, float]],
) -> dict[int, Node]:
    return {
        number: Node(
            number,
            coordinates,
            outside_area=area_by_number.get(number) if area_by_number else None,
            depth=depth_by_number.get(number) if depth_by_number else None,
        )
        for number, coordinates in coordinates_by_number.items()
    }


def _get_area_by_node_number(
    *,
    areas_by_zone: dict[int, tuple[tuple[float]]],
    nodes_by_zone: dict[int, tuple[int]],
) -> dict[int, tuple[float]]:
    mismatched_keys = areas_by_zone.keys() ^ nodes_by_zone.keys()  # ^ is the symmetric difference operator for sets
    if mismatched_keys:
        raise ValueError(f'Area and node number lookups do not have the same zones: {mismatched_keys}')

    area_by_node_number = {}
    for zone_number, areas in areas_by_zone.items():
        node_numbers = nodes_by_zone[zone_number]
        if len(areas) != len(node_numbers):
            raise ValueError(
                f'Different number of nodes ({len(node_numbers)}) and areas ({len(areas)}) in zone "{zone_number}"'
            )

        for node_number, area in zip(node_numbers, areas):
            assigned_area = area_by_node_number.get(node_number)
            if assigned_area:
                if assigned_area != area:
                    raise ValueError(
                        f'Node "{node_number}"" area ({area}) for zone "{zone_number}" '
                        f'does not match area assigned from previous zone ({assigned_area})'
                    )
                continue
            area_by_node_number[node_number] = area

    return area_by_node_number


def _validate_outside_zone_lookups_match(lookup_1: dict, lookup_2: dict):
    if lookup_1 != lookup_2:
        mismatched_keys = lookup_1.keys() ^ lookup_2.keys()  # ^ is the symmetric difference operator for sets
        if mismatched_keys:
            raise ValueError(f'Different zone names between .area and _outside_zone files: {mismatched_keys}')

        for key in lookup_1.keys():
            if lookup_1[key] != lookup_2[key]:
                raise ValueError(f'Different zone numbers for zone "{key}": [{lookup_1[key]}, {lookup_2[key]}]')

        raise ValueError('Different zone names or numbers between .area and _outside.zone files.')


def calculate_node_depths(
    coordinates_by_number: dict[int, Vector],
    top_nodes: Optional[Iterable[int]],
) -> Optional[dict[int, float]]:
    if not top_nodes:
        return None

    top_coordinates = np.array([coordinates_by_number[node_number].value for node_number in top_nodes])
    flat_dimension = _get_flat_dimension_or_none(top_coordinates)
    if flat_dimension is not None:
        model_dimension = 1 if flat_dimension == 0 else 0
        seafloor_1d = interpolate.interp1d(
            x=top_coordinates[:, model_dimension],
            y=top_coordinates[:, 2],
            bounds_error=False,
            fill_value='extrapolate',
        )
        return {
            number: float(seafloor_1d(coordinates.value[model_dimension])) - coordinates.z
            for number, coordinates in coordinates_by_number.items()
        }

    seafloor_2d_linear = interpolate.LinearNDInterpolator(top_coordinates[:, 0:2], top_coordinates[:, 2])
    seafloor_2d_nearest = interpolate.NearestNDInterpolator(top_coordinates[:, 0:2], top_coordinates[:, 2])

    ordered_entries = sorted(coordinates_by_number.items())
    ordered_xy = np.array([coordinates.value[:2] for number, coordinates in ordered_entries])
    linear_interpolated = seafloor_2d_linear(ordered_xy)

    depth_by_number = {}
    for linear, (number, coordinates) in zip(linear_interpolated, ordered_entries):
        seafloor = linear if not np.isnan(linear) else float(seafloor_2d_nearest(coordinates.x, coordinates.y))
        depth_by_number[number] = round(seafloor - coordinates.z, 10)  # rounding avoids floating point variation
    return depth_by_number


def _get_flat_dimension_or_none(coordinates: np.array) -> Optional[int]:
    """Identify which (if any) of the first two dimensions has no variance.
    >>> import numpy as np
    >>> _get_flat_dimension_or_none(np.array([[1, 1, 1], [2, 1, 2], [3, 1, 3]]))
    1
    >>> _get_flat_dimension_or_none(np.array([[1, 1, 1], [1, 1, 1], [1, 1, 1]]))
    0
    >>> _get_flat_dimension_or_none(np.array([[1, 1, 1], [2, 2, 1], [3, 3, 1]]))
    """
    for dim in (0, 1):
        if not coordinates[:, dim].var():
            return dim
    return None
