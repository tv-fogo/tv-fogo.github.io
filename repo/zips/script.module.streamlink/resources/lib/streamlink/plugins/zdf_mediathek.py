import logging
import re

from streamlink.plugin import Plugin, pluginmatcher
from streamlink.plugin.api import validate
from streamlink.stream import HLSStream
from streamlink.utils.url import url_join

log = logging.getLogger(__name__)


@pluginmatcher(re.compile(
    r"https?://(\w+\.)?zdf\.de/",
))
class ZDFMediathek(Plugin):
    _re_api_json = re.compile(r"""data-zdfplayer-jsb=(["'])(?P<json>{.+?})\1""", re.DOTALL)

    def _get_streams(self):
        res = self.session.http.get(self.url)
        match = self._re_api_json.search(res.text)
        if not match:
            log.debug("Could not find player data")
            return

        player_data = validate.parse_json(match.group("json"))
        api_token = player_data.get("apiToken")
        content_url = player_data.get("content")

        if not all([api_token, content_url]):
            log.error("Could not find API token or content URL in player data")
            return

        headers = {
            "Api-Auth": f"Bearer {api_token}",
        }

        content_data = self.session.http.get(
            content_url,
            headers=headers,
            schema=validate.Schema(
                validate.parse_json(),
                {
                    "mainVideoContent": {
                        "http://zdf.de/rels/target": {
                            "http://zdf.de/rels/streams/ptmd-template": str,
                        },
                    },
                },
                validate.get("mainVideoContent"),
                validate.get("http://zdf.de/rels/target"),
                validate.get("http://zdf.de/rels/streams/ptmd-template"),
            ),
        )

        player_id = "ngplayer_2_4"  # default player
        stream_url_template = content_data.replace("{playerId}", player_id)
        stream_api_url = url_join(content_url, stream_url_template)

        stream_data = self.session.http.get(
            stream_api_url,
            headers=headers,
            schema=validate.Schema(
                validate.parse_json(),
                {"priorityList": list},
                validate.get("priorityList"),
            ),
        )

        for priority in stream_data:
            for formitaet in priority.get("formitaeten", []):
                if formitaet.get("type") != "h264_aac_ts_http_m3u8_http":
                    continue
                for quality in formitaet.get("qualities", []):
                    for track in quality.get("audio", {}).get("tracks", []):
                        yield from HLSStream.parse_variant_playlist(self.session, track["uri"], headers=headers).items()


__plugin__ = ZDFMediathek
