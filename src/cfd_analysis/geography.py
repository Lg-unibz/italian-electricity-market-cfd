"""Dependency-light plotting of official ISTAT regional shapefiles."""

from __future__ import annotations

import struct
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection
from matplotlib.colors import LogNorm, Normalize, SymLogNorm, TwoSlopeNorm
from matplotlib.path import Path as MplPath
from matplotlib.patches import PathPatch
from matplotlib.ticker import NullFormatter, NullLocator

from market_preprocessing.config import RAW_DIR
from market_preprocessing.mapping import REGION_TO_ZONE

from .historical_inputs import canonicalize_region


ISTAT_DIR = RAW_DIR / "istat"


@dataclass(frozen=True)
class RegionGeometry:
    """One ISTAT region represented as polygon rings in WGS84 / UTM32N."""

    region: str
    rings: tuple[tuple[tuple[float, float], ...], ...]


def find_istat_region_shapefile(root: Path = ISTAT_DIR) -> Path:
    """Find the generalized 2024 ISTAT regional WGS84 shapefile."""

    candidates = sorted(root.rglob("Reg01012024_g_WGS84.shp"))
    if not candidates:
        candidates = sorted(root.rglob("*Reg*2024*g*WGS84*.shp"))
    if not candidates:
        raise FileNotFoundError(
            "Missing official generalized ISTAT 2024 region shapefile under "
            f"{root}. Run scripts/fetch_istat_boundaries.py."
        )
    return candidates[0]


def load_istat_region_geometries(shp_path: Path) -> dict[str, RegionGeometry]:
    """Read ISTAT polygon geometry and DBF attributes using the standard library."""

    dbf_path = shp_path.with_suffix(".dbf")
    if not dbf_path.exists():
        raise FileNotFoundError(f"Missing shapefile attribute table: {dbf_path}")
    polygons = _read_polygon_shapefile(shp_path)
    attributes = _read_dbf(dbf_path)
    if len(polygons) != len(attributes):
        raise ValueError(
            f"SHP/DBF record mismatch: {len(polygons)} geometries, "
            f"{len(attributes)} attribute rows"
        )
    name_field = _select_field(attributes, ("DEN_REG", "NOME_REG", "REG_NAME", "NAME_1"))
    grouped: dict[str, list[tuple[tuple[float, float], ...]]] = defaultdict(list)
    for rings, row in zip(polygons, attributes, strict=True):
        if not rings:
            continue
        region = canonicalize_region(row[name_field])
        grouped[region].extend(rings)
    missing = sorted(set(REGION_TO_ZONE) - set(grouped))
    extra = sorted(set(grouped) - set(REGION_TO_ZONE))
    if missing or extra or len(grouped) != 20:
        raise ValueError(
            f"ISTAT geographic join must contain exactly 20 regions; "
            f"missing={missing}, extra={extra}"
        )
    return {
        region: RegionGeometry(region=region, rings=tuple(rings))
        for region, rings in grouped.items()
    }


