"""Client functions to call ffmpeg subprocesses"""
import json
import logging
import re
import shutil
import subprocess


class FFClient:

    versionRegex = re.compile(r'^ffmpeg\sversion\s(\S+)')

    logger: logging.Logger

    def __init__(self, logger):
        self.logger = logger

    def ff_get_info(self):
        """get info of system ffmpeg binary"""
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True)
        version_match = FFClient.versionRegex.match(result.stdout.decode())
        path = shutil.which('ffmpeg')
        return {
            'path': path,
            'version': version_match.group(1)
        }

    def ff_get_audio_streams(self, filepath: str):
        """get streams content ordered by quality"""
        cmd = ['ffprobe', '-show_streams', '-select_streams', 'a', '-loglevel', 'quiet', '-of', 'json', filepath]
        res = subprocess.run(cmd, capture_output=True)
        res_dict: dict = json.loads(res.stdout.decode())
        streams: list = sorted(res_dict['streams'], key=lambda s: s['channels'], reverse=True)
        return streams

