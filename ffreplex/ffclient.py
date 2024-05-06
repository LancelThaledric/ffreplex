"""Client functions to call ffmpeg subprocesses"""
import json
import os
import re
import shutil
import subprocess
import itertools
from typing import TypedDict

STANDARD_AUDIO_LAYOUTS = [
    'mono',
    'stereo',
    'downmix',
    '2.1',
    '3.0',
    '3.0(back)',
    '4.0',
    'quad',
    'quad(side)',
    '3.1',
    '5.0',
    '5.0(side)',
    '4.1',
    '5.1',
    '5.1(side)',
    '6.0',
    '6.0(front)',
    'hexagonal',
    '6.1',
    '6.1(back)',
    '6.1(front)',
    '7.0',
    '7.0(front)',
    '7.1',
    '7.1(wide)',
    '7.1(wide-side)',
    '7.1(top)',
    'octagonal',
    'cube',
    'hexadecagonal',
    '22.2',
]
"""
Standard audio layout in quality order as defined in
https://trac.ffmpeg.org/wiki/AudioChannelManipulation#Listchannelnamesandstandardchannellayouts
(except 'downmix' is considered as same quality as 'stereo')
"""

STEREO_COMPATIBLE = ['stereo', 'downmix']
FIVE_ONE_COMPATIBLE = ['5.1', '5.1(side)']
SEVEN_ONE_COMPATIBLE = ['7.1', '7.1(wide)',  '7.1(wide-side)', '7.1(top)']

COMPATIBLE_DOWNMIXES = {
    'stereo': [
        (FIVE_ONE_COMPATIBLE, '5.1_to_2.0'),
        (SEVEN_ONE_COMPATIBLE, '7.1_to_2.0')
    ],
    '5.1': [
        (SEVEN_ONE_COMPATIBLE, '7.1_to_5.1')
    ]
}

COMPATIBLE_DOWNMIX_LAYOUTS = {
    key: set(itertools.chain.from_iterable([formats[0] for formats in COMPATIBLE_DOWNMIXES[key]]))
    for key in COMPATIBLE_DOWNMIXES.keys()
}


class AudioTrack:
    """represent ane existing audio track in input media"""
    index: int
    type: str


class GenerableStream(TypedDict):
    from_index: int | None
    from_compatible: list[int] | None


class ExistentStream(GenerableStream):
    index: int


class AudioGenerableStream(GenerableStream):
    layout: str
    title: str


class AudioExistentStream(ExistentStream):
    layout: str
    title: str


class VideoExistentStream(ExistentStream):
    display_aspect_ratio: str
    width: int
    height: int


type StreamList = list[ExistentStream]

type AudioStreamList = dict[str, list[AudioExistentStream]]
type AudioGenerableStreamList = dict[str, list[AudioExistentStream | AudioGenerableStream]]

type VideoStreamList = list[VideoExistentStream]


class AllStreams(TypedDict):
    video: StreamList
    audio: AudioStreamList
    subtitle: StreamList
    other: StreamList


class AllStreamsWithGenerables(TypedDict):
    video: StreamList
    audio: AudioGenerableStreamList
    subtitle: StreamList
    other: StreamList


