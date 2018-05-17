import asyncio
import logging
import aiohttp.web
from NvidiaSettingsService import NvidiaSettingsService

class Api:
    """ Main API definition """

    def __init__(self, loop=None, config=None):
        """ Create the aiohttp application """

        self.logger = logging.getLogger(self.__class__.__name__)
        self.loop = loop if loop is not None else asyncio.get_event_loop()
        self.config = config

        self.app = aiohttp.web.Application(loop=loop)
        self.app.factory = self

        # NvidiaSettingsService
        self.app.on_startup.append(self.setup_nvidia_settings_service)

    async def setup_nvidia_settings_service(self, app):
        app['nvidia_settings'] = NvidiaSettingsService(
            nvidia_settings_path=self.config.nvidia_settings_path,
            xterm_path=self.config.xterm_path,
            display_env=self.config.display_env,
        )
        await app['nvidia_settings'].register_all_routes()
