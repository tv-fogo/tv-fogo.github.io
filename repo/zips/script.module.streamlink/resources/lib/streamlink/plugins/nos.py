import logging
import re

from streamlink.plugin import Plugin, pluginmatcher
from streamlink.plugin.api import validate
from streamlink.stream import HLSStream

log = logging.getLogger(__name__)


@pluginmatcher(re.compile(
    r"https?://(?:www\.)?nos\.nl/(?P<path>artikel|uitzending|livestream)/",
))
class NOS(Plugin):
    _re_artikel = re.compile(r'data-react-id="video-player-artikel"\s*data-id="(?P<id>\w+)"')
    _re_uitzending = re.compile(r'data-react-id="video-player-uitzending"\s*data-id="(?P<id>\w+)"')
    _re_livestream = re.compile(r'data-react-id="live-player"\s*data-id="(?P<id>\w+)"')
    _re_player_config = re.compile(r"NPOTV\.player\((?P<json>.+)\);")
    _URL_PLAYER = "https://nos.nl/player/playout/{id}"

    def _get_streams(self):
        path = self.match.group("path")
        if path == "artikel":
            _re = self._re_artikel
        elif path == "uitzending":
            _re = self._re_uitzending
        elif path == "livestream":
            _re = self._re_livestream
        else:
            return

        match = _re.search(self.session.http.get(self.url).text)
        if not match:
            return

        video_id = match.group("id")
        log.debug(f"Found video ID: {video_id}")

        res = self.session.http.get(self._URL_PLAYER.format(id=video_id))
        match = self._re_player_config.search(res.text)
        if not match:
            return

        data = validate.parse_json(
            match.group("json"),
            schema=validate.Schema({
                "title": str,
                "streams": [str],
            }),
        )

        for stream_url in data["streams"]:
            if "m3u8" in stream_url:
                return HLSStream.parse_variant_playlist(self.session, stream_url)


__plugin__ = NOS
