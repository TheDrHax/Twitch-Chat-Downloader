from __future__ import unicode_literals

import io
import os
import re
import textwrap

from datetime import timedelta, datetime as dtt

from .settings import settings
from .twitch import Messages


class Subtitle(object):
    def __init__(self, filename: str):
        if not os.path.exists(os.path.dirname(filename)):
            os.makedirs(os.path.dirname(filename))

        self.file = io.open(filename, mode='w+', encoding='UTF8')

    @staticmethod
    def _duration(msg):
        T_MIN = settings['subtitle_duration']
        T_MAX = settings['dynamic_duration']['max']
        MSG_MAX = settings['dynamic_duration']['max_length']

        if settings['dynamic_duration']['enabled']:
            part = (MSG_MAX - min(len(msg), MSG_MAX)) / MSG_MAX
            return T_MAX - (T_MAX - T_MIN) * part
        else:
            return T_MIN

    @staticmethod
    def ftime(seconds: float) -> str:
        t = dtt.strptime('00:00', '%H:%M') + timedelta(seconds=seconds)
        ts = dtt.strftime(t, '%H:%M:%S.%f')
        return ts[1:] if ts.startswith('00') else ts

    @staticmethod
    def wrap(username, text):
        max_width = settings['max_width']
        full_text = username + ': ' + text

        if len(full_text) <= max_width or max_width <= 0:
            return text

        text = textwrap.wrap(full_text, max_width, drop_whitespace=False)
        text = '\n'.join(text).replace('\n ', ' \n')
        text = text[len(username)+2:]

        return text

    def close(self):
        self.file.flush()
        self.file.close()


class SubtitlesASS(Subtitle):
    def __init__(self, filename: str):
        super(SubtitlesASS, self).__init__(filename)

        self.line = settings['ssa_events_line_format'] + '\n'

        self.file.writelines([
            '[Script Info]\n',
            'PlayResX: 1280\n',
            'PlayResY: 720\n',
            '\n',
            '[V4 Styles]\n',
            settings['ssa_style_format'],
            '\n',
            settings['ssa_style_default'],
            '\n\n',
            '[Events]\n',
            settings['ssa_events_format'],
            '\n'
        ])

    @staticmethod
    def _rgb_to_bgr(color):
        return color[4:6] + color[2:4] + color[0:2]

    @staticmethod
    def _color(text, color):
        return '{\\c&H' + color + '&}' + text + '{\\c&HFFFFFF&}'

    @staticmethod
    def wrap(username, message):
        return Subtitle.wrap(username, message).replace('\n', '\\N')

    @staticmethod
    def ftime(seconds: float) -> str:
        return Subtitle.ftime(seconds)[:-4]

    def add(self, comment):
        offset = round(comment.offset, 2)
        color = self._rgb_to_bgr(comment.color)

        self.file.write(self.line.format(
            start=self.ftime(offset),
            end=self.ftime(offset + self._duration(comment.message)),
            user=self._color(comment.user, color),
            message=self.wrap(comment.user, comment.message),
            badge=comment.badge,
            badges=comment.badges,
        ).replace('  ', ' '))


class SubtitlesSRT(Subtitle):
    def __init__(self, filename: str):
        super(SubtitlesSRT, self).__init__(filename)
        self.count = 0

    @staticmethod
    def ftime(seconds):
        return Subtitle.ftime(seconds)[:-3].replace('.', ',')

    def add(self, comment):
        time = comment.offset

        self.file.write(str(self.count) + '\n')
        self.file.write('{start} --> {end}\n'.format(
            start=self.ftime(time),
            end=self.ftime(time + self._duration(comment.message))
        ))
        self.file.write('{user}: {message}\n\n'.format(
            user=comment.user,
            message=comment.message
        ))

        self.count += 1


class SubtitlesIRC(Subtitle):
    def __init__(self, filename: str):
        super(SubtitlesIRC, self).__init__(filename)

    @staticmethod
    def ftime(seconds):
        return Subtitle.ftime(seconds)[:-3].replace('.', settings['millisecond_separator'])

    def add(self, comment):
        self.file.write('[{start}] <{badge}{user}> {message}\n'.format(
            start=self.ftime(comment.offset),
            badge=comment.badge,
            user=comment.user,
            message=comment.message
        ))


class SubtitleWriter:
    @staticmethod
    def clean_filename(string, valid_filename_regex=re.compile(r'(?u)[^-\w.()\[\]{}@%! ]')):
        return re.sub(valid_filename_regex, '', string.strip())

    @classmethod
    def filename(cls, video: Messages, ext: str) -> str:
        # TODO: make time configurable
        time_str = str(video.created_at.replace(microsecond=0).replace(tzinfo=None).isoformat())

        return settings['filename_format'].format(
            directory=settings['directory'],
            video_id=video.video_id,
            format=ext,
            user_name=cls.clean_filename(video.creator_name),
            title=cls.clean_filename(video.title),
            created_at=cls.clean_filename(time_str)
        )

    def __init__(self, video: Messages):
        self.drivers = set()

        for ext in settings['formats']:
            filename = self.filename(video, ext)

            if ext in ('ass', 'ssa'):
                self.drivers.add(SubtitlesASS(filename))

            if ext == 'srt':
                self.drivers.add(SubtitlesSRT(filename))

            if ext == 'irc':
                self.drivers.add(SubtitlesIRC(filename))

    def add(self, comment):
        [driver.add(comment) for driver in self.drivers]

    def close(self):
        [driver.close() for driver in self.drivers]
