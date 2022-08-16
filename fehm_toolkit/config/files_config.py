import dataclasses
from pathlib import Path
from typing import Optional


@dataclasses.dataclass
class FilesConfig:
    """Files configuration defining paths for model run."""
    run_root: str
    material_zone: Path
    outside_zone: Path
    area: Path
    rock_properties: Path
    conductivity: Path
    pore_pressure: Path
    permeability: Path
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
    flow: Optional[Path] = None
    heat_flux: Optional[Path] = None
    initial_conditions: Optional[Path] = None

    @classmethod
    def from_dict(cls, dct):
        return cls(**{
            k: Path(v) if k != 'run_root' and v is not None else v
            for k, v in dct.items()
        })

    def validate(self):
        self._assert_specified_paths_exist()

    def _assert_specified_paths_exist(self):
        does_not_exist = set()
        for key, path in dataclasses.asdict(self).items():
            if key == 'run_root':
                continue
            if path is not None and not path.exists():
                does_not_exist.add(path)
        if does_not_exist:
            raise AssertionError(
                f'FileConfig contains specified paths that do not exist: {[p.absolute() for p in does_not_exist]}'
            )
