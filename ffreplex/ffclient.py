"""Client functions to call ffmpeg subprocesses"""
import json
import os
import pprint
import re
import shutil
import subprocess
import itertools
from typing import TypedDict, Dict, List, Tuple

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

type I_downmix_for_layout = tuple[list[str], str, str]
type I_downmixes_map_for_layout = list[I_downmix_for_layout]
type I_downmixes_map = dict[str, I_downmixes_map_for_layout]

COMPATIBLE_DOWNMIXES: I_downmixes_map = {
    'stereo': [
        (FIVE_ONE_COMPATIBLE, 'volume=1.66, pan=stereo|c0=0.5*c2+0.707*c0+0.707*c4+0.5*c3|c1=0.5*c2+0.707*c1+0.707*c5+0.5*c3', 'aac_at'),  # 5.1 to stereo
        (SEVEN_ONE_COMPATIBLE, 'volume=1.66, pan=stereo|c0=0.5*c2+0.707*c0+0.707*c4+0.5*c3|c1=0.5*c2+0.707*c1+0.707*c5+0.5*c3', 'aac_at')  # 7.1 to stereo TODO change downmix function here
    ],
    '5.1': [
        # (SEVEN_ONE_COMPATIBLE, '7.1_to_5.1', 'codec')  # 7.1 to 5.1
    ]
}

COMPATIBLE_DOWNMIX_LAYOUTS = {
    key: set(itertools.chain.from_iterable([formats[0] for formats in COMPATIBLE_DOWNMIXES[key]]))
    for key in COMPATIBLE_DOWNMIXES.keys()
}

print('=== Available downmixes ===')
for (layout, downmixes) in COMPATIBLE_DOWNMIXES.items():
    print(f"- {layout} :")
    if len(downmixes) == 0:
        print(f"  None")
    else:
        for downmix in downmixes:
            print(f"  - {', '.join(downmix[0])}")



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


type ExistentStreamList = list[ExistentStream]

type AudioStreamList = dict[str, list[AudioExistentStream]]
type AudioGenerableStreamList = dict[str, list[AudioExistentStream | AudioGenerableStream]]

type VideoStreamList = list[VideoExistentStream]


class AllStreams(TypedDict):
    video: VideoStreamList
    audio: AudioStreamList
    subtitle: ExistentStreamList
    other: ExistentStreamList


class AllStreamsWithGenerables(TypedDict):
    video: VideoStreamList
    audio: AudioGenerableStreamList
    subtitle: ExistentStreamList
    other: ExistentStreamList


class FFClient:
    versionRegex = re.compile(r'^ffmpeg\sversion\s(\S+)')

    layoutStereoRegex = re.compile(r'^stereo')
    layoutFiveRegex = re.compile(r'^5\.1')
    layoutSevenRegex = re.compile(r'^7\.1')

    @staticmethod
    def ff_create_empty_data():
        return {'video': [], 'audio': {}, 'subtitle': [], 'other': []}

    @staticmethod
    def ff_get_info():
        """get info of system ffmpeg binary"""
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True)
        version_match = FFClient.versionRegex.match(result.stdout.decode())
        path = shutil.which('ffmpeg')
        return {
            'path': path,
            'version': version_match.group(1)
        }

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

        streams: AllStreams = FFClient.ff_create_empty_data()
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
                    'from_index': stream['index'],
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
                    # stream['from_index'] = compatible_sources[0]['index'] if len(compatible_sources) else None
                    stream['from_compatible'] = [source['index'] for source in compatible_sources] if len(compatible_sources) else None
                elif stream['layout'] in FIVE_ONE_COMPATIBLE:
                    compatible_sources = list(filter(
                        lambda stream: stream['layout'] in COMPATIBLE_DOWNMIX_LAYOUTS['5.1'],
                        existent_streams_of_lang
                    ))
                    # stream['from_index'] = compatible_sources[0]['index'] if len(compatible_sources) else None
                    stream['from_compatible'] = [source['index'] for source in compatible_sources]

                stream['from_index'] = stream['index']

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

    @staticmethod
    def ff_get_command_args(streams: AllStreamsWithGenerables) -> str:

        pprint.pprint(streams)
        args = ["-strict -2",
                "-global_quality:a 0"]

        # video
        current_video_index_out = 0
        for stream in streams['video']:
            args.append(f"-map 0:{stream['index']} -c:v:{current_video_index_out} copy")
            current_video_index_out = current_video_index_out + 1

        # audio
        current_audio_index_out = 0
        for lang in streams['audio']:
            streams_of_lang = streams['audio'][lang]
            for stream in streams_of_lang:
                index = stream.get('index')
                layout = stream.get('layout')
                from_index = stream.get('from_index')
                if from_index is None:
                    if index is not None:
                        print(f' REMOVE ─ 0:{index} {lang}({layout})')
                    else:
                        print(f'   PASS ─ {lang}({layout})')
                    pass
                else:
                    # print(lang.upper(), stream)
                    if index is not None and from_index == index:
                        # Copy audio
                        args.append(f"-map 0:{stream['from_index']} -c:a:{current_audio_index_out} copy")
                        print(f'   KEEP ─ 0:a:{current_audio_index_out} {lang}({layout}) FROM 0:{from_index} {lang}({layout})')

                    elif from_index is not None:
                        # Convert audio
                        def find_stream_fn(x: AudioExistentStream) -> bool:
                            return x.get('index') == from_index
                        from_stream = next(x for x in streams_of_lang if find_stream_fn(x))
                        from_layout = from_stream.get('layout')
                        print(f'CONVERT ┬ 0:a:{current_audio_index_out} {lang}({layout}) FROM 0:{from_index} {lang}({from_layout})')

                        def find_downstream(x: I_downmix_for_layout) -> bool:
                            return from_layout in x[0]
                        downmix_from, downmix_filter, downmix_codec = next(x for x in COMPATIBLE_DOWNMIXES[layout] if find_downstream(x))
                        print("        └── with :", downmix_filter, downmix_codec)

                        args.append(f"-map 0:{stream['from_index']} -c:a:{current_audio_index_out} {downmix_codec} \\\n"
                                    f"     -filter:a:{current_audio_index_out} \"{downmix_filter}\"")

                    current_audio_index_out = current_audio_index_out + 1

        # subtitles
        current_other_index_out = current_video_index_out + current_audio_index_out
        for stream in streams['subtitle']:
            args.append(f"-map 0:{stream['index']} -c:{current_other_index_out} mov_text")
            current_other_index_out = current_other_index_out + 1
        # other
        for stream in streams['other']:
            args.append(f"-map 0:{stream['index']} -c:{current_other_index_out} copy")
            current_other_index_out = current_other_index_out + 1

        return " \\\n ".join(args)

    @staticmethod
    def ff_get_command(file: str, command_args: str) -> str:
        in_file = file
        out_file = os.path.splitext(file)[0]+'.ffreplex.mp4'
        return f'ffmpeg -i "{in_file.replace(r'"', r'\"')}" \\\n {command_args} \\\n "{out_file.replace(r'"', r'\"')}"'

    @staticmethod
    def ff_process_files(files: list[str], streams: AllStreamsWithGenerables):
        print(files)

        args = FFClient.ff_get_command_args(streams)
        commands = [FFClient.ff_get_command(file, args) for file in files]
        for c in commands:
            print(c)

    @staticmethod
    def ff_process_file(file: str):
        print(file)

