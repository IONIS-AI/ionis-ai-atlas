"""Guards on compose.yaml, the file users run. Needs no database or container engine.

The healthchecks must live in compose.yaml, not only in the images. The published images are OCI
format (buildx needs it to attach the SBOM and provenance), and podman ignores HEALTHCHECK in OCI
images: release df983305c2b2 came up under podman with no database healthcheck, and Atlas never
started. Docker honours both, so the duplication looks redundant from a Docker machine. It is not;
these tests stop it being tidied away.
"""
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


class ComposeLoader(yaml.SafeLoader):
    """Compose's own tags (`!reset`, `!override`) are not YAML's; read them as their plain value."""


for _tag in ("!reset", "!override"):
    ComposeLoader.add_constructor(_tag, lambda loader, node: (
        loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode)
        else loader.construct_mapping(node) if isinstance(node, yaml.MappingNode)
        else loader.construct_scalar(node)))


def services(name):
    return yaml.load((ROOT / name).read_text(), Loader=ComposeLoader)["services"]


@pytest.mark.parametrize("service", ["atlas", "db"])
def test_every_service_has_a_healthcheck_in_compose(service):
    hc = services("compose.yaml")[service].get("healthcheck") or {}
    assert hc.get("test"), f"compose.yaml: {service} has no healthcheck (podman ignores the image's)"
    assert not hc.get("disable"), f"compose.yaml: {service} healthcheck is disabled"


def test_db_healthcheck_allows_a_first_start_load():
    """A first start on an empty volume loads ADIF before PostgreSQL answers on TCP."""
    assert services("compose.yaml")["db"]["healthcheck"].get("start_period"), "db needs a start_period"


def test_atlas_waits_for_a_healthy_database():
    assert services("compose.yaml")["atlas"]["depends_on"]["db"]["condition"] == "service_healthy"


def test_dev_overlay_does_not_switch_healthchecks_off():
    for name, svc in services("compose.dev.yaml").items():
        hc = svc.get("healthcheck")
        assert hc is None or (hc.get("test") and not hc.get("disable")), \
            f"compose.dev.yaml: {name} overrides its healthcheck away"


@pytest.mark.parametrize("service", ["atlas", "db"])
def test_compose_names_a_release_stream(service):
    """#58, BUILD-SPEC "Release streams": the published compose file names a stream tag. Not
    `:latest` (it crosses breaking changes) and not an exact version (a stream gets fixes by pull).
    During 0.x a stream is major.minor; from 1.0 it is the major number."""
    import re
    image = services("compose.yaml")[service]["image"]
    default = re.fullmatch(r"\$\{ATLAS_(APP|DB)_IMAGE:-(.+)\}", image)
    assert default, f"{service}: the image must stay overridable by ATLAS_*_IMAGE (pinning, dev): {image}"
    tag = default.group(2).rsplit(":", 1)[1]
    assert re.fullmatch(r"0\.\d+|[1-9]\d*", tag), f"{service}: {tag!r} is not a release stream"
