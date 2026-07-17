"""Provision the Alibaba Cloud ECS instance that the LedgerPilot backend runs on.

=== ALIBABA CLOUD DEPLOYMENT PROOF ===
This file calls the Alibaba Cloud ECS and VPC OpenAPIs directly (DescribeAvailableResource,
ImportKeyPair, CreateSecurityGroup, AuthorizeSecurityGroup, DescribeImages, RunInstances,
DescribeInstances) to stand up the Linux server the agent runs on. Together with
ledgerpilot/planner.py (Alibaba Cloud Model Studio / Qwen), these two files are the proof
that LedgerPilot's backend is deployed on, and calls, Alibaba Cloud.

Idempotent by design: every resource is looked up by name before it is created, so re-running
reuses the existing key pair, security group and instance instead of leaking duplicates.

Run:
    python scripts/deploy_ecs.py             provision (or reuse) and print the public IP
    python scripts/deploy_ecs.py --destroy   release the instance so it stops billing

Credentials are read from the environment and never committed:
    ALIBABA_CLOUD_ACCESS_KEY_ID
    ALIBABA_CLOUD_ACCESS_KEY_SECRET
    ALIBABA_CLOUD_REGION       optional, defaults to ap-southeast-1 (Singapore)
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import time

from alibabacloud_ecs20140526 import models as ecs_models
from alibabacloud_ecs20140526.client import Client as EcsClient
from alibabacloud_tea_openapi import models as open_api
from alibabacloud_vpc20160428 import models as vpc_models
from alibabacloud_vpc20160428.client import Client as VpcClient

PROJECT = "ledgerpilot"
KEY_NAME = "ledgerpilot-key"
SG_NAME = "ledgerpilot-sg"
INSTANCE_NAME = "ledgerpilot-agent"

# The agent is I/O bound on model calls, so the smallest burstable box is plenty.
# Ordered cheapest-first; the first one actually available in the region wins.
CANDIDATE_TYPES = [
    "ecs.t6-c1m2.large",   # 2 vCPU / 4 GiB burstable
    "ecs.t6-c1m1.large",   # 2 vCPU / 2 GiB burstable
    "ecs.e-c1m2.large",
    "ecs.e-c1m1.large",
    "ecs.u1-c1m2.large",
    "ecs.s6-c1m2.large",
    "ecs.g6.large",
]

KEY_PATH = pathlib.Path.home() / ".ssh" / "ledgerpilot_ecs"


def _fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def _clients(region: str) -> tuple[EcsClient, VpcClient]:
    key_id = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID")
    key_secret = os.environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
    if not key_id or not key_secret:
        _fail("set ALIBABA_CLOUD_ACCESS_KEY_ID and ALIBABA_CLOUD_ACCESS_KEY_SECRET")
    ecs_cfg = open_api.Config(access_key_id=key_id, access_key_secret=key_secret,
                              region_id=region, endpoint=f"ecs.{region}.aliyuncs.com")
    vpc_cfg = open_api.Config(access_key_id=key_id, access_key_secret=key_secret,
                              region_id=region, endpoint=f"vpc.{region}.aliyuncs.com")
    return EcsClient(ecs_cfg), VpcClient(vpc_cfg)


# --- ssh key -------------------------------------------------------------

def ensure_key_pair(ecs: EcsClient, region: str) -> None:
    """Generate a local SSH key if needed and import its public half into ECS."""
    if not KEY_PATH.exists():
        KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ssh-keygen", "-t", "rsa", "-b", "2048", "-N", "", "-C", PROJECT,
             "-f", str(KEY_PATH)],
            check=True, capture_output=True,
        )
        print(f"  generated ssh key   {KEY_PATH}")

    existing = ecs.describe_key_pairs(
        ecs_models.DescribeKeyPairsRequest(region_id=region, key_pair_name=KEY_NAME))
    if existing.body.total_count:
        print(f"  key pair            {KEY_NAME} (existing)")
        return

    public_key = KEY_PATH.with_suffix(".pub").read_text().strip()
    ecs.import_key_pair(ecs_models.ImportKeyPairRequest(
        region_id=region, key_pair_name=KEY_NAME, public_key_body=public_key))
    print(f"  key pair            {KEY_NAME} (imported)")


# --- network -------------------------------------------------------------

def ensure_network(vpc: VpcClient, region: str, zone: str) -> tuple[str, str]:
    """Return (vpc_id, vswitch_id) for the zone, creating the default VPC if absent."""
    vpcs = vpc.describe_vpcs(vpc_models.DescribeVpcsRequest(region_id=region, page_size=50))
    entries = vpcs.body.vpcs.vpc if vpcs.body.vpcs else []
    if not entries:
        print("  no VPC found; creating the default VPC")
        vpc.create_default_vpc(vpc_models.CreateDefaultVpcRequest(region_id=region))
        time.sleep(5)
        vpcs = vpc.describe_vpcs(vpc_models.DescribeVpcsRequest(region_id=region, page_size=50))
        entries = vpcs.body.vpcs.vpc

    # Prefer the default VPC when one exists.
    chosen = next((v for v in entries if v.is_default), entries[0])
    vpc_id = chosen.vpc_id

    switches = vpc.describe_vswitches(vpc_models.DescribeVSwitchesRequest(
        region_id=region, vpc_id=vpc_id, zone_id=zone, page_size=50))
    found = switches.body.v_switches.v_switch if switches.body.v_switches else []
    if not found:
        print(f"  no vSwitch in {zone}; creating the default vSwitch")
        vpc.create_default_vswitch(vpc_models.CreateDefaultVSwitchRequest(
            region_id=region, zone_id=zone))
        time.sleep(5)
        switches = vpc.describe_vswitches(vpc_models.DescribeVSwitchesRequest(
            region_id=region, vpc_id=vpc_id, zone_id=zone, page_size=50))
        found = switches.body.v_switches.v_switch
    if not found:
        _fail(f"could not obtain a vSwitch in zone {zone}")

    print(f"  network             vpc={vpc_id} vswitch={found[0].v_switch_id}")
    return vpc_id, found[0].v_switch_id


def ensure_security_group(ecs: EcsClient, region: str, vpc_id: str) -> str:
    """Security group allowing SSH (22) and the LedgerPilot web UI (80, 8080)."""
    groups = ecs.describe_security_groups(ecs_models.DescribeSecurityGroupsRequest(
        region_id=region, vpc_id=vpc_id, security_group_name=SG_NAME))
    found = groups.body.security_groups.security_group if groups.body.security_groups else []
    if found:
        sg_id = found[0].security_group_id
        print(f"  security group      {sg_id} (existing)")
        return sg_id

    created = ecs.create_security_group(ecs_models.CreateSecurityGroupRequest(
        region_id=region, vpc_id=vpc_id, security_group_name=SG_NAME,
        description="LedgerPilot agent: ssh + web UI"))
    sg_id = created.body.security_group_id
    #   22   ssh
    #   80   the gate's web UI, and the ACME http-01 challenge Caddy answers to
    #        obtain the certificate
    #  443   the same UI over TLS once a hostname points here
    # 8080   the MCP server Model Studio connects out to
    for port in ("22/22", "80/80", "443/443", "8080/8080"):
        ecs.authorize_security_group(ecs_models.AuthorizeSecurityGroupRequest(
            region_id=region, security_group_id=sg_id, ip_protocol="tcp",
            port_range=port, source_cidr_ip="0.0.0.0/0",
            description=f"LedgerPilot {port}"))
    print(f"  security group      {sg_id} (created, tcp 22/80/443/8080)")
    return sg_id


# --- compute -------------------------------------------------------------

def pick_instance_type(ecs: EcsClient, region: str) -> tuple[str, str]:
    """Choose the cheapest candidate instance type that is actually sellable, plus its zone."""
    resp = ecs.describe_available_resource(ecs_models.DescribeAvailableResourceRequest(
        region_id=region, destination_resource="InstanceType",
        instance_charge_type="PostPaid"))
    zones = resp.body.available_zones.available_zone if resp.body.available_zones else []

    offered: dict[str, list[str]] = {}  # instance_type -> [zone, ...]
    for z in zones:
        if z.status != "Available":
            continue
        for res in (z.available_resources.available_resource or []):
            for sup in (res.supported_resources.supported_resource or []):
                if sup.status == "Available":
                    offered.setdefault(sup.value, []).append(z.zone_id)

    for candidate in CANDIDATE_TYPES:
        if candidate in offered:
            return candidate, offered[candidate][0]
    _fail(f"none of {CANDIDATE_TYPES} are available in {region}; "
          f"try another region via ALIBABA_CLOUD_REGION")
    raise AssertionError("unreachable")


def pick_image(ecs: EcsClient, region: str, instance_type: str) -> str:
    """Latest official Ubuntu LTS image supported by the chosen instance type."""
    resp = ecs.describe_images(ecs_models.DescribeImagesRequest(
        region_id=region, architecture="x86_64", image_owner_alias="system",
        instance_type=instance_type, page_size=100, status="Available"))
    images = resp.body.images.image if resp.body.images else []
    if not images:
        _fail(f"no system images available for {instance_type} in {region}")

    def rank(img) -> tuple[int, str]:
        name = (img.image_id or "").lower()
        for i, family in enumerate(("ubuntu_24_04", "ubuntu_22_04", "ubuntu_20_04")):
            if family in name:
                return (i, name)
        return (99, name)

    best = sorted(images, key=rank)[0]
    print(f"  image               {best.image_id}")
    return best.image_id


def find_instance(ecs: EcsClient, region: str) -> object | None:
    resp = ecs.describe_instances(ecs_models.DescribeInstancesRequest(
        region_id=region, instance_name=INSTANCE_NAME))
    found = resp.body.instances.instance if resp.body.instances else []
    return found[0] if found else None


def ensure_instance(ecs: EcsClient, vpc: VpcClient, region: str) -> str:
    """Create the instance if it does not exist, then return its public IP."""
    existing = find_instance(ecs, region)
    if existing:
        print(f"  instance            {existing.instance_id} (existing, {existing.status})")
        if existing.status == "Stopped":
            ecs.start_instance(ecs_models.StartInstanceRequest(
                instance_id=existing.instance_id))
        return wait_for_ip(ecs, region, existing.instance_id)

    instance_type, zone = pick_instance_type(ecs, region)
    print(f"  instance type       {instance_type} in {zone}")
    vpc_id, vswitch_id = ensure_network(vpc, region, zone)
    sg_id = ensure_security_group(ecs, region, vpc_id)
    image_id = pick_image(ecs, region, instance_type)
    ensure_key_pair(ecs, region)

    req = ecs_models.RunInstancesRequest(
        region_id=region,
        zone_id=zone,
        image_id=image_id,
        instance_type=instance_type,
        security_group_id=sg_id,
        v_switch_id=vswitch_id,
        instance_name=INSTANCE_NAME,
        host_name=PROJECT,
        key_pair_name=KEY_NAME,
        instance_charge_type="PostPaid",
        # A public IP is what makes the running backend demonstrable.
        internet_charge_type="PayByTraffic",
        internet_max_bandwidth_out=5,
        amount=1,
        unique_suffix=False,
        system_disk=ecs_models.RunInstancesRequestSystemDisk(size="40", category="cloud_essd"),
        tag=[ecs_models.RunInstancesRequestTag(key="project", value=PROJECT)],
    )
    try:
        resp = ecs.run_instances(req)
    except Exception as exc:  # noqa: BLE001 - ESSD is not offered everywhere
        if "cloud_essd" not in str(exc):
            raise
        print("  cloud_essd unavailable; falling back to cloud_efficiency")
        req.system_disk = ecs_models.RunInstancesRequestSystemDisk(
            size="40", category="cloud_efficiency")
        resp = ecs.run_instances(req)

    instance_id = resp.body.instance_id_sets.instance_id_set[0]
    print(f"  instance            {instance_id} (created)")
    return wait_for_ip(ecs, region, instance_id)


def wait_for_ip(ecs: EcsClient, region: str, instance_id: str, timeout: int = 300) -> str:
    print("  waiting for the instance to reach Running with a public IP...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = ecs.describe_instances(ecs_models.DescribeInstancesRequest(
            region_id=region, instance_ids=f'["{instance_id}"]'))
        found = resp.body.instances.instance if resp.body.instances else []
        if found:
            inst = found[0]
            ips = inst.public_ip_address.ip_address if inst.public_ip_address else []
            if inst.status == "Running" and ips:
                return ips[0]
        time.sleep(6)
    _fail(f"instance {instance_id} did not come up within {timeout}s")
    raise AssertionError("unreachable")


def destroy(ecs: EcsClient, region: str) -> None:
    inst = find_instance(ecs, region)
    if not inst:
        print("no LedgerPilot instance to release")
        return
    ecs.delete_instance(ecs_models.DeleteInstanceRequest(
        instance_id=inst.instance_id, force=True))
    print(f"released {inst.instance_id}; billing stops")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destroy", action="store_true",
                        help="release the instance instead of creating it")
    args = parser.parse_args()

    region = os.environ.get("ALIBABA_CLOUD_REGION", "ap-southeast-1")
    ecs, vpc = _clients(region)

    if args.destroy:
        destroy(ecs, region)
        return

    print(f"Provisioning the LedgerPilot backend on Alibaba Cloud ECS ({region})")
    ip = ensure_instance(ecs, vpc, region)
    print()
    print(f"  PUBLIC IP           {ip}")
    print(f"  ssh                 ssh -i {KEY_PATH} root@{ip}")
    print(f"  web UI (after bootstrap)  http://{ip}/")


if __name__ == "__main__":
    main()
