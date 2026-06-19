"""Video frame splitter + mock source tests (no ffmpeg, no capture hardware).

The splitter is the correctness core of the video path: it must reassemble whatever
chunking ffmpeg's stdout produces back into exactly the embedded JPEG frames.
"""

import asyncio

from backend.video.mock_source import MockVideoSource
from backend.video.source import EOI, SOI, JpegStreamSplitter


def _jpeg(payload: bytes) -> bytes:
    return SOI + payload + EOI


def test_splitter_single_whole_frame():
    sp = JpegStreamSplitter()
    f = _jpeg(b"hello")
    assert sp.feed(f) == [f]


def test_splitter_two_frames_in_one_chunk():
    sp = JpegStreamSplitter()
    a, b = _jpeg(b"A"), _jpeg(b"BB")
    assert sp.feed(a + b) == [a, b]


def test_splitter_frame_split_across_reads():
    sp = JpegStreamSplitter()
    f = _jpeg(b"frame-data")
    assert sp.feed(f[:1]) == []
    assert sp.feed(f[1:6]) == []
    assert sp.feed(f[6:]) == [f]


def test_splitter_discards_leading_junk():
    sp = JpegStreamSplitter()
    f = _jpeg(b"x")
    assert sp.feed(b"garbage before frame" + f) == [f]


def test_splitter_handles_soi_byte_boundary():
    sp = JpegStreamSplitter()
    # The 0xFF of the SOI arrives in one read, the 0xD8 in the next.
    assert sp.feed(b"\xff") == []
    assert sp.feed(b"\xd8payload" + EOI) == [SOI + b"payload" + EOI]


def test_splitter_keeps_partial_until_eoi():
    sp = JpegStreamSplitter()
    assert sp.feed(SOI + b"incomplete") == []
    assert sp.feed(b"...done" + EOI) == [SOI + b"incomplete...done" + EOI]


def test_mock_source_loads_bundled_assets():
    src = MockVideoSource()
    assert len(src._frames) >= 1
    for fr in src._frames:
        assert fr[:2] == SOI
        assert fr[-2:] == EOI


def test_mock_source_streams_latest_frames():
    async def go():
        src = MockVideoSource(fps=120)
        await src.start()
        out = []
        async for fr in src.frames():
            out.append(fr)
            if len(out) >= 3:
                break
        await src.stop()
        return out, src.has_frames

    frames, had_frames = asyncio.run(go())
    assert len(frames) == 3
    assert had_frames is True
    assert all(f[:2] == SOI and f[-2:] == EOI for f in frames)
