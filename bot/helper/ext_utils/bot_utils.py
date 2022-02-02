import ssl

from re import match, findall, split
from threading import Thread, Event
from time import time
from math import ceil
from psutil import virtual_memory, cpu_percent, disk_usage
from requests import head as rhead
from urllib.request import urlopen, Request
from telegram import InlineKeyboardMarkup
from urllib.parse import quote

from bot.helper.telegram_helper.bot_commands import BotCommands
from bot import download_dict, download_dict_lock, STATUS_LIMIT, botStartTime
from bot.helper.telegram_helper.button_build import ButtonMaker

MAGNET_REGEX = r"magnet:\?xt=urn:btih:[a-zA-Z0-9]*"

URL_REGEX = r"(?:(?:https?|ftp):\/\/)?[\w/\-?=%.]+\.[\w/\-?=%.]+"

COUNT = 0
PAGE_NO = 1


class MirrorStatus:
    STATUS_UPLOADING = "📤 Uploading"
    STATUS_DOWNLOADING = "📥 Downloading"
    STATUS_CLONING = "♻️ Cloning"
    STATUS_WAITING = "💤 Queued"
    STATUS_FAILED = "🚫 Failed. Cleaning Download"
    STATUS_PAUSE = "⛔️ Paused"
    STATUS_ARCHIVING = "🔐 Archiving"
    STATUS_EXTRACTING = "📂 Extracting"
    STATUS_SPLITTING = "✂️ Splitting"
    STATUS_CHECKING = "📝 CheckingUp"
    STATUS_SEEDING = "🌧 Seeding"

SIZE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']


class setInterval:
    def __init__(self, interval, action):
        self.interval = interval
        self.action = action
        self.stopEvent = Event()
        thread = Thread(target=self.__setInterval)
        thread.start()

    def __setInterval(self):
        nextTime = time() + self.interval
        while not self.stopEvent.wait(nextTime - time()):
            nextTime += self.interval
            self.action()

    def cancel(self):
        self.stopEvent.set()

def get_readable_file_size(size_in_bytes) -> str:
    if size_in_bytes is None:
        return '0B'
    index = 0
    while size_in_bytes >= 1024:
        size_in_bytes /= 1024
        index += 1
    try:
        return f'{round(size_in_bytes, 2)}{SIZE_UNITS[index]}'
    except IndexError:
        return 'File terlalu besar'

def getDownloadByGid(gid):
    with download_dict_lock:
        for dl in list(download_dict.values()):
            status = dl.status()
            if (
                status
                not in [
                    MirrorStatus.STATUS_ARCHIVING,
                    MirrorStatus.STATUS_EXTRACTING,
                    MirrorStatus.STATUS_SPLITTING,
                ]
                and dl.gid() == gid
            ):
                return dl
    return None

def getAllDownload():
    with download_dict_lock:
        for dlDetails in list(download_dict.values()):
            status = dlDetails.status()
            if (
                status
                not in [
                    MirrorStatus.STATUS_ARCHIVING,
                    MirrorStatus.STATUS_EXTRACTING,
                    MirrorStatus.STATUS_SPLITTING,
                    MirrorStatus.STATUS_CLONING,
                    MirrorStatus.STATUS_UPLOADING,
                    MirrorStatus.STATUS_CHECKING,
                ]
                and dlDetails
            ):
                return dlDetails
    return None

def get_progress_bar_string(status):
    completed = status.processed_bytes() / 8
    total = status.size_raw() / 8
    p = 0 if total == 0 else round(completed * 100 / total)
    p = min(max(p, 0), 100)
    cFull = p // 8
    p_str = '■' * cFull
    p_str += '□' * (12 - cFull)
    p_str = f"[{p_str}]"
    return p_str

