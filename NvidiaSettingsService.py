import logging
import asyncio
import sys
import array
import fcntl
import termios
import tempfile
import re
from collections import defaultdict


class NvidiaSettingsServiceException(Exception):
    pass


class NvidiaSettingsService:
    """
    Run nvidia-settings to register all available commands
    as REST resources

    Provide GET and POST handlers for commands
    """

    def __init__(self, *, nvidia_settings_path, display_env, xterm_path, loop=None):
        """
        Creates a new instance of the service
        :param nvidia_settings_path: Absolute path to nvidia-settings binary
        :param display_env: Xorg display name to be used as DISPLAY env var
        """

        self.logger = logging.getLogger(self.__class__.__name__)
        self.loop = loop if loop is not None else asyncio.get_event_loop()

        self.nvidia_settings_path = nvidia_settings_path
        self.xterm_path = xterm_path
        self.display_env = display_env

    async def execute_process(self, *args):
        """
        Run an asyncio subprocess and put stdout to a file object
        The problem here is that if I pipe stdout, the output gets
        wrapped to 80 columns.

        I found a solution here for sync code:
        https://www.osso.nl/blog/python-subprocess-winch/

        But nothing for asyncio and I am not sure how to do this
        Simply resizing terminal before asyncio calls does not work
        It's either rewritten later or no-op cuz running in another
        process.

        Anyway, here is the shitty trick: start the process in
        xterm and sets its size large enough to not wrap output
        I also tried to apply the same script with a second tempfile
        for stderr but sadly it wraps again to 80, let's forget that.
        """

        with tempfile.NamedTemporaryFile() as stdout_file:

            cmd = """{xterm_path} -geometry 500x50 -e '{real_command} >{stdout_file}'""".format(
                xterm_path=self.xterm_path,
                real_command=' '.join(args),
                stdout_file=stdout_file.name,
            )

            process = await asyncio.create_subprocess_shell(
                cmd=cmd,
                env={'DISPLAY': self.display_env},
            )

            stdout, stderr = await process.communicate()

            stdout_file.seek(0)
            stdout = stdout_file.read()

            if process.returncode != 0:
                raise NvidiaSettingsServiceException('%s failed with code %d\nStdout was:\n%s\nStderr was:\n%s' % (cmd, process.returncode, stdout, stderr))

        return stdout

    async def parse_query_all(self, stdout):
        """
        Run nvidia-settings --query all and turn its output into a dict
        to be used to build the API routes

        Example output:
          Attribute 'GPUCurrentClockFreqs' (rig1.metz.levert:0[gpu:1]): 2012,4752."
            'GPUCurrentClockFreqs' is a packed integer attribute.
            'GPUCurrentClockFreqs' is a read-only attribute.
            'GPUCurrentClockFreqs' can use the following target types: X Screen, GPU.
        """

        gpus_attributes = defaultdict(lambda: defaultdict(dict))
        current_attribute = None
        current_index = None

        for line in str(stdout, 'utf-8').splitlines():

            re_match = re.match(r"""\s+Attribute\s+'(\w+)'\s+\([\w.]+:\d+\[gpu:(\d+)\]\):\s+(.+)\.$""", line)
            if re_match:
                attribute, index, example = re_match.groups()
                gpus_attributes[index][attribute] = {}
                gpus_attributes[index][attribute]['example'] = example
                gpus_attributes[index][attribute]['read-only'] = False
                current_attribute = attribute
                current_index = index

            re_match = re.match(r"""\s+'{attribute}'\s+is an? ([\w-]+) attribute\.$""".format(attribute=current_attribute), line)
            if re_match:
                attribute_type = re_match.group(1)
                if attribute_type == 'read-only':
                    gpus_attributes[current_index][current_attribute]['read-only'] = True
                elif attribute_type == 'integer':
                    gpus_attributes[current_index][current_attribute]['type'] = 'number'
                    gpus_attributes[current_index][current_attribute]['format'] = None
                    gpus_attributes[current_index][current_attribute]['example'] = int(gpus_attributes[current_index][current_attribute]['example'])
                elif attribute_type == 'bitmask':
                    gpus_attributes[current_index][current_attribute]['type'] = 'string'
                    gpus_attributes[current_index][current_attribute]['pattern'] = '0x[0-9a-z]{8}'
                else:
                    raise NvidiaSettingsServiceException('nvidia-settings --query all return attribute %s of unhandled type %s' % (current_attribute, attribute_type))

            re_match = re.match(r"""\s+The valid values for '{attribute}' are in the range (-?\d+) - (\d+) \(inclusive\)\.$""".format(attribute=current_attribute), line)
            if re_match:
                start, end = re_match.groups()
                start, end = int(start), int(end)
                gpus_attributes[current_index][current_attribute]['type'] = 'number'
                gpus_attributes[current_index][current_attribute]['format'] = None
                gpus_attributes[current_index][current_attribute]['minimum'] = start
                gpus_attributes[current_index][current_attribute]['maximum'] = end
 
        import json
        self.logger.info(json.dumps(gpus_attributes, indent=4))

    async def register_all_routes(self):
        stdout = await self.execute_process(self.nvidia_settings_path, '--query', 'all')
        await self.parse_query_all(stdout)
