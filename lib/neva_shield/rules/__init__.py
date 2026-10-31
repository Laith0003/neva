"""The Shield rule families, in report order."""
from . import bypass, hooks, injection, mcp, permissions, provenance, secrets

FAMILIES = (
    ("permissions", permissions),
    ("bypass", bypass),
    ("hooks", hooks),
    ("mcp", mcp),
    ("secrets", secrets),
    ("injection", injection),
    ("provenance", provenance),
)

__all__ = ["FAMILIES"]
