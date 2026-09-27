"""Synthetic text databases and installations; never use game files in tests."""

from pathlib import Path

from ksm2sdvx.packs.models import DATABASE


def song_xml(song_id: int = 2, title: str = "Song", *, jacket: int = -2) -> str:
    return f'''<music id="{song_id}" custom="keep"><info>
    <title_name __type="str">{title}</title_name><artist_name __type="str">Artist</artist_name>
    <ascii __type="str">song{song_id}</ascii><bpm_min>12000</bpm_min><bpm_max>12000</bpm_max>
    <volume>91</volume><version>7</version></info>
    <!-- retained between sections --><unknown x="1"><child>untouched</child></unknown>
    <difficulty><novice><difnum>50</difnum><jacket_print>{jacket}</jacket_print>
    <effected_by>Author</effected_by><illustrator>Illustrator</illustrator></novice></difficulty></music>'''


def database(*songs: str, encoding: str = "shift-jis") -> bytes:
    return (
        f'<?xml version="1.0" encoding="{encoding}"?>\n<?custom keep?>\n'
        '<mdb custom="retain">\n<!-- database comment -->\n' + "\n".join(songs) + "\n</mdb>\n"
    ).encode("cp932" if encoding == "shift-jis" else "utf-8")


def write(root: Path, name: str, content: bytes) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def installation(root: Path, *songs: str) -> Path:
    write(root, "data/others/music_db.xml", database(song_xml(1, "Original")))
    write(root, f"data_mods/custom/{DATABASE}", database(*(songs or (song_xml(),))))
    return root


def assets(root: Path, song_id: int = 2) -> None:
    stem = f"{song_id:04}_song{song_id}"
    for name in (
        f"{stem}_1n.vox",
        f"{stem}_1n.s3v",
        f"{stem}_pre.s3v",
        f"jk_{song_id:04}_1.png",
        f"jk_{song_id:04}_1_s.png",
        f"jk_{song_id:04}_1_b.png",
    ):
        write(root, f"music/{stem}/{name}", name.encode())
    write(root, f"graphics/s_jacket00_ifs/jk_{song_id:04}_1_t.png", b"selector")
