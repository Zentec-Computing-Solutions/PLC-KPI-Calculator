import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))

from rtsp_stream import Settings, SharedState, generate_frame, start_ffmpeg  # noqa: E402


class SettingsTests(unittest.TestCase):
    def test_defaults_match_current_installation(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            settings = Settings.from_environment()

        self.assertEqual(settings.plc_ip, "192.168.88.5")
        self.assertEqual(settings.shift_register, 15)
        self.assertEqual(settings.shift_register_count, 5)
        self.assertEqual(settings.rtsp_url, "rtsp://127.0.0.1:8554/shift-count")

    def test_environment_overrides(self) -> None:
        environment = {
            "PLC_IP": "10.0.0.25",
            "PLC_PORT": "1502",
            "FRAME_RATE": "4",
            "MOCK_PLC": "true",
        }
        with patch.dict("os.environ", environment, clear=True):
            settings = Settings.from_environment()

        self.assertEqual(settings.plc_ip, "10.0.0.25")
        self.assertEqual(settings.plc_port, 1502)
        self.assertEqual(settings.frame_rate, 4.0)
        self.assertTrue(settings.mock_plc)

    def test_ffmpeg_uses_short_keyframe_interval(self) -> None:
        with patch.dict(
            "os.environ",
            {"FRAME_RATE": "2", "KEYFRAME_INTERVAL": "2"},
            clear=True,
        ):
            settings = Settings.from_environment()

        with patch("rtsp_stream.subprocess.Popen") as popen:
            start_ffmpeg(settings, "/usr/bin/ffmpeg")

        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("-g") + 1], "4")
        self.assertEqual(command[command.index("-keyint_min") + 1], "4")
        self.assertEqual(command[command.index("-sc_threshold") + 1], "0")
        self.assertEqual(command[command.index("-bf") + 1], "0")


class FrameTests(unittest.TestCase):
    def test_frame_has_configured_dimensions(self) -> None:
        with patch.dict("os.environ", {"FRAME_WIDTH": "640", "FRAME_HEIGHT": "360"}, clear=True):
            settings = Settings.from_environment()
        state = SharedState()
        state.update(42, [100, 99, 98, 97])

        frame = generate_frame(settings, state)

        self.assertEqual(frame.shape, (360, 640, 3))


if __name__ == "__main__":
    unittest.main()
