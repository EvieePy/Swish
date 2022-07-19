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

import logging
from typing import Any

import toml


logger: logging.Logger = logging.getLogger('swish.config')


try:
    config = toml.load('swish.toml')
    logger.info('Successfully loaded swish.toml configuration.')
except Exception as e:
    config: dict[str, Any] = {
        'SERVER':  {
            'host':     '127.0.0.1',
            'port':     8000,
            'password': 'helloworld!'
        },
        'IP':      {
            'blocks': []
        },
        "SEARCH":  {
            "max_results": 10
        },
        'LOGGING': {
            'path':         'logs/',
            'backup_count': 5,
            'max_bytes':    5242880,
            'LEVEL':        {
                'swish':   'DEBUG',
                'discord': 'NOTSET',
                'aiohttp': 'NOTSET'
            }
        }

    }
    logger.error(f'Exception: {e} while loading swish.toml, using default configuration.')


CONFIG = config