def plot_regional_mechanism_comparison(
    geometries: dict[str, RegionGeometry],
    source: pd.DataFrame,
    value_column: str,
    colour_map: str,
    colour_bar_label: str,
    output_path: Path,
    *,
    centre_on_zero: bool = False,
    colour_scale: str = "linear",
    symmetric_log_linthresh: float = 5.0,
    scale_source: pd.DataFrame | None = None,
    mechanisms: tuple[str, ...] = (
        "conventional_cfd",
        "zonal_yardstick_cfd",
        "schlecht_fcfd",
    ),
) -> None:
    """Plot one regional metric for the selected mechanisms.

    ``scale_source`` optionally supplies the values used to calculate the colour
    scale, allowing comparable maps across strike scenarios.
    """

    required = {"region", "mechanism", value_column}
    missing = sorted(required - set(source.columns))
    if missing:
        raise ValueError(f"Missing regional comparison map columns: {missing}")
    panel_titles = {
        "market_only": "Market only",
        "conventional_cfd": "Conventional two-sided CfD",
        "zonal_yardstick_cfd": "Zonal Yardstick CfD",
        "schlecht_fcfd": "Financial CfD",
    }
    for mechanism in mechanisms:
        _validate_map_source(
            source[source["mechanism"] == mechanism][["region", value_column]],
            geometries,
        )

    source_values = pd.to_numeric(source[value_column], errors="raise")
    scale_values = source_values if scale_source is None else pd.to_numeric(
        scale_source[value_column], errors="raise"
    )
    _, infinite_present = _finite_plot_values(source_values)
    scale_values_plot, _ = _finite_plot_values(scale_values)
    scale_values_plot = (
        scale_values_plot / 1_000 if "eur" in value_column else scale_values_plot
    )
    norm = _build_colour_norm(
        scale_values_plot,
        centre_on_zero=centre_on_zero,
        colour_scale=colour_scale,
        symmetric_log_linthresh=symmetric_log_linthresh,
    )

    fig, axes = plt.subplots(
        1,
        len(mechanisms),
        figsize=(4.2 * len(mechanisms), 6.0),
        constrained_layout=True,
    )
    axes = np.atleast_1d(axes)
    last_mappable = None
    for axis, mechanism in zip(axes.flat, mechanisms, strict=True):
        selected_values, _ = _finite_plot_values(
            _select_mechanism_values(source, mechanism, value_column)
        )
        if "eur" in value_column:
            selected_values = selected_values / 1_000
        region_values = selected_values.to_dict()
        last_mappable = _draw_regions(
            axis,
            geometries,
            region_values,
            cmap=colour_map,
            norm=norm,
        )
        axis.set_title(panel_titles[mechanism], loc="center", fontsize=12, pad=8)

    colorbar_label = colour_bar_label
    if colour_scale == "log":
        colorbar_label = f"{colorbar_label}; logarithmic colour scale"
    elif colour_scale == "symlog":
        colorbar_label = (
            f"{colorbar_label}; symmetric logarithmic colour scale "
            f"(linear within ±{symmetric_log_linthresh:g})"
        )
    if infinite_present:
        colorbar_label = f"{colorbar_label}; ∞ = zero annual SD"
    colour_bar = fig.colorbar(
        last_mappable,
        ax=list(axes.flat),
        orientation="horizontal",
        shrink=0.68,
        pad=0.025,
        aspect=36,
        label=colorbar_label,
    )
    colour_bar.ax.tick_params(labelsize=10)
    colour_bar.set_label(colorbar_label, fontsize=11)
    if colour_scale == "log":
        ticks = [
            value
            for value in (1, 2, 5, 10, 20, 50, 80, 100, 200)
            if float(norm.vmin) <= value <= float(norm.vmax)
        ]
        colour_bar.set_ticks(ticks)
        colour_bar.set_ticklabels([f"{value:g}" for value in ticks])
        colour_bar.ax.xaxis.set_minor_locator(NullLocator())
        colour_bar.ax.xaxis.set_minor_formatter(NullFormatter())
    elif colour_scale == "symlog":
        ticks = [
            value
            for value in (-100, -50, -20, -10, -5, 0, 5, 10, 20, 50, 100)
            if float(norm.vmin) <= value <= float(norm.vmax)
        ]
        colour_bar.set_ticks(ticks)
        colour_bar.set_ticklabels([f"{value:g}" for value in ticks])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=450, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _select_mechanism_values(
    source: pd.DataFrame,
    mechanism: str,
    value_column: str,
) -> pd.Series:
    """Return one unique regional value per mechanism for map rendering."""

    selection = source.loc[
        source["mechanism"] == mechanism,
        ["region", value_column],
    ]
    if selection["region"].duplicated().any() or len(selection) != 20:
        raise ValueError(
            f"Map panel {mechanism} must contain 20 unique regional rows"
        )
    return pd.to_numeric(selection.set_index("region")[value_column], errors="raise")


