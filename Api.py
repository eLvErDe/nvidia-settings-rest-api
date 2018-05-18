import asyncio
import logging
import aiohttp.web
import aiohttp_swagger
from NvidiaSettingsService import NvidiaSettingsService

class Api:
    """ Main API definition """

    def __init__(self, config=None, name=None, version=None):
        """ Create the aiohttp application """

        self.logger = logging.getLogger(self.__class__.__name__)
        self.config = config
        self.name = name
        self.version = version

        self.app = aiohttp.web.Application()
        self.app.factory = self

        loop = asyncio.get_event_loop()

        # Should be done in on_startup callback but:
        # RuntimeError: Cannot register a resource into frozen router.

        # NvidiaSettingsService
        asyncio.wait(loop.run_until_complete(self.setup_nvidia_settings_service()))

        # Setup Swagger and routes
        asyncio.wait(loop.run_until_complete(self.setup_routes_and_swagger()))

        # Print configured routes
        self.print_routes()

    @staticmethod
    def route_join(*args):
        """ Create relative route url """

        route_url = '/'.join([x.strip('/') for x in args])
        if not route_url.startswith('/'):
            route_url = '/' + route_url
        return route_url

    def print_routes(self):
        """ Log all configured routes """

        for route in self.app.router.routes():
            route_info = route.get_info()
            if 'formatter' in route_info:
                url = route_info['formatter']
            elif 'path' in route_info:
                url = route_info['path']
            elif 'prefix' in route_info:
                url = route_info['prefix']
            else:
                url = 'Unknown type of route %s' % route_info

            self.logger.info('Route has been setup %s at %s', route.method, url)

    def generate_swagger_dict(self, items):
        """
        Generate a dict that will be dumped to swagger.json
        """

        d_swagger = {
            'swagger': '2.0',
            'info': {
                'title': self.name,
                'version': self.version,
                'contact': {
                    'name': 'Adam Cecile',
                    'email': 'acecile@le-vert.net',
                    'url': 'https://github.com/eLvErDe/nvidia-settings-rest-api',
                },
                'license': {
                    'name': 'GPL-3.0',
                    'url': 'https://www.gnu.org/licenses/gpl-3.0.txt',
                }
            }
        }

        return d_swagger

    async def setup_routes_and_swagger(self):
        """
        Setup NvidaSettings service to get available items
        and then create corresponding routes and swagger documentation
        """

        items = await self.setup_nvidia_settings_service()
        d_swagger = self.generate_swagger_dict(items)

        swagger_url = self.route_join(self.config.context_path, '/swagger')

        aiohttp_swagger.setup_swagger(
            self.app,
            swagger_info=d_swagger,
            api_base_url=self.config.context_path,
            swagger_url=swagger_url,
        )
        self.app.router.add_route('GET', '/', lambda x: aiohttp.web.HTTPFound(swagger_url))

    async def setup_nvidia_settings_service(self):
        """ Create NvidiaSettingsService """

        self.app['nvidia_settings'] = NvidiaSettingsService(
            nvidia_settings_path=self.config.nvidia_settings_path,
            xterm_path=self.config.xterm_path,
            display_env=self.config.display_env,
        )
