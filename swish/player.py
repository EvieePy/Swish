"""Swish. A standalone audio player and server for bots on Discord.

Copyright (C) 2022 PythonistaGuild <https://github.com/PythonistaGuild>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any, TYPE_CHECKING

import aiohttp
import aiohttp.web
import discord.backoff
from discord.ext.native_voice import native_voice  # type: ignore

from .types.payloads import (
    PayloadHandlers,
    ReceivedPayload,
    SentPayloadOp,
    VoiceUpdateData,
    PlayData,
    SetPauseStateData,
    SetPositionData,
    SetFilterData,
)

if TYPE_CHECKING:
    from .app import App


__all__ = (
    'Player',
)


LOG: logging.Logger = logging.getLogger('swish.player')


class Player:

    def __init__(
        self,
        websocket: aiohttp.web.WebSocketResponse,
        guild_id: str,
    ) -> None:

        self._app: App = websocket['app']
        self._websocket: aiohttp.web.WebSocketResponse = websocket
        self._guild_id: str = guild_id

        self._connector: native_voice.VoiceConnector = native_voice.VoiceConnector()
        self._connector.user_id = int(websocket['user_id'])

        self._connection: native_voice.VoiceConnection | None = None
        self._runner: asyncio.Task[None] | None = None

        self._PAYLOAD_HANDLERS: PayloadHandlers = {
            'voice_update':    self._voice_update,
            'destroy':         self._destroy,
            'play':            self._play,
            'stop':            self._stop,
            'set_pause_state': self._set_pause_state,
            'set_position':    self._set_position,
            'set_filter':      self._set_filter,
        }

        self._LOG_PREFIX: str = f'{self._websocket["client_name"]} - Player \'{self._guild_id}\''

        self._NO_CONNECTION_MESSAGE: Callable[[str], str] = (
            lambda op: f'{self._LOG_PREFIX} attempted \'{op}\' op while internal connection is down.'
        )
        self._MISSING_KEY_MESSAGE: Callable[[str, str], str] = (
            lambda op, key: f'{self._LOG_PREFIX} received \'{op}\' op with missing \'{key}\' key.'
        )

    # websocket handlers

    async def handle_payload(self, payload: ReceivedPayload) -> None:

        op = payload['op']

        if op not in self._PAYLOAD_HANDLERS:
            LOG.error(f'{self._LOG_PREFIX} received payload with unknown \'op\' key.\nPayload: {payload}')
            return

        LOG.debug(f'{self._LOG_PREFIX} received payload with \'{op}\' op.\nPayload: {payload}')
        await self._PAYLOAD_HANDLERS[op](payload['d'])

    async def send_payload(self, op: SentPayloadOp, data: Any) -> None:
        await self._websocket.send_json({'op': op, 'd': data})

    # connection handlers

    async def _connect(self) -> None:

        loop = asyncio.get_running_loop()
        self._connection = await self._connector.connect(loop)

        if self._runner is not None:
            self._runner.cancel()
        self._runner = loop.create_task(self._reconnect_handler())

    async def _reconnect_handler(self) -> None:

        loop = asyncio.get_running_loop()
        backoff = discord.backoff.ExponentialBackoff()

        while True:

            try:
                assert self._connection is not None
                await self._connection.run(loop)

            except native_voice.ConnectionClosed:
                await self._disconnect()
                return

            except native_voice.ConnectionError:
                await self._disconnect()
                return

            except native_voice.ReconnectError:

                retry = backoff.delay()
                await asyncio.sleep(retry)

                try:
                    await self._connect()
                except asyncio.TimeoutError:
                    continue

            else:
                await self._disconnect()
                return

    async def _disconnect(self) -> None:

        if self._connection is None:
            return

        self._connection.disconnect()
        self._connection = None

    # payload handlers

    async def _voice_update(self, data: VoiceUpdateData) -> None:

        if not (session_id := data.get('session_id')):
            LOG.error(self._MISSING_KEY_MESSAGE('voice_update', 'session_id'))
            return
        if not (token := data.get('token')):
            LOG.error(self._MISSING_KEY_MESSAGE('voice_update', 'token'))
            return
        if not (endpoint := data.get('endpoint')):
            LOG.error(self._MISSING_KEY_MESSAGE('voice_update', 'endpoint'))
            return

        self._connector.session_id = session_id

        endpoint, _, _ = endpoint.rpartition(':')
        endpoint = endpoint.removeprefix('wss://')

        self._connector.update_socket(
            token,
            data['guild_id'],
            endpoint
        )
        await self._connect()
        LOG.info(f'{self._LOG_PREFIX} connected to internal voice server \'{endpoint}\'.')

    async def _destroy(self) -> None:

        await self._disconnect()
        LOG.info(f'{self._LOG_PREFIX} has been disconnected.')

        del self._websocket['players'][self._guild_id]

    async def _play(self, data: PlayData) -> None:

        if not self._connection:
            LOG.error(self._NO_CONNECTION_MESSAGE('play'))
            return

        if not (track_id := data.get('track_id')):
            LOG.error(self._MISSING_KEY_MESSAGE('play', 'track_id'))
            return

        # TODO: handle start_time
        # TODO: handle end_time
        # TODO: handle replace

        track_info = self._app._decode_track_id(track_id)
        url = await self._app._get_playback_url(track_info['url'])

        self._connection.play(url)
        LOG.info(f'{self._LOG_PREFIX} started playing track \'{track_info["title"]}\' by \'{track_info["author"]}\'.')

    async def _stop(self) -> None:

        if not self._connection:
            LOG.error(self._NO_CONNECTION_MESSAGE('stop'))
            return
        if not self._connection.is_playing():
            LOG.error(f'{self._LOG_PREFIX} attempted \'stop\' op while no tracks are playing.')
            return

        self._connection.stop()
        LOG.info(f'{self._LOG_PREFIX} stopped the current track.')

    async def _set_pause_state(self, data: SetPauseStateData) -> None:

        if not self._connection:
            LOG.error(self._NO_CONNECTION_MESSAGE('set_pause_state'))
            return
        if not (state := data.get('state')):
            LOG.error(self._MISSING_KEY_MESSAGE('set_pause_state', 'state'))
            return

        if state != self._connection.is_paused():
            self._connection.pause() if state else self._connection.resume()

        LOG.info(f'{self._LOG_PREFIX} set its paused state to \'{state}\'.')

    async def _set_position(self, data: SetPositionData) -> None:

        if not self._connection:
            LOG.error(self._NO_CONNECTION_MESSAGE('set_position'))
            return
        if not self._connection.is_playing():
            LOG.error(f'{self._LOG_PREFIX} attempted \'set_position\' op while no tracks are playing.')
            return

        if not (position := data.get('position')):
            LOG.error(self._MISSING_KEY_MESSAGE('set_position', 'position'))
            return

        # TODO: implement
        LOG.info(f'{self._LOG_PREFIX} set its position to \'{position}\'.')

    async def _set_filter(self, data: SetFilterData) -> None:
        LOG.error(f'{self._LOG_PREFIX} received \'set_filter\' op which is not yet implemented.')
