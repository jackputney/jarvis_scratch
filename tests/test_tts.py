"""TTS PCM alignment smoke tests."""

from tts.cartesia import FRAME_BYTES, WRITE_BYTES, iter_aligned_writes


def test_aligned_writes_never_split_samples():
    """Odd-sized network chunks must not produce misaligned PyAudio writes."""
    # Deliberately awkward chunk sizes (including odd lengths).
    chunks = [b"\x01\x02", b"\x03", b"\x04\x05\x06", b"\x07" * 5]
    writes = list(iter_aligned_writes(iter(chunks), write_bytes=4))

    assert all(len(w) % FRAME_BYTES == 0 for w in writes)
    assert b"".join(writes) == b"".join(chunks)[: len(b"".join(chunks)) - (len(b"".join(chunks)) % FRAME_BYTES)]


def test_write_bytes_is_sample_aligned():
    assert WRITE_BYTES % FRAME_BYTES == 0
