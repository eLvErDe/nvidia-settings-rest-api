#!/usr/bin/python3

import sys
import os
import logging
import argparse

import aiohttp.web
import setproctitle

from Api import Api


def set_process_name(artifact_id, version, config_obj=None):
    """ Set process name according to pom.xml file """

    # Protected suffixes (to hide from ps aux)
    protected_suffixes = ('pass', 'password', 'passwd', 'key', 'keys')

    # Strip passwords from arguments
    cli_args = ' '.join(sys.argv[1:])
    if isinstance(config_obj, argparse.Namespace):
        for k, v in config_obj.__dict__.items():
            if isinstance(v, str) and k.lower().endswith(protected_suffixes):
                cli_args = cli_args.replace(v, '<hidden>')
            if isinstance(v, list) and k.lower().endswith(protected_suffixes):
                for x in v:
                    if isinstance(x, str):
                        cli_args = cli_args.replace(x, '<hidden>')

    setproctitle.setproctitle('%s-%s %s' % (artifact_id, version, cli_args))  # pylint: disable=maybe-no-member


def configure_root_logger(level=logging.INFO):
    """Override root logger to use a better formatter"""

    logging.basicConfig(
        level=level,
        format='%(asctime)s %(levelname)-8s [%(name)s] %(message)s',
        stream=sys.stdout
    )


def cli_args(description='API description'):

    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument('-b', '--bind', type=str, default='::1', help='Address to bind on', metavar='0.0.0.0')
    parser.add_argument('-p', '--port', type=int, default=8877,  help='Port to bind on', metavar=8877)
    parser.add_argument('-n', '--nvidia-settings-path', type=str, default='/usr/bin/nvidia-settings', help='Absolute path to nvidia-settings binary')
    parser.add_argument('-x', '--xterm-path',           type=str, default='/usr/bin/xterm',           help='Absolute path to xterm binary')
    parser.add_argument('-e', '--display-env',          type=str, default=':0', help='Xorg address to be used as DISPLAY env var')

    parsed = parser.parse_args()

    if not os.path.isfile(parsed.nvidia_settings_path) or not os.access(parsed.nvidia_settings_path, os.X_OK):
        parser.error('%s does not exist or no permissions or not executable' % parsed.nvidia_settings_path)

    if not os.path.isfile(parsed.xterm_path) or not os.access(parsed.xterm_path, os.X_OK):
        parser.error('%s does not exist or no permissions or not executable' % parsed.xterm_path)

    return parsed


if __name__ == '__main__':

    name = 'nvidia-settings-rest-api'
    version = '0.0.1'

    config = cli_args(description='%s-%s' % (name, version))
    configure_root_logger(level=logging.DEBUG)
    set_process_name('name', 'version', config_obj=config)

    os.terminal_size((500, 20))

    api = Api(config=config, name=name, version=version)
    aiohttp.web.run_app(
        api.app,
        host=api.config.bind,
        port=api.config.port,
    )
