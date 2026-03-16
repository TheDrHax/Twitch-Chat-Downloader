from time import sleep
from iso8601 import parse_date as parse8601
from progressbar import ProgressBar
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3 import Retry

from .settings import settings


client = Session()
client.headers['Acccept'] = '*/*'
client.headers['Client-ID'] = settings['client_id']

# Configure retries for all requests
retries = Retry(connect=5, read=2, redirect=5)
http_adapter = HTTPAdapter(max_retries=retries)
client.mount('http://', http_adapter)
client.mount('https://', http_adapter)


def gql(query: str):
    res = client.post('https://gql.twitch.tv/gql', json={'query': query})

    if res.status_code == 200:
        return res.json()
    else:
        raise Exception(res.text)


class Message(object):
    @staticmethod
    def _find_groups(words, threshold=3, collocations=1,
                     collocations_threshold=2):
        groups = []
        words = words.copy()

        for size in range(min(collocations, len(words) // threshold + 1), 0, -1):
            for pos in range(len(words) - size):
                chunk = words[pos:pos+size]

                if None in chunk or \
                   len(Message._find_groups(chunk, threshold=2)) > 0:
                    continue

                count = 1
                for j in range(1, len(words) // size):
                    if chunk == words[pos+j*size:pos+j*size+size]:
                        count += 1
                    else:
                        break

                if count >= threshold or \
                   len(chunk) > 1 and count >= collocations_threshold:
                    groups.append((chunk, pos, count))
                    words[pos:pos+size*count] = [None] * size * count
        
        return groups

    @staticmethod
    def group(message, threshold=3, collocations=1, collocations_threshold=2,
              format='{emote} x{count}', **kwargs):
        words = message.split(' ')

        if len(words) < threshold:
            return message

        groups = Message._find_groups(words, threshold, collocations,
                                      collocations_threshold)
        groups = sorted(groups, key=lambda x: x[1], reverse=True)

        for chunk, pos, count in groups:
            emote = ' '.join(chunk)  # thin space!
            words = words[:pos] + \
                [format.format(emote=emote, count=count)] + \
                words[pos + count * len(chunk):]

        return ' '.join(words)

    def __init__(self, comment):
        self.user = comment['commenter']['displayName']

        if settings['badges']['enabled']:
            badge_ids = [badge['setID']
                         for badge in comment['commenter']['displayBadges']]

            badges = [val
                      for key, val in settings['badges']['map'].items()
                      if key in badge_ids]

            max_count = settings['badges']['max_count']
            if max_count >= 1:
                if len(badges) > max_count:
                    badges = badges[0:max_count]

            self.badge = ''.join(badges)
        else:
            self.badge = ''

        group_prefs = settings.get('group_repeating_emotes')

        message = ''.join(frag['text']
                          for frag in comment['message']['fragments']).strip()

        if group_prefs['enabled'] is True:
            self.message = self.group(message, **group_prefs)
        else:
            self.message = message

        self.offset = comment['contentOffsetSeconds']

        if comment['message']['userColor']:
            self.color = comment['message']['userColor'][1:]
        else:
            self.color = 'FFFFFF'

    def hash(self) -> int:
        return hash((self.offset, self.user, self.message))

class Messages(object):
    def __init__(self, video_id):
        self.video_id = video_id

        video = gql(f'''
            query {{
                video(id: "{video_id}") {{
                    creator {{
                        displayName
                        id
                    }}
                    createdAt
                    lengthSeconds
                    title
                }}
            }}
        ''')

        self.created_at = parse8601(video['data']['video']['createdAt'])
        self.duration = video['data']['video']['lengthSeconds']
        self.title = video['data']['video']['title']
        self.creator_name = video['data']['video']['creator']['displayName']
        self.creator_id = video['data']['video']['creator']['id']

        if settings.get('display_progress') in [None, True]:
            self.progressbar = ProgressBar(max_value=self.duration)

    def _get_comments(self, selector: str):
        return gql(f'''
            query {{
                video(id: "{self.video_id}") {{
                    comments{selector} {{
                        edges {{
                            cursor
                            node {{
                                commenter {{
                                    displayName
                                    login
                                    displayBadges(channelID: {self.creator_id}) {{
                                        setID
                                    }}
                                }}
                                createdAt
                                contentOffsetSeconds
                                message {{
                                    fragments {{
                                        text
                                    }}
                                    userColor
                                }}
                            }}
                        }}

                        pageInfo {{
                            hasNextPage
                        }}
                    }}
                }}
            }}
        ''')['data']['video']['comments']

    def __iter__(self):
        hasNextPage = True
        offset = 0
        cursor = None
        hashes = set()

        while hasNextPage and offset <= self.duration:
            if cursor:
                selector = f'(after: "{cursor}")'
            elif offset > 0:
                selector = f'(contentOffsetSeconds: {offset})'
            else:
                selector = ''

            comments = self._get_comments(selector)

            if not comments or len(comments) == 0:
                if cursor:
                    print('WARN: Cursors are not working, '
                          'falling back to content offset')
                    cursor = None
                    continue

                break

            # Always true without cursor
            hasNextPage = comments['pageInfo']['hasNextPage']

            if offset == 0 or cursor:
                cursor = comments['edges'][-1]['cursor']

            offset = comments['edges'][-1]['node']['contentOffsetSeconds'] + 1

            for comment in comments['edges']:
                # Calculate more accurate offset
                ts = parse8601(comment['node']['createdAt'])

                if ts > self.created_at:
                    precise_offset = (ts - self.created_at).total_seconds()
                    comment['node']['contentOffsetSeconds'] = precise_offset

                try:
                    msg = Message(comment['node'])
                except Exception:
                    continue
            
                msg_hash = msg.hash()

                if msg_hash in hashes:
                    continue
                else:
                    hashes.add(msg_hash)

                yield msg

            if self.progressbar:
                ts = offset - 1
                self.progressbar.update(min(self.duration, ts))

            if settings['cooldown'] > 0:
                sleep(settings['cooldown'] / 1000)


class Channel(object):
    def __init__(self, channel):
        self.name = channel

    def videos(self):
        hasNextPage = True
        cursor = None

        while hasNextPage:
            res = gql(f'''
                query {{
                    user(login: "{self.name}") {{
                        videos({f'after: "{cursor}"' if cursor else 'type: ARCHIVE'}) {{
                            edges {{
                                cursor
                                node {{
                                    id
                                    createdAt
                                }}
                            }}
                            pageInfo {{
                                hasNextPage
                            }}
                        }}
                    }}
                }}
            ''')

            videos = res['data']['user']['videos']
            hasNextPage = videos['pageInfo']['hasNextPage']
            cursor = videos['edges'][-1]['cursor']

            for video in res['data']['user']['videos']['edges']:
                yield int(video['node']['id'])
