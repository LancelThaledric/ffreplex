#!/usr/bin/env python
"""ffreplex entry point"""

import argparse
import pprint
import re
import sys
import random
from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtCore import Slot, Signal

from ffreplex.ffclient import FFClient, AudioExistentStream, AudioGenerableStream, AllStreamsWithGenerables, AllStreams, \
    AudioStreamList
from ffreplex.filewalk import list_files


def get_options():
    description = ''
    parser = argparse.ArgumentParser(description=description)

    parser.add_argument('input',
                        help='File or folder')

    return parser.parse_args()


class FFStreamWidget(QtWidgets.QFrame):

    changed = Signal(object)

    def __init__(self, stream: AudioGenerableStream | AudioExistentStream,
                 streams_of_lang: list[AudioExistentStream | AudioGenerableStream]):
        super().__init__()
        self.stream = stream

        self.label = QtWidgets.QLabel()
        self.layout = QtWidgets.QHBoxLayout()
        self.combo_box = QtWidgets.QComboBox()

        index = stream.get('index')
        from_compatible = stream.get('from_compatible')

        # Add "Keep it" option
        if index:
            self.combo_box.addItem(f'KEEP | {stream['title']}', index)

        # Add "Encrypt" option
        if from_compatible is not None:
            for from_index in from_compatible:
                def find_stream_fn(x: AudioExistentStream) -> bool: return x.get('index') == from_index
                from_stream = next(x for x in streams_of_lang if find_stream_fn(x))
                self.combo_box.addItem(f'GENERATE FROM | {from_stream['title']}', from_stream['index'])

        # Add "Remove option"
        if stream.get('index'):
            self.combo_box.addItem(f'REMOVE | {stream['title']}', None)
        else:
            self.combo_box.addItem(f'DO NOT GENERERATE', None)

        # Layout all this
        self.label.setText(stream['layout'])

        self.layout.addWidget(self.label)
        self.layout.addWidget(self.combo_box)
        self.setLayout(self.layout)
        self.layout.setStretch(1, 1)

        # Reactive stuff

        self.combo_box.activated.connect(self.on_change)

        # Styling

    @Slot(int)
    def on_change(self, value):
        data = self.combo_box.itemData(value)
        self.changed.emit((self.stream, data))


class FFReplexGui(QtWidgets.QMainWindow):
    """GUI for ffreplex task"""

    ffclient = FFClient()

    streams: AllStreamsWithGenerables = FFClient.ff_create_empty_data()
    initial_streams: AllStreams = FFClient.ff_create_empty_data()
    files: list[str] = []

    def __init__(self):
        super().__init__()
        self.system_ffmpeg = FFReplexGui.ffclient.ff_get_info()

        # Parse args and find files
        options = get_options()
        self.files = list_files(options.input, re.compile(r'\.mkv$'))

        # Find streams of first file
        self.streams, self.initial_streams = FFClient.read_streams(self.files[0])
        # print(self.initial_streams)
        # pprint.pprint(self.streams['audio'])
        # print('====================================')

        # Print window
        self.setWindowTitle(f"FFReplex – {self.files[0]}")
        self.main_widget = QtWidgets.QWidget()
        self.layout = QtWidgets.QVBoxLayout()
        self.main_widget.setLayout(self.layout)
        self.setCentralWidget(self.main_widget)

        self.scroll_view = QtWidgets.QScrollArea()
        self.grid = QtWidgets.QGridLayout()
        self.scroll_view.setLayout(self.grid)

        self.file_widget = QtWidgets.QLabel(f'{len(self.files)} files – {self.files[0]}')
        self.video_widget = QtWidgets.QLabel(
            f'Video : {len(self.streams['video'])} streams – {self.streams['video'][0]['width']}x{self.streams['video'][0]['height']} | {self.streams['video'][0]['display_aspect_ratio']}')
        self.layout.addWidget(self.file_widget)
        self.layout.addWidget(self.video_widget)
        self.layout.addWidget(self.scroll_view)

        self.audio_widgets = []

        for i, (audio_lang, audio_streams_of_lang) in enumerate(self.streams['audio'].items()):
            self.grid.setRowMinimumHeight(i, 24)
            self.audio_widgets.append({})
            self.audio_widgets[i]['language'] = QtWidgets.QLabel()
            self.audio_widgets[i]['language'].setText(audio_lang.upper())
            self.audio_widgets[i]['language'].setStyleSheet("""
                border-left-width: 2px;
                border-style: solid;
                border-color: darkblue;
                padding-left: 16;
                font-weight: bold;
            """)
            self.grid.addWidget(self.audio_widgets[i]['language'], i, 0)
            self.audio_widgets[i]['streams'] = []
            for j, audio_stream in enumerate(audio_streams_of_lang):
                self.audio_widgets[i]['streams'].append(FFStreamWidget(audio_stream, audio_streams_of_lang))
                self.grid.addWidget(self.audio_widgets[i]['streams'][j], i, j + 1)
                self.grid.setColumnStretch(j + 1, 1)

                self.audio_widgets[i]['streams'][j].changed.connect(self.on_change)

    @Slot(AudioExistentStream, int)
    @Slot(AudioExistentStream, None)
    @Slot(AudioGenerableStream, int)
    @Slot(AudioGenerableStream, None)
    def on_change(self, arg):
        stream, new_index = arg
        stream['from_index'] = new_index
        # pprint.pprint(self.streams['audio'])
        # print('====================================')


if __name__ == "__main__":
    app = QtWidgets.QApplication([])

    app.setApplicationName("FFReplex")
    app.setApplicationDisplayName("FFReplex")
    app.setApplicationVersion("0.1.0")

    window = FFReplexGui()
    window.show()

    sys.exit(app.exec())
