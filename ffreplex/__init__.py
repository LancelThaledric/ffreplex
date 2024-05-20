#!/usr/bin/env python
"""ffreplex entry point"""

import argparse
import asyncio
import io
import json
import os
import pprint
import re
import sys
import random
import threading
from io import StringIO
from typing import List, Tuple

from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtGui import QAction, QKeySequence, QFont
from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtCore import Slot, Signal, QObject, QProcess

from ffreplex.ffclient import FFClient, AudioExistentStream, AudioGenerableStream, AllStreamsWithGenerables, AllStreams, \
    AudioStreamList, COMPATIBLE_DOWNMIXES
from ffreplex.filewalk import list_files


def get_options():
    description = ''
    parser = argparse.ArgumentParser(description=description)

    parser.add_argument('input',
                        help='File or folder')

    return parser.parse_args()


class FFProcess(QProcess):
    index: int

    def __init__(self, index: int):
        super().__init__()
        self.index = index


class FFStreamWidget(QtWidgets.QFrame):
    changed = Signal(object)

    def __init__(self, stream: AudioGenerableStream | AudioExistentStream,
                 streams_of_lang: list[AudioExistentStream | AudioGenerableStream]):
        super().__init__()
        self.stream = stream

        # Setup UI

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


async def wait():
    await asyncio.sleep(0.5)


class FFReplexGui(QtWidgets.QMainWindow):
    """GUI for ffreplex task"""

    ffclient = FFClient()

    streams: AllStreamsWithGenerables = FFClient.ff_create_empty_data()
    initial_streams: AllStreams = FFClient.ff_create_empty_data()
    files: list[str] = []

    def __init__(self):
        super().__init__()
        self.system_ffmpeg = FFReplexGui.ffclient.ff_get_info()

        # Setup Processes

        self.parent_process = QObject()
        self.process_count = 1
        self.processes: list[FFProcess] = []
        self.command_distribution: list[list[int]] = []
        self.commands: list[tuple[str, list[str]]] = []
        self.remaining_tasks = 0

        # self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        # self.process.readyReadStandardOutput.connect(self.on_process_message)
        # self.process.readyReadStandardError.connect(self.on_process_error)
        # self.process.finished.connect(self.on_finish)

        # Parse args and find files
        options = get_options()
        pathabs = os.path.abspath(options.input)
        self.files = list_files(pathabs, re.compile(r'\.mkv$'))

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
        self.process_button = QtWidgets.QPushButton('START')
        self.console = QtWidgets.QPlainTextEdit()
        self.console.setReadOnly(True)
        monospace_font = QFont('Menlo')
        monospace_font.setStyleHint(QFont.Monospace)
        self.console.setFont(monospace_font)

        self.process_widget = QtWidgets.QFrame()
        self.process_layout = QtWidgets.QHBoxLayout()
        self.threads_label = QtWidgets.QLabel('Threads :')
        self.spinbox = QtWidgets.QSpinBox()
        self.spinbox.setMaximum(12)
        self.spinbox.setMinimum(1)
        self.spinbox.setValue(4)

        self.process_layout.addWidget(self.threads_label)
        self.process_layout.addWidget(self.spinbox)
        self.process_layout.addWidget(self.process_button)
        self.process_widget.setLayout(self.process_layout)
        self.process_layout.setStretch(2, 1)

        self.file_widget = QtWidgets.QLabel(f'{len(self.files)} files – {self.files[0]}')
        self.video_widget = QtWidgets.QLabel(
            f'Video : {len(self.streams['video'])} streams – {self.streams['video'][0]['width']}x{self.streams['video'][0]['height']} | {self.streams['video'][0]['display_aspect_ratio']}')
        self.layout.addWidget(self.file_widget)
        self.layout.addWidget(self.video_widget)
        self.layout.addWidget(self.scroll_view)
        self.layout.addWidget(self.process_widget)
        self.process_button.pressed.connect(self.process_files)
        self.layout.addWidget(self.console)
        self.layout.setStretch(0, 0)
        self.layout.setStretch(1, 0)
        self.layout.setStretch(2, 0)
        self.layout.setStretch(3, 0)
        self.layout.setStretch(4, 1)

        self.audio_widgets = []
        self.iostream = io.StringIO()

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

    def print_console(self):
        self.console.appendPlainText(' === FFReplex === \n')
        self.console.appendPlainText(' === Available downmixes === \n')
        for (layout, downmixes) in COMPATIBLE_DOWNMIXES.items():
            self.console.appendPlainText(f"- {layout} :")
            if len(downmixes) == 0:
                self.console.appendPlainText(f"  None")
            else:
                for downmix in downmixes:
                    self.console.appendPlainText(f"  - {', '.join(downmix[0])}")

        self.console.appendPlainText('\n === Files === \n')
        self.console.appendPlainText(f"{len(self.files)} files :")
        for file in self.files:
            self.console.appendPlainText(f" - {file}")

        self.console.appendPlainText('\n === Select streams above then press Start button === \n')

    @Slot()
    def on_process_message(self):
        process = self.sender()
        output = bytes(process.readAllStandardOutput()).decode('UTF-8').strip()
        self.console.appendPlainText(output)

    @Slot()
    def on_process_error(self):
        process = self.sender()
        output = bytes(process.readAllStandardOutput()).decode('UTF-8').strip()
        self.console.appendPlainText(output)

    @Slot()
    def on_process_finish(self):
        process = self.sender()
        self.remaining_tasks = self.remaining_tasks - 1
        if self.remaining_tasks == 0:
            self.console.appendPlainText('\n === FINISHED ===')
            self.started = False
            self.scroll_view.setDisabled(False)
            self.process_widget.setDisabled(False)
        elif process is not None and process.index is not None:
            self.start_next_command(process.index)

    started: bool = False

    def process_files(self):
        if self.started: return

        self.started = True
        self.scroll_view.setDisabled(True)
        self.process_widget.setDisabled(True)
        self.commands = self.ffclient.ff_get_commands(self.files, self.streams, self.iostream)

        self.console.appendPlainText(self.iostream.getvalue())

        # Here : populate self.process_count
        self.process_count = self.spinbox.value()
        self.remaining_tasks = len(self.commands)
        self.command_distribution = [[] for _ in range(self.process_count)]
        for i in range(self.remaining_tasks):
            self.command_distribution[i % self.process_count].append(i)
        self.processes = [FFProcess(index=i) for i in range(self.process_count)]
        for process in self.processes:
            process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
            process.readyReadStandardOutput.connect(self.on_process_message)
            process.readyReadStandardError.connect(self.on_process_error)
            process.finished.connect(self.on_process_finish)
            self.start_next_command(process.index)

    def start_next_command(self, index):
        if len(self.command_distribution[index]) == 0:
            return
        next_command_id = self.command_distribution[index].pop(0)
        while self.processes[index].state() is not QProcess.ProcessState.NotRunning:
            asyncio.run(wait())
        command = self.commands[next_command_id]
        self.console.appendPlainText(f' === Starting process of file #{next_command_id} on thread [{index}]\n\n')
        self.console.appendPlainText(f' > {command[0]} {' '.join(command[1])}\n')
        self.processes[index].start(command[0], command[1])


if __name__ == "__main__":
    app = QtWidgets.QApplication([])

    app.setApplicationName("FFReplex")
    app.setApplicationDisplayName("FFReplex")
    app.setApplicationVersion("0.1.0")

    window = FFReplexGui()
    window.show()
    window.print_console()

    sys.exit(app.exec())