class FFClient:
    versionRegex = re.compile(r'^ffmpeg\sversion\s(\S+)')

    layoutStereoRegex = re.compile(r'^stereo')
    layoutFiveRegex = re.compile(r'^5\.1')
    layoutSevenRegex = re.compile(r'^7\.1')

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
        streams: list = res_dict['streams']

        result: dict[str, list[tuple[int, str]]] = {}
        for stream in streams:
            tags = stream.get('tags')
            if tags is None:
                break
            language: str = tags.get('language')
            if language is None:
                break
            if result.get(language) is None:
                result[language] = []
            result[language].append((stream.get('index'), stream.get('channel_layout')))

        for lang in result:
            result[lang].sort(key=lambda track: track[1], reverse=True)

        return streams, result

    @staticmethod
    def read_streams(filepath: str):
        """
        get streams categorized by type :
        - video are in a list ordered by index in input file
        - audio are in a dict by language, ordered by index
        - subtitles and other are as-is
        """
        if not os.path.exists(filepath) or not os.path.isfile(filepath):
            raise FileNotFoundError()
        cmd = ['ffprobe', '-show_streams', '-loglevel', 'quiet', '-of', 'json', filepath]
        data_json = subprocess.run(cmd, capture_output=True).stdout.decode()
        data: list[dict] = json.loads(data_json)['streams']
        if not data:
            raise TypeError()

        streams: AllStreams = {'video': [], 'audio': {}, 'subtitle': [], 'other': []}
        for stream in data:
            if stream['codec_type'] == 'video':
                streams['video'].append({
                    'index': stream['index'],
                    'width': stream['width'],
                    'height': stream['height'],
                    'display_aspect_ratio': stream['display_aspect_ratio']
                })
            elif stream['codec_type'] == 'audio':
                lang = stream.get('tags', {}).get('language')
                if streams['audio'].get(lang) is None:
                    streams['audio'][lang] = []
                streams['audio'][lang].append({
                    'index': stream['index'],
                    'layout': stream['channel_layout'],
                    'title': stream.get('tags', {}).get('title')
                })
            elif stream['codec_type'] == 'subtitle':
                streams['subtitle'].append({'index': stream['index']})
            else:
                streams['other'].append({'index': stream['index']})

        # Finally sort audio streams by quality
        for lang in streams['audio']:
            streams['audio'][lang] = sorted(
                streams['audio'][lang],
                key=lambda s: FFClient.get_audio_layout_order(s['layout']),
                reverse=True
            )

        streams_with_generables = FFClient.populate_generable_streams(streams)
        return streams_with_generables, streams

    @staticmethod
    def get_audio_layout_order(layout: str) -> int:
        try:
            return STANDARD_AUDIO_LAYOUTS.index(layout)
        except ValueError:
            return -1

    @staticmethod
    def populate_generable_streams(streams: AllStreams) -> AllStreamsWithGenerables:
        """generate generable streams information and return all streams plus the generable ones"""
        streams_with_generables: AllStreamsWithGenerables = {'video': [stream for stream in streams['video']],
                                                             'audio': {},
                                                             'subtitle': [stream for stream in streams['subtitle']],
                                                             'other': [stream for stream in streams['other']]}
        for lang in streams['audio']:
            # copy existent audios
            streams_with_generables['audio'][lang] = [stream for stream in streams['audio'][lang]]
            existent_streams_of_lang: list = streams_with_generables['audio'][lang]
            if len(existent_streams_of_lang) == 0:
                continue
            generable_streams_of_lang: list[AudioGenerableStream] = []

            for stream in existent_streams_of_lang:
                if stream['layout'] in STEREO_COMPATIBLE:
                    compatible_sources = list(filter(
                        lambda stream: stream['layout'] in COMPATIBLE_DOWNMIX_LAYOUTS['stereo'],
                        existent_streams_of_lang
                    ))
                    stream['from_index'] = compatible_sources[0]['index'] if len(compatible_sources) else None
                    stream['from_compatible'] = [source['index'] for source in compatible_sources] if len(compatible_sources) else None
                elif stream['layout'] in FIVE_ONE_COMPATIBLE:
                    compatible_sources = list(filter(
                        lambda stream: stream['layout'] in COMPATIBLE_DOWNMIX_LAYOUTS['5.1'],
                        existent_streams_of_lang
                    ))
                    stream['from_index'] = compatible_sources[0]['index'] if len(compatible_sources) else None
                    stream['from_compatible'] = [source['index'] for source in compatible_sources]

            # stereo generation
            if not FFClient.audio_lang_has_stereo(streams['audio'][lang]):
                compatible_sources = list(filter(
                    lambda stream: stream['layout'] in COMPATIBLE_DOWNMIX_LAYOUTS['stereo'],
                    existent_streams_of_lang
                ))
                generable_streams_of_lang.append({
                    'from_index': compatible_sources[0]['index'] if len(compatible_sources) else None,
                    'from_compatible': [source['index'] for source in compatible_sources],
                    'layout': 'stereo',
                    'title': ''
                })

            # 5.1 generation
            if not FFClient.audio_lang_has_five(streams['audio'][lang]):
                generable_streams_of_lang.append({
                    'from_index': existent_streams_of_lang[0]['index'],
                    'layout': '5.1',
                    'title': ''
                })
            existent_streams_of_lang.extend(generable_streams_of_lang)
            existent_streams_of_lang.sort(
                key=lambda s: FFClient.get_audio_layout_order(s['layout']),
                reverse=True
            )

        return streams_with_generables

    @staticmethod
    def audio_lang_has_stereo(streams: list[AudioExistentStream]):
        return any(stream['layout'] in STEREO_COMPATIBLE for stream in streams)

    @staticmethod
    def audio_lang_has_five(streams: list[AudioExistentStream]):
        return any(stream['layout'] in FIVE_ONE_COMPATIBLE
                   for stream in streams)

    def ff_process_file(self, filepath: str, args=None):
        """process given file by converting it to mp4 + process args supplied"""
        if args is None:
            args = []
        newfile = os.path.splitext(filepath)[0] + '.mp4'
        command = ['ffmpeg', '-i', filepath]
        command.extend(args)
        command.append(newfile)
        # subprocess.run(command)
