from __future__ import annotations

import json
import logging
import os
from json import JSONDecodeError
from pathlib import Path
from typing import TypedDict

from ipv8.configuration import default as ipv8_default_config

logger = logging.getLogger(__name__)


class ApiConfig(TypedDict):
    """
    Settings for the API key component.
    """

    key: str
    http_enabled: bool
    http_port: int
    http_host: str
    https_enabled: bool
    https_host: str
    https_port: int


class ContentDiscoveryCommunityConfig(TypedDict):
    """
    Settings for the content discovery component.
    """

    enabled: bool


class DHTDiscoveryCommunityConfig(TypedDict):
    """
    Settings for the DHT discovery component.
    """

    enabled: bool


class KnowledgeCommunityConfig(TypedDict):
    """
    Settings for the knowledge component.
    """

    enabled: bool


class DatabaseConfig(TypedDict):
    """
    Settings for the database component.
    """

    enabled: bool


class DownloadDefaultsConfig(TypedDict):
    """
    Settings for default downloads, used by libtorrent.
    """

    anonymity_enabled: bool
    number_hops: int
    safeseeding_enabled: bool
    saveas: str
    seeding_mode: str
    seeding_ratio: float
    seeding_time: float
    channel_download: bool
    add_download_to_channel: bool


class LibtorrentConfig(TypedDict):
    """
    Settings for the libtorrent component.
    """

    socks_listen_ports: list[int]
    port: int
    proxy_type: int
    proxy_server: str
    proxy_auth: str
    max_connections_download: int
    max_download_rate: int
    max_upload_rate: int
    utp: bool
    dht: bool
    dht_readiness_timeout: int
    upnp: bool
    natpmp: bool
    lsd: bool

    download_defaults: DownloadDefaultsConfig


class RendezvousConfig(TypedDict):
    """
    Settings for the rendezvous component.
    """

    enabled: bool


class TorrentCheckerConfig(TypedDict):
    """
    Settings for the torrent checker component.
    """

    enabled: bool


class TunnelCommunityConfig(TypedDict):
    """
    Settings for the tunnel community component.
    """

    enabled: bool
    min_circuits: int
    max_circuits: int


class UserActivityConfig(TypedDict):
    """
    Settings for the user activity component.
    """

    enabled: bool
    max_query_history: int
    health_check_interval: float


class TriblerConfig(TypedDict):
    """
    The main Tribler settings and all of its components' sub-settings.
    """

    api: ApiConfig

    ipv8: dict
    statistics: bool

    content_discovery_community: ContentDiscoveryCommunityConfig
    database: DatabaseConfig
    knowledge_community: KnowledgeCommunityConfig
    libtorrent: LibtorrentConfig
    rendezvous: RendezvousConfig
    torrent_checker: TorrentCheckerConfig
    tunnel_community: TunnelCommunityConfig
    user_activity: UserActivityConfig

    state_dir: str
    memory_db: bool


DEFAULT_CONFIG = {
    "api": {
        "http_enabled": True,
        "http_port": 0,
        "http_host": "127.0.0.1",
        "https_enabled": False,
        "https_host": "127.0.0.1",
        "https_port": 0,
        "https_certfile": "https_certfile"
    },

    "ipv8": ipv8_default_config,
    "statistics": False,

    "content_discovery_community": ContentDiscoveryCommunityConfig(enabled=True),
    "database": DatabaseConfig(enabled=True),
    "dht_discovery": DHTDiscoveryCommunityConfig(enabled=True),
    "knowledge_community": KnowledgeCommunityConfig(enabled=True),
    "libtorrent": LibtorrentConfig(
        socks_listen_ports=[0, 0, 0, 0, 0],
        port=0,
        proxy_type=0,
        proxy_server='',
        proxy_auth='',
        max_connections_download=-1,
        max_download_rate=0,
        max_upload_rate=0,
        utp=True,
        dht=True,
        dht_readiness_timeout=30,
        upnp=True,
        natpmp=True,
        lsd=True,
        download_defaults=DownloadDefaultsConfig(
            anonymity_enabled=True,
            number_hops=1,
            safeseeding_enabled=True,
            saveas=str(Path("~/Downloads").expanduser()),
            seeding_mode='forever',
            seeding_ratio=2.0,
            seeding_time=60,
            channel_download=False,
            add_download_to_channel=False)
        ),
    "rendezvous": RendezvousConfig(enabled=True),
    "torrent_checker": TorrentCheckerConfig(enabled=True),
    "tunnel_community": TunnelCommunityConfig(enabled=True, min_circuits=1, max_circuits=8),
    "user_activity": UserActivityConfig(enabled=True, max_query_history=500, health_check_interval=5.0),

    "state_dir": str((Path(os.environ.get("APPDATA", "~")) / ".TriblerExperimental").expanduser().absolute()),
    "memory_db": False
}

# Changes to IPv8 default config
DEFAULT_CONFIG["ipv8"]["keys"].append({
    'alias': "secondary",
    'generation': "curve25519",
    'file': "secondary_key.pem"
})
DEFAULT_CONFIG["ipv8"]["overlays"] = [overlay for overlay in DEFAULT_CONFIG["ipv8"]["overlays"]
                                      if overlay["class"] == "DiscoveryCommunity"]
DEFAULT_CONFIG["ipv8"]["working_directory"] = DEFAULT_CONFIG["state_dir"]
for key_entry in DEFAULT_CONFIG["ipv8"]["keys"]:
    if "file" in key_entry:
        key_entry["file"] = str(Path(DEFAULT_CONFIG["state_dir"]) / key_entry["file"])


class TriblerConfigManager:
    """
    A class that interacts with a JSON configuration file.
    """

    def __init__(self, config_file: Path = Path("configuration.json")) -> None:
        """
        Load a config from a file.
        """
        super().__init__()
        self.config_file = config_file

        logger.info("Load: %s.", self.config_file)
        self.configuration = {}
        if config_file.exists():
            try:
                with open(self.config_file) as f:
                    self.configuration = json.load(f)
            except JSONDecodeError:
                logger.exception("Failed to load stored configuration. Falling back to defaults!")
        if not self.configuration:
            self.configuration = DEFAULT_CONFIG

    def write(self) -> None:
        """
        Write the configuration to disk.
        """
        with open(self.config_file, "w") as f:
            json.dump(self.configuration, f, indent=4)

    def get(self, option: os.PathLike | str) -> dict | list | str | float | bool | None:
        """
        Get a config option based on the path-like descriptor.
        """
        out = self.configuration
        for part in Path(option).parts:
            if part in out:
                out = out.get(part)
            else:
                # Fetch from defaults instead.
                out = DEFAULT_CONFIG
                for df_part in Path(option).parts:
                    out = out.get(df_part)
                break
        return out

    def set(self, option: os.PathLike | str, value: dict | list | str | float | bool | None) -> None:
        """
        Set a config option value based on the path-like descriptor.
        """
        current = self.configuration
        for part in Path(option).parts[:-1]:
            current = current[part]
        current[Path(option).parts[-1]] = value
