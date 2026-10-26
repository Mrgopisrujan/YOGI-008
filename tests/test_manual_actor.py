"""Unit tests for ManualActorController."""
import pytest
from unittest.mock import MagicMock
from garuda.flight.manual_actor import ManualActorController


class TestManualActorController:
    def test_initial_pose(self):
        mock_world = MagicMock()
        ctrl = ManualActorController(mock_world, "Walker1", initial_pos=(-1.0, 15.0, 0.0), initial_yaw_deg=90.0)
        assert ctrl.x == -1.0
        assert ctrl.y == 15.0
        assert ctrl.z == 0.0
        assert ctrl.yaw_deg == 90.0
        assert mock_world.set_object_pose.called

    def test_move_forward_east(self):
        mock_world = MagicMock()
        ctrl = ManualActorController(mock_world, "Walker1", initial_pos=(0.0, 0.0, 0.0), initial_yaw_deg=90.0, step_distance_m=1.0)
        ctrl.move_forward()
        # yaw=90 means pointing along +y
        assert abs(ctrl.x - 0.0) < 1e-4
        assert abs(ctrl.y - 1.0) < 1e-4
        assert ctrl.total_distance_m == pytest.approx(1.0)

    def test_move_forward_north(self):
        mock_world = MagicMock()
        ctrl = ManualActorController(mock_world, "Walker1", initial_pos=(0.0, 0.0, 0.0), initial_yaw_deg=0.0, step_distance_m=1.0)
        ctrl.move_forward()
        # yaw=0 means pointing along +x
        assert abs(ctrl.x - 1.0) < 1e-4
        assert abs(ctrl.y - 0.0) < 1e-4

    def test_turning(self):
        mock_world = MagicMock()
        ctrl = ManualActorController(mock_world, "Walker1", initial_pos=(0.0, 0.0, 0.0), initial_yaw_deg=90.0, turn_angle_deg=15.0)
        ctrl.turn_left()
        assert ctrl.yaw_deg == pytest.approx(75.0)
        ctrl.turn_right(30.0)
        assert ctrl.yaw_deg == pytest.approx(105.0)

    def test_handle_command(self):
        mock_world = MagicMock()
        ctrl = ManualActorController(mock_world, "Walker1", initial_pos=(0.0, 0.0, 0.0), initial_yaw_deg=0.0, step_distance_m=0.5)
        assert ctrl.handle_command("W") is True
        assert ctrl.x == pytest.approx(0.5)
        assert ctrl.handle_command("UP") is True
        assert ctrl.x == pytest.approx(1.0)
        assert ctrl.handle_command("LEFT") is True
        assert ctrl.yaw_deg == pytest.approx(345.0)
        assert ctrl.handle_command("UNKNOWN") is False

    def test_terminal_key_reader_context(self):
        from garuda.flight.manual_actor import TerminalKeyReader

        with TerminalKeyReader() as reader:
            assert reader.get_key() is None
            reader._key_queue.put("W")
            assert reader.get_key() == "W"
            assert reader.get_key() is None

