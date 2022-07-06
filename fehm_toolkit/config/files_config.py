from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class FilesConfig:
    """Files configuration defining paths for model run."""
    material_zone: Path
    outside_zone: Path
    area: Path
    rock_properties: Path
    conductivity: Path
    pore_pressure: Path
    permeability: Path
    heat_flux: Path
    flow: Path
    files: Path
    grid: Path
    input: Path
    output: Path
    store: Path
    history: Path
    water_properties: Path
    check: Path
    error: Path
    final_conditions: Path
    initial_conditions: Optional[Path] = None

    @classmethod
    def from_dict(cls, dct):
        return cls(**{k: Path(v) for k, v in dct.items()})
