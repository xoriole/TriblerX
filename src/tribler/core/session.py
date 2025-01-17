from __future__ import annotations

import logging
from asyncio import Event
from contextlib import contextmanager, nullcontext
from typing import TYPE_CHECKING, Generator

from ipv8.loader import IPv8CommunityLoader
from ipv8_service import IPv8

from tribler.core.components import (
    ContentDiscoveryComponent,
    DatabaseComponent,
    DHTDiscoveryComponent,
    KnowledgeComponent,
    RendezvousComponent,
    TorrentCheckerComponent,
    TunnelComponent,
)
from tribler.core.libtorrent.download_manager.download_manager import DownloadManager
from tribler.core.libtorrent.restapi.create_torrent_endpoint import CreateTorrentEndpoint
from tribler.core.libtorrent.restapi.downloads_endpoint import DownloadsEndpoint
from tribler.core.libtorrent.restapi.libtorrent_endpoint import LibTorrentEndpoint
from tribler.core.libtorrent.restapi.torrentinfo_endpoint import TorrentInfoEndpoint
from tribler.core.notifier import Notification, Notifier
from tribler.core.restapi.events_endpoint import EventsEndpoint
from tribler.core.restapi.ipv8_endpoint import IPv8RootEndpoint
from tribler.core.restapi.rest_manager import RESTManager
from tribler.core.restapi.settings_endpoint import SettingsEndpoint
from tribler.core.restapi.shutdown_endpoint import ShutdownEndpoint
from tribler.core.restapi.statistics_endpoint import StatisticsEndpoint
from tribler.core.socks5.server import Socks5Server

if TYPE_CHECKING:
    from tribler.tribler_config import TriblerConfigManager

logger = logging.getLogger(__name__)


@contextmanager
def rust_enhancements(session: Session) -> Generator[None, None, None]:
    """
    Attempt to import the IPv8 Rust anonymization backend.
    """
    try:
        from ipv8.messaging.interfaces.dispatcher.endpoint import INTERFACES
        from ipv8_rust_tunnels.endpoint import RustEndpoint
        INTERFACES["UDPIPv4"] = RustEndpoint
        for ifc in session.config.configuration["ipv8"]["interfaces"]:
            if ifc["interface"] == "UDPIPv4":
                ifc["worker_threads"] = session.config.get("tunnel_community/max_circuits")
        yield
        if any(nif["interface"] == "UDPIPv4" for nif in session.config.get("ipv8/interfaces")):
            for server in session.socks_servers:
                ipv4_endpoint = session.ipv8.endpoint.interfaces["UDPIPv4"]
                server.rust_endpoint = ipv4_endpoint if isinstance(ipv4_endpoint, RustEndpoint) else None
    except ImportError:
        logger.info("Rust endpoint not found (pip install ipv8-rust-tunnels).")
        for ifc in session.config.configuration["ipv8"]["interfaces"]:
            if ifc["interface"] == "UDPIPv4":
                ifc.pop("worker_threads")
        yield


class Session:
    """
    A session manager that manages all components.
    """

    def __init__(self, config: TriblerConfigManager) -> None:
        """
        Create a new session without initializing any components yet.
        """
        self.config = config

        self.shutdown_event = Event()
        self.notifier = Notifier()

        # Libtorrent
        self.download_manager = DownloadManager(self.config, self.notifier)
        self.socks_servers = [Socks5Server(port) for port in self.config.get("libtorrent/socks_listen_ports")]

        # IPv8
        with nullcontext() if self.config.get("statistics") else rust_enhancements(self):
            self.ipv8 = IPv8(self.config.get("ipv8"), enable_statistics=self.config.get("statistics"))
        self.loader = IPv8CommunityLoader()

        # REST
        self.rest_manager = RESTManager(self.config)

        # Optional globals, set by components:
        self.db = None
        self.mds = None
        self.torrent_checker = None

    def register_launchers(self) -> None:
        """
        Register all IPv8 launchers that allow communities to be loaded.
        """
        self.loader.set_launcher(ContentDiscoveryComponent())
        self.loader.set_launcher(DatabaseComponent())
        self.loader.set_launcher(DHTDiscoveryComponent())
        self.loader.set_launcher(KnowledgeComponent())
        self.loader.set_launcher(RendezvousComponent())
        self.loader.set_launcher(TorrentCheckerComponent())
        self.loader.set_launcher(TunnelComponent())

    def register_rest_endpoints(self) -> None:
        """
        Register all REST endpoints without initializing them.
        """
        self.rest_manager.add_endpoint(CreateTorrentEndpoint(self.download_manager))
        self.rest_manager.add_endpoint(DownloadsEndpoint(self.download_manager))
        self.rest_manager.add_endpoint(EventsEndpoint(self.notifier))
        self.rest_manager.add_endpoint(IPv8RootEndpoint()).initialize(self.ipv8)
        self.rest_manager.add_endpoint(LibTorrentEndpoint(self.download_manager))
        self.rest_manager.add_endpoint(SettingsEndpoint(self.config))
        self.rest_manager.add_endpoint(ShutdownEndpoint(self.shutdown_event.set))
        self.rest_manager.add_endpoint(StatisticsEndpoint(self.ipv8))
        self.rest_manager.add_endpoint(TorrentInfoEndpoint(self.download_manager))

    async def start(self) -> None:
        """
        Initialize and launch all components and REST endpoints.
        """
        # REST (1/2)
        self.register_rest_endpoints()

        # Libtorrent
        for server in self.socks_servers:
            await server.start()
        self.download_manager.socks_listen_ports = [s.port for s in self.socks_servers]
        self.download_manager.initialize()
        self.download_manager.start()

        # IPv8
        self.register_launchers()
        self.loader.load(self.ipv8, self)
        await self.ipv8.start()

        # REST (2/2)
        if self.config.get("statistics"):
            self.rest_manager.get_endpoint("/ipv8").endpoints["/overlays"].enable_overlay_statistics(True, None, True)
        await self.rest_manager.start()

    async def shutdown(self) -> None:
        """
        Shut down all connections and components.
        """
        # Stop network event generators
        if self.torrent_checker:
            self.notifier.notify(Notification.tribler_shutdown_state, state="Shutting down torrent checker.")
            await self.torrent_checker.shutdown()
        if self.ipv8:
            self.notifier.notify(Notification.tribler_shutdown_state, state="Shutting down IPv8 peer-to-peer overlays.")
            await self.ipv8.stop()

        # Stop libtorrent managers
        self.notifier.notify(Notification.tribler_shutdown_state, state="Shutting down download manager.")
        await self.download_manager.shutdown()
        self.notifier.notify(Notification.tribler_shutdown_state, state="Shutting down local SOCKS5 interface.")
        for server in self.socks_servers:
            await server.stop()

        # Stop database activities
        if self.db:
            self.notifier.notify(Notification.tribler_shutdown_state, state="Shutting down general-purpose database.")
            self.db.shutdown()
        if self.mds:
            self.notifier.notify(Notification.tribler_shutdown_state, state="Shutting down metadata database.")
            self.mds.shutdown()

        # Stop communication with the GUI
        self.notifier.notify(Notification.tribler_shutdown_state, state="Shutting down GUI connection. Going dark.")
        await self.rest_manager.stop()
