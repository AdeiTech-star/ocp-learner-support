import random
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined

TEMPLATE_DIR = Path(__file__).parent / "templates"

env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    undefined=StrictUndefined,
    autoescape=False,
)


def list_variants(flag_type: str) -> list[str]:
    """Return all variant letters available for a flag type."""
    prefix = f"{flag_type}_"
    return sorted(
        p.stem.removeprefix(prefix)
        for p in TEMPLATE_DIR.glob(f"{prefix}*.j2")
    )


def render_template(flag_type: str, context: dict, variant: str | None = None) -> tuple[str, str]:
    """
    Render a flag template with the given context.
    Returns (rendered_text, variant_used) so the audit log can record which variant.
    """
    variants = list_variants(flag_type)
    if not variants:
        raise ValueError(f"No templates found for flag_type: {flag_type}")

    chosen = variant or random.choice(variants)
    if chosen not in variants:
        raise ValueError(f"Unknown variant '{chosen}' for {flag_type}. Available: {variants}")

    template = env.get_template(f"{flag_type}_{chosen}.j2")
    return template.render(**context), chosen