def _build_colour_norm(
    values: pd.Series,
    *,
    centre_on_zero: bool,
    colour_scale: str,
    symmetric_log_linthresh: float,
) -> Normalize:
    """Build a shared linear, logarithmic, or symmetric-log colour scale."""

    finite = pd.to_numeric(values, errors="raise").astype(float)
    finite = finite[np.isfinite(finite)]
    if finite.empty:
        raise ValueError("Colour-scale values must contain at least one finite value")
    if colour_scale == "log":
        if bool((finite <= 0).any()):
            raise ValueError("A logarithmic colour scale requires positive values")
        return LogNorm(
            vmin=float(finite.min()) / 1.03,
            vmax=float(finite.max()) * 1.03,
        )
    if colour_scale == "symlog":
        if symmetric_log_linthresh <= 0:
            raise ValueError("Symmetric-log linear threshold must be positive")
        absolute_limit = max(float(finite.abs().max()) * 1.03, 1.0)
        return SymLogNorm(
            linthresh=symmetric_log_linthresh,
            linscale=1.0,
            vmin=-absolute_limit,
            vmax=absolute_limit,
            base=10,
        )
    if colour_scale != "linear":
        raise ValueError(f"Unsupported colour scale: {colour_scale}")
    if centre_on_zero:
        absolute_limit = max(float(finite.abs().max()) * 1.03, 1.0)
        return TwoSlopeNorm(
            vmin=-absolute_limit,
            vcenter=0.0,
            vmax=absolute_limit,
        )
    minimum = float(finite.min())
    maximum = float(finite.max())
    span = maximum - minimum
    padding = max(span * 0.03, 0.5)
    return Normalize(vmin=minimum - padding, vmax=maximum + padding)


