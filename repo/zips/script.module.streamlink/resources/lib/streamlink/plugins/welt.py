import logging
import re

from streamlink.plugin import Plugin, pluginmatcher
from streamlink.plugin.api import validate
from streamlink.stream import HLSStream

log = logging.getLogger(__name__)


@pluginmatcher(re.compile(
    r"https?://(?:www\.)?welt\.de/",
))
class Welt(Plugin):
    _re_data = re.compile(r"window\.__WELT__\s*=\s*({.+});")

    def _get_streams(self):
        match = self._re_data.search(self.session.http.get(self.url).text)
        if not match:
            return

        data = validate.parse_json(
            match.group(1),
            schema=validate.Schema(
                {
                    "page": {
                        "content": {
                            "elements": [
                                validate.all(
                                    {
                                        "type": str,
                                        validate.optional("player"): {
                                            "config": {
                                                "sources": [{
                                                    "src": validate.url(),
                                                    "type": str,
                                                }],
                                            },
                                        },
                                    },
                                ),
                            ],
                        },
                    },
                },
                validate.get("page", {}),
                validate.get("content", {}),
                validate.get("elements", []),
            ),
        )

        for element in data:
            if element.get("type") != "video":
                continue
            player = element.get("player")
            if not player:
                continue
            for source in player.get("config", {}).get("sources", []):
                if source.get("type") == "application/x-mpegURL":
                    return HLSStream.parse_variant_playlist(self.session, source["src"])


__plugin__ = Welt
