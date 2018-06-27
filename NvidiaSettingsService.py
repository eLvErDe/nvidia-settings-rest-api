import logging
import asyncio
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

    def __init__(self, *, nvidia_settings_path, display_env, xterm_path):
        """
        Creates a new instance of the service
        :param nvidia_settings_path: Absolute path to nvidia-settings binary
        :param display_env: Xorg display name to be used as DISPLAY env var
        """

        self.logger = logging.getLogger(self.__class__.__name__)

        self.nvidia_settings_path = nvidia_settings_path
        self.xterm_path = xterm_path
        self.display_env = display_env

        self.items = {}

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
            self.logger.info('Running: %s', cmd)

            process = await asyncio.create_subprocess_shell(
                cmd=cmd,
                env={'DISPLAY': self.display_env},
            )

            await process.communicate()

            stdout_file.seek(0)
            stdout = stdout_file.read()

            if process.returncode != 0:
                raise NvidiaSettingsServiceException('%s failed with code %d\nStdout was:\n%s' % (cmd, process.returncode, stdout))

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

            re_match = re.match(r"""\s+'{attribute}'\s+is an? (.+) attribute\.$""".format(attribute=current_attribute), line)
            if re_match:
                attribute_type = re_match.group(1)
                if attribute_type == 'read-only':
                    gpus_attributes[current_index][current_attribute]['read-only'] = True
                elif attribute_type == 'integer':
                    gpus_attributes[current_index][current_attribute]['type'] = 'integer'
                    gpus_attributes[current_index][current_attribute]['example'] = int(gpus_attributes[current_index][current_attribute]['example'])
                elif attribute_type == 'bitmask':
                    gpus_attributes[current_index][current_attribute]['type'] = 'string'
                    gpus_attributes[current_index][current_attribute]['pattern'] = '0x[0-9a-z]{8}'
                elif attribute_type == 'packed integer':
                    gpus_attributes[current_index][current_attribute]['type'] = 'string'
                    gpus_attributes[current_index][current_attribute]['pattern'] = ','.join(['[0-9]+'] * (gpus_attributes[current_index][current_attribute]['example'].count(',') + 1))
                else:
                    raise NvidiaSettingsServiceException('nvidia-settings --query all return attribute %s of unhandled type %s' % (current_attribute, attribute_type))

            re_match = re.match(r"""\s+The valid values for '{attribute}' are in the range (-?\d+) - (\d+) \(inclusive\)\.$""".format(attribute=current_attribute), line)
            if re_match:
                start, end = re_match.groups()
                start, end = int(start), int(end)
                gpus_attributes[current_index][current_attribute]['type'] = 'integer'
                gpus_attributes[current_index][current_attribute]['minimum'] = start
                gpus_attributes[current_index][current_attribute]['maximum'] = end

            re_match = re.match(r"""\s+'{attribute}'\s+is a boolean attribute; valid values are: 1 \(on/true\) and 0 \(off/false\)\.$""".format(attribute=current_attribute), line)
            if re_match:
                gpus_attributes[current_index][current_attribute]['type'] = 'boolean'
                gpus_attributes[current_index][current_attribute]['example'] = bool(int(gpus_attributes[current_index][current_attribute]['example']))

            re_match = re.match(r"""\s+Valid values for '{attribute}' are: (.+)\.""".format(attribute=current_attribute), line)
            if re_match:
                valid_values = re_match.group(1)
                valid_values = valid_values.split('and')
                valid_values = [x.split(',') for x in valid_values]
                flat_list = [x.strip() for y in valid_values for x in y]
                try:
                    flat_list = [int(x) for x in flat_list]
                    gpus_attributes[current_index][current_attribute]['type'] = 'integer'
                    gpus_attributes[current_index][current_attribute]['enum'] = flat_list
                except ValueError:
                    try:
                        flat_list = [float(x) for x in flat_list]
                        gpus_attributes[current_index][current_attribute]['type'] = 'number'
                        gpus_attributes[current_index][current_attribute]['format'] = 'float'
                        gpus_attributes[current_index][current_attribute]['enum'] = flat_list
                    except ValueError:
                        gpus_attributes[current_index][current_attribute]['type'] = 'string'
                        gpus_attributes[current_index][current_attribute]['enum'] = flat_list
 
        return gpus_attributes

    async def return_available_items(self):
        stdout = await self.execute_process(self.nvidia_settings_path, '--query', 'all')
        return await self.parse_query_all(stdout)
