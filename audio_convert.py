"""
WebM/Opus → WAV 转换模块
解析 WebM 容器，用 opuslib 解码，写出 PCM WAV
支持 Safari 的 MP4 通过 afconvert 转换
"""
import struct
import subprocess
import tempfile
import os


def read_ebml_id(data, offset):
    first = data[offset]
    if first & 0x80:   length = 1
    elif first & 0x40: length = 2
    elif first & 0x20: length = 3
    elif first & 0x10: length = 4
    else: raise ValueError(f"Invalid EBML ID at {offset}: {first:#x}")
    return offset + length


def read_ebml_size(data, offset):
    first = data[offset]
    if first & 0x80:   length, mask = 1, 0x7F
    elif first & 0x40: length, mask = 2, 0x3FFF
    elif first & 0x20: length, mask = 3, 0x1FFFFF
    elif first & 0x10: length, mask = 4, 0x0FFFFFFF
    elif first & 0x08: length, mask = 5, 0x07FFFFFFFF
    elif first & 0x04: length, mask = 6, 0x03FFFFFFFFFF
    elif first & 0x02: length, mask = 7, 0x01FFFFFFFFFFFF
    elif first & 0x01: length, mask = 8, 0x00FFFFFFFFFFFFFF
    else: raise ValueError(f"Invalid EBML size at {offset}: {first:#x}")

    size_bytes = data[offset:offset + length]
    value = size_bytes[0] & mask
    for b in size_bytes[1:]:
        value = (value << 8) | b
    return value, offset + length


def skip_element(data, offset):
    _, off = read_ebml_id(data, offset)
    size, off = read_ebml_size(data, off)
    return off + size


def offset_after_ebml_header(data):
    off = 0
    if data[0:4] == b'\x1a\x45\xdf\xa3':
        off = skip_element(data, off)
    return off


def find_opus_codec_private(data):
    """从 WebM Tracks 中提取 Opus CodecPrivate (OpusHead)"""
    off = offset_after_ebml_header(data)
    _, off = read_ebml_id(data, off)  # Segment
    seg_size, off = read_ebml_size(data, off)
    seg_end = off + seg_size if seg_size > 0 else len(data)

    while off < seg_end and off < len(data) - 2:
        try:
            eid, new_off = read_ebml_id(data, off)
            esize, new_off2 = read_ebml_size(data, new_off)
        except (ValueError, IndexError):
            break

        if eid == b'\x16\x54\xae\x6b':  # Tracks
            tracks_end = new_off2 + esize
            inner = new_off2
            while inner < tracks_end and inner < len(data) - 2:
                ieid, ioff = read_ebml_id(data, inner)
                isize, ioff2 = read_ebml_size(data, ioff)
                if ieid == b'\xae':  # TrackEntry
                    entry_end = ioff2 + isize
                    j = ioff2
                    codec_id = None
                    while j < entry_end and j < len(data) - 2:
                        jeid, joff = read_ebml_id(data, j)
                        jsize, joff2 = read_ebml_size(data, joff)
                        if jeid == b'\x86':
                            codec_id = data[joff2:joff2 + jsize].decode()
                        elif jeid == b'\x63\xa2':
                            if codec_id == 'A_OPUS':
                                return data[joff2:joff2 + jsize]
                        j = joff2 + jsize
                    return None
                inner = ioff2 + isize
            return None
        elif eid == b'\x1f\x43\xb6\x75':  # Cluster
            return None
        off = new_off2 + esize
    return None


def extract_opus_frames(data):
    """从 WebM Clusters 中提取所有 Opus SimpleBlock 帧"""
    off = offset_after_ebml_header(data)
    _, off = read_ebml_id(data, off)
    seg_size, off = read_ebml_size(data, off)
    seg_end = off + seg_size if seg_size > 0 else len(data)

    frames = []
    while off < seg_end and off < len(data) - 2:
        try:
            eid, new_off = read_ebml_id(data, off)
            esize, elem_data_start = read_ebml_size(data, new_off)
        except (ValueError, IndexError):
            break

        if eid == b'\x1f\x43\xb6\x75':  # Cluster
            _collect_simpleblocks(data, elem_data_start, elem_data_start + esize, frames)
            off = elem_data_start + esize
        elif eid == b'\xa3':  # Standalone SimpleBlock
            _extract_simpleblock_opus(data, new_off, elem_data_start + esize, frames)
            off = elem_data_start + esize
        else:
            off = elem_data_start + esize
    return frames


def _collect_simpleblocks(data, start, end, frames):
    off = start
    while off < end and off < len(data) - 2:
        try:
            eid, new_off = read_ebml_id(data, off)
            esize, elem_data_start = read_ebml_size(data, new_off)
        except (ValueError, IndexError):
            break
        if eid == b'\xa3':
            _extract_simpleblock_opus(data, new_off, elem_data_start + esize, frames)
        off = elem_data_start + esize


def _extract_simpleblock_opus(data, header_off, end_off, frames):
    """解析 SimpleBlock: track_number(EBML) + timecode(2B) + flags(1B) + Opus frames"""
    block_off = header_off
    # skip track_number
    block_off = read_ebml_size(data, block_off)[1]
    # skip timecode(2B) + flags(1B) = 3B
    block_off += 3
    opus_data = data[block_off:end_off]

    pos = 0
    while pos + 2 <= len(opus_data):
        frame_len = struct.unpack('>H', opus_data[pos:pos + 2])[0]
        pos += 2
        if pos + frame_len <= len(opus_data):
            frames.append(opus_data[pos:pos + frame_len])
            pos += frame_len
        else:
            break


def opus_frames_to_pcm(frames, sample_rate=16000, channels=1):
    """用 opuslib 解码 Opus 帧为 PCM"""
    import opuslib
    decoder = opuslib.Decoder(sample_rate, channels)
    pcm_chunks = []
    for frame in frames:
        try:
            pcm = decoder.decode(frame, sample_rate * 20 // 1000,  # 20ms frame
                                 decode_fec=False)
            pcm_chunks.append(pcm)
        except Exception:
            continue
    return b''.join(pcm_chunks)


def write_wav(filepath, pcm_data, sample_rate=16000, channels=1, bits=16):
    import wave
    with wave.open(filepath, 'wb') as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(bits // 8)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)


def webm_to_wav(webm_path, wav_path):
    """WebM/Opus 文件 → WAV 文件"""
    with open(webm_path, 'rb') as f:
        data = f.read()
    frames = extract_opus_frames(data)
    if not frames:
        raise ValueError("No Opus frames found in WebM")
    pcm = opus_frames_to_pcm(frames)
    write_wav(wav_path, pcm)
    return True


def any_to_wav(input_path, output_path):
    """统一转换入口：尝试 WebM→WAV，失败则走 afconvert"""
    # 先尝试 WebM path
    try:
        with open(input_path, 'rb') as f:
            header = f.read(4)
        if header == b'\x1a\x45\xdf\xa3':
            return webm_to_wav(input_path, output_path)
    except Exception:
        pass

    # fallback: afconvert (handles m4a/mp4 from Safari, etc.)
    result = subprocess.run(
        ['afconvert', '-f', 'WAVE', '-d', 'LEI16@16000', '-c', '1',
         input_path, output_path],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        raise RuntimeError(f"afconvert failed: {result.stderr.strip()}")
    return True
