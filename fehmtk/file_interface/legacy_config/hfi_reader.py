from decimal import Decimal
from pathlib import Path
import re

from fehmtk.config import BoundaryConfig, HeatFluxConfig, ModelConfig

CRUSTAL_AGE_MODEL_KIND = 'crustal_age'

CRUSTAL_AGE_MODEL_SIGNATURE = 'HFLX=@(x,y,z)A./AGE(x).^(.5)'
AGE_SIGN_PATTERN = r'AGE=@\(x\)\(1\.\/\(SPREADRATE\.\*1E3\)\)\.\*\((-?)x\+X0\)'
NUMERIC_PATTERN = r'(?:(?:\d+\.\d+)|(?:\.{0,1}\d+))(?:(?:e|E)-{0,1}\d+){0,1}'


def read_legacy_hfi_config(hfi_file: Path) -> HeatFluxConfig:
    """Read legacy heatflux in files (.hfi)

    This assumes a fairly specific format for these files, supporting only a few files with a specific structure.
    """
    processed_text = _read_and_process_hfi(hfi_file)

    is_crustal_age_model = CRUSTAL_AGE_MODEL_SIGNATURE in processed_text
    if is_crustal_age_model:
        return HeatFluxConfig(
            boundary_configs=[
                BoundaryConfig(
                    boundary_model=ModelConfig(
                        kind=CRUSTAL_AGE_MODEL_KIND,
                        params=_get_crustal_age_model_parameters(processed_text, hfi_file),
                    ),
                    outside_zones=['bottom'],
                    material_zones=[],
                ),
            ],
        )

    constant = _get_constant_or_none(processed_text)
    if constant is not None:
        return HeatFluxConfig(
            boundary_configs=[
                BoundaryConfig(
                    boundary_model=ModelConfig(kind='constant_MW_per_m2', params={'constant': constant}),
                    outside_zones=['bottom'],
                    material_zones=[],
                ),
            ],
        )

    raise NotImplementedError(f'No model matched for {hfi_file}. File format not supported.')


def _get_crustal_age_model_parameters(processed_text: str, hfi_file: Path) -> dict[str, Decimal]:
    return {
        'crustal_age_dimension': 'x',
        'crustal_age_sign': _get_crustal_age_sign(processed_text, hfi_file),
        'spread_rate_mm_per_year': _get_spread_rate(processed_text, hfi_file),
        'coefficient_MW': _get_heatflux_coefficient(processed_text, hfi_file),
        'boundary_distance_to_ridge_m': _get_distance_to_ridge(processed_text, hfi_file),
    }


def _get_crustal_age_sign(processed_text: str, hfi_file: Path) -> int:
    match = re.search(AGE_SIGN_PATTERN, processed_text)
    if match is None:
        raise NotImplementedError(
            f'File ({hfi_file}) is a crustal age model, but no age function found.'
        )
    crustal_age_sign = -1 if match.group(1) == '-' else 1
    return crustal_age_sign


def _get_spread_rate(processed_text: str, hfi_file: Path) -> Decimal:
    match = re.search(fr'SPREADRATE=({NUMERIC_PATTERN})', processed_text)
    if match is None:
        raise NotImplementedError(f'File {hfi_file} is a crustal age model, but no SPREADRATE found.')
    return Decimal(match.group(1))


def _get_heatflux_coefficient(processed_text: str, hfi_file: Path) -> Decimal:
    match = re.search(fr'A=({NUMERIC_PATTERN})', processed_text)
    if match is None:
        raise NotImplementedError(f'File {hfi_file} is a crustal age model, but no coefficient (A=) found.')
    return Decimal(match.group(1))


def _get_distance_to_ridge(processed_text: str, hfi_file: Path) -> Decimal:
    match = re.search(fr'X0=({NUMERIC_PATTERN})', processed_text)
    if match is None:
        raise NotImplementedError(f'File {hfi_file} is a crustal age model, but no distance to ridge (X0=) found.')
    return Decimal(match.group(1))


def _read_and_process_hfi(hfi_file: Path) -> str:
    with open(hfi_file) as f:
        processed_text = ''
        save_lines = False
        for line in f:
            if line.strip() == 'stop':
                break

            if save_lines:
                comments_removed = line.strip().split('%')[0]
                compressed = comments_removed.replace(' ', '')
                processed_text += compressed + '\n'

            if line.strip() == 'hflx':
                save_lines = True

    if not processed_text:
        raise NotImplementedError(f'File ({hfi_file}) read no text, file format not supported.')

    return processed_text


def _get_constant_or_none(processed_text: str) -> Decimal:
    match = re.search(fr'HFLX=@\(x,y,z\)({NUMERIC_PATTERN})(?:;|\n)', processed_text)
    if match is None:
        return None
    return Decimal(match.group(1))
