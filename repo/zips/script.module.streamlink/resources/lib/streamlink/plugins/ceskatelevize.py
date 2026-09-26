import logging
import re
from html import unescape as html_unescape

from streamlink.plugin import Plugin, pluginmatcher
from streamlink.plugin.api import validate
from streamlink.stream.dash import DASHStream
from streamlink.stream.hls import HLSStream

log = logging.getLogger(__name__)


@pluginmatcher(re.compile(
    r"https?://(?:www\.)?ceskatelevize\.cz/",
))
class Ceskatelevize(Plugin):
    _re_ivysilani_data = re.compile(r"ivysilaniData\s*=\s*({.+?});")
    _URL_PLAYLIST_V2 = "https://playlist.ceskatelevize.cz/v2/playlist/vod"

    def _get_playlist_data(self, video_id):
        params = {
            "video_id": video_id,
            "stream_type": "vod",
            "type": "html",
            "request_source": "ivysilani",
        }
        res = self.session.http.post(
            "https://www.ceskatelevize.cz/ivysilani/ajax/get-playlist-url",
            data=params,
        )
        data = self.session.http.json(res, schema=validate.Schema(
            {"url": validate.url()},
            validate.get("url"),
        ))
        return self.session.http.get(data)

    def _get_playlist_data_v2(self, video_id):
        params = {
            "app": "ivysilani",
            "device": "web_browser",
            "user": "plus",
            "vodId": video_id,
        }
        res = self.session.http.get(self._URL_PLAYLIST_V2, params=params)
        return res

    def _get_streams(self):
        match = self._re_ivysilani_data.search(self.session.http.get(self.url).text)
        if not match:
            return

        data = validate.parse_json(
            match.group(1),
            transform_source=html_unescape,
            schema=validate.Schema(
                {"id": str},
                validate.get("id"),
            ),
        )

        try:
            res = self._get_playlist_data_v2(data)
            playlist_data = self.session.http.json(res, schema=validate.Schema(
                {"data": {"playlist": {
                    "items": [{
                        "type": str,
                        "url": validate.url(),
                    }],
                }}},
                validate.get("data", {}),
                validate.get("playlist", {}),
            ))
            for item in playlist_data.get("items", []):
                if item["type"] == "hls":
                    yield from HLSStream.parse_variant_playlist(self.session, item["url"]).items()
                elif item["type"] == "dash":
                    yield from DASHStream.parse_manifest(self.session, item["url"]).items()
        except Exception as e:
            log.debug(f"Failed to get V2 playlist: {e}")
            res = self._get_playlist_data(data)
            playlist_data = self.session.http.json(res, schema=validate.Schema(
                {"playlist": [{
                    "streamUrls": {
                        "main": validate.url(),
                    },
                }]},
                validate.get("playlist", []),
            ))
            if playlist_data:
                yield from HLSStream.parse_variant_playlist(self.session, playlist_data[0]["streamUrls"]["main"]).items()


__plugin__ = Ceskatelevize
