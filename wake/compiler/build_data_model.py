from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, FrozenSet, List, Optional

from intervaltree import IntervalTree
from pydantic import (
    BaseModel,
    ConfigDict,
    PlainSerializer,
    PlainValidator,
    WithJsonSchema,
    errors,
    field_serializer,
)
from typing_extensions import Annotated

from wake.compiler.solc_frontend import SolcInputSettings, SolcOutputError
from wake.core.solidity_version import SolidityVersion
from wake.ir import SourceUnit
from wake.ir.reference_resolver import ReferenceResolver


def hex_bytes_validator(val: Any) -> bytes:
    if isinstance(val, bytes):
        return val
    elif isinstance(val, bytearray):
        return bytes(val)
    elif isinstance(val, str):
        return bytes.fromhex(val)
    raise errors.BytesError()


HexBytes = Annotated[
    bytes,
    PlainValidator(hex_bytes_validator),
    PlainSerializer(lambda b: b.hex()),
    WithJsonSchema({"type": "string"}),
]


class BuildInfoModel(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        frozen=True,
    )


class CompilationUnitBuildInfo(BuildInfoModel):
    """
    Holds all compilation errors and warnings that occurred during compilation of a single compilation unit.
    Some errors and warnings may not be associated with any specific source code location.
    Because of incremental compilation, it is important to keep track of all errors and warnings that occurred during compilation of a compilation unit with a given hash.

    Attributes:
        errors: List of compilation warnings and errors that occurred during compilation of the compilation unit.
    """

    errors: List[SolcOutputError]


class SourceUnitInfo(BuildInfoModel):
    """
    Attributes:
        fs_path: Path to the source unit.
        blake2b_hash: 256-bit blake2b hash of the source unit contents.
    """

    fs_path: Path
    blake2b_hash: HexBytes


class ProjectBuildInfo(BuildInfoModel):
    """
    Attributes:
        compilation_units: Mapping of compilation unit hex-encoded hashes to compilation unit build info.
        source_units_info: Mapping of source unit names to source unit info.
        allow_paths: Compilation [allow_paths][wake.config.data_model.SolcConfig.allow_paths] used during compilation.
        exclude_paths: Compilation [exclude_paths][wake.config.data_model.SolcConfig.exclude_paths] used during compilation.
        include_paths: Compilation [include_paths][wake.config.data_model.SolcConfig.include_paths] used during compilation.
        settings: solc input settings used during compilation.
        target_solidity_version: Solidity [target_version][wake.config.data_model.SolcConfig.target_version] used during compilation, if any.
        wake_version: `eth-wake` version used during compilation.
        incremental: Whether the compilation was performed in incremental mode.
    """

    compilation_units: Dict[str, CompilationUnitBuildInfo]
    source_units_info: Dict[str, SourceUnitInfo]
    allow_paths: FrozenSet[Path]
    exclude_paths: FrozenSet[Path]
    include_paths: FrozenSet[Path]
    settings: SolcInputSettings
    target_solidity_version: Optional[SolidityVersion]
    wake_version: str
    incremental: bool

    @field_serializer("target_solidity_version", when_used="json")
    def serialize_target_version(self, version: Optional[SolidityVersion], info):
        return str(version) if version is not None else None


class ProjectBuild:
    """
    Class holding a single project build.
    """

    _interval_trees: Dict[Path, IntervalTree]
    _reference_resolver: ReferenceResolver
    _source_units: Dict[Path, SourceUnit]

    def __init__(
        self,
        interval_trees: Dict[Path, IntervalTree],
        reference_resolver: ReferenceResolver,
        source_units: Dict[Path, SourceUnit],
    ):
        self._interval_trees = interval_trees
        self._reference_resolver = reference_resolver
        self._source_units = source_units

    @property
    def interval_trees(self) -> Dict[Path, IntervalTree]:
        """
        Returns:
            Mapping of source file paths to [interval trees](https://github.com/chaimleib/intervaltree) that can be used to query IR nodes by byte offsets in the source code.
        """
        return MappingProxyType(
            self._interval_trees
        )  # pyright: ignore reportGeneralTypeIssues

    @property
    def reference_resolver(self) -> ReferenceResolver:
        """
        Returns:
            Reference resolver responsible for resolving AST node IDs to IR nodes. Useful especially for resolving references across different compilation units.
        """
        return self._reference_resolver

    @property
    def source_units(self) -> Dict[Path, SourceUnit]:
        """
        Returns:
            Mapping of source file paths to top-level [SourceUnit][wake.ir.meta.source_unit.SourceUnit] IR nodes.
        """
        return MappingProxyType(
            self._source_units
        )  # pyright: ignore reportGeneralTypeIssues
