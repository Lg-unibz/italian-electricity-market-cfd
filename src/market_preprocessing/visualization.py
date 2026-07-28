"""Exploratory preprocessing plots for the 2024 baseline."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import seaborn as sns

from .config import PREPROCESSING_FIGURES_DIR, ZONE_ORDER, ZONE_TO_SLUG
from .gme_prices import PriceRecord
from .mapping import regions_by_zone
from .preprocess_types import PreprocessingPanelRecord, ZoneMarketValueSummary
from .terna_wind import RegionalWindRecord


ZONE_COLORS = {
    "Nord": "#1D4E89",
    "Centro Nord": "#2A9D8F",
    "Centro Sud": "#E9C46A",
    "Sud": "#F4A261",
    "Calabria": "#B91C1C",
    "Sardegna": "#6D597A",
    "Sicilia": "#4B5563",
}


def build_preprocessing_figures(
    price_records: list[PriceRecord],
    regional_records: list[RegionalWindRecord],
    panel_records: list[PreprocessingPanelRecord],
    market_value_summary: list[ZoneMarketValueSummary],
    figures_dir: Path = PREPROCESSING_FIGURES_DIR,
) -> list[Path]:
    """Generate all 2024 preprocessing validation figures."""

    figures_dir.mkdir(parents=True, exist_ok=True)
    _configure_matplotlib()
    outputs = [
        _plot_simple_market_revenue(panel_records, figures_dir),
        _plot_market_value_decomposition(market_value_summary, figures_dir),
    ]
    outputs.extend(_plot_capacity_factor_by_zone_region(regional_records, figures_dir))
    outputs.extend(_plot_zonal_prices(price_records, figures_dir))
    return outputs


def _plot_capacity_factor_by_zone_region(
    records: list[RegionalWindRecord],
    figures_dir: Path,
) -> list[Path]:
    outputs: list[Path] = []
    grouped_regions = regions_by_zone()
    base_dir = figures_dir
    base_dir.mkdir(parents=True, exist_ok=True)
    for zone in ZONE_ORDER:
        zone_records = [record for record in records if record.zone == zone]
        regions = [
            region
            for region in grouped_regions.get(zone, [])
            if any(record.region == region for record in zone_records)
        ]
        if not regions:
            continue
        ncols = 2 if len(regions) > 1 else 1
        nrows = (len(regions) + ncols - 1) // ncols
        fig, axes = plt.subplots(
            nrows,
            ncols,
            figsize=(6.6 * ncols, 2.35 * nrows + 0.7),
            sharex=True,
            sharey=True,
        )
        axes_list = _as_axes_list(axes)
        for axis, region in zip(axes_list, regions, strict=False):
            selected = [record for record in zone_records if record.region == region]
            axis.plot(
                [record.day_of_year for record in selected],
                [record.capacity_factor for record in selected],
                color=ZONE_COLORS[zone],
                linewidth=0.75,
            )
            axis.set_title(region, fontsize=9, loc="left")
            axis.set_xlim(1, 366)
            axis.set_ylim(0, 1)
            _finish_axis(axis)
        for axis in axes_list[len(regions):]:
            axis.set_visible(False)
        for axis in axes_list[-ncols:]:
            if axis.get_visible():
                axis.set_xlabel("Day of 2024")
        for axis in axes_list[::ncols]:
            axis.set_ylabel("Hourly capacity factor [0-1]")
        path = base_dir / f"capacity_factor_by_region_2024_{ZONE_TO_SLUG[zone]}.png"
        fig.savefig(path, dpi=450, bbox_inches="tight")
        plt.close(fig)
        outputs.append(path)

    # Generate 4x5 summary plot for all regions
    all_regions = sorted(list({record.region for record in records}))
    if all_regions:
        ncols = 5
        nrows = (len(all_regions) + ncols - 1) // ncols
        fig, axes = plt.subplots(
            nrows,
            ncols,
            figsize=(3.3 * ncols, 2.35 * nrows + 0.7),
            sharex=True,
            sharey=True,
        )
        axes_list = _as_axes_list(axes)
        for axis, region in zip(axes_list, all_regions, strict=False):
            selected = [record for record in records if record.region == region]
            if not selected:
                continue
            zone = selected[0].zone
            axis.plot(
                [record.day_of_year for record in selected],
                [record.capacity_factor for record in selected],
                color=ZONE_COLORS[zone],
                linewidth=0.5,
            )
            axis.set_title(region, fontsize=9, loc="left")
            axis.set_xlim(1, 366)
            axis.set_ylim(0, 1)
            _finish_axis(axis)
        for axis in axes_list[len(all_regions):]:
            axis.set_visible(False)
        for axis in axes_list[-ncols:]:
            if axis.get_visible():
                axis.set_xlabel("Day of 2024")
        for axis in axes_list[::ncols]:
            axis.set_ylabel("Hourly capacity factor [0-1]")
        path = base_dir / "capacity_factor_by_region_2024_all.png"
        fig.savefig(path, dpi=450, bbox_inches="tight")
        plt.close(fig)
        outputs.append(path)

    return outputs


def _plot_zonal_prices(records: list[PriceRecord], figures_dir: Path) -> list[Path]:
    ncols = 2
    nrows = (len(ZONE_ORDER) + ncols - 1) // ncols
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(13.2, 2.7 * nrows + 0.5),
        sharex=True,
        sharey=True,
    )
    axes_list = _as_axes_list(axes)
    for axis, zone in zip(axes_list, ZONE_ORDER, strict=False):
        selected = [record for record in records if record.zone == zone]
        axis.plot(
            [record.day_of_year for record in selected],
            [record.price_eur_mwh for record in selected],
            color=ZONE_COLORS[zone],
            linewidth=0.75,
        )
        axis.set_title(zone, fontsize=9, loc="left")
        axis.set_xlim(1, 366)
        _finish_axis(axis)
    for axis in axes_list[len(ZONE_ORDER):]:
        axis.set_visible(False)
    for axis in axes_list[-ncols:]:
        if axis.get_visible():
            axis.set_xlabel("Day of 2024")
    for axis in axes_list[::ncols]:
        axis.set_ylabel("Zonal price [EUR/MWh]")
    path = figures_dir / "zonal_price_by_zone_2024.png"
    fig.savefig(path, dpi=450, bbox_inches="tight")
    plt.close(fig)
    return [path]


def _plot_simple_market_revenue(
    records: list[PreprocessingPanelRecord],
    figures_dir: Path,
) -> Path:
    ncols = 2
    nrows = (len(ZONE_ORDER) + ncols - 1) // ncols
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(13.2, 2.7 * nrows + 0.5),
        sharex=True,
        sharey=True,
    )
    axes_list = _as_axes_list(axes)
    for axis, zone in zip(axes_list, ZONE_ORDER, strict=False):
        selected = [record for record in records if record.zone == zone]
        axis.plot(
            [record.day_of_year for record in selected],
            [record.simple_market_revenue_eur_per_mw_hour for record in selected],
            color=ZONE_COLORS[zone],
            linewidth=0.75,
        )
        axis.set_title(zone, fontsize=9, loc="left")
        axis.set_xlim(1, 366)
        _finish_axis(axis)
    for axis in axes_list[len(ZONE_ORDER):]:
        axis.set_visible(False)
    for axis in axes_list[-ncols:]:
        if axis.get_visible():
            axis.set_xlabel("Day of 2024")
    for axis in axes_list[::ncols]:
        axis.set_ylabel("Revenue [EUR/MW-hour]")
    path = figures_dir / "simple_market_revenue_by_zone_2024.png"
    fig.savefig(path, dpi=450, bbox_inches="tight")
    plt.close(fig)
    return path


def _plot_market_value_decomposition(
    records: list[ZoneMarketValueSummary],
    figures_dir: Path,
) -> Path:
    ordered = [
        record
        for zone in ZONE_ORDER
        for record in records
        if record.zone == zone
    ]
    zones = [record.zone for record in ordered]
    colors = [ZONE_COLORS[record.zone] for record in ordered]

    fig, axes = plt.subplots(
        3,
        1,
        figsize=(11.2, 8.2),
        sharex=True,
    )
    axes_list = _as_axes_list(axes)

    _draw_bar_panel(
        axes_list[0],
        zones,
        [record.full_load_hours_mwh_per_mw_year for record in ordered],
        colors,
        "Full-load hours [MWh/MW-year]",
        "{:,.0f}",
    )
    _draw_capture_price_panel(axes_list[1], ordered, zones, colors)
    _draw_bar_panel(
        axes_list[2],
        zones,
        [record.annual_market_revenue_eur_per_mw / 1_000 for record in ordered],
        colors,
        "Market revenue [kEUR/MW-year]",
        "{:,.0f}",
    )

    axes_list[0].set_title(
        "2024 wind market-value decomposition by zone",
        fontsize=11,
        loc="left",
    )
    axes_list[2].set_xlabel("Market zone")
    fig.tight_layout(h_pad=1.15)
    path = figures_dir / "market_value_decomposition_by_zone_2024.png"
    fig.savefig(path, dpi=450, bbox_inches="tight")
    plt.close(fig)
    return path


def _draw_capture_price_panel(
    axis: plt.Axes,
    records: list[ZoneMarketValueSummary],
    zones: list[str],
    colors: list[str],
) -> None:
    values = [record.capture_price_eur_mwh for record in records]
    mean_prices = [record.mean_zonal_price_eur_mwh for record in records]
    bars = axis.bar(zones, values, color=colors, width=0.72)
    axis.scatter(
        zones,
        mean_prices,
        color="#111827",
        marker="D",
        s=22,
        label="Arithmetic zonal price",
        zorder=3,
    )
    _label_bars(axis, bars, "{:,.0f}", y_offset=-12, va="top")
    axis.set_ylabel("Capture price [EUR/MWh]")
    axis.legend(frameon=False, loc="upper right")
    _finish_axis(axis)
    axis.set_ylim(0, max(max(values), max(mean_prices)) * 1.22)


def _draw_bar_panel(
    axis: plt.Axes,
    zones: list[str],
    values: list[float],
    colors: list[str],
    ylabel: str,
    label_format: str,
) -> None:
    bars = axis.bar(zones, values, color=colors, width=0.72)
    _label_bars(axis, bars, label_format)
    axis.set_ylabel(ylabel)
    _finish_axis(axis)
    axis.set_ylim(0, max(values) * 1.2)


def _label_bars(
    axis: plt.Axes,
    bars: object,
    label_format: str,
    y_offset: int = 3,
    va: str = "bottom",
) -> None:
    for bar in bars:
        height = bar.get_height()
        axis.annotate(
            label_format.format(height),
            xy=(bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, y_offset),
            textcoords="offset points",
            ha="center",
            va=va,
            fontsize=8,
        )


def _configure_matplotlib() -> None:
    sns.set_theme(style="whitegrid", context="paper")
    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.serif": ["Times New Roman", "Times", "Aptos", "DejaVu Serif"],
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 9,
            "savefig.facecolor": "white",
            "axes.facecolor": "white",
            "axes.edgecolor": "#111827",
        }
    )


def _finish_axis(axis: plt.Axes) -> None:
    axis.grid(axis="y", color="#E5E7EB", linewidth=0.8)
    axis.xaxis.grid(False)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)


def _as_axes_list(axes: object) -> list[plt.Axes]:
    if isinstance(axes, plt.Axes):
        return [axes]
    return list(axes.ravel())  # type: ignore[attr-defined]
