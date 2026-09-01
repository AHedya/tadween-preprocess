import logging
from typing import Any

import aiofiles.os  # type: ignore

from tadween_preprocess.core.models import Envelope

logger = logging.getLogger(__name__)


async def cleanup_envelope(env: Envelope[Any]) -> None:
    """
    Non-blocking cleanup of temporary files and symlinks for an individual envelope.
    Respects item retention options and guarantees safe symlink unlinking.
    """
    arts = env.artifacts
    opts = env.options

    # 1. Clean up Raw Path (downloads or symlinks)
    if arts.raw_path is not None and not getattr(opts, "keep_raw", False):
        try:
            is_link = await aiofiles.os.path.islink(arts.raw_path)
            if arts.is_temporary or is_link:
                await aiofiles.os.unlink(arts.raw_path)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning("Failed to clean up raw path %s: %s", arts.raw_path, e)

    # 2. Clean up Converted Opus Path
    if arts.opus_path is not None and not getattr(opts, "keep_converted", False):
        try:
            await aiofiles.os.unlink(arts.opus_path)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning("Failed to clean up opus path %s: %s", arts.opus_path, e)
