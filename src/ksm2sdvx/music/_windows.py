"""WMA Professional encoding through the Windows Media Format runtime."""

import ctypes
import sys
import wave
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import cast
from uuid import UUID

from ksm2sdvx.music.errors import MusicError


class _Guid(ctypes.Structure):
    _fields_ = [("bytes", ctypes.c_ubyte * 16)]

    @classmethod
    def parse(cls, value: str) -> _Guid:
        return cls.from_buffer_copy(UUID(value).bytes_le)


class _MediaType(ctypes.Structure):
    _fields_ = [
        ("major", _Guid),
        ("subtype", _Guid),
        ("fixed_size", ctypes.c_int32),
        ("temporal_compression", ctypes.c_int32),
        ("sample_size", ctypes.c_uint32),
        ("format_type", _Guid),
        ("unknown", ctypes.c_void_p),
        ("format_size", ctypes.c_uint32),
        ("format", ctypes.c_void_p),
    ]
    format: int | None
    format_size: int


class _WaveFormat(ctypes.LittleEndianStructure):
    _pack_ = 1
    _fields_ = [
        ("tag", ctypes.c_uint16),
        ("channels", ctypes.c_uint16),
        ("sample_rate", ctypes.c_uint32),
        ("bytes_per_second", ctypes.c_uint32),
        ("block_align", ctypes.c_uint16),
        ("bits", ctypes.c_uint16),
        ("extra_size", ctypes.c_uint16),
    ]
    tag: int
    channels: int
    sample_rate: int
    bytes_per_second: int
    bits: int


_AUDIO = _Guid.parse("73647561-0000-0010-8000-00aa00389b71")
_PCM = _Guid.parse("00000001-0000-0010-8000-00aa00389b71")
_WAVE_FORMAT = _Guid.parse("05589f81-c356-11ce-bf01-00aa0055595a")
_CODEC_INFO = _Guid.parse("a970f41e-34de-4a98-b3ba-e4b3ca7528f0")
_MEDIA_PROPS = _Guid.parse("96406bce-2b2b-11d3-b36b-00c04f6108ff")
type _ArgumentType = (
    type[ctypes.c_void_p]
    | type[ctypes.c_uint16]
    | type[ctypes.c_uint32]
    | type[ctypes.c_uint64]
    | type[ctypes.c_wchar_p]
)


def _check(result: int, operation: str) -> None:
    if result < 0:
        raise MusicError(f"Windows audio encoder {operation} failed (0x{result & 0xFFFFFFFF:08X})")


class _Com:
    """Own one COM reference and call explicitly declared native signatures."""

    def __init__(self, pointer: ctypes.c_void_p) -> None:
        if not pointer.value:
            raise MusicError("Windows audio encoder returned an empty interface")
        self.pointer = pointer

    def call(self, slot: int, argument_types: tuple[_ArgumentType, ...], *arguments: object) -> int:
        table = ctypes.cast(self.pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))
        address = table.contents[slot]
        signature = ctypes.WINFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, *argument_types)
        function = cast(Callable[..., int], signature(address))
        return function(self.pointer, *arguments)

    def checked(self, slot: int, types: tuple[_ArgumentType, ...], *arguments: object) -> None:
        _check(self.call(slot, types, *arguments), f"method {slot}")

    def query(self, guid: _Guid) -> _Com:
        pointer = ctypes.c_void_p()
        self.checked(
            0, (ctypes.c_void_p, ctypes.c_void_p), ctypes.byref(guid), ctypes.byref(pointer)
        )
        return _Com(pointer)

    def close(self) -> None:
        if self.pointer.value:
            self.call(2, ())
            self.pointer = ctypes.c_void_p()


def _own(stack: ExitStack, pointer: ctypes.c_void_p) -> _Com:
    interface = _Com(pointer)
    stack.callback(interface.close)
    return interface


def _find_stream(manager: _Com, stack: ExitStack) -> _Com:
    codecs = manager.query(_CODEC_INFO)
    stack.callback(codecs.close)
    codec_count = ctypes.c_uint32()
    codecs.checked(
        3, (ctypes.c_void_p, ctypes.c_void_p), ctypes.byref(_AUDIO), ctypes.byref(codec_count)
    )
    for codec_index in range(codec_count.value):
        format_count = ctypes.c_uint32()
        codecs.checked(
            4,
            (ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p),
            ctypes.byref(_AUDIO),
            codec_index,
            ctypes.byref(format_count),
        )
        for format_index in range(format_count.value):
            pointer = ctypes.c_void_p()
            codecs.checked(
                5,
                (ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p),
                ctypes.byref(_AUDIO),
                codec_index,
                format_index,
                ctypes.byref(pointer),
            )
            stream = _Com(pointer)
            selected = False
            try:
                props = stream.query(_MEDIA_PROPS)
                try:
                    size = ctypes.c_uint32()
                    props.checked(4, (ctypes.c_void_p, ctypes.c_void_p), None, ctypes.byref(size))
                    storage = ctypes.create_string_buffer(size.value)
                    props.checked(
                        4, (ctypes.c_void_p, ctypes.c_void_p), storage, ctypes.byref(size)
                    )
                    media = _MediaType.from_buffer(storage)
                    if media.format is None or media.format_size < ctypes.sizeof(_WaveFormat):
                        continue
                    audio = _WaveFormat.from_address(media.format)
                    if (
                        audio.tag == 0x0162
                        and audio.channels == 2
                        and audio.sample_rate == 44100
                        and 48000 <= audio.bytes_per_second <= 48008
                    ):
                        selected = True
                        stack.callback(stream.close)
                        return stream
                finally:
                    props.close()
            finally:
                # Ownership moves to the caller only for the matching format.
                if not selected:
                    stream.close()
    raise MusicError("A 44.1 kHz stereo 384 kb/s WMA Professional encoder is not installed")


