import logging
import re

from streamlink.plugin import Plugin, pluginmatcher
from streamlink.plugin.api import validate
from streamlink.stream.hls import HLSStream
from streamlink.stream.http import HTTPStream

log = logging.getLogger(__name__)


@pluginmatcher(re.compile(
    r"https?://(?:www\.)?ardmediathek\.de/(?:player|live|video)/.+",
))
class ARDMediathek(Plugin):
    _re_bcast_id = re.compile(r"broadcastId=(\d+)")
    _re_doc_id = re.compile(r"documentId=(\d+)")
    _re_player_page = re.compile(r"window\.__PLAYER_CONFIG__\s*=\s*({.+});")

    _MEDIA_TYPES = ("video", "audio")

    def _get_streams_from_media_obj(self, media_obj):
        media_type = media_obj.get("_type")
        if media_type not in self._MEDIA_TYPES:
            return

        for stream in media_obj.get("_mediaStreamArray", []):
            stream_url = stream.get("_stream")
            if not stream_url:
                continue

            if ".m3u8" in stream_url:
                yield from HLSStream.parse_variant_playlist(self.session, stream_url).items()
            elif ".mp4" in stream_url:
                quality = stream.get("_quality")
                q = f"{quality}p" if isinstance(quality, int) else "vod"
                yield q, HTTPStream(self.session, stream_url)

    def _get_streams(self):
        res = self.session.http.get(self.url)
        match = self._re_player_page.search(res.text)
        if not match:
            return

        data = validate.parse_json(match.group(1))
        video_data = data.get("video", {})
        media_collection = video_data.get("mediaCollection")
        if media_collection:
            for media_obj in media_collection.get("_mediaArray", []):
                yield from self._get_streams_from_media_obj(media_obj)
        elif video_data.get("_type") in self._MEDIA_TYPES:
            yield from self._get_streams_from_media_obj(video_data)


__plugin__ = ARDMediathek
