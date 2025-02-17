from decimal import Decimal
import logging
from pathlib import Path
import re
from typing import Union
import warnings

from matplotlib import cm, colors, pyplot as plt
import pandas as pd
from scipy.spatial import Voronoi, voronoi_plot_2d

from fehmtk.config import BoundaryConfig, FlowConfig, HeatFluxConfig, RunConfig
from fehmtk.fehm_objects import Grid, Node
from fehmtk.file_interface import read_grid, write_compact_node_data

from .boundary_models import get_boundary_model


logger = logging.getLogger(__name__)


def generate_flow_boundaries(config_file: Path):
    logger.info(f'Reading configuration file: {config_file}')
    config = RunConfig.from_yaml(config_file)
    if config.files_config.flow is None:
        raise ValueError(f'Flow file missing from files_config in RunConfig at {config_file}')

    _validate_config(config.flow_config)

    logger.info('Parsing grid into memory')
    grid = read_grid(
        config.files_config.grid,
        outside_zone_file=config.files_config.outside_zone,
        material_zone_file=config.files_config.material_zone,
        storage_file=config.files_config.storage,
        read_elements=False,
    )

    logger.info('Generating flow data')
    flow_by_node = generate_boundary_data_by_node_number(
        grid,
        boundary_configs=config.flow_config.boundary_configs,
        boundary_kind='flow',
    )
    write_compact_node_data(
        flow_by_node,
        output_file=config.files_config.flow,
        header='flow\n',
        footer='0\n',
    )

    warn_if_file_not_referenced(input_file=config.files_config.input, referenced_file=config.files_config.flow)


def generate_heat_flux_boundaries(config_file: Path, plot: bool = False):
    logger.info(f'Reading configuration file: {config_file}')
    config = RunConfig.from_yaml(config_file)
    if not config.files_config.heat_flux:
        raise ValueError(f'No heat_flux file defined in {config_file}, required for output.')

    _validate_config(config.heat_flux_config)

    if plot and len(config.heat_flux_config.boundary_configs) > 1:
        raise NotImplementedError('No support for plotting when multiple boundary_configs are present.')

    logger.info('Parsing grid into memory')
    grid = read_grid(
        config.files_config.grid,
        outside_zone_file=config.files_config.outside_zone,
        area_file=config.files_config.area,
        read_elements=False,
    )

    logger.info('Computing boundary heat flux')
    heatflux_by_node = generate_boundary_data_by_node_number(
        grid,
        boundary_configs=config.heat_flux_config.boundary_configs,
        boundary_kind='heat_flux',
    )

    logger.info(f'Writing heat flux to disk: {config.files_config.heat_flux}')
    write_compact_node_data(
        {node_number: (heatflux, '0.') for node_number, heatflux in heatflux_by_node.items()},
        output_file=config.files_config.heat_flux,
        header='hflx\n',
        footer='0\n',
    )
    warn_if_file_not_referenced(input_file=config.files_config.input, referenced_file=config.files_config.heat_flux)

    if plot:
        plot_heatflux(heatflux_by_node, grid)


def generate_boundary_data_by_node_number(
    grid: Grid,
    *,
    boundary_configs: list[BoundaryConfig],
    boundary_kind: str,
) -> dict[int, float]:
    flow_data_by_number = {}
    for boundary_config in boundary_configs:
        model = get_boundary_model(boundary_kind, boundary_config.boundary_model.kind)
        nodes = _gather_nodes(grid, boundary_config.outside_zones, boundary_config.material_zones)
        for node in nodes:
            flow_data_by_number[node.number] = model(node, boundary_config.boundary_model.params)

    return flow_data_by_number


def _gather_nodes(grid: Grid, outside_zones: list[Union[str, int]], material_zones: list[Union[str, int]]) -> set[Node]:
    nodes = set()
    for zone in outside_zones:
        nodes.update(grid.get_nodes_in_outside_zone(zone))
    for zone in material_zones:
        nodes.update(grid.get_nodes_in_material_zone(zone))
    return nodes


def warn_if_file_not_referenced(*, input_file: Path, referenced_file: Path):
    content = input_file.read_text()
    match = re.search(rf'(\s){referenced_file.name}(\s)', content)
    if not match:
        warnings.warn(f'Generated file {referenced_file.name} IS NOT REFERENCED in {input_file.name}.')


def _validate_config(config: Union[FlowConfig, HeatFluxConfig]):
    if config is None:
        raise ValueError('No relevant boundary config (flow, heat_flux) found in config file.')

    for boundary_config in config.boundary_configs:
        if not boundary_config.material_zones and not boundary_config.outside_zones:
            raise ValueError('No zones specified (outside or material), at least one zone is required.')


def plot_heatflux(heatflux_by_node: dict[int, Decimal], grid: Grid):
    entries = []
    for node_number, heatflux_MW in heatflux_by_node.items():
        node = grid.node(node_number)
        entries.append({
            'x': node.x / 1E3,  # convert m -> km
            'y': node.y / 1E3,  # convert m -> km
            'heatflux_mW': 1E9 * heatflux_MW / node.outside_area.z,  # convert to MW -> mW
        })
    plot_data = pd.DataFrame(entries)

    axis_2d = _get_2d_axis_or_none(plot_data)
    if axis_2d:
        _plot_heatflux_2d(plot_data, plot_axis='x' if axis_2d == 'y' else 'y')
        return

    _plot_heatflux_3d(plot_data)


def _plot_heatflux_2d(plot_data: pd.DataFrame, plot_axis: str):
    fig, ax = plt.subplots(figsize=(8, 5))
    plot_data.plot(x=plot_axis, y='heatflux_mW', marker='o', legend=False, ax=ax)
    ax.set_xlabel(rf'{plot_axis} ($km$)')
    ax.set_ylabel(r'Heat flux ($mW/m^2$)')
    ax.set_title('Bottom boundary heat flux')
    plt.show()


def _plot_heatflux_3d(plot_data: pd.DataFrame):
    vor = Voronoi(plot_data[['x', 'y']].values)
    heatflux_mW = plot_data['heatflux_mW'].values

    norm = colors.Normalize(vmin=min(heatflux_mW), vmax=max(heatflux_mW), clip=True)
    mapper = cm.ScalarMappable(norm=norm, cmap=cm.Reds)

    fig, ax = plt.subplots(figsize=(8, 8))
    voronoi_plot_2d(vor, show_points=False, show_vertices=False, line_width=0.3, ax=ax)
    for region_index, region_heatflux_mW in zip(vor.point_region, heatflux_mW):
        region = vor.regions[region_index]
        if -1 in region:
            continue

        polygon = [vor.vertices[i] for i in region]
        ax.fill(*zip(*polygon), color=mapper.to_rgba(region_heatflux_mW))

    ax.set_aspect('equal')
    ax.set_xlabel(r'x ($km$)')
    ax.set_ylabel(r'y ($km$)')
    ax.set_title(r'Bottom boundary heat flux ($mW/m^2$)')
    plt.colorbar(mapper, ax=ax)
    plt.show()


def _get_2d_axis_or_none(plot_data: pd.DataFrame) -> str:
    if not plot_data.x.var():
        return 'x'

    if not plot_data.y.var():
        return 'y'

    return None
