"""
Operator Warnings Generator

Generates warnings for shop floor operators based on extracted PDF data.
Focus: Prevent errors with tap holes, toleranced holes, and critical dimensions.
"""

from dataclasses import dataclass, field
from typing import Any, Literal, Optional
import re


@dataclass
class WarningDetail:
    """Detail of a warning item."""
    type: Literal["tappedHole", "hole", "dimension"]
    thread_size: Optional[str] = None
    diameter: Optional[str] = None
    tolerance: Optional[str] = None
    tolerance_upper: Optional[str] = None
    tolerance_lower: Optional[str] = None
    value: Optional[str] = None
    count: int = 1


@dataclass
class OperatorWarning:
    """Warning for shop floor operators."""
    type: Literal["TAPPED_HOLES", "HOLE_TOLERANCE", "CRITICAL_DIMENSION"]
    priority: Literal["HIGH", "MEDIUM", "LOW"]
    message: str
    details: list[WarningDetail] = field(default_factory=list)
    count: Optional[int] = None


@dataclass
class ExtractedItem:
    """Extracted item data for warning generation."""
    part_number: Optional[str] = None
    description: Optional[str] = None
    material: Optional[str] = None
    surface_treatment: Optional[str] = None
    holes: list[dict[str, Any]] = field(default_factory=list)
    critical_lengths: list[dict[str, Any]] = field(default_factory=list)


def group_tapped_holes(holes: list[dict[str, Any]]) -> str:
    """
    Group tapped holes by type and format: "4x M6, 2x M8 (6H)"
    Includes tolerance if present.
    """
    grouped: dict[str, int] = {}

    for hole in holes:
        size = hole.get("threadSize") or "Unknown"
        tolerance = hole.get("tolerance", "")
        if tolerance and tolerance not in ["None", "null", ""]:
            key = f"{size} ({tolerance})"
        else:
            key = size
        count = hole.get("count", 1) or 1
        grouped[key] = grouped.get(key, 0) + count

    # Sort by thread size (M6, M8, M10, etc.)
    def sort_key(item: tuple[str, int]) -> int:
        # Match specifically M-thread sizes, not any digit
        match = re.search(r"M(\d+)", item[0])
        if match:
            return int(match.group(1))
        # Fallback: try to match any number
        match = re.search(r"\d+", item[0])
        return int(match.group()) if match else 0

    sorted_items = sorted(grouped.items(), key=sort_key)
    return ", ".join(
        f"{count}x {size_with_tol}" if count > 1 else size_with_tol
        for size_with_tol, count in sorted_items
    )


def group_hole_tolerances(holes: list[dict[str, Any]]) -> str:
    """
    Group holes with tolerances: "2x O20 H9, O40 +0.6/+0.1"
    """
    grouped: dict[str, int] = {}

    for hole in holes:
        dia = f"O{hole.get('diameter', '?')}"
        tol = ""

        if hole.get("tolerance"):
            tol = f" {hole['tolerance']}"
        elif hole.get("upperTolerance") or hole.get("lowerTolerance"):
            upper = hole.get("upperTolerance") or "+0"
            lower = hole.get("lowerTolerance") or "-0"
            tol = f" {upper}/{lower}"

        key = f"{dia}{tol}"
        count = hole.get("count", 1) or 1
        grouped[key] = grouped.get(key, 0) + count

    return ", ".join(
        f"{count}x {spec}" if count > 1 else spec
        for spec, count in grouped.items()
    )


def group_critical_dimensions(dimensions: list[dict[str, Any]]) -> str:
    """
    Group critical dimensions: "2x 40, 25.5"
    """
    grouped: dict[str, int] = {}

    for dim in dimensions:
        key = str(dim.get("dimension", "?"))
        grouped[key] = grouped.get(key, 0) + 1

    return ", ".join(
        f"{count}x {dim}" if count > 1 else dim
        for dim, count in grouped.items()
    )


def generate_operator_warnings(item: ExtractedItem) -> list[OperatorWarning]:
    """
    Generate operator warnings for a single part - COMBINED FORMAT.

    Args:
        item: Extracted item data

    Returns:
        List of operator warnings (usually 0 or 1 combined warning)
    """
    parts: list[str] = []
    all_details: list[WarningDetail] = []

    # 1. CHECK TAPPED HOLES
    tapped_holes = [h for h in item.holes if h.get("type") == "tapped"]
    if tapped_holes:
        grouped = group_tapped_holes(tapped_holes)
        parts.append(f"{grouped} tapgat")
        all_details.extend([
            WarningDetail(
                type="tappedHole",
                thread_size=h.get("threadSize"),
                count=h.get("count", 1) or 1,
            )
            for h in tapped_holes
        ])

    # 2. CHECK HOLES WITH TOLERANCES (no "None" tolerances)
    holes_with_tolerance = [
        h for h in item.holes
        if h.get("type") != "tapped"
        and h.get("tolerance") != "None"
        and (
            h.get("tolerance")
            or h.get("upperTolerance")
            or h.get("lowerTolerance")
        )
    ]

    if holes_with_tolerance:
        grouped = group_hole_tolerances(holes_with_tolerance)
        parts.append(grouped)
        all_details.extend([
            WarningDetail(
                type="hole",
                diameter=str(h.get("diameter", "")),
                tolerance=h.get("tolerance"),
                tolerance_upper=h.get("upperTolerance"),
                tolerance_lower=h.get("lowerTolerance"),
                count=h.get("count", 1) or 1,
            )
            for h in holes_with_tolerance
        ])

    # 3. CHECK CRITICAL DIMENSIONS WITH TOLERANCES
    critical_with_tolerance = [
        c for c in item.critical_lengths
        if c.get("toleranceType") != "parenthesized"
        and (
            c.get("upperTolerance")
            or c.get("lowerTolerance")
        )
    ]

    if critical_with_tolerance:
        grouped = group_critical_dimensions(critical_with_tolerance)
        parts.append(f"{grouped} tol")
        all_details.extend([
            WarningDetail(
                type="dimension",
                value=str(c.get("dimension", "")),
                tolerance_upper=c.get("upperTolerance"),
                tolerance_lower=c.get("lowerTolerance"),
            )
            for c in critical_with_tolerance
        ])

    # Combine everything into 1 warning
    if not parts:
        return []

    message = f"Nabewerking: {', '.join(parts)}"

    return [
        OperatorWarning(
            type="TAPPED_HOLES",
            priority="HIGH",
            message=message,
            details=all_details,
        )
    ]


def escape_xml(text: str) -> str:
    """Escape XML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def generate_warning_xml(warnings: list[OperatorWarning]) -> str:
    """
    Generate XML for warnings - SIMPLIFIED SINGLE LINE FORMAT.

    Args:
        warnings: List of operator warnings

    Returns:
        XML string for warnings section
    """
    if not warnings:
        return ""

    # Combined format: all warnings in 1 message node
    message = " | ".join(w.message for w in warnings)

    return f"    <PDF_Warnings>\n      <Message>{escape_xml(message)}</Message>\n    </PDF_Warnings>\n"
