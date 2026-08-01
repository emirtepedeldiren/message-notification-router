"""Media type detection.

Several dataset files carry the wrong extension, and the API rejects a payload
whose declared type contradicts its bytes — so the content has to decide.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from data_loader import DATASET_DIR, load_dataset
from perception import MediaFacts, sniff_mime


@pytest.fixture(scope="module")
def dataset():
    return load_dataset()


def write(tmp_path: Path, name: str, payload: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(payload)
    return path


class TestSniffing:
    @pytest.mark.parametrize(
        "payload,expected",
        [
            (b"\xff\xd8\xff\xe0" + b"\x00" * 12, "image/jpeg"),
            (b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "image/png"),
            (b"GIF89a" + b"\x00" * 10, "image/gif"),
            (b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 4, "image/webp"),
            (b"RIFF\x00\x00\x00\x00WAVE" + b"\x00" * 4, "audio/wav"),
            (b"ID3\x04" + b"\x00" * 12, "audio/mp3"),
            (b"OggS" + b"\x00" * 12, "audio/ogg"),
            (b"\x00\x00\x00\x20ftypavif" + b"\x00" * 4, "image/avif"),
            (b"\x00\x00\x00\x20ftypheic" + b"\x00" * 4, "image/heic"),
            (b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 4, "audio/mp4"),
        ],
    )
    def test_content_decides_the_type(self, tmp_path, payload, expected):
        """The extension says .jpg throughout; only the bytes differ."""
        assert sniff_mime(write(tmp_path, "thing.jpg", payload)) == expected

    def test_ftyp_brand_separates_images_from_audio(self, tmp_path):
        """An AVIF still and an M4A track share the ftyp box — the brand splits them."""
        image = write(tmp_path, "a.jpg", b"\x00\x00\x00\x20ftypavif" + b"\x00" * 4)
        audio = write(tmp_path, "b.mp3", b"\x00\x00\x00\x20ftypM4A " + b"\x00" * 4)
        assert sniff_mime(image).startswith("image/")
        assert sniff_mime(audio).startswith("audio/")

    def test_unrecognised_content_falls_back_to_the_extension(self, tmp_path):
        assert sniff_mime(write(tmp_path, "thing.png", b"not a real header")) == "image/png"

    def test_unknown_everything_returns_none(self, tmp_path):
        assert sniff_mime(write(tmp_path, "thing.xyz", b"not a real header")) is None


class TestRealDatasetFiles:
    """The specific files whose extension lies about their contents."""

    @pytest.mark.parametrize(
        "media_id,expected",
        [
            ("img_001", "image/jpeg"),
            ("img_004", "image/png"),
            ("img_010", "image/png"),
            ("img_011", "image/png"),
            ("img_016", "image/webp"),
            ("img_020", "image/avif"),
            ("img_022", "image/png"),
        ],
    )
    def test_images(self, dataset, media_id, expected):
        path = dataset.media_path("image", media_id)
        if path is None or not path.exists():
            pytest.skip(f"{media_id} not present")
        assert sniff_mime(path) == expected

    def test_wav_named_mp3(self, dataset):
        path = dataset.media_path("voice", "vn_005")
        if path is None or not path.exists():
            pytest.skip("vn_005 not present")
        assert sniff_mime(path) == "audio/wav"

    def test_every_media_file_has_a_detectable_type(self, dataset):
        """Nothing in the corpus should be unroutable because of its container."""
        undetected = []
        for media_id in list(dataset.images) + list(dataset.voice_notes):
            kind = "image" if media_id in dataset.images else "voice"
            path = dataset.media_path(kind, media_id)
            if path and path.exists() and sniff_mime(path) is None:
                undetected.append(media_id)
        assert undetected == []


class TestMediaFacts:
    def test_unavailable_media_renders_a_placeholder(self):
        facts = MediaFacts(media_id="img_x", media_type="image", available=False)
        assert "could not be analysed" in facts.render()

    def test_query_text_combines_the_readable_parts(self):
        facts = MediaFacts(
            media_id="vn_x",
            media_type="voice",
            text="call me back",
            summary="a short personal request",
            direct_request="return the call",
        )
        query = facts.query_text
        assert "call me back" in query and "return the call" in query

    def test_flags_surface_in_the_rendered_block(self):
        facts = MediaFacts(
            media_id="img_y",
            media_type="image",
            summary="a poster",
            asks_for_payment=True,
            asks_for_credentials=True,
        )
        rendered = facts.render()
        assert "requests payment" in rendered
        assert "requests credentials or OTP" in rendered
