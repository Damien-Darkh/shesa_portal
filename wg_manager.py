"""
wg_manager.py - OPNsense WireGuard API wrapper.

This is the same logic proven working in the standalone wg_onboard.py CLI
tool, refactored into importable functions for the Flask portal. Field
names are taken from OPNsense's own source (ClientController.php,
dialogConfigBuilder.xml) and confirmed working in production.
"""

import base64
import ipaddress
import os
import re

import requests
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

OPNSENSE_URL = os.environ["OPNSENSE_URL"].rstrip("/")
API_KEY = os.environ["OPNSENSE_API_KEY"]
API_SECRET = os.environ["OPNSENSE_API_SECRET"]
INSTANCE_UUID = os.environ["WG_INSTANCE_UUID"]
WG_ENDPOINT = os.environ["WG_ENDPOINT"]
WG_PORT = os.environ.get("WG_PORT", "51820")
WG_SUBNET = os.environ.get("WG_SUBNET", "10.10.10.0/24")
WG_DNS = os.environ.get("WG_DNS", "192.168.11.254")
ALLOWED_IPS_CLIENT = os.environ.get("ALLOWED_IPS_CLIENT", "192.168.11.0/24,10.10.10.0/24")
VERIFY_SSL = os.environ.get("VERIFY_SSL", "false").lower() == "true"

_session = requests.Session()
_session.auth = (API_KEY, API_SECRET)
_session.verify = VERIFY_SSL
if not VERIFY_SSL:
    requests.packages.urllib3.disable_warnings()


class WgApiError(Exception):
    pass


def _get(path):
    r = _session.get(f"{OPNSENSE_URL}/api/{path}")
    r.raise_for_status()
    return r.json()


def _post(path, payload=None):
    r = _session.post(f"{OPNSENSE_URL}/api/{path}", json=payload or {})
    r.raise_for_status()
    return r.json()


def sanitize_peer_name(name):
    """OPNsense's Client.xml only allows letters/numbers/./-/_"""
    sanitized = re.sub(r"[^0-9a-zA-Z._-]", "_", name)
    return sanitized[:64]


def gen_keypair():
    priv = X25519PrivateKey.generate()
    priv_b = priv.private_bytes_raw()
    pub_b = priv.public_key().public_bytes_raw()
    return base64.b64encode(priv_b).decode(), base64.b64encode(pub_b).decode()


def gen_psk():
    return base64.b64encode(os.urandom(32)).decode()


def list_clients():
    data = _post("wireguard/client/search_client", {"current": 1, "rowCount": -1})
    return data.get("rows", [])


def next_free_ip():
    net = ipaddress.ip_network(WG_SUBNET, strict=False)
    used = set()
    for row in list_clients():
        for part in row.get("tunneladdress", "").split(","):
            part = part.strip().split("/")[0]
            if part:
                used.add(part)
    for host in net.hosts():
        if str(host) == str(net.network_address + 1):
            continue
        if str(host) not in used:
            return str(host)
    raise WgApiError("No free IPs left in WireGuard subnet")


def create_peer(display_name):
    """Creates a new WireGuard peer on OPNsense. Returns a dict with the
    client .conf text and the OPNsense uuid - the private key is returned
    ONLY here and is never stored by this module; the caller must show it
    to the user once and discard it."""
    api_name = sanitize_peer_name(display_name)
    ip = next_free_ip()
    priv, pub = gen_keypair()
    psk = gen_psk()

    payload = {
        "configbuilder": {
            "server": INSTANCE_UUID,
            "servers": INSTANCE_UUID,
            "endpoint": f"{WG_ENDPOINT}:{WG_PORT}",
            "name": api_name,
            "pubkey": pub,
            "privkey": priv,
            "address": f"{ip}/32",
            "psk": psk,
            "tunneladdress": ALLOWED_IPS_CLIENT,
            "keepalive": "25",
            "peer_dns": WG_DNS,
        }
    }
    result = _post("wireguard/client/add_client_builder", payload)
    if result.get("result") != "saved":
        raise WgApiError(f"OPNsense rejected peer creation: {result}")

    _post("wireguard/service/reconfigure")

    created = None
    for row in list_clients():
        if row.get("name") == api_name:
            created = row
            break
    if created is None:
        raise WgApiError("Peer reported saved but not found afterward")

    server_pub = get_server_pubkey()
    conf = (
        f"[Interface]\n"
        f"PrivateKey = {priv}\n"
        f"Address = {ip}/32\n"
        f"DNS = {WG_DNS}\n\n"
        f"[Peer]\n"
        f"PublicKey = {server_pub}\n"
        f"PresharedKey = {psk}\n"
        f"Endpoint = {WG_ENDPOINT}:{WG_PORT}\n"
        f"AllowedIPs = {ALLOWED_IPS_CLIENT}\n"
        f"PersistentKeepalive = 25\n"
    )
    return {
        "uuid": created["uuid"],
        "api_name": api_name,
        "address": ip,
        "conf": conf,
        # Discrete fields, same values baked into `conf` above - kept
        # separate too so callers (e.g. the Windows launcher generator)
        # don't need to re-parse the .conf text to get them back out.
        "private_key": priv,
        "address_cidr": f"{ip}/32",
        "dns": WG_DNS,
        "peer_public_key": server_pub,
        "preshared_key": psk,
        "endpoint": f"{WG_ENDPOINT}:{WG_PORT}",
        "allowed_ips": ALLOWED_IPS_CLIENT,
        "keepalive": "25",
    }


def get_server_pubkey():
    server = _get(f"wireguard/server/get_server/{INSTANCE_UUID}")
    body = server.get("server", server)
    return body.get("pubkey", "")


def revoke_peer(uuid):
    _post(f"wireguard/client/toggle_client/{uuid}", {"enabled": "0"})
    _post("wireguard/service/reconfigure")


def enable_peer(uuid):
    _post(f"wireguard/client/toggle_client/{uuid}", {"enabled": "1"})
    _post("wireguard/service/reconfigure")


def delete_peer(uuid):
    _post(f"wireguard/client/del_client/{uuid}")
    _post("wireguard/service/reconfigure")


def get_peer_status():
    """Live handshake/traffic info, keyed by public key, from the service."""
    try:
        data = _get("wireguard/service/show")
        return data
    except Exception:
        return {}