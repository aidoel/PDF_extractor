# Configuration

Configuration is loaded from YAML and deep-merged at runtime.

## Hierarchy

```text
config/base.yaml
  -> customers/<customer>/config.yaml
  -> customers/<customer>/surface-treatments.yaml
```

Lists are replaced, not appended.

## Main configuration areas

- `signals.tolerated_lengths`: regex signals for tolerated lengths
- `signals.holes`: hole patterns and capture metadata
- `surfaceTreatments`: valid surface treatment options + keywords
- `material_patterns`: guidance for material extraction
- `prompt_additions`: customer-specific prompt instructions

## Add a new customer

1. Create `config/customers/<new_customer>/config.yaml`
2. Create `config/customers/<new_customer>/surface-treatments.yaml`
3. Add signal patterns and prompt additions matching drawing conventions
4. Run a small validation batch and inspect output XML + logs

!!! tip "Safe rollout"
    Keep `base` rules minimal and move customer-specific behavior into customer folders to avoid cross-customer regressions.
