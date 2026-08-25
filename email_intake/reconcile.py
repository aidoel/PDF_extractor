"""Combine PDF and STEP evidence without silently resolving contradictions."""

from __future__ import annotations

import re

from .models import CanonicalPart, ExtractedPart, FieldConflict


def _part_key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _normalized_text(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.upper().split())


def _different(field: str, left: object, right: object) -> bool:
    if left is None or right is None:
        return False
    if field == "thickness_mm":
        return abs(float(left) - float(right)) > 0.01
    if isinstance(left, str) and isinstance(right, str):
        return _normalized_text(left) != _normalized_text(right)
    return left != right


def reconcile_parts(
    pdf_parts: list[ExtractedPart], step_parts: list[ExtractedPart]
) -> tuple[list[CanonicalPart], list[FieldConflict]]:
    """Join parts by normalized number and return every blocking conflict."""

    pdf_by_key = {_part_key(part.part_number): part for part in pdf_parts}
    step_by_key = {_part_key(part.part_number): part for part in step_parts}
    parts: list[CanonicalPart] = []
    conflicts: list[FieldConflict] = []

    for key in sorted(set(pdf_by_key) | set(step_by_key)):
        pdf = pdf_by_key.get(key)
        step = step_by_key.get(key)
        reference = pdf or step
        assert reference is not None

        if pdf is None or step is None:
            missing = "PDF" if pdf is None else "STEP"
            conflicts.append(
                FieldConflict(
                    part_number=reference.part_number,
                    field="attachment_pair",
                    pdf_value=pdf.part_number if pdf else None,
                    step_value=step.part_number if step else None,
                    message=f"Bijbehorende {missing}-bron ontbreekt",
                )
            )

        if pdf and step:
            for field_name in ("material", "thickness_mm"):
                pdf_value = getattr(pdf, field_name)
                step_value = getattr(step, field_name)
                if _different(field_name, pdf_value, step_value):
                    conflicts.append(
                        FieldConflict(
                            part_number=pdf.part_number,
                            field=field_name,
                            pdf_value=pdf_value,
                            step_value=step_value,
                            message=(
                                f"{field_name} verschilt tussen PDF en STEP"
                            ),
                        )
                    )

        sources = [
            candidate.evidence
            for candidate in (pdf, step)
            if candidate is not None and candidate.evidence is not None
        ]
        parts.append(
            CanonicalPart(
                part_number=reference.part_number,
                quantity=(pdf.quantity if pdf and pdf.quantity is not None else 1),
                material=(
                    pdf.material
                    if pdf and pdf.material
                    else (step.material if step else None)
                ),
                thickness_mm=(
                    step.thickness_mm
                    if step and step.thickness_mm is not None
                    else (pdf.thickness_mm if pdf else None)
                ),
                surface_treatment=(pdf.surface_treatment if pdf else None),
                sources=sources,
            )
        )

    return parts, conflicts
