#!/usr/bin/env python
"""ffreplex entry point"""
import json
import logging
import argparse
import re
import subprocess

from ffreplex.ffclient import FFClient, AudioExistentStream, AudioGenerableStream
from ffreplex.filewalk import list_files

from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer, Grid, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Button, Footer, Header, Static, Label, Select


def get_options():
    description = ''
    parser = argparse.ArgumentParser(description=description)

    parser.add_argument('input',
                        help='File or folder')

    return parser.parse_args()


def print_audio(streams):
    for s in streams:
        print(f'"{s['tags'].get('title')}": {s['tags']['language']} {s['profile']} {s['channel_layout']}')


class UITrack(Static):
    """A line widget for a specific track."""

    def __init__(self, info: tuple[int, str]):
        super().__init__()
        self.index = info[0]
        self.type = info[1]

    def compose(self) -> ComposeResult:
        """Create child widgets of a stopwatch."""
        yield Button(self.type, classes="track")

class UIMissingTrack(Static):
    """A line widget for a specific track that will be generated."""

    def __init__(self, info: tuple[int, str]):
        super().__init__()
        self.index = info[0]
        self.type = info[1]

    def compose(self) -> ComposeResult:
        yield Label(self.type, classes="track missing")


class UILanguage(Static):
    """A line widget for a specific track."""

    def __init__(self, lang: str, tracks: list[tuple[int, str]]):
        super().__init__()
        self.lang = lang
        self.tracks = tracks

    def compose(self) -> ComposeResult:
        yield Label(self.lang, classes="language")
        for t in self.tracks:
            yield UITrack(t)
        # Missing tracks
        stereo = [v for i, v in enumerate(self.tracks) if FFClient.layoutStereoRegex.search(v[1])]
        fiveone = [v for i, v in enumerate(self.tracks) if FFClient.layoutFiveRegex.search(v[1])]
        sevenone = [v for i, v in enumerate(self.tracks) if FFClient.layoutSevenRegex.search(v[1])]


class AudioLanguageWidget(Static):

    def __init__(self, lang: str, streams: list[AudioExistentStream]):
        super().__init__()
        self.lang = lang
        self.streams = streams
        self.classes = 'row'

    def compose(self) -> ComposeResult:
        yield Label(self.lang.upper(), classes="col language")

        for stream in self.streams:
            yield AudioExistentStreamWidget(stream)
        if not FFClient.audio_lang_has_stereo(self.streams):
            yield AudioNonexistentStreamWidget({'layout': 'stereo', 'encode_from': self.streams[0]['index']}, self.streams)


class AudioExistentStreamWidget(Static):
    def __init__(self, stream: AudioExistentStream):
        super().__init__()
        self.stream = stream

    def compose(self) -> ComposeResult:
        options = [(self.stream['title'], self.stream['index']), ('[red]Remove[/]', None)]
        yield Label(self.stream['layout'], classes='layout')
        yield Select[int | None](
                options,
                classes="stream audio existent",
                allow_blank=False,
                id=f'stream-{self.stream['index']}'
            )
        # yield Button(f'[blue]{self.stream['layout']}[/] [gray]|[/] {self.stream['title']}', classes="col stream audio existent")


class AudioNonexistentStreamWidget(Static):
    def __init__(self, stream: AudioGenerableStream, existent: list[AudioExistentStream]):
        super().__init__()
        self.stream = stream
        self.existent = existent

    def compose(self) -> ComposeResult:
        options: list[tuple[str, int | None]] = ([(s['title'], s['index']) for s in self.existent])
        options.append(('[red]Do not create[/]', None))
        yield Label(self.stream['layout'], classes='layout create')
        yield Select[int | None](
            options,
            classes="stream audio nonexistent",
            allow_blank=False,
        )


class FFReplexGui(App):
    """GUI for ffreplex task"""

    CSS_PATH = "ffreplex.tcss"
    ffclient = FFClient()

    def __init__(self):
        super().__init__()
        options = get_options()
        self.system_ffmpeg = FFReplexGui.ffclient.ff_get_info()
        self.files = list_files(options.input, re.compile(r'\.mkv$'))
        (self.audio, self.audio_tracks) = FFReplexGui.ffclient.ff_get_audio_streams(self.files[0])

        self.streams, self.initial_streams = FFClient.read_streams(self.files[0])
        print(self.initial_streams)
        print(self.streams)

    def mount_file(self):
        file_widget = Label(f'{len(self.files)} files | {self.files[0]}', classes='row file')
        self.query_one("#tracks").mount(file_widget)

    def mount_video(self):
        video_widget = Label(f'{self.streams['video'][0]['width']}x{self.streams['video'][0]['height']} {self.streams['video'][0]['display_aspect_ratio']}', classes='row video')
        self.query_one("#tracks").mount(video_widget)

    def mount_audio(self):
        for lang in self.streams['audio']:
            print(f'mount audio {lang}')
            audio_widget = AudioLanguageWidget(lang, self.streams['audio'][lang])
            self.query_one("#tracks").mount(audio_widget)

    def mount_lang(self, lang: str, tracks: list[tuple[int, str]]) -> None:
        new_track = UILanguage(lang, tracks)
        self.query_one("#tracks").mount(new_track)

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield Footer()
        yield ScrollableContainer(id="tracks")

    # def on_mount(self) -> None:
        # self.mount_file()
        # self.mount_video()
        # self.mount_audio()


if __name__ == "__main__":
    app = FFReplexGui()
    app.run()


# if __name__ == "__main__":
#     options = get_options()
#     ffclient = FFClient()
#     system_ffmpeg = ffclient.ff_get_info()
#     print(system_ffmpeg)
#     files = list_files(options.input, re.compile(r'\.mkv$'))
#     files.sort()
#     print(f'Detected {len(files)} videos.')
#     if len(files) > 1:
#         print(f'Using {files[0]} as reference.')
#
#     audio_streams = ffclient.ff_get_audio_streams(files[0])
#
#     print_audio(audio_streams)
#
#     ffclient.ff_process_file(files[0])


