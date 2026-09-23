"""Test fixtures re-exported from the kernel package.

The builders live in `upstream_kernel.compile.synthetic` rather than here because CI
needs them too: `data/artifacts` is git-ignored, so a checkout has no compiled network
and the API tests have nothing to snap against. Keeping one definition means the
network CI tests against is the same one these tests reason about.
"""
from upstream_kernel.compile.synthetic import line_network_gdfs, toy_gdfs

__all__ = ["line_network_gdfs", "toy_gdfs"]