def get_readable_message():
    with download_dict_lock:
        msg = ""
        dlspeed_bytes = 0
        uldl_bytes = 0
        START = 0
        if STATUS_LIMIT is not None:
            tasks = len(download_dict)
            global pages
            pages = ceil(tasks/STATUS_LIMIT)
            if PAGE_NO > pages and pages != 0:
                globals()['COUNT'] -= STATUS_LIMIT
                globals()['PAGE_NO'] -= 1
            START = COUNT
        for index, download in enumerate(list(download_dict.values())[START:], start=1):
            # user yang mirror
            pemirror = download.Pemirror()
            reply_to = pemirror.reply_to_message
            if reply_to is not None:
                if reply_to.from_user.username:
                    tag = f"<code>@{reply_to.from_user.username}</code> (<code>{reply_to.from_user.id}</code>)"
                else:
                    tag = f"<code>{reply_to.from_user.first_name}</code> (<code>{reply_to.from_user.id}</code>)"
            else:
                if pemirror.from_user.username:
                    tag = f"<code>@{pemirror.from_user.username}</code> (<code>{pemirror.from_user.id}</code>)"
                else:
                    tag = f"<code>{pemirror.from_user.first_name}</code> (<code>{pemirror.from_user.id}</code>)"
            # link yang di mirror
            message_args = pemirror.text.split(' ', maxsplit=1)
            try:
                link = message_args[1]
                if link.startswith("s ") or link == "s":
                    message_args = pemirror.text.split(' ', maxsplit=2)
                    link = message_args[2].strip()
            except IndexError:
                link = ''
            link = split(r"pswd:|\|", link)[0]
            link = link.strip()
            # jika link adalah magnet link
            if findall(MAGNET_REGEX, link):
                link = f"https://t.me/share/url?url={quote(link)}"
            # jika user reply ke sebuah link
            if not findall(URL_REGEX, link):
                if reply_to is not None:
                    link = f"https://t.me/c/{str(pemirror.chat.id)[4:]}/{reply_to.message_id}"
            # sampai sini custom statusnya
            msg += f"💽 <code>{download.name()}</code>"
            msg += f"\n<a href=\"{link}\"><b>{download.status()}</b></a>"
            if download.status() not in [
                MirrorStatus.STATUS_ARCHIVING,
                MirrorStatus.STATUS_EXTRACTING,
                MirrorStatus.STATUS_SPLITTING,
                MirrorStatus.STATUS_SEEDING,
            ]:
                msg += f"\n🌀 {get_progress_bar_string(download)} {download.progress()}"
                msg += f"\n📦 {get_readable_file_size(download.processed_bytes())} / {download.size()}"
                msg += f"\n⚡️ {download.speed()} | ⏳ {download.eta()}"
                try:
                    msg += f"\n🧲 <b>Seeders:</b> {download.aria_download().num_seeders}" \
                           f" | <b>Peers:</b> {download.aria_download().connections}"
                except:
                    pass
                try:
                    msg += f"\n🧲 <b>Seeders:</b> {download.torrent_info().num_seeds}" \
                           f" | <b>Leechers:</b> {download.torrent_info().num_leechs}"
                except:
                    pass
                msg += f"\n👤 {tag}"
                msg += f"\n❌ <code>/{BotCommands.CancelMirror} {download.gid()}</code>"
            elif download.status() == MirrorStatus.STATUS_SEEDING:
                msg += f"\n📦 <b>Size: </b>{download.size()}"
                msg += f"\n⚡️ <b>Speed: </b>{get_readable_file_size(download.torrent_info().upspeed)}/s"
                msg += f" | 📤 <b>Uploaded: </b>{get_readable_file_size(download.torrent_info().uploaded)}"
                msg += f"\n📐 <b>Ratio: </b>{round(download.torrent_info().ratio, 3)}"
                msg += f" | 🕒 <b>Time: </b>{get_readable_time(download.torrent_info().seeding_time)}"
                msg += f"\n❌ <code>/{BotCommands.CancelMirror} {download.gid()}</code>"
            else:
                msg += f"\n📦 {download.size()}"
                msg += f"\n👤 {tag}"
            msg += "\n\n"
            if STATUS_LIMIT is not None and index == STATUS_LIMIT:
                break
        total, used, free, _ = disk_usage('.')
        free = get_readable_file_size(free)
        currentTime = get_readable_time(time() - botStartTime)
        bmsg = f"🖥️ <b>CPU:</b> {cpu_percent()}% | 💿 <b>FREE:</b> {free}"
        for download in list(download_dict.values()):
            speedy = download.speed()
            if download.status() == MirrorStatus.STATUS_DOWNLOADING:
                if 'K' in speedy:
                    dlspeed_bytes += float(speedy.split('K')[0]) * 1024
                elif 'M' in speedy:
                    dlspeed_bytes += float(speedy.split('M')[0]) * 1048576
            if download.status() == MirrorStatus.STATUS_UPLOADING:
                if 'KB/s' in speedy:
                    uldl_bytes += float(speedy.split('K')[0]) * 1024
                elif 'MB/s' in speedy:
                    uldl_bytes += float(speedy.split('M')[0]) * 1048576
        dlspeed = get_readable_file_size(dlspeed_bytes)
        ulspeed = get_readable_file_size(uldl_bytes)
        bmsg += f"\n💾 <b>RAM:</b> {virtual_memory().percent}% | 🕒 <b>UPTIME:</b> {currentTime}" \
                f"\n🔻 <b>DL:</b> {dlspeed}/s | 🔺 <b>UL:</b> {ulspeed}/s"
        if STATUS_LIMIT is not None and tasks > STATUS_LIMIT:
            msg += f"📑 {PAGE_NO}/{pages} Pages | 🎯 {tasks} Tasks\n"
            buttons = ButtonMaker()
            buttons.sbutton("Previous", "status pre")
            buttons.sbutton("Next", "status nex")
            button = InlineKeyboardMarkup(buttons.build_menu(2))
            return msg + bmsg, button
        return msg + bmsg, ""

