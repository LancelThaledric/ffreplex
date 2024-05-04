#!/usr/bin/env python
"""ffreplex entry point"""
import json
import logging
import argparse
import re
import subprocess

from ffreplex.ffclient import FFClient
from ffreplex.filewalk import list_files


def get_options():
    description = ''
    parser = argparse.ArgumentParser(description=description)

    parser.add_argument('input',
                        help='File or folder')

    return parser.parse_args()


def set_logging(level=logging.INFO):
    logger = logging.getLogger()
    logger.setLevel(level)
    ch = logging.StreamHandler()
    logger.addHandler(ch)
    return logger


def print_audio(streams):
    for s in streams:
        print(f'"{s['tags']['title']}": {s['tags']['language']} {s['profile']} {s['channel_layout']}')


if __name__ == "__main__":
    options = get_options()
    logger = set_logging()
    ffclient = FFClient(logger)
    system_ffmpeg = ffclient.ff_get_info()
    print(system_ffmpeg)
    files = list_files(options.input, re.compile(r'\.mkv$'))
    files.sort()
    print(f'Detected {len(files)} videos.')
    if len(files) > 1:
        print(f'Using {files[0]} as reference.')

    audio_streams = ffclient.ff_get_audio_streams(files[0])

    print_audio(audio_streams)