def plot_market_only_metrics(
    geometries: dict[str, RegionGeometry],
    source: pd.DataFrame,
    decadal_value_factor: pd.DataFrame,
    output_path: Path,
) -> None:
    """Plot market-only revenue, annual revenue SD, and decadal Value Factor."""

    required = {
        "region",
        "producer_mean_annual_revenue_real_2024_eur_per_mw",
        "producer_std_annual_revenue_real_2024_eur_per_mw",
    }
    missing = sorted(required - set(source.columns))
    if missing:
        raise ValueError(f"Missing market-only map columns: {missing}")
    _validate_map_source(source[["region"]].assign(value=0), geometries)
    required_value_factor = {"region", "ten_year_mean_value_factor"}
    missing = sorted(required_value_factor - set(decadal_value_factor.columns))
    if missing:
        raise ValueError(f"Missing decadal map columns: {missing}")
    _validate_map_source(
        decadal_value_factor[["region", "ten_year_mean_value_factor"]],
        geometries,
    )
    specifications = (
        (
            "producer_mean_annual_revenue_real_2024_eur_per_mw",
            "viridis",
            "Mean annual revenue [kEUR/MW-year, real 2024]",
            "Mean annual revenue",
        ),
        (
            "producer_std_annual_revenue_real_2024_eur_per_mw",
            "magma",
            "Annual revenue SD [kEUR/MW-year, real 2024]",
            "Annual revenue SD",
        ),
        (
            "ten_year_mean_value_factor",
            "RdBu_r",
            "10-year mean Value Factor",
            "10-year mean Value Factor",
        ),
    )
    fig, axes = plt.subplots(
        1,
        3,
        figsize=(13.2, 6.0),
        constrained_layout=True,
    )
    source_by_region = source.set_index("region")
    value_factor_by_region = decadal_value_factor.set_index("region")
    for axis, (column, colour_map, label, title) in zip(
        axes, specifications, strict=True
    ):
        values_source = (
            value_factor_by_region[column]
            if column == "ten_year_mean_value_factor"
            else source_by_region[column]
        )
        values, infinite_present = _finite_plot_values(
            pd.to_numeric(values_source, errors="raise")
        )
        multiplier = 1 / 1_000 if "eur" in column else 1.0
        values = values * multiplier
        finite = values[np.isfinite(values)]
        if column == "ten_year_mean_value_factor":
            distance = max(
                abs(float(finite.min()) - 1.0), abs(float(finite.max()) - 1.0)
            )
            limit = max(distance * 1.03, 0.02)
            norm: Normalize = TwoSlopeNorm(
                vmin=1.0 - limit,
                vcenter=1.0,
                vmax=1.0 + limit,
            )
        else:
            minimum = float(finite.min())
            maximum = float(finite.max())
            padding = max((maximum - minimum) * 0.03, 0.5)
            norm = Normalize(vmin=minimum - padding, vmax=maximum + padding)
        mappable = _draw_regions(
            axis,
            geometries,
            values.to_dict(),
            cmap=colour_map,
            norm=norm,
        )
        colour_bar = fig.colorbar(
            mappable,
            ax=axis,
            orientation="horizontal",
            shrink=0.78,
            pad=0.03,
            aspect=28,
            label=label,
        )
        colour_bar.ax.tick_params(labelsize=10)
        colour_bar.set_label(label, fontsize=11)
        if infinite_present:
            axis.text(
                0.5,
                -0.08,
                "∞ = zero annual revenue SD",
                transform=axis.transAxes,
                ha="center",
                fontsize=8,
            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=450, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_benchmark_concentration_risk_compression(
    summary: pd.DataFrame,
    output_path: Path,
) -> None:
    """Plot descriptive own-share versus inclusive/leave-one-out SD ratios."""

    required = {
        "historical_zone",
        "mechanism",
        "mean_own_capacity_share",
        "inclusive_to_leave_one_out_sd_ratio",
    }
    missing = sorted(required - set(summary.columns))
    if missing:
        raise ValueError(f"Missing concentration scatter columns: {missing}")
    source = summary.loc[
        np.isfinite(summary["mean_own_capacity_share"])
        & np.isfinite(summary["inclusive_to_leave_one_out_sd_ratio"])
    ].copy()
    if source.empty:
        raise ValueError("Concentration scatter requires at least one finite ratio")
    colours = {
        "Nord": "#35608d",
        "Centro Nord": "#668e43",
        "Centro Sud": "#d98a2b",
        "Sud": "#a64848",
    }
    markers = {"schlecht_fcfd": "o", "zonal_yardstick_cfd": "s"}
    fig, axis = plt.subplots(figsize=(7.2, 5.2), constrained_layout=True)
    for (zone, mechanism), frame in source.groupby(["historical_zone", "mechanism"], sort=True):
        mechanism_label = "Financial" if mechanism == "schlecht_fcfd" else "Yardstick K_P50"
        axis.scatter(
            frame["mean_own_capacity_share"],
            frame["inclusive_to_leave_one_out_sd_ratio"],
            color=colours.get(zone, "#666666"),
            marker=markers[mechanism],
            s=58,
            alpha=0.85,
            label=f"{zone} — {mechanism_label}",
        )
    axis.axhline(1.0, color="#555555", linewidth=0.8, linestyle="--")
    axis.set_xlabel("Mean own capacity share in historical zone")
    axis.set_ylabel("Inclusive SD / leave-one-out SD")
    axis.set_title("Benchmark concentration and descriptive risk compression")
    axis.set_ylim(bottom=0.0)
    axis.grid(alpha=0.25)
    axis.set_axisbelow(True)
    axis.legend(frameon=False, fontsize=7, ncols=2)
    fig.text(
        0.5,
        -0.02,
        "Descriptive diagnostic: benchmark exposure is mechanically attenuated by own capacity share.",
        ha="center",
        fontsize=8,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=450, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_centro_sud_benchmark_self_influence(
    geometries: dict[str, RegionGeometry],
    summary: pd.DataFrame,
    output_path: Path,
) -> None:
    """Plot the focused Centro Sud benchmark self-influence diagnostic."""

    regions = ("Campania", "Abruzzo", "Lazio", "Umbria")
    required = {
        "region", "mechanism", "eligible_years", "mean_own_capacity_share",
        "inclusive_std_annual_revenue_real_2024_eur_per_mw",
        "leave_one_out_std_annual_revenue_real_2024_eur_per_mw",
    }
    missing = sorted(required - set(summary.columns))
    if missing:
        raise ValueError(f"Missing Centro Sud diagnostic columns: {missing}")
    subset_geometries = {region: geometries[region] for region in regions}
    if len(summary) != 8 or set(summary["region"]) != set(regions):
        raise ValueError("Centro Sud diagnostic must have two rows for each focus region")
    financial = summary.loc[summary["mechanism"].eq("Financial CfD")].set_index("region")
    yardstick = summary.loc[summary["mechanism"].eq("Zonal Yardstick CfD")].set_index("region")
    if len(financial) != 4 or len(yardstick) != 4:
        raise ValueError("Centro Sud diagnostic mechanisms are incomplete")

    fig, axes = plt.subplots(1, 3, figsize=(15.0, 5.0), constrained_layout=True)
    norm = Normalize(vmin=0.0, vmax=1.0)
    mappable = _draw_regions(
        axes[0],
        subset_geometries,
        financial["mean_own_capacity_share"].to_dict(),
        "YlOrRd",
        norm,
    )
    for region in regions:
        xmin, ymin, xmax, ymax = _bounds({region: subset_geometries[region]})
        axes[0].text(
            (xmin + xmax) / 2, (ymin + ymax) / 2,
            f"{region}\n{financial.loc[region, 'mean_own_capacity_share'] * 100:.1f}%",
            ha="center", va="center", fontsize=8,
            fontweight="bold" if region == "Campania" else "normal",
            bbox={"facecolor": "white", "alpha": 0.72, "edgecolor": "none", "pad": 1.0},
        )
    axes[0].set_title("Mean Centro Sud capacity share")
    colour_bar = fig.colorbar(mappable, ax=axes[0], fraction=0.048, pad=0.02)
    colour_bar.set_label("Share of zonal capacity")

    labels = [f"{region}\n(n={int(financial.loc[region, 'eligible_years'])})" for region in regions]
    positions = np.arange(len(regions))
    width = 0.37
    for axis, source, title in (
        (axes[1], financial, "Financial CfD"),
        (axes[2], yardstick, "Zonal Yardstick CfD ($K_{P50}$)"),
    ):
        inclusive = source.loc[list(regions), "inclusive_std_annual_revenue_real_2024_eur_per_mw"].to_numpy() / 1_000
        leave_one_out = source.loc[list(regions), "leave_one_out_std_annual_revenue_real_2024_eur_per_mw"].to_numpy() / 1_000
        axis.bar(positions - width / 2, inclusive, width, label="Inclusive", color="#35608d")
        axis.bar(positions + width / 2, leave_one_out, width, label="Leave-one-out", color="#e17c40")
        axis.set_xticks(positions, labels, fontsize=8)
        axis.set_ylabel("Annual revenue SD [kEUR/MW-year]")
        axis.set_title(title)
        axis.grid(axis="y", alpha=0.25)
        axis.set_axisbelow(True)
        for tick, region in zip(axis.get_xticklabels(), regions, strict=True):
            if region == "Campania":
                tick.set_fontweight("bold")
    axes[1].legend(frameon=False, fontsize=8)
    fig.text(
        0.5, -0.02,
        "Statistics use historical zone membership; Umbria is comparable only from 2021 to 2024.",
        ha="center", fontsize=8,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=450, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_single_regional_map(
    geometries: dict[str, RegionGeometry],
    source: pd.DataFrame,
    value_column: str,
    colour_map: str,
    colour_bar_label: str,
    output_path: Path,
    *,
    title: str = "",
    multiplier: float = 1.0,
) -> None:
    """Plot a single regional metric on the ISTAT map of Italy."""

    if "region" not in source.columns or value_column not in source.columns:
        raise ValueError(f"Missing required columns in source: region, {value_column}")

    selection = source.set_index("region")
    values, infinite_present = _finite_plot_values(
        pd.to_numeric(selection[value_column], errors="raise")
    )
    region_values = (values * multiplier).to_dict()

    finite_values = [value for value in region_values.values() if np.isfinite(value)]
    minimum = float(min(finite_values))
    maximum = float(max(finite_values))
    span = maximum - minimum
    padding = max(span * 0.03, 0.01)
    norm = Normalize(vmin=minimum - padding, vmax=maximum + padding)

    fig, axis = plt.subplots(figsize=(6.2, 7.0), constrained_layout=True)
    mappable = _draw_regions(
        axis,
        geometries,
        region_values,
        cmap=colour_map,
        norm=norm,
    )
    colour_bar = fig.colorbar(
        mappable,
        ax=axis,
        orientation="horizontal",
        shrink=0.75,
        pad=0.03,
        aspect=30,
        label=colour_bar_label,
    )
    colour_bar.ax.tick_params(labelsize=10)
    colour_bar.set_label(colour_bar_label, fontsize=11)
    if infinite_present:
        fig.text(
            0.5,
            0.005,
            "∞ denotes zero sample standard deviation of annual revenue",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=450, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _finite_plot_values(values: pd.Series) -> tuple[pd.Series, bool]:
    """Replace infinities with a finite upper/lower plotting sentinel."""

    numeric = pd.to_numeric(values, errors="raise").astype(float)
    finite = numeric[np.isfinite(numeric)]
    if finite.empty:
        raise ValueError("Plot values must contain at least one finite value")
    span = max(float(finite.max() - finite.min()), 1.0)
    upper = float(finite.max() + 0.05 * span)
    lower = float(finite.min() - 0.05 * span)
    output = numeric.replace(np.inf, upper).replace(-np.inf, lower)
    return output, bool((~np.isfinite(numeric)).any())



def _draw_regions(
    axis: plt.Axes,
    geometries: dict[str, RegionGeometry],
    values: dict[str, float],
    cmap: str,
    norm: Normalize,
):
    colormap = plt.get_cmap(cmap)
    for region, geometry in geometries.items():
        patch = _geometry_patch(
            geometry,
            facecolor=colormap(norm(float(values[region]))),
            edgecolor="#555555",
            linewidth=0.35,
        )
        axis.add_patch(patch)
    zone_segments = _zone_boundary_segments(geometries)
    axis.add_collection(LineCollection(zone_segments, colors="#111111", linewidths=1.15))
    xmin, ymin, xmax, ymax = _bounds(geometries)
    margin_x = (xmax - xmin) * 0.025
    margin_y = (ymax - ymin) * 0.025
    axis.set_xlim(xmin - margin_x, xmax + margin_x)
    axis.set_ylim(ymin - margin_y, ymax + margin_y)
    axis.set_aspect("equal", adjustable="box")
    axis.set_axis_off()
    return plt.cm.ScalarMappable(norm=norm, cmap=colormap)


def _geometry_patch(
    geometry: RegionGeometry,
    facecolor: object,
    edgecolor: str,
    linewidth: float,
) -> PathPatch:
    vertices: list[tuple[float, float]] = []
    codes: list[int] = []
    for ring in geometry.rings:
        if len(ring) < 3:
            continue
        vertices.extend(ring)
        codes.extend([MplPath.MOVETO] + [MplPath.LINETO] * (len(ring) - 1))
        vertices.append(ring[0])
        codes.append(MplPath.CLOSEPOLY)
    return PathPatch(
        MplPath(vertices, codes),
        facecolor=facecolor,
        edgecolor=edgecolor,
        linewidth=linewidth,
        joinstyle="round",
    )


def _zone_boundary_segments(
    geometries: dict[str, RegionGeometry],
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    by_zone: dict[str, Counter[tuple[tuple[float, float], tuple[float, float]]]] = defaultdict(Counter)
    original: dict[
        tuple[str, tuple[tuple[float, float], tuple[float, float]]],
        tuple[tuple[float, float], tuple[float, float]],
    ] = {}
    for region, geometry in geometries.items():
        zone = REGION_TO_ZONE[region]
        for ring in geometry.rings:
            points = list(ring)
            if points and points[0] != points[-1]:
                points.append(points[0])
            for start, end in zip(points, points[1:]):
                rounded = (tuple(round(value, 7) for value in start), tuple(round(value, 7) for value in end))
                key = tuple(sorted(rounded))
                by_zone[zone][key] += 1
                original[(zone, key)] = (start, end)
    return [
        original[(zone, key)]
        for zone, counts in by_zone.items()
        for key, count in counts.items()
        if count == 1
    ]


def _bounds(
    geometries: dict[str, RegionGeometry],
) -> tuple[float, float, float, float]:
    points = [point for geometry in geometries.values() for ring in geometry.rings for point in ring]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _validate_map_source(
    frame: pd.DataFrame,
    geometries: dict[str, RegionGeometry],
) -> None:
    if frame["region"].duplicated().any():
        raise ValueError("Map source has duplicate region rows")
    missing = sorted(set(geometries) - set(frame["region"]))
    extra = sorted(set(frame["region"]) - set(geometries))
    if missing or extra or len(frame) != 20:
        raise ValueError(f"Incomplete 20-region map join; missing={missing}, extra={extra}")


def _read_polygon_shapefile(
    path: Path,
) -> list[tuple[tuple[tuple[float, float], ...], ...]]:
    records: list[tuple[tuple[tuple[float, float], ...], ...]] = []
    with path.open("rb") as handle:
        header = handle.read(100)
        if len(header) != 100 or struct.unpack(">i", header[:4])[0] != 9994:
            raise ValueError(f"Invalid shapefile header: {path}")
        while True:
            record_header = handle.read(8)
            if not record_header:
                break
            if len(record_header) != 8:
                raise ValueError(f"Truncated shapefile record header: {path}")
            _, content_words = struct.unpack(">2i", record_header)
            content = handle.read(content_words * 2)
            if len(content) != content_words * 2:
                raise ValueError(f"Truncated shapefile record: {path}")
            shape_type = struct.unpack("<i", content[:4])[0]
            if shape_type == 0:
                records.append(tuple())
                continue
            if shape_type not in (5, 15, 25):
                raise ValueError(f"Unsupported region shapefile type {shape_type}")
            num_parts, num_points = struct.unpack("<2i", content[36:44])
            parts = list(struct.unpack(f"<{num_parts}i", content[44 : 44 + 4 * num_parts]))
            points_offset = 44 + 4 * num_parts
            coordinates = struct.unpack(
                f"<{num_points * 2}d",
                content[points_offset : points_offset + 16 * num_points],
            )
            points = [
                (coordinates[index], coordinates[index + 1])
                for index in range(0, len(coordinates), 2)
            ]
            part_ends = parts[1:] + [num_points]
            rings = tuple(tuple(points[start:end]) for start, end in zip(parts, part_ends, strict=True))
            records.append(rings)
    return records


def _read_dbf(path: Path) -> list[dict[str, str]]:
    with path.open("rb") as handle:
        header = handle.read(32)
        record_count = struct.unpack("<I", header[4:8])[0]
        header_length = struct.unpack("<H", header[8:10])[0]
        record_length = struct.unpack("<H", header[10:12])[0]
        field_bytes = handle.read(header_length - 33)
        terminator = handle.read(1)
        if terminator != b"\r":
            raise ValueError(f"Invalid DBF field terminator: {path}")
        fields: list[tuple[str, int]] = []
        for offset in range(0, len(field_bytes), 32):
            descriptor = field_bytes[offset : offset + 32]
            if len(descriptor) < 32:
                continue
            name = descriptor[:11].split(b"\0", 1)[0].decode("ascii")
            fields.append((name, descriptor[16]))
        rows: list[dict[str, str]] = []
        for _ in range(record_count):
            record = handle.read(record_length)
            if len(record) != record_length:
                raise ValueError(f"Truncated DBF record: {path}")
            if record[:1] == b"*":
                rows.append({name: "" for name, _ in fields})
                continue
            cursor = 1
            row: dict[str, str] = {}
            for name, length in fields:
                raw = record[cursor : cursor + length]
                cursor += length
                row[name] = (
                    raw.decode("utf-8", errors="replace").replace("\x00", "").strip()
                )
            rows.append(row)
    return rows


def _select_field(rows: list[dict[str, str]], candidates: tuple[str, ...]) -> str:
    if not rows:
        raise ValueError("Empty DBF attribute table")
    for candidate in candidates:
        if candidate in rows[0]:
            return candidate
    raise ValueError(f"No region-name field found; available={sorted(rows[0])}")