class WindowsWmaProEncoder:
    """Encode an ASF .s3v file with the installed Windows WMA Professional codec."""

    def encode(self, source: Path, destination: Path) -> None:
        if sys.platform != "win32":
            raise MusicError("WMA Professional encoding requires the Windows Media Format runtime")
        try:
            runtime = ctypes.WinDLL("wmvcore.dll")
            ole = ctypes.WinDLL("ole32.dll")
        except OSError as exc:
            raise MusicError(f"Windows Media Format runtime is unavailable: {exc}") from exc
        initialize = ole.CoInitializeEx
        initialize.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        initialize.restype = ctypes.c_int32
        result = cast(int, initialize(None, 0))
        if result < 0 and result != -2147417850:  # RPC_E_CHANGED_MODE: already initialized.
            _check(result, "initialization")
        try:
            with wave.open(str(source), "rb") as pcm, ExitStack() as stack:
                if (pcm.getnchannels(), pcm.getsampwidth(), pcm.getframerate()) != (2, 2, 44100):
                    raise MusicError("WMA Professional encoder requires 44.1 kHz 16-bit stereo PCM")
                if pcm.getnframes() == 0:
                    raise MusicError("Audio is empty after applying its offset or preview interval")
                manager_pointer = ctypes.c_void_p()
                create_manager = runtime.WMCreateProfileManager
                create_manager.argtypes = [ctypes.c_void_p]
                create_manager.restype = ctypes.c_int32
                _check(cast(int, create_manager(ctypes.byref(manager_pointer))), "profile creation")
                manager = _own(stack, manager_pointer)
                stream = _find_stream(manager, stack)
                stream.checked(5, (ctypes.c_uint16,), 1)
                stream.checked(7, (ctypes.c_wchar_p,), "Audio")
                stream.checked(9, (ctypes.c_wchar_p,), "Audio")
                profile_pointer = ctypes.c_void_p()
                manager.checked(
                    3, (ctypes.c_uint32, ctypes.c_void_p), 0x00090000, ctypes.byref(profile_pointer)
                )
                profile = _own(stack, profile_pointer)
                profile.checked(13, (ctypes.c_void_p,), stream.pointer)
                writer_pointer = ctypes.c_void_p()
                create_writer = runtime.WMCreateWriter
                create_writer.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                create_writer.restype = ctypes.c_int32
                _check(
                    cast(int, create_writer(None, ctypes.byref(writer_pointer))), "writer creation"
                )
                writer = _own(stack, writer_pointer)
                writer.checked(4, (ctypes.c_void_p,), profile.pointer)
                writer.checked(5, (ctypes.c_wchar_p,), str(destination.resolve()))
                _configure_pcm(writer, stack)
                writer.checked(11, ())
                _write_pcm(writer, pcm)
                writer.checked(12, ())
        except (OSError, EOFError, wave.Error) as exc:
            raise MusicError(f"Unable to encode audio: {exc}") from exc
        finally:
            if result >= 0:
                ole.CoUninitialize()


def _configure_pcm(writer: _Com, stack: ExitStack) -> None:
    pointer = ctypes.c_void_p()
    writer.checked(7, (ctypes.c_uint32, ctypes.c_void_p), 0, ctypes.byref(pointer))
    properties = _own(stack, pointer)
    audio = _WaveFormat(1, 2, 44100, 176400, 4, 16, 0)
    media = _MediaType(
        _AUDIO, _PCM, 1, 0, 4, _WAVE_FORMAT, None, ctypes.sizeof(audio), ctypes.addressof(audio)
    )
    properties.checked(5, (ctypes.c_void_p,), ctypes.byref(media))
    writer.checked(8, (ctypes.c_uint32, ctypes.c_void_p), 0, properties.pointer)


def _write_pcm(writer: _Com, pcm: wave.Wave_read) -> None:
    frames_written = 0
    while data := pcm.readframes(4410):
        if len(data) % 4:
            raise MusicError("PCM audio ends inside a stereo sample frame")
        pointer = ctypes.c_void_p()
        writer.checked(13, (ctypes.c_uint32, ctypes.c_void_p), len(data), ctypes.byref(pointer))
        sample = _Com(pointer)
        try:
            buffer = ctypes.c_void_p()
            sample.checked(6, (ctypes.c_void_p,), ctypes.byref(buffer))
            ctypes.memmove(buffer, data, len(data))
            sample.checked(4, (ctypes.c_uint32,), len(data))
            writer.checked(
                14,
                (ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint32, ctypes.c_void_p),
                0,
                frames_written * 10_000_000 // 44100,
                0,
                sample.pointer,
            )
            frames_written += len(data) // 4
        finally:
            sample.close()
    if frames_written != pcm.getnframes():
        raise MusicError("PCM audio is truncated")