def turn(data):
    try:
        with download_dict_lock:
            global COUNT, PAGE_NO
            if data[1] == "nex":
                if PAGE_NO == pages:
                    COUNT = 0
                    PAGE_NO = 1
                else:
                    COUNT += STATUS_LIMIT
                    PAGE_NO += 1
            elif data[1] == "pre":
                if PAGE_NO == 1:
                    COUNT = STATUS_LIMIT * (pages - 1)
                    PAGE_NO = pages
                else:
                    COUNT -= STATUS_LIMIT
                    PAGE_NO -= 1
        return True
    except:
        return False

def get_readable_time(seconds: int) -> str:
    result = ''
    (days, remainder) = divmod(seconds, 86400)
    days = int(days)
    if days != 0:
        result += f'{days}d'
    (hours, remainder) = divmod(remainder, 3600)
    hours = int(hours)
    if hours != 0:
        result += f'{hours}h'
    (minutes, seconds) = divmod(remainder, 60)
    minutes = int(minutes)
    if minutes != 0:
        result += f'{minutes}m'
    seconds = int(seconds)
    result += f'{seconds}s'
    return result

def is_url(url: str):
    url = findall(URL_REGEX, url)
    return bool(url)

def is_gdrive_link(url: str):
    return "drive.google.com" in url

def is_gdtot_link(url: str):
    url = match(r'https?://.*\.gdtot\.\S+', url)
    return bool(url)

def is_mega_link(url: str):
    return "mega.nz" in url or "mega.co.nz" in url

def get_mega_link_type(url: str):
    if "folder" in url:
        return "folder"
    elif "file" in url:
        return "file"
    elif "/#F!" in url:
        return "folder"
    return "file"

def is_magnet(url: str):
    magnet = findall(MAGNET_REGEX, url)
    return bool(magnet)

def new_thread(fn):
    """To use as decorator to make a function call threaded.
    Needs import
    from threading import Thread"""

    def wrapper(*args, **kwargs):
        thread = Thread(target=fn, args=args, kwargs=kwargs)
        thread.start()
        return thread

    return wrapper

def get_content_type(link: str):
def get_content_type(link: str):
    header = {
        'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:95.0) Gecko/20100101 Firefox/95.0'
    }
    try:
        req= Request(link, headers=header)
        res = urlopen(req, context=ssl._create_unverified_context(), timeout=10)
        info = res.info()
        content_type = info.get_content_type()
    except:
        content_type = None

    if content_type is None:
        try:
            res = rhead(link, headers=header, allow_redirects=True, verify=False, timeout=10)
            content_type = res.headers.get('content-type')
        except:
            content_type = None

    return content_type

