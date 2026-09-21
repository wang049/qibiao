"""把 .ico 写进 Windows PE，供桌面快捷方式和资源管理器显示。"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

RT_ICON = 3
RT_GROUP_ICON = 14
IMAGE_SCN_CNT_INITIALIZED_DATA = 0x00000040
IMAGE_SCN_MEM_READ = 0x40000000
RSRC_CHARS = IMAGE_SCN_CNT_INITIALIZED_DATA | IMAGE_SCN_MEM_READ


def parse_ico(blob: bytes) -> tuple[bytes, list[bytes]]:
    if len(blob) < 6:
        raise SystemExit("ico too small")
    reserved, kind, count = struct.unpack_from("<HHH", blob, 0)
    if reserved != 0 or kind != 1 or count < 1:
        raise SystemExit("not a Windows icon")
    images: list[bytes] = []
    group = bytearray(struct.pack("<HHH", 0, 1, count))
    off = 6
    for i in range(count):
        if off + 16 > len(blob):
            raise SystemExit("ico directory truncated")
        entry = blob[off : off + 16]
        width, height, colors, reserved_b, planes, bits, nbytes, start = struct.unpack(
            "<BBBBHHII", entry
        )
        if start + nbytes > len(blob):
            raise SystemExit("ico image truncated")
        images.append(blob[start : start + nbytes])
        group += struct.pack(
            "<BBBBHHIH",
            width,
            height,
            colors,
            reserved_b,
            planes or 1,
            bits or 32,
            nbytes,
            i + 1,
        )
        off += 16
    return bytes(group), images


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


class _Dir:
    def __init__(self, entries: list[tuple[int, "_Dir | bytes"]]) -> None:
        self.entries = entries
        self.offset = 0


def build_rsrc(group: bytes, images: list[bytes], section_rva: int) -> bytes:
    icon_dir = _Dir(
        [
            (index + 1, _Dir([(0, payload)]))
            for index, payload in enumerate(images)
        ]
    )
    group_dir = _Dir([(1, _Dir([(0, group)]))])
    root = _Dir([(RT_ICON, icon_dir), (RT_GROUP_ICON, group_dir)])

    dirs: list[_Dir] = []
    payloads: list[bytes] = []

    def walk(node: _Dir) -> None:
        dirs.append(node)
        for _, child in node.entries:
            if isinstance(child, _Dir):
                walk(child)
            else:
                payloads.append(child)

    walk(root)

    cursor = 0
    for node in dirs:
        node.offset = cursor
        cursor += 16 + 8 * len(node.entries)
    data_off = cursor
    cursor = _align(data_off + 16 * len(payloads), 4)
    raw_offsets: list[int] = []
    for payload in payloads:
        raw_offsets.append(cursor)
        cursor = _align(cursor + len(payload), 4)

    blob = bytearray(cursor)
    payload_i = 0
    for node in dirs:
        struct.pack_into("<IIHHHH", blob, node.offset, 0, 0, 0, 0, 0, len(node.entries))
        entry_at = node.offset + 16
        for i, (ident, child) in enumerate(node.entries):
            if isinstance(child, _Dir):
                child_off = child.offset | 0x80000000
            else:
                child_off = data_off + payload_i * 16
                struct.pack_into(
                    "<IIII",
                    blob,
                    child_off,
                    section_rva + raw_offsets[payload_i],
                    len(payloads[payload_i]),
                    0,
                    0,
                )
                start = raw_offsets[payload_i]
                blob[start : start + len(payloads[payload_i])] = payloads[payload_i]
                payload_i += 1
            struct.pack_into("<II", blob, entry_at + i * 8, ident, child_off)
    return bytes(blob)


def _read_pe(data: bytes) -> dict:
    if data[:2] != b"MZ":
        raise SystemExit("not a PE")
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew : e_lfanew + 4] != b"PE\x00\x00":
        raise SystemExit("missing PE signature")
    coff = e_lfanew + 4
    machine, nsec, _, _, _, optsz, _ = struct.unpack_from("<HHIIIHH", data, coff)
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    if magic == 0x20B:
        sect_align, file_align = struct.unpack_from("<II", data, opt + 32)
        size_of_image = struct.unpack_from("<I", data, opt + 56)[0]
        size_of_headers = struct.unpack_from("<I", data, opt + 60)[0]
        num_rva = struct.unpack_from("<I", data, opt + 108)[0]
        dd = opt + 112
    elif magic == 0x10B:
        sect_align, file_align = struct.unpack_from("<II", data, opt + 32)
        size_of_image = struct.unpack_from("<I", data, opt + 56)[0]
        size_of_headers = struct.unpack_from("<I", data, opt + 60)[0]
        num_rva = struct.unpack_from("<I", data, opt + 92)[0]
        dd = opt + 96
    else:
        raise SystemExit("unsupported optional header")
    sec = opt + optsz
    sections = []
    for i in range(nsec):
        name, vsz, va, rsz, raw, *_rest, chars = struct.unpack_from("<8sIIIIIIHHI", data, sec + i * 40)
        sections.append(
            {
                "name": name,
                "vsz": vsz,
                "va": va,
                "rsz": rsz,
                "raw": raw,
                "chars": chars,
                "off": sec + i * 40,
            }
        )
    return {
        "e_lfanew": e_lfanew,
        "coff": coff,
        "opt": opt,
        "magic": magic,
        "nsec": nsec,
        "optsz": optsz,
        "sect_align": sect_align,
        "file_align": file_align,
        "size_of_image": size_of_image,
        "size_of_headers": size_of_headers,
        "num_rva": num_rva,
        "dd": dd,
        "sec": sec,
        "sections": sections,
        "machine": machine,
    }


def has_icon_resource(data: bytes) -> bool:
    info = _read_pe(data)
    if info["num_rva"] < 3:
        return False
    rva, size = struct.unpack_from("<II", data, info["dd"] + 16)
    return rva != 0 and size != 0 and b".rsrc" in data[: info["size_of_headers"] + 80]


def embed_icon(exe: Path, ico: Path) -> None:
    data = bytearray(exe.read_bytes())
    group, images = parse_ico(ico.read_bytes())
    info = _read_pe(data)
    sections = list(info["sections"])
    if info["num_rva"] < 3:
        raise SystemExit("PE has no resource data directory slot")

    if sections and sections[-1]["name"].rstrip(b"\x00") == b".rsrc":
        last = sections.pop()
        del data[last["raw"] :]
        info["nsec"] -= 1
        struct.pack_into("<H", data, info["coff"] + 2, info["nsec"])
        sections = list(_read_pe(data)["sections"])
        info = _read_pe(data)

    last = sections[-1]
    rsrc_va = _align(last["va"] + max(last["vsz"], last["rsz"]), info["sect_align"])
    rsrc = build_rsrc(group, images, rsrc_va)
    rsrc_vsz = len(rsrc)
    rsrc_raw_sz = _align(len(rsrc), info["file_align"])
    rsrc_raw = _align(len(data), info["file_align"])
    if rsrc_raw > len(data):
        data.extend(b"\x00" * (rsrc_raw - len(data)))

    new_header_end = info["sec"] + (info["nsec"] + 1) * 40
    if new_header_end > info["size_of_headers"]:
        raise SystemExit("PE headers have no room for .rsrc section")

    padded = rsrc + b"\x00" * (rsrc_raw_sz - len(rsrc))
    data.extend(padded)

    sec_off = info["sec"] + info["nsec"] * 40
    name = b".rsrc" + b"\x00" * 3
    struct.pack_into(
        "<8sIIIIIIHHI",
        data,
        sec_off,
        name,
        rsrc_vsz,
        rsrc_va,
        rsrc_raw_sz,
        rsrc_raw,
        0,
        0,
        0,
        0,
        RSRC_CHARS,
    )
    struct.pack_into("<H", data, info["coff"] + 2, info["nsec"] + 1)
    struct.pack_into("<II", data, info["dd"] + 16, rsrc_va, rsrc_vsz)
    size_of_image = _align(rsrc_va + rsrc_vsz, info["sect_align"])
    if info["magic"] == 0x20B:
        struct.pack_into("<I", data, info["opt"] + 56, size_of_image)
        struct.pack_into("<I", data, info["opt"] + 64, 0)
    else:
        struct.pack_into("<I", data, info["opt"] + 56, size_of_image)
        struct.pack_into("<I", data, info["opt"] + 64, 0)
    exe.write_bytes(data)
    if not has_icon_resource(exe.read_bytes()):
        raise SystemExit("embed icon failed to write resource directory")


def make_blank_pe32plus() -> bytes:
    """最小 PE32+，只给测试往里写图标。"""
    e_lfanew = 0x80
    optsz = 240
    nsec = 1
    sect_align = 0x1000
    file_align = 0x200
    headers = 0x400
    text_raw = headers
    text = b"\xc3" + b"\x00" * (file_align - 1)
    size = headers + len(text)
    buf = bytearray(size)
    buf[0:2] = b"MZ"
    struct.pack_into("<I", buf, 0x3C, e_lfanew)
    buf[e_lfanew : e_lfanew + 4] = b"PE\x00\x00"
    coff = e_lfanew + 4
    struct.pack_into("<HHIIIHH", buf, coff, 0x8664, nsec, 0, 0, 0, optsz, 0x22)
    opt = coff + 20
    struct.pack_into("<H", buf, opt, 0x20B)
    struct.pack_into("<I", buf, opt + 16, 0x1000)
    struct.pack_into("<Q", buf, opt + 24, 0x140000000)
    struct.pack_into("<II", buf, opt + 32, sect_align, file_align)
    struct.pack_into("<I", buf, opt + 56, 0x2000)
    struct.pack_into("<I", buf, opt + 60, headers)
    struct.pack_into("<H", buf, opt + 68, 3)
    struct.pack_into("<I", buf, opt + 108, 16)
    sec = opt + optsz
    struct.pack_into(
        "<8sIIIIIIHHI",
        buf,
        sec,
        b".text\x00\x00\x00",
        1,
        0x1000,
        file_align,
        text_raw,
        0,
        0,
        0,
        0,
        0x60000020,
    )
    buf[text_raw : text_raw + len(text)] = text
    return bytes(buf)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("exe")
    parser.add_argument("ico")
    args = parser.parse_args()
    embed_icon(Path(args.exe), Path(args.ico))
    print("icon", args.ico, "->", args.exe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